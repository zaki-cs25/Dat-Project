"""Provider-agnostic LLM adapter with bounded, observable calls."""
from __future__ import annotations

import time
import uuid
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from contextlib import contextmanager
from typing import Protocol

import httpx

from central_park.config import Config, load


class LLMProvider(Protocol):
    def complete(self, system: str, messages: list[dict], *, max_tokens: int | None = None) -> str: ...


@contextmanager
def _span(stage: str, **meta):
    try:
        from central_park.telemetry import span
    except ImportError:
        record = dict(meta)
        yield record
    else:
        with span(stage, **meta) as record:
            yield record


def _parent_stage():
    try:
        from central_park.telemetry import current_stage
        return current_stage()
    except ImportError:
        return None


def _model_metadata():
    try:
        from central_park.telemetry import current_model_metadata
        return current_model_metadata()
    except ImportError:
        return {}


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if type(exc).__name__ in {"APIConnectionError", "APITimeoutError", "ConnectTimeout", "ReadTimeout"}:
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in (408, 409, 429) or status >= 500
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in (408, 409, 429) or status >= 500
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError, APIStatusError
        if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
            return True
        return isinstance(exc, APIStatusError) and (exc.status_code in (408, 409, 429) or exc.status_code >= 500)
    except ImportError:
        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


def _retry_after(exc: Exception, default: float, cap: float) -> float:
    response = exc.response if isinstance(exc, httpx.HTTPStatusError) else getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    try:
        value = float(headers.get("retry-after", default))
    except (ValueError, TypeError):
        try:
            retry_at = parsedate_to_datetime(headers.get("retry-after", ""))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            value = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            value = default
    if not math.isfinite(value):
        value = default
    return max(0.0, min(value, cap))


def _status(exc: Exception):
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _finite_number(value):
    return ((type(value) is int and value >= 0) or
            (type(value) is float and math.isfinite(value) and value >= 0))


def _native_timings(value):
    """Extract only documented vLLM/llama.cpp timing and token counters."""
    if hasattr(value, "model_extra"):
        raw_obj = value.model_extra or {}
    elif isinstance(value, dict):
        raw_obj = value
    else:
        raw_obj = {}
    if isinstance(raw_obj.get("timings"), dict):
        raw_obj = raw_obj["timings"]
    names = ("prompt_ms", "predicted_ms", "cache_n", "prompt_n", "predicted_n")
    rate_names = ("prompt_per_second", "predicted_per_second")
    raw = {key: raw_obj[key] for key in (*names, *rate_names) if _finite_number(raw_obj.get(key))}
    seconds = {}
    if "prompt_ms" in raw:
        seconds["prompt_seconds"] = raw["prompt_ms"] / 1000
    if "predicted_ms" in raw:
        seconds["predicted_seconds"] = raw["predicted_ms"] / 1000
    if "prompt_per_second" in raw:
        seconds["prompt_tokens_per_second"] = raw["prompt_per_second"]
    if "predicted_per_second" in raw:
        seconds["predicted_tokens_per_second"] = raw["predicted_per_second"]
    return {"native_timings": seconds or None, "native_timings_raw": raw or None,
            "native_timing_origin": "server_native" if raw else None}


def _vllm_metrics(value):
    extra = getattr(value, "model_extra", None) or {}
    metrics = extra.get("metrics") if isinstance(extra, dict) else None
    allowed = ("time_to_first_token_ms", "generation_time_ms", "queue_time_ms",
               "mean_itl_ms", "tokens_per_second")
    raw = {key: metrics[key] for key in allowed
           if isinstance(metrics, dict) and _finite_number(metrics.get(key))}
    normalized = {key.removesuffix("_ms") + "_seconds": val / 1000
                  for key, val in raw.items() if key.endswith("_ms")}
    if "tokens_per_second" in raw:
        normalized["tokens_per_second"] = raw["tokens_per_second"]
    return {"native_metrics": normalized or None, "native_metrics_raw": raw or None,
            "native_metrics_origin": "vllm_response" if raw else None,
            "tokens_per_second_scope": "prefill_and_decode" if "tokens_per_second" in raw else None}


