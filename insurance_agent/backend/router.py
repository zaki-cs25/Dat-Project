"""
LLM Router — connect to any OpenAI-compatible endpoint.

Reads backend list from router_config.yaml (or .env fallback).
Tries backends in order until one succeeds.

Works with vLLM, Google Gemini, OpenAI, OpenRouter, and any
other OpenAI-compatible API. Uses raw HTTP for the primary
interface (avoids LangChain version-compatibility surprises).
A LangChain wrapper is also provided for backward compatibility.

Usage anywhere in the codebase:
    # New: raw HTTP, no LangChain dependency
    from backend.router import get_llm
    llm = get_llm()
    response = await llm.chat(messages)          # -> dict
    async for token in llm.stream(messages):     # -> str tokens

    # Legacy: LangChain ChatOpenAI (for existing chains)
    from backend.router import get_llm_langchain
    llm = get_llm_langchain()
    response = llm.invoke("hello")

No env vars needed if router_config.yaml is set up.
Fallback to .env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
"""

import asyncio
import json
import os
import re
import time
import uuid
from typing import AsyncIterator

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ---------------------------------------------------------------------------
# Lazy YAML loader — avoid a hard dependency on pyyaml
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict | None:
    """Try to load a YAML file; return None on any failure."""
    try:
        import yaml
    except ImportError:
        print("Warning: pyyaml not installed. Falling back to .env variables.")
        return None
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_config_path = os.path.join(os.path.dirname(__file__), "router_config.yaml")
_config_cache: dict | None = None


def _resolve_env(value: str) -> str:
    """Replace ${ENV_VAR} with the actual env var value."""
    if not isinstance(value, str):
        return str(value) if value else ""
    def _repl(m):
        return os.environ.get(m.group(1), "")
    return re.sub(r"\$\{(\w+)\}", _repl, value)


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    raw = _load_yaml(_config_path)

    if raw:
        backends = []
        for b in raw.get("backends", []):
            backends.append({
                "name": b.get("name", ""),
                "base_url": _resolve_env(b.get("base_url", "")),
                "api_key": _resolve_env(b.get("api_key", "key")),
                "model": _resolve_env(b.get("model", "gpt-4o")),
            })
        defaults = raw.get("defaults", {})
        _config_cache = {"backends": backends, "defaults": defaults}
    else:
        base_url = os.getenv("LLM_BASE_URL", "")
        api_key = os.getenv("LLM_API_KEY", "key")
        model = os.getenv("LLM_MODEL", "gpt-4o")

        if not base_url:
            raise ValueError(
                "No LLM backend configured.\n"
                "Either set up backend/router_config.yaml or export:\n"
                "  LLM_BASE_URL=http://127.0.0.1:9000/v1\n"
                "  LLM_API_KEY=key\n"
                "  LLM_MODEL=Qwen3.6-27B"
            )

        _config_cache = {
            "backends": [{"name": ".env", "base_url": base_url, "api_key": api_key, "model": model}],
            "defaults": {},
        }

    return _config_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_transient_error(exc: Exception) -> bool:
    """Check if an exception is a transient HTTP error (429, 503, 5xx)."""
    err_str = str(exc).lower()
    return any(code in err_str for code in ("429", "503", "500", "502", "504", "unavailable", "rate"))


async def _retry_async(coro_fn, max_retries: int = 3, base_delay: float = 2.0, label: str = "request"):
    """Execute an async callable with retries on transient errors."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except Exception as exc:
            last_exc = exc
            if _is_transient_error(exc) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"  Transient error on {label} (attempt {attempt + 1}/{max_retries}), "
                      f"retrying in {delay}s: {exc}")
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc


# ---------------------------------------------------------------------------
# LLM client — raw HTTP, no LangChain
# ---------------------------------------------------------------------------

class LLM:
    """Minimal, backend-agnostic LLM client over OpenAI-compatible HTTP API.

    Works with vLLM, Google Gemini, OpenAI, OpenRouter, and any other
    OpenAI-compatible endpoint.
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.7, max_retries: int = 3,
                 timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self._client = None

    # -- public API --------------------------------------------------------

    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   temperature: float | None = None,
                   max_tokens: int | None = None) -> dict:
        """
        Send a chat completion request.

        Returns a dict with keys:
            content        — str (text content or None if tool_calls present)
            tool_calls     — list[{"name": ..., "arguments": dict, "id": ...}] or []
            input_tokens   — int
            output_tokens  — int
            raw            — full API response dict
        """
        async def _do_chat():
            body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature if temperature is not None else self.temperature,
            }
            if tools:
                body["tools"] = tools
            if max_tokens:
                body["max_tokens"] = max_tokens

            response = await self._post("/chat/completions", body)
            return self._parse_chat_response(response)

        return await _retry_async(_do_chat, self.max_retries, label=f"chat({self.model})")

    async def stream(self, messages: list[dict],
                     tools: list[dict] | None = None,
                     temperature: float | None = None) -> AsyncIterator[str]:
        """Stream text tokens from the API."""
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        client = self._get_client()
        url = f"{self.base_url}/chat/completions"
        headers = self._headers()

        async with client.stream("POST", url, json=body, headers=headers,
                                  timeout=self.timeout) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise RuntimeError(f"Stream error {resp.status_code}: {text.decode()[:500]}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

    async def health_check(self) -> bool:
        """Ping the API with a tiny request."""
        async def _ping():
            resp = await self._post("/chat/completions", {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            })
            return True

        await _retry_async(_ping, max_retries=2, base_delay=2.0, label="health_check")
        return True

    def health_check_sync(self) -> bool:
        """Synchronous health check (for use outside async context)."""
        import httpx
        timeout = httpx.Timeout(self.timeout, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            url = f"{self.base_url}/chat/completions"
            for attempt in range(3):
                try:
                    resp = client.post(url, json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "temperature": 0,
                    }, headers=self._headers())
                    if resp.status_code == 200:
                        return True
                    raise RuntimeError(f"Error code: {resp.status_code} - {resp.text[:200]}")
                except Exception as exc:
                    if _is_transient_error(exc) and attempt < 2:
                        delay = 2.0 * (2 ** attempt)
                        time.sleep(delay)
                    else:
                        raise
        return True

    # -- internals ---------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10.0))
        return self._client

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _post(self, path: str, body: dict) -> dict:
        client = self._get_client()
        url = f"{self.base_url}{path}"
        resp = await client.post(url, json=body, headers=self._headers())

        if resp.status_code != 200:
            raise RuntimeError(
                f"Error code: {resp.status_code} - {resp.text[:500]}"
            )
        return resp.json()

    @staticmethod
    def _parse_chat_response(api_response: dict) -> dict:
        """Parse an OpenAI-compatible chat completion response."""
        choice = api_response["choices"][0]
        message = choice["message"]
        content = message.get("content")
        tool_calls_raw = message.get("tool_calls")

        # Normalize tool calls
        tool_calls = []
        if tool_calls_raw:
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_raw = func.get("arguments", "{}")
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "id": tc.get("id", f"call-{uuid.uuid4().hex[:12]}"),
                    "name": func.get("name", ""),
                    "arguments": args,
                })

        usage = api_response.get("usage", {})
        return {
            "content": content,
            "tool_calls": tool_calls,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "raw": api_response,
        }


