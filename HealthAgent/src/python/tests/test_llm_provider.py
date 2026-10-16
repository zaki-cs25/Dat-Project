"""Exercise the real SDK's HTTP contract without sending data to any service."""
import json

import httpx
import openai
import pytest

from central_park import benchmark_context as bench
from central_park.config import load
from central_park.llm.provider import get_provider


@pytest.fixture
def transport(monkeypatch):
    for name in ("CP_LLM_API_KEY", "CP_OPENAI_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_KEY",
                 "CP_OPENAI_JSON_MODE", "CP_OPENAI_TOKEN_LIMIT_PARAM", "CP_OPENAI_CHAT_TEMPLATE_KWARGS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CP_LLM_PROVIDER", "openai")
    calls = []
    status = [200]
    finish_reason = ["stop"]
    stream_body = [None]
    response_extra = [{}]
    injected_errors = []
    response_stream = [None]

    def respond(request):
        calls.append(request)
        if injected_errors:
            raise injected_errors.pop(0)
        current = status.pop(0) if len(status) > 1 else status[0]
        if current != 200:
            return httpx.Response(current, json={"error": {"message": "Fixture rejection", "type": "invalid_request_error"}})
        if stream_body[0] is not None:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream_body[0])
        if response_stream[0] is not None:
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=response_stream[0])
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "created": 0, "model": "fixture-model",
            "choices": [{"index": 0, "finish_reason": finish_reason[0],
                         "message": {"role": "assistant", "content": '{"ok":true}'}}],
            **response_extra[0],
        })

    real_client = openai.OpenAI
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: real_client(
        **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond))))
    return calls, status, finish_reason, stream_body, response_extra, injected_errors, response_stream