def _usage(usage) -> dict:
    def val(obj, key):
        v = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        if type(v) is int and v >= 0:
            return v
        if type(v) is float and math.isfinite(v) and v >= 0 and v.is_integer():
            return int(v)
        return None
    prompt = val(usage, "prompt_tokens")
    completion = val(usage, "completion_tokens")
    details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else getattr(usage, "prompt_tokens_details", None)
    completion_details = usage.get("completion_tokens_details") if isinstance(usage, dict) else getattr(usage, "completion_tokens_details", None)
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "cached_tokens": val(details, "cached_tokens"),
            "reasoning_tokens": val(completion_details, "reasoning_tokens")}


class OpenAIProvider:
    def __init__(self, api_key: str, model: str, *, base_url: str | None = None,
                 json_mode: bool = True, token_limit_param: str = "max_completion_tokens",
                 chat_template_kwargs: dict | None = None, timeout: float = 60,
                 max_retries: int = 1, retry_backoff: float = .5, stream: bool = False,
                 temperature: float | None = None, top_p: float | None = None,
                 seed: int | None = None, max_output_tokens: int = 2048,
                 backend: str = "generic", profile_id: str | None = None) -> None:
        from openai import OpenAI
        if token_limit_param not in ("max_completion_tokens", "max_tokens"):
            raise ValueError("CP_OPENAI_TOKEN_LIMIT_PARAM must be max_completion_tokens or max_tokens")
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self._model, self._json_mode, self._token_limit_param = model, json_mode, token_limit_param
        self._chat_template_kwargs = chat_template_kwargs or {}
        self._timeout, self._retries, self._backoff = timeout, max(0, min(5, int(max_retries))), max(0, min(30, retry_backoff))
        self._stream, self._temperature, self._top_p, self._seed = stream, temperature, top_p, seed
        self._max_output_tokens, self._backend, self._profile_id = max_output_tokens, backend, profile_id

    def complete(self, system: str, messages: list[dict], *, max_tokens: int | None = None) -> str:
        call_id = uuid.uuid4().hex
        budget = max_tokens if max_tokens is not None else self._max_output_tokens
        with _span("llm.call", logical_call_id=call_id, provider="openai", model=self._model,
                   backend=self._backend, profile_id=self._profile_id,
                   parent_stage=_parent_stage(), generation_attempt=_model_metadata().get("generation_attempt"),
                   prompt_chars=len(system) + sum(len(str(m.get("content", ""))) for m in messages), output_token_budget=budget,
                   status="ok", http_status=None, attempt_count=0, retry_count=0, backoff_seconds_total=0.0,
                   finish_reason=None, truncated=False, **_usage(None)) as logical_record:
            try:
                return self._complete(system, messages, max_tokens, call_id, logical_record)
            except Exception as exc:
                logical_record.update(status="error", outcome="error", error_type=type(exc).__name__)
                if _status(exc) is not None:
                    logical_record["http_status"] = _status(exc)
                raise

    def _complete(self, system, messages, max_tokens, call_id, logical_record):
        budget = max_tokens if max_tokens is not None else self._max_output_tokens
        params = {"model": self._model, "messages": [{"role": "system", "content": system}, *messages],
                  self._token_limit_param: budget, "stream": self._stream}
        if self._json_mode: params["response_format"] = {"type": "json_object"}
        if self._chat_template_kwargs: params["extra_body"] = {"chat_template_kwargs": self._chat_template_kwargs}
        for k, v in (("temperature", self._temperature), ("top_p", self._top_p), ("seed", self._seed)):
            if v is not None: params[k] = v
        if self._stream: params["stream_options"] = {"include_usage": True}
        last_exc = None
        backoff_total = 0.0
        for attempt in range(self._retries + 1):
            logical_record.update(attempt_count=attempt + 1, retry_count=attempt,
                                  backoff_seconds_total=backoff_total)
            attempt_id, start = uuid.uuid4().hex, time.monotonic()
            data = {"logical_call_id": call_id, "http_attempt_id": attempt_id, "provider": "openai",
                    "model": self._model, "backend": self._backend, "profile_id": self._profile_id,
                    "attempt": attempt + 1, "prompt_chars": len(system) + sum(len(str(m.get("content", ""))) for m in messages),
                    "prompt_sha256": __import__("hashlib").sha256((system + repr(messages)).encode()).hexdigest(),
                    "status": "ok", "http_status": None, "error_type": None, **_usage(None), "first_streamed_content_seconds": None,
                    "finish_reason": None, "truncated": False, "output_token_budget": budget,
                    "generation_attempt": _model_metadata().get("generation_attempt"),
                    "returned_model": None, "response_id": None,
                    "native_timings": None, "native_timings_raw": None, "native_timing_origin": None}
            data.update(native_metrics=None, native_metrics_raw=None, native_metrics_origin=None,
                        tokens_per_second_scope=None)
            data["parent_stage"] = _parent_stage()
            with _span("llm.attempt", **data) as record:
                try:
                    if self._stream:
                        result = self._client.chat.completions.create(**params)
                        record.update(status="ok", http_status=200)
                        logical_record["http_status"] = 200
                        chunks, usage, first, finish, received = [], None, None, None, False
                        last_timing_source, last_metrics_source = None, None
                        try:
                            for chunk in result:
                                received = True
                                if getattr(chunk, "usage", None) is not None: usage = chunk.usage
                                timing_fields = _native_timings(chunk)
                                if timing_fields["native_timings_raw"]:
                                    last_timing_source = chunk
                                metric_fields = _vllm_metrics(chunk)
                                if metric_fields["native_metrics_raw"]:
                                    last_metrics_source = chunk
                                record.update(status="ok", http_status=200, stream_received_bytes=True,
                                              returned_model=getattr(chunk, "model", None) or record.get("returned_model"),
                                              response_id=getattr(chunk, "id", None) or record.get("response_id"))
                                if usage is not None:
                                    record.update(_usage(usage))
                                if last_timing_source is not None:
                                    record.update(_native_timings(last_timing_source))
                                if last_metrics_source is not None:
                                    record.update(_vllm_metrics(last_metrics_source))
                                logical_record.update(
                                    returned_model=record.get("returned_model"), response_id=record.get("response_id"),
                                    **(_usage(usage) if usage is not None else {}),
                                    **(timing_fields if timing_fields["native_timings_raw"] else {}),
                                    **(metric_fields if metric_fields["native_metrics_raw"] else {}))
                                for choice in getattr(chunk, "choices", []) or []:
                                    delta = getattr(choice, "delta", None)
                                    if getattr(choice, "finish_reason", None) is not None:
                                        finish = choice.finish_reason
                                    content_piece = getattr(delta, "content", None)
                                    if content_piece:
                                        if first is None: first = time.monotonic() - start
                                        chunks.append(content_piece)
                                        record["first_streamed_content_seconds"] = first
                                        logical_record["first_streamed_content_seconds"] = first
                                    # Some compatible servers stream reasoning separately.
                                    if delta is not None and any(isinstance(v, str) and v for k, v in (getattr(delta, "model_extra", None) or {}).items() if k not in ("content",)):
                                        received = True
                        finally:
                            close = getattr(result, "close", None)
                            if callable(close): close()
                        content = "".join(chunks)
                        record.update(_usage(usage), first_streamed_content_seconds=first, status="ok", http_status=200,
                                      stream_received_bytes=received)
                    else:
                        result = self._client.chat.completions.create(**params)
                        record.update(status="ok", http_status=200,
                                      returned_model=getattr(result, "model", None), response_id=getattr(result, "id", None))
                        logical_record["http_status"] = 200
                        if not result.choices: raise ValueError("Model returned no choices")
                        choice = result.choices[0]
                        finish, content = choice.finish_reason, choice.message.content or ""
                        record.update(_usage(result.usage), status="ok", http_status=200,
                                      **_native_timings(result), **_vllm_metrics(result))
                    if self._stream:
                        logical_record.update(returned_model=record.get("returned_model"),
                                              response_id=record.get("response_id"))
                    record["finish_reason"] = finish
                    logical_record.update(finish_reason=finish)
                    if finish == "length":
                        record["truncated"] = True
                        logical_record.update(finish_reason=finish, truncated=True)
                        raise ValueError("Model response was truncated at the token limit; check the endpoint's thinking settings or token budget")
                    if finish is None:
                        record["truncated"] = True
                        logical_record.update(finish_reason=None, truncated=True)
                        raise ValueError("Model stream ended without a finish reason")
                    if not content:
                        raise ValueError("Model returned no content")
                    logical_record.update(status="ok", http_status=200, outcome="success", finish_reason=finish,
                                          truncated=False, **_usage(usage if self._stream else result.usage),
                                          first_streamed_content_seconds=first if self._stream else None,
                                          returned_model=record.get("returned_model") if self._stream else getattr(result, "model", None),
                                          response_id=record.get("response_id") if self._stream else getattr(result, "id", None),
                                          **({"native_timings": record.get("native_timings"),
                                              "native_timings_raw": record.get("native_timings_raw"),
                                              "native_timing_origin": record.get("native_timing_origin"),
                                              "native_metrics": record.get("native_metrics"),
                                              "native_metrics_raw": record.get("native_metrics_raw"),
                                              "native_metrics_origin": record.get("native_metrics_origin"),
                                              "tokens_per_second_scope": record.get("tokens_per_second_scope")} if self._stream else
                                             {**_native_timings(result), **_vllm_metrics(result)}))
                    record.update(duration_seconds=time.monotonic() - start, outcome="success")
                    return content
                except Exception as exc:
                    last_exc = exc
                    record.update(duration_seconds=time.monotonic() - start, status="error",
                                  http_status=_status(exc) or record.get("http_status"),
                                  error_type=type(exc).__name__, outcome="error")
                    if attempt >= self._retries or not _retryable(exc) or (self._stream and locals().get("received", False)):
                        raise
                    delay = _retry_after(exc, self._backoff * (2 ** attempt), 30)
                    record["backoff_seconds"] = delay
                    backoff_total += delay
                    logical_record.update(status="ok", http_status=_status(exc) or logical_record.get("http_status"),
                                          backoff_seconds_total=backoff_total)
            with _span("llm.retry", logical_call_id=call_id, attempt=attempt + 1,
                       backoff_seconds=delay, error_type=type(last_exc).__name__, http_status=_status(last_exc)):
                time.sleep(delay)
        raise last_exc