# ---------------------------------------------------------------------------
# Public API — raw HTTP (primary, recommended)
# ---------------------------------------------------------------------------

def get_llm(temperature: float | None = None, **kwargs) -> LLM:
    """Return an LLM instance connected to the first working backend.

    Uses raw HTTP (no LangChain).  Tries each backend in router_config.yaml
    order and runs a health check on each.
    """
    config = load_config()
    backends = config["backends"]
    defaults = config.get("defaults", {})
    max_retries: int = defaults.get("max_retries", 3)

    last_error: Exception | None = None

    for backend in backends:
        url = backend["base_url"]
        if not url:
            continue

        llm_kwargs = dict(
            base_url=url,
            api_key=backend["api_key"] or "key",
            model=backend["model"],
            temperature=temperature if temperature is not None else defaults.get("temperature", 0.7),
            max_retries=max_retries,
        )

        try:
            llm = LLM(**llm_kwargs)
            llm.health_check_sync()
            print(f"LLM Router connected to backend: {backend['name']} ({url})")
            return llm
        except Exception as exc:
            last_error = exc
            print(f"LLM Router backend {backend['name']} ({url}) failed: {exc}")

    raise RuntimeError(
        f"All LLM backends failed. Last error: {last_error}\n"
        "Check router_config.yaml and ensure at least one backend is reachable."
    )


# ---------------------------------------------------------------------------
# Public API — LangChain wrapper (backward compat for existing chains)
# ---------------------------------------------------------------------------

def get_llm_langchain(temperature: float | None = None, **kwargs):
    """Return a LangChain ChatOpenAI instance connected to the first
    working backend.  Use this only if your code depends on LangChain
    (e.g. LCEL chains, LangGraph).
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain_openai is not installed. "
            "Install it with: pip install langchain-openai"
        )

    config = load_config()
    backends = config["backends"]
    defaults = config.get("defaults", {})
    max_retries: int = defaults.get("max_retries", 2)

    last_error: Exception | None = None

    for backend in backends:
        url = backend["base_url"]
        if not url:
            continue

        llm_kwargs = dict(
            base_url=url,
            api_key=backend["api_key"] or "key",
            model=backend["model"],
            temperature=temperature if temperature is not None else defaults.get("temperature", 0.7),
            max_retries=max_retries,
            **kwargs,
        )

        try:
            llm = ChatOpenAI(**llm_kwargs)
            # Quick health check with retries
            for attempt in range(3):
                try:
                    llm.invoke("ping")
                    print(f"LLM Router connected to backend: {backend['name']} ({url})")
                    return llm
                except Exception as exc:
                    if _is_transient_error(exc) and attempt < 2:
                        delay = 2.0 * (2 ** attempt)
                        print(f"  Transient error on health check (attempt {attempt + 1}/3), "
                              f"retrying in {delay}s: {exc}")
                        time.sleep(delay)
                    else:
                        raise
        except Exception as exc:
            last_error = exc
            print(f"LLM Router backend {backend['name']} ({url}) failed: {exc}")

    raise RuntimeError(
        f"All LLM backends failed. Last error: {last_error}\n"
        "Check router_config.yaml and ensure at least one backend is reachable."
    )


# Convenience: chat with any backend (no LangChain graph needed)
async def chat(prompt: str, temperature: float = 0.7) -> str:
    """Simple chat helper — just send a prompt and get back a string."""
    llm = get_llm(temperature=temperature)
    result = await llm.chat([{"role": "user", "content": prompt}])
    return result["content"] or ""