def test_custom_chat_endpoint_does_not_change_embedding_key(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-chat-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-embedding-key")
    monkeypatch.setenv("CP_OPENAI_BASE_URL", "https://chat.example.invalid/tenant/v1")
    monkeypatch.setenv("CP_OPENAI_MODEL", "custom-model")
    monkeypatch.setenv("CP_OPENAI_TOKEN_LIMIT_PARAM", "max_tokens")
    cfg = load()
    assert cfg.openai_api_key == "synthetic-embedding-key"
    assert get_provider(cfg).complete("Return JSON", [{"role": "user", "content": "Synthetic test"}], max_tokens=1024) == '{"ok":true}'
    request = transport[0][0]
    assert str(request.url) == "https://chat.example.invalid/tenant/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer synthetic-chat-key"
    body = json.loads(request.content)
    assert body["model"] == "custom-model"
    assert body["max_tokens"] == 1024 and "max_completion_tokens" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == {"role": "system", "content": "Return JSON"}


def test_native_openai_defaults_preserved(monkeypatch, transport):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    get_provider().complete("Return JSON", [], max_tokens=4096)
    request = transport[0][0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer synthetic-openai-key"
    body = json.loads(request.content)
    assert body["max_completion_tokens"] == 4096 and "max_tokens" not in body
    assert "chat_template_kwargs" not in body


def test_optional_template_kwargs_reach_compatible_endpoint(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_OPENAI_CHAT_TEMPLATE_KWARGS", '{"enable_thinking":false}')
    get_provider().complete("Return JSON", [], max_tokens=4096)
    body = json.loads(transport[0][0].content)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("value", ["bad JSON", "[]", "null", "false"])
def test_invalid_template_kwargs_fail_before_request(monkeypatch, transport, value):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_OPENAI_CHAT_TEMPLATE_KWARGS", value)
    with pytest.raises(ValueError, match="CP_OPENAI_CHAT_TEMPLATE_KWARGS"):
        get_provider()
    assert transport[0] == []


def test_truncated_response_is_rejected_even_if_json_parses(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    transport[2][0] = "length"
    with pytest.raises(ValueError, match="truncated at the token limit"):
        get_provider().complete("Return JSON", [], max_tokens=1024)


def test_chat_only_endpoint_without_json_mode(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "local-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9000/v1")
    monkeypatch.setenv("CP_OPENAI_JSON_MODE", "false")
    get_provider().complete("Return JSON", [])
    assert len(transport[0]) == 1
    body = json.loads(transport[0][0].content)
    assert "response_format" not in body
    assert body["max_completion_tokens"] == 2048
    assert load().openai_api_key is None


def test_custom_endpoint_error_never_falls_back_to_openai(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_OPENAI_BASE_URL", "https://chat.example.invalid/v1")
    transport[1][0] = 401
    with pytest.raises(openai.AuthenticationError):
        get_provider().complete("Return JSON", [])
    assert len(transport[0]) == 1
    assert transport[0][0].url.host == "chat.example.invalid"


@pytest.mark.parametrize("setting,value", [("CP_OPENAI_JSON_MODE", "maybe"), ("CP_OPENAI_TOKEN_LIMIT_PARAM", "unbounded")])
def test_invalid_compatibility_setting_rejected(monkeypatch, transport, setting, value):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=setting):
        get_provider()
    assert transport[0] == []


def test_missing_chat_credentials_fail_before_request(transport):
    with pytest.raises(RuntimeError, match="CP_LLM_API_KEY or OPENAI_API_KEY"):
        get_provider()
    assert transport[0] == []


def test_retryable_429_retries_once_with_new_attempt(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("CP_LLM_RETRY_BACKOFF_SECONDS", "0")
    transport[1][:] = [429, 200]
    events = []
    token = bench.EVENTS.set(events)
    try:
        assert get_provider().complete("safe prompt", []) == '{"ok":true}'
    finally:
        bench.EVENTS.reset(token)
    assert len(transport[0]) == 2
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished" and e["http_status"] == 429)
    retry = next(e for e in events if e["stage"] == "llm.retry.finished")
    assert attempt["status"] == "error" and attempt["error_type"] == "RateLimitError" and attempt["backoff_seconds"] == 0
    assert attempt["logical_call_id"] == retry["logical_call_id"]
    assert not any(e["stage"] == "llm.call" for e in events)


def test_stream_assembles_content_and_sends_token_budget(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_STREAM", "true")
    monkeypatch.setenv("CP_LLM_BACKEND", "vllm")
    transport[3][0] = (
        'data: {"id":"s","choices":[{"index":0,"delta":{"content":"{\\"ok\\":"},"finish_reason":null}]}\n\n'
        'data: {"id":"s","choices":[{"index":0,"delta":{"content":"true}"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":3,"completion_tokens":2,"prompt_tokens_details":{"cached_tokens":1}},'
        '"metrics":{"time_to_first_token_ms":25,"tokens_per_second":21.5}}\n\n'
        'data: [DONE]\n\n'
    )
    events = []
    token = bench.EVENTS.set(events)
    try:
        assert get_provider().complete("safe prompt", []) == '{"ok":true}'
    finally:
        bench.EVENTS.reset(token)
    request = json.loads(transport[0][0].content)
    assert request["stream"] is True and request["stream_options"] == {"include_usage": True}
    assert request["max_completion_tokens"] == 2048
    final = next(e for e in events if e["stage"] == "llm.attempt.finished")
    assert final["prompt_tokens"] == 3 and final["completion_tokens"] == 2
    assert final["cached_tokens"] == 1 and final["first_streamed_content_seconds"] is not None
    assert final["native_metrics"] == {"time_to_first_token_seconds": .025, "tokens_per_second": 21.5}
    assert final["native_metrics_origin"] == "vllm_response"
    assert "safe prompt" not in repr(final) and "content" not in final


def test_stream_without_finish_reason_fails_and_does_not_retry(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_STREAM", "true")
    monkeypatch.setenv("CP_LLM_MAX_RETRIES", "2")
    transport[3][0] = 'data: {"id":"s","choices":[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]}\n\n'
    with pytest.raises(ValueError, match="without a finish reason"):
        get_provider().complete("safe prompt", [])
    assert len(transport[0]) == 1


def test_partial_stream_failure_keeps_first_content_usage_and_metrics(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_STREAM", "true")
    monkeypatch.setenv("CP_LLM_MAX_RETRIES", "2")

    class BrokenStream(httpx.SyncByteStream):
        def __init__(self): self.closed = False
        def __iter__(self):
            yield (b'data: {"id":"s","model":"served-model","choices":[{"index":0,'
                   b'"delta":{"content":"part"},"finish_reason":null}]}\n\n')
            yield (b'data: {"id":"s","model":"served-model","choices":[],"usage":'
                   b'{"prompt_tokens":7,"completion_tokens":1},"metrics":{"time_to_first_token_ms":11}}\n\n')
            raise httpx.ReadError("fixture disconnect")
        def close(self): self.closed = True

    body = BrokenStream()
    transport[6][0] = body
    events = []
    token = bench.EVENTS.set(events)
    try:
        with pytest.raises(openai.APIConnectionError):
            get_provider().complete("safe prompt", [])
    finally:
        bench.EVENTS.reset(token)
    assert body.closed and len(transport[0]) == 1
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    logical = next(e for e in events if e["stage"] == "llm.call.finished")
    assert attempt["status"] == logical["status"] == "error"
    assert attempt["first_streamed_content_seconds"] is not None
    assert attempt["prompt_tokens"] == logical["prompt_tokens"] == 7
    assert attempt["native_metrics"] == logical["native_metrics"] == {"time_to_first_token_seconds": .011}
    assert attempt["response_id"] == "s" and attempt["returned_model"] == "served-model"


def test_finish_reason_and_truncation_are_in_attempt_and_logical_spans(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    transport[2][0] = "length"
    events = []
    token = bench.EVENTS.set(events)
    try:
        with pytest.raises(ValueError, match="truncated at the token limit"):
            get_provider().complete("safe prompt", [], max_tokens=17)
    finally:
        bench.EVENTS.reset(token)
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    logical = next(e for e in events if e["stage"] == "llm.call.finished")
    assert attempt["finish_reason"] == logical["finish_reason"] == "length"
    assert attempt["truncated"] is logical["truncated"] is True
    assert logical["output_token_budget"] == 17


def test_missing_usage_is_explicitly_null(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    events = []
    token = bench.EVENTS.set(events)
    try:
        get_provider().complete("safe prompt", [])
    finally:
        bench.EVENTS.reset(token)
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    assert all(attempt[k] is None for k in ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens"))


@pytest.mark.parametrize("value", [-1, True, float("nan"), 1.5])
def test_usage_counts_reject_non_integer_or_invalid_values(value):
    from central_park.llm.provider import _usage
    assert _usage({"prompt_tokens": value, "completion_tokens": 2}) == {
        "prompt_tokens": None, "completion_tokens": 2, "cached_tokens": None, "reasoning_tokens": None}


def test_openai_compatible_llamacpp_native_timings_are_whitelisted(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_BACKEND", "llamacpp")
    transport[4][0] = {"timings": {"prompt_ms": 250, "predicted_ms": 500, "cache_n": 4,
        "prompt_n": 10, "predicted_n": 20, "prompt_per_second": 40, "predicted_per_second": 30,
        "private": "discard"}}
    events = []
    token = bench.EVENTS.set(events)
    try:
        get_provider().complete("safe prompt", [])
    finally:
        bench.EVENTS.reset(token)
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    assert attempt["native_timings"] == {"prompt_seconds": .25, "predicted_seconds": .5,
        "prompt_tokens_per_second": 40, "predicted_tokens_per_second": 30}
    assert attempt["native_timings_raw"] == {"prompt_ms": 250, "predicted_ms": 500, "cache_n": 4,
        "prompt_n": 10, "predicted_n": 20, "prompt_per_second": 40, "predicted_per_second": 30}
    assert attempt["native_timing_origin"] == "server_native"


def test_vllm_nonstream_metrics_are_normalized_and_whitelisted(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_BACKEND", "vllm")
    transport[4][0] = {"metrics": {"time_to_first_token_ms": 25, "generation_time_ms": 500,
        "queue_time_ms": 10, "mean_itl_ms": 3, "tokens_per_second": 21.5, "private": "discard"}}
    events = []
    token = bench.EVENTS.set(events)
    try:
        get_provider().complete("safe prompt", [])
    finally:
        bench.EVENTS.reset(token)
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    assert attempt["native_metrics"] == {"time_to_first_token_seconds": .025,
        "generation_time_seconds": .5, "queue_time_seconds": .01,
        "mean_itl_seconds": .003, "tokens_per_second": 21.5}
    assert attempt["native_metrics_raw"]["time_to_first_token_ms"] == 25
    assert "private" not in repr(attempt["native_metrics_raw"])
    assert attempt["native_metrics_origin"] == "vllm_response"
    assert attempt["tokens_per_second_scope"] == "prefill_and_decode"


def test_timeout_from_mock_transport_is_retried(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("CP_LLM_RETRY_BACKOFF_SECONDS", "0")
    transport[5].append(httpx.ReadTimeout("simulated timeout"))
    assert get_provider().complete("safe prompt", []) == '{"ok":true}'
    assert len(transport[0]) == 2


def test_generation_attempt_is_carried_into_llm_attempt_span(monkeypatch, transport):
    monkeypatch.setenv("CP_LLM_API_KEY", "synthetic-key")
    from central_park.telemetry import model_stage
    events = []
    token = bench.EVENTS.set(events)
    try:
        with model_stage("careplan.generation", generation_attempt=3):
            get_provider().complete("safe prompt", [])
    finally:
        bench.EVENTS.reset(token)
    attempt = next(e for e in events if e["stage"] == "llm.attempt.finished")
    assert attempt["generation_attempt"] == 3


def test_non_openai_streaming_and_anthropic_seed_are_rejected(monkeypatch):
    monkeypatch.setenv("CP_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("CP_LLM_STREAM", "true")
    with pytest.raises(ValueError, match="not supported by the Anthropic adapter"):
        get_provider()
    monkeypatch.setenv("CP_LLM_STREAM", "false")
    monkeypatch.setenv("CP_LLM_SEED", "123")
    with pytest.raises(ValueError, match="CP_LLM_SEED is not supported"):
        get_provider()


def test_anthropic_max_tokens_stop_reason_is_truncation(monkeypatch):
    import anthropic
    import httpx2
    from central_park.llm.provider import AnthropicProvider
    calls = []

    def respond(request):
        calls.append(request)
        return httpx2.Response(200, json={"id": "msg", "type": "message", "role": "assistant",
            "model": "fixture", "content": [{"type": "text", "text": '{"ok":true}'}],
            "stop_reason": "max_tokens", "stop_sequence": None,
            "usage": {"input_tokens": 4, "output_tokens": 5}})

    real = anthropic.Anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: real(
        **kwargs, http_client=httpx2.Client(transport=httpx2.MockTransport(respond))))
    with pytest.raises(ValueError, match="truncated at the token limit"):
        AnthropicProvider("synthetic-key", "fixture-model").complete("safe", [], max_tokens=5)
    assert len(calls) == 1


def test_ollama_retries_http_error_and_records_native_timing_and_sampling(monkeypatch):
    from central_park.llm.provider import OllamaProvider
    requests = []
    statuses = [503, 200]

    def respond(request):
        requests.append(request)
        status = statuses.pop(0)
        if status != 200:
            return httpx.Response(status, json={"error": "redacted fixture"})
        return httpx.Response(200, json={"model": "served-model", "done": True, "done_reason": "stop",
            "message": {"content": '{"ok":true}'}, "prompt_eval_count": 3, "eval_count": 2,
            "eval_duration": 500000000, "prompt_eval_duration": 250000000})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "post", client.post)
    provider = OllamaProvider("http://localhost:11434", "requested-model", max_retries=1,
        retry_backoff=0, temperature=.2, top_p=.8, seed=9, backend="llamacpp")
    events = []
    token = bench.EVENTS.set(events)
    try:
        assert provider.complete("safe prompt", []) == '{"ok":true}'
    finally:
        bench.EVENTS.reset(token)
        client.close()
    assert len(requests) == 2
    body = json.loads(requests[-1].content)
    assert body["options"]["temperature"] == .2 and body["options"]["top_p"] == .8
    assert body["options"]["seed"] == 9
    failed = next(e for e in events if e["stage"] == "llm.attempt.finished" and e["http_status"] == 503)
    success = [e for e in events if e["stage"] == "llm.attempt.finished" and e["http_status"] == 200][-1]
    logical = next(e for e in events if e["stage"] == "llm.call.finished")
    assert failed["status"] == "error" and failed["error_type"] == "HTTPStatusError"
    assert success["native_timings"] == {"prompt_eval_duration": .25, "eval_duration": .5}
    assert success["native_timing_origin"] == "server_native"
    assert success["returned_model"] == "served-model"
    assert logical["attempt_count"] == 2 and logical["retry_count"] == 1