class AnthropicProvider:
    def __init__(self, api_key: str, model: str, *, timeout=60, max_retries=1, max_output_tokens=2048,
                 retry_backoff=.5, temperature=None, top_p=None, profile_id=None, backend="generic"):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key, timeout=timeout, max_retries=0)
        self._model, self._timeout, self._retries, self._max_output_tokens = model, timeout, max(0, min(5, int(max_retries))), max_output_tokens
        self._profile_id, self._backend = profile_id, backend
        self._backoff, self._temperature, self._top_p = max(0, min(30, retry_backoff)), temperature, top_p

    def complete(self, system, messages, *, max_tokens=None):
        cid = uuid.uuid4().hex
        prompt_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        budget = max_tokens if max_tokens is not None else self._max_output_tokens
        with _span("llm.call", logical_call_id=cid, provider="anthropic", model=self._model, profile_id=self._profile_id,
                   backend=self._backend, parent_stage=_parent_stage(), generation_attempt=_model_metadata().get("generation_attempt"),
                   prompt_chars=prompt_chars, output_token_budget=budget, finish_reason=None, truncated=False,
                   status="ok", http_status=None, attempt_count=0, retry_count=0, backoff_seconds_total=0.0,
                   **_usage(None)) as logical:
            backoff_total = 0.0
            for attempt in range(self._retries + 1):
                logical.update(attempt_count=attempt + 1, retry_count=attempt, backoff_seconds_total=backoff_total)
                aid, started = uuid.uuid4().hex, time.monotonic()
                retry_error_type, retry_status = None, None
                record = {"logical_call_id": cid, "http_attempt_id": aid, "provider": "anthropic",
                          "model": self._model, "backend": self._backend, "profile_id": self._profile_id,
                          "generation_attempt": _model_metadata().get("generation_attempt"), "attempt": attempt + 1,
                          "output_token_budget": budget, "finish_reason": None, "truncated": False,
                          "prompt_chars": prompt_chars, "prompt_sha256": __import__("hashlib").sha256((system + repr(messages)).encode()).hexdigest(),
                          "prompt_tokens": None, "completion_tokens": None, "cached_tokens": None,
                          "reasoning_tokens": None, "native_timings": None, "native_timings_raw": None,
                          "native_timing_origin": None, "first_streamed_content_seconds": None,
                          "status": "ok", "http_status": None, "returned_model": None, "response_id": None}
                with _span("llm.attempt", **record) as span_record:
                    try:
                        sampling = {}
                        if self._temperature is not None: sampling["temperature"] = self._temperature
                        if self._top_p is not None: sampling["top_p"] = self._top_p
                        resp = self._client.messages.create(model=self._model, system=system, messages=messages,
                            max_tokens=budget, **sampling)
                        logical["http_status"] = 200
                        usage = getattr(resp, "usage", None)
                        span_record.update(status="ok", http_status=200, returned_model=getattr(resp, "model", None),
                            response_id=getattr(resp, "id", None), duration_seconds=time.monotonic() - started,
                            prompt_tokens=getattr(usage, "input_tokens", None),
                            completion_tokens=getattr(usage, "output_tokens", None),
                            cached_tokens=getattr(usage, "cache_read_input_tokens", None), outcome="success")
                        finish = getattr(resp, "stop_reason", None)
                        span_record["finish_reason"] = finish
                        logical.update(status="ok", http_status=200, returned_model=getattr(resp, "model", None),
                                       response_id=getattr(resp, "id", None), outcome="success", finish_reason=finish,
                                       prompt_tokens=span_record["prompt_tokens"],
                                       completion_tokens=span_record["completion_tokens"],
                                       cached_tokens=span_record["cached_tokens"])
                        if finish == "max_tokens":
                            span_record["truncated"] = True
                            logical.update(outcome="error", truncated=True)
                            raise ValueError("Model response was truncated at the token limit; check the endpoint's thinking settings or token budget")
                        return "".join(getattr(block, "text", "") for block in resp.content)
                    except Exception as exc:
                        span_record.update(status="error", http_status=_status(exc) or span_record.get("http_status"),
                                           error_type=type(exc).__name__,
                                           duration_seconds=time.monotonic() - started, outcome="error")
                        logical.update(outcome="error", error_type=type(exc).__name__, status="error")
                        if _status(exc) is not None: logical["http_status"] = _status(exc)
                        if attempt == self._retries or not _retryable(exc):
                            raise
                        delay = _retry_after(exc, self._backoff * (2 ** attempt), 30)
                        retry_error_type, retry_status = type(exc).__name__, _status(exc)
                        span_record["backoff_seconds"] = delay
                        backoff_total += delay
                        logical.update(status="ok", http_status=retry_status, backoff_seconds_total=backoff_total)
                with _span("llm.retry", logical_call_id=cid, attempt=attempt + 1,
                           backoff_seconds=delay, error_type=retry_error_type, http_status=retry_status):
                    time.sleep(delay)


