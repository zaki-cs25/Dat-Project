"""Runtime configuration, populated from environment variables.

Centralising config here means the rest of the package never reads os.environ
directly, which makes tests easier (monkeypatch one object) and the surface
of "what knobs exist" visible in one file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    llm_provider: str
    openai_api_key: str | None
    openai_model: str
    anthropic_api_key: str | None
    anthropic_model: str
    ollama_base_url: str
    ollama_model: str
    fhir_base_url: str
    fhir_user: str | None
    fhir_password: str | None
    iris_rest_base_url: str
    llm_api_key: str | None = None
    openai_base_url: str | None = None
    openai_json_mode: bool = True
    openai_token_limit_param: str = "max_completion_tokens"
    openai_chat_template_kwargs: dict = field(default_factory=dict)
    care_catalogue_path: str = "md_care_documents/.preparation/catalogue.json"
    care_generation_mode: str = "enriched"
    care_context_max_chars: int = 24000
    model_input_max_chars: int = 120000
    benchmark_api_enabled: bool = False
    llm_backend: str = 'generic'
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 1
    llm_retry_backoff_seconds: float = 0.5
    llm_stream: bool = False
    llm_temperature: float | None = None
    llm_top_p: float | None = None
    llm_seed: int | None = None
    llm_max_output_tokens: int = 2048
    serving_metadata: dict = field(default_factory=dict)
    serving_metrics_url: str | None = None
    host_metrics_url: str | None = None
    embedding_provider: str = 'openai'
    embedding_model: str = 'text-embedding-3-small'
    embedding_base_url: str | None = None
    embedding_dimensions: int = 1536
    embedding_revision: str | None = None
    embedding_metrics_url: str | None = None


def _boolean(name: str, default: str) -> bool:
    value = os.environ.get(name, default).strip().lower()
    if value not in ("true", "false", "1", "0"):
        raise ValueError(f"{name} must be true or false")
    return value in ("true", "1")


def load() -> Config:
    care_mode = os.environ.get("CP_CARE_GENERATION_MODE", "enriched").lower()
    if care_mode not in ('enriched', 'grounded'):
        raise ValueError('CP_CARE_GENERATION_MODE must be enriched or grounded')
    context_limit = int(os.environ.get('CP_CARE_CONTEXT_MAX_CHARS', '24000'))
    if context_limit < 1000:
        raise ValueError('CP_CARE_CONTEXT_MAX_CHARS must be at least 1000')
    input_limit = int(os.environ.get('CP_MODEL_INPUT_MAX_CHARS', '120000'))
    if input_limit < 1000:
        raise ValueError('CP_MODEL_INPUT_MAX_CHARS must be at least 1000')
    backend = os.environ.get('CP_LLM_BACKEND', 'generic').lower()
    if backend not in ('generic', 'vllm', 'llamacpp'):
        raise ValueError('CP_LLM_BACKEND must be generic, vllm or llamacpp')
    timeout = _number('CP_LLM_TIMEOUT_SECONDS', 60.0, low=0.01, high=3600)
    retries = _integer('CP_LLM_MAX_RETRIES', 1, low=0, high=5)
    backoff = _number('CP_LLM_RETRY_BACKOFF_SECONDS', 0.5, low=0, high=30)
    temperature = _optional_number('CP_LLM_TEMPERATURE', low=0, high=2)
    top_p = _optional_number('CP_LLM_TOP_P', low=0.000001, high=1)
    seed = int(os.environ['CP_LLM_SEED']) if os.environ.get('CP_LLM_SEED') else None
    return Config(
        # OpenAI is the default so the chat LLM call is reliable. IRIS handles
        # embeddings via its independent CP_EMBEDDING_* configuration, so the sidecar
        # only does chat. Switch to anthropic by setting CP_LLM_PROVIDER and
        # ANTHROPIC_API_KEY. Ollama is supported but experimental on ARM64.
        llm_provider=os.environ.get("CP_LLM_PROVIDER", "openai").lower(),
        care_catalogue_path=os.environ.get("CP_CARE_CATALOGUE_PATH", "md_care_documents/.preparation/catalogue.json"),
        care_generation_mode=care_mode,
        care_context_max_chars=context_limit,
        model_input_max_chars=input_limit,
        benchmark_api_enabled=_boolean('CP_BENCHMARK_API_ENABLED', 'false'),
        llm_backend=backend, llm_timeout_seconds=timeout, llm_max_retries=retries,
        llm_retry_backoff_seconds=backoff, llm_stream=_boolean('CP_LLM_STREAM', 'false'),
        llm_temperature=temperature, llm_top_p=top_p, llm_seed=seed,
        llm_max_output_tokens=_integer('CP_LLM_MAX_OUTPUT_TOKENS', 2048, low=1, high=1000000),
        serving_metadata=_serving_metadata(),
        serving_metrics_url=_optional_url('CP_SERVING_METRICS_URL'),
        host_metrics_url=_optional_url('CP_HOST_METRICS_URL'),
        embedding_provider=os.environ.get('CP_EMBEDDING_PROVIDER', 'openai'),
        embedding_model=os.environ.get('CP_EMBEDDING_MODEL', 'text-embedding-3-small'),
        embedding_base_url=_optional_url('CP_EMBEDDING_BASE_URL'),
        embedding_dimensions=_integer('CP_EMBEDDING_DIMENSIONS', 1536, low=1, high=65536),
        embedding_revision=os.environ.get('CP_EMBEDDING_REVISION') or None,
        embedding_metrics_url=_optional_url('CP_EMBEDDING_METRICS_URL'),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_model=os.environ.get("CP_OPENAI_MODEL", "gpt-4o-mini"),
        llm_api_key=os.environ.get("CP_LLM_API_KEY") or None,
        openai_base_url=os.environ.get("CP_OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or None,
        openai_json_mode=_boolean("CP_OPENAI_JSON_MODE", "true"),
        openai_token_limit_param=os.environ.get("CP_OPENAI_TOKEN_LIMIT_PARAM", "max_completion_tokens"),
        openai_chat_template_kwargs=_chat_template_kwargs(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("CP_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        ollama_base_url=os.environ.get("CP_OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        ollama_model=os.environ.get("CP_OLLAMA_MODEL", "llama3.2:3b"),
        fhir_base_url=os.environ.get(
            "CP_FHIR_BASE_URL",
            "http://localhost:52773/csp/healthshare/centralpark/fhir/r4",
        ),
        fhir_user=os.environ.get("CP_FHIR_USER"),
        fhir_password=os.environ.get("CP_FHIR_PASSWORD"),
        iris_rest_base_url=os.environ.get(
            "CP_IRIS_REST_BASE_URL",
            "http://iris:52773/centralpark",
        ),
    )


def _chat_template_kwargs() -> dict:
    try:
        value = json.loads(os.environ.get("CP_OPENAI_CHAT_TEMPLATE_KWARGS") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("CP_OPENAI_CHAT_TEMPLATE_KWARGS must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("CP_OPENAI_CHAT_TEMPLATE_KWARGS must be a JSON object")
    return value


def _number(name, default, *, low, high):
    import math
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return value


def _integer(name, default, *, low, high):
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return value


def _optional_number(name, *, low, high):
    return _number(name, 0, low=low, high=high) if os.environ.get(name) else None


def _optional_url(name):
    from urllib.parse import urlsplit
    value = os.environ.get(name) or None
    if value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f'{name} must be an HTTP(S) URL without credentials, query or fragment')
    return value


def _serving_metadata():
    value = json.loads(os.environ.get('CP_SERVING_METADATA') or '{}')
    allowed = {'model_revision', 'weights_identity', 'quantization', 'tokenizer', 'chat_template',
               'context_limit_tokens', 'server_version', 'parallelism', 'cache_policy', 'hardware',
               'embedding_model', 'embedding_endpoint', 'embedding_dimensions', 'collector_location',
               'n_ctx', 'max_model_len'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('CP_SERVING_METADATA has unknown fields; only serving identity metadata is allowed')
    # Reject nested free-form configuration that could accidentally contain credentials.
    if any(v is not None and (type(v) not in (str, int, float, bool)) for v in value.values()):
        raise ValueError('CP_SERVING_METADATA values must be scalar or null')
    for name in ('context_limit_tokens', 'embedding_dimensions', 'n_ctx', 'max_model_len'):
        if name in value and value[name] is not None and (type(value[name]) is not int or value[name] < 1):
            raise ValueError(f'CP_SERVING_METADATA {name} must be a positive integer')
    if value.get('embedding_endpoint'):
        from urllib.parse import urlsplit
        endpoint = urlsplit(value['embedding_endpoint'])
        if endpoint.scheme not in ('http', 'https') or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError('Embedding metadata endpoint must be HTTP(S) without credentials')
    return value