class OllamaProvider:
    def __init__(self, base_url, model, *, timeout=60, max_retries=1, max_output_tokens=2048, profile_id=None,
                 backend="generic", retry_backoff=.5, temperature=None, top_p=None, seed=None):
        self._base_url, self._model = base_url.rstrip("/"), model
        self._timeout, self._retries, self._max_output_tokens = timeout, max(0, min(5, int(max_retries))), max_output_tokens
        self._profile_id, self._backend = profile_id, backend
        self._backoff, self._temperature, self._top_p, self._seed = max(0, min(30, retry_backoff)), temperature, top_p, seed

    def complete(self, system, messages, *, max_tokens=None):
        cid = uuid.uuid4().hex
        prompt_chars = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        with _span("llm.call", logical_call_id=cid, provider="ollama", model=self._model,
                   backend=self._backend, profile_id=self._profile_id, parent_stage=_parent_stage(),
                   generation_attempt=_model_metadata().get("generation_attempt"), prompt_chars=prompt_chars,
                   output_token_budget=max_tokens if max_tokens is not None else self._max_output_tokens,
                   finish_reason=None, truncated=False, status="ok", http_status=None,
                   attempt_count=0, retry_count=0, backoff_seconds_total=0.0, **_usage(None)) as logical:
            backoff_total = 0.0
            for attempt in range(self._retries + 1):
                logical.update(attempt_count=attempt + 1, retry_count=attempt, backoff_seconds_total=backoff_total)
                aid, started = uuid.uuid4().hex, time.monotonic()
                retry_error_type, retry_status = None, None
                data = {"logical_call_id": cid, "http_attempt_id": aid, "provider": "ollama", "model": self._model,
                        "backend": self._backend, "profile_id": self._profile_id, "attempt": attempt + 1, "prompt_chars": prompt_chars,
                        "prompt_sha256": __import__("hashlib").sha256((system + repr(messages)).encode()).hexdigest(),
                        "generation_attempt": _model_metadata().get("generation_attempt"),
                        "output_token_budget": max_tokens if max_tokens is not None else self._max_output_tokens,
                        "finish_reason": None, "truncated": False,
                        "status": "ok", "http_status": None, "returned_model": None, "response_id": None,
                        "prompt_tokens": None, "completion_tokens": None, "cached_tokens": None,
                        "reasoning_tokens": None, "native_timings": None, "native_timings_raw": None}
                with _span("llm.attempt", **data) as record:
                    try:
                        resp = httpx.post(f"{self._base_url}/api/chat", json={"model": self._model,
                            "messages": [{"role": "system", "content": system}, *messages], "stream": False, "format": "json",
                            "options": {"num_predict": max_tokens if max_tokens is not None else self._max_output_tokens,
                                        **({"temperature": self._temperature} if self._temperature is not None else {}),
                                        **({"top_p": self._top_p} if self._top_p is not None else {}),
                                        **({"seed": self._seed} if self._seed is not None else {})}}, timeout=self._timeout)
                        record.update(status="ok", http_status=resp.status_code)
                        logical["http_status"] = resp.status_code
                        resp.raise_for_status()
                        body = resp.json()
                        for key in ("prompt_eval_count", "eval_count"):
                            if key in body:
                                record["prompt_tokens" if key == "prompt_eval_count" else "completion_tokens"] = body[key]
                        raw = {key: body[key] for key in
                               ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration") if _finite_number(body.get(key))}
                        timings = {key: value / 1_000_000_000 for key, value in raw.items()}
                        record["finish_reason"] = body.get("done_reason")
                        record.update(returned_model=body.get("model"), response_id=body.get("id"),
                                      native_timings=timings or None, native_timings_raw=raw or None,
                                      native_timing_origin="server_native" if raw else None,
                                      duration_seconds=time.monotonic() - started, outcome="success")
                        finish = body.get("done_reason")
                        logical.update(finish_reason=finish)
                        if finish == "length":
                            record.update(truncated=True, outcome="error")
                            logical.update(outcome="error", truncated=True)
                            raise ValueError("Model response was truncated at the token limit; check the endpoint's thinking settings or token budget")
                        logical.update(status="ok", http_status=200, returned_model=body.get("model"),
                            response_id=body.get("id"), outcome="success", finish_reason=body.get("done_reason"), **_usage({
                            "prompt_tokens": record["prompt_tokens"], "completion_tokens": record["completion_tokens"]}),
                            native_timings=timings or None, native_timings_raw=raw or None,
                            native_timing_origin="server_native" if raw else None)
                        return body["message"]["content"]
                    except Exception as exc:
                        record.update(status="error", http_status=_status(exc) or record.get("http_status"),
                                      error_type=type(exc).__name__,
                                      duration_seconds=time.monotonic() - started, outcome="error")
                        logical.update(outcome="error", error_type=type(exc).__name__, status="error")
                        if _status(exc) is not None: logical["http_status"] = _status(exc)
                        if attempt == self._retries or not _retryable(exc):
                            raise
                        delay = _retry_after(exc, self._backoff * (2 ** attempt), 30)
                        retry_error_type, retry_status = type(exc).__name__, _status(exc)
                        record["backoff_seconds"] = delay
                        backoff_total += delay
                        logical.update(status="ok", http_status=retry_status, backoff_seconds_total=backoff_total)
                with _span("llm.retry", logical_call_id=cid, attempt=attempt + 1,
                           backoff_seconds=delay, error_type=retry_error_type, http_status=retry_status):
                    time.sleep(delay)

    def warmup(self):
        try:
            httpx.post(f"{self._base_url}/api/chat", json={"model": self._model,
                "messages": [{"role": "user", "content": "ready?"}], "stream": False,
                "options": {"num_predict": 4}, "keep_alive": "30m"}, timeout=self._timeout)
        except Exception:
            pass


def get_provider(cfg: Config | None = None) -> LLMProvider:
    cfg = cfg or load()
    try:
        from central_park.serving_profiles import snapshot
        profile_id = snapshot(cfg)["profile_id"]
    except (ImportError, AttributeError, TypeError):
        profile_id = None
    timeout = getattr(cfg, "llm_timeout_seconds", 60)
    retries = getattr(cfg, "llm_max_retries", 1)
    backoff = getattr(cfg, "llm_retry_backoff_seconds", .5)
    max_tokens = getattr(cfg, "llm_max_output_tokens", 2048)
    if cfg.llm_provider == "openai":
        api_key = cfg.llm_api_key or cfg.openai_api_key
        if not api_key: raise RuntimeError("CP_LLM_PROVIDER=openai requires CP_LLM_API_KEY or OPENAI_API_KEY.")
        return OpenAIProvider(api_key, cfg.openai_model, base_url=cfg.openai_base_url,
            json_mode=cfg.openai_json_mode, token_limit_param=cfg.openai_token_limit_param,
            chat_template_kwargs=cfg.openai_chat_template_kwargs, timeout=timeout, max_retries=retries,
            retry_backoff=backoff, stream=getattr(cfg, "llm_stream", False),
            temperature=getattr(cfg, "llm_temperature", None), top_p=getattr(cfg, "llm_top_p", None),
            seed=getattr(cfg, "llm_seed", None), max_output_tokens=max_tokens,
            backend=getattr(cfg, "llm_backend", "generic"), profile_id=profile_id)
    if cfg.llm_provider == "anthropic":
        if not cfg.anthropic_api_key: raise RuntimeError("CP_LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is unset.")
        if getattr(cfg, "llm_stream", False):
            raise ValueError("CP_LLM_STREAM is not supported by the Anthropic adapter")
        if getattr(cfg, "llm_seed", None) is not None:
            raise ValueError("CP_LLM_SEED is not supported by the Anthropic adapter")
        return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model, timeout=timeout, max_retries=retries,
            max_output_tokens=max_tokens, retry_backoff=backoff,
            temperature=getattr(cfg, "llm_temperature", None), top_p=getattr(cfg, "llm_top_p", None),
            profile_id=profile_id, backend=getattr(cfg, "llm_backend", "generic"))
    if cfg.llm_provider == "ollama":
        if getattr(cfg, "llm_stream", False):
            raise ValueError("CP_LLM_STREAM is not supported by the Ollama adapter")
        return OllamaProvider(cfg.ollama_base_url, cfg.ollama_model, timeout=timeout, max_retries=retries,
            max_output_tokens=max_tokens, profile_id=profile_id, backend=getattr(cfg, "llm_backend", "generic"),
            retry_backoff=backoff, temperature=getattr(cfg, "llm_temperature", None), top_p=getattr(cfg, "llm_top_p", None),
            seed=getattr(cfg, "llm_seed", None))
    raise ValueError(f"Unknown CP_LLM_PROVIDER: {cfg.llm_provider!r}. Expected openai | anthropic | ollama.")
