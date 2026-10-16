"""Secret-free, reproducible descriptions of model serving configuration.

Snapshots are deliberately local: collecting one never probes a server.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from . import benchmark_context as bench

_METADATA_KEYS = {
    'model_revision', 'weights_identity', 'quantization', 'tokenizer',
    'chat_template', 'context_limit_tokens', 'server_version', 'parallelism',
    'cache_policy', 'hardware', 'monitoring', 'embedding_model',
    'embedding_endpoint', 'embedding_dimensions', 'collector_location',
    'embedding_provider', 'embedding_revision', 'n_ctx', 'max_model_len',
}


def _get(cfg, name, default=None):
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    return getattr(cfg, name, default)


def _safe_endpoint(value):
    if not value:
        return None
    try:
        p = urlsplit(str(value))
        if p.scheme not in ('http', 'https') or not p.hostname:
            return None
        host = f'[{p.hostname}]' if ':' in p.hostname else p.hostname
        port = f':{p.port}' if p.port else ''
        # Retain an API prefix (e.g. /v1/tenant) for serving identity, while
        # removing user-info and query strings where credentials often live.
        return urlunsplit((p.scheme, host + port, p.path.rstrip('/'), '', ''))
    except (ValueError, TypeError):
        return None


def _provider_endpoint(cfg, provider=None):
    provider = provider if provider is not None else _get(cfg, 'llm_provider')
    if provider == 'openai':
        return _get(cfg, 'openai_base_url') or 'https://api.openai.com/v1'
    if provider == 'anthropic':
        return _get(cfg, 'anthropic_base_url') or 'https://api.anthropic.com/v1'
    if provider == 'ollama':
        return _get(cfg, 'ollama_base_url') or 'http://localhost:11434'
    return _get(cfg, 'llm_endpoint')


def _safe_digest(value):
    try:
        return bench.digest(value)
    except (TypeError, ValueError):
        return None


def snapshot(cfg=None) -> dict:
    """Return a canonical-hashable serving profile with unknowns as null."""
    metadata = _get(cfg, 'serving_metadata', {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = {k: metadata.get(k) for k in sorted(_METADATA_KEYS) if k in metadata}
    backend = _get(cfg, 'llm_backend', 'generic')
    if backend not in ('generic', 'vllm', 'llamacpp'):
        backend = 'generic'
    provider = _get(cfg, 'llm_provider')
    template_kwargs = _get(cfg, 'openai_chat_template_kwargs', {}) or {}
    template_thinking = template_kwargs.get('enable_thinking') if isinstance(template_kwargs, dict) else None
    model = (_get(cfg, 'openai_model') if provider == 'openai' else
             _get(cfg, 'anthropic_model') if provider == 'anthropic' else
             _get(cfg, 'ollama_model') if provider == 'ollama' else
             _get(cfg, 'llm_model'))
    profile = {
        'provider': provider,
        'model': model,
        'backend': backend,
        'api_endpoint': _safe_endpoint(_provider_endpoint(cfg, provider)),
        'model_revision': metadata.get('model_revision'),
        'weights_identity': metadata.get('weights_identity'),
        'quantization': metadata.get('quantization'),
        'tokenizer': metadata.get('tokenizer'),
        'chat_template': metadata.get('chat_template'),
        'context_limit_tokens': metadata.get('context_limit_tokens') or metadata.get('n_ctx') or metadata.get('max_model_len'),
        'sampling': {
            'temperature': _get(cfg, 'llm_temperature'),
            'top_p': _get(cfg, 'llm_top_p'),
            'seed': _get(cfg, 'llm_seed'),
        },
        'timeout_seconds': _get(cfg, 'llm_timeout_seconds', 60),
        'max_retries': _get(cfg, 'llm_max_retries', 1),
        'retry_backoff_seconds': _get(cfg, 'llm_retry_backoff_seconds', 0.5),
        'stream': _get(cfg, 'llm_stream', False),
        'max_output_tokens': _get(cfg, 'llm_max_output_tokens', 2048),
        'stage_output_budgets': {
            'interview.question': _get(cfg, 'llm_max_output_tokens', 2048),
            'assessment': _get(cfg, 'llm_max_output_tokens', 2048),
            'assessment.review': _get(cfg, 'llm_max_output_tokens', 2048),
            'careplan.generation': 4096, 'careplan.review.enriched': 2048,
            'careplan.review.grounded': 1024,
        },
        'application_input_character_limit': _get(cfg, 'model_input_max_chars', 120000),
        'retrieval_character_budget': _get(cfg, 'care_context_max_chars', 24000),
        'thinking': template_thinking if type(template_thinking) is bool else _get(cfg, 'llm_thinking'),
        'json_mode': _get(cfg, 'openai_json_mode'),
        'token_limit_parameter': _get(cfg, 'openai_token_limit_param'),
        'chat_template_kwargs_sha256': _safe_digest(template_kwargs),
        'server_version': metadata.get('server_version'),
        'parallelism': metadata.get('parallelism'),
        'cache_policy': metadata.get('cache_policy'),
        'hardware': metadata.get('hardware'),
        'monitoring': {
            'collector_location': metadata.get('collector_location'),
            'serving_metrics_endpoint': _safe_endpoint(_get(cfg, 'serving_metrics_url')),
            'host_metrics_endpoint': _safe_endpoint(_get(cfg, 'host_metrics_url')),
            'embedding_metrics_endpoint': _safe_endpoint(_get(cfg, 'embedding_metrics_url')),
        },
        'embedding': {
            'provider': _get(cfg, 'embedding_provider', metadata.get('embedding_provider')),
            'model': _get(cfg, 'embedding_model', metadata.get('embedding_model')),
            'endpoint': _safe_endpoint(_get(cfg, 'embedding_base_url') or
                                       metadata.get('embedding_endpoint')),
            'dimensions': _get(cfg, 'embedding_dimensions', metadata.get('embedding_dimensions')),
            'revision': _get(cfg, 'embedding_revision', metadata.get('embedding_revision')),
        },
    }
    profile['profile_id'] = bench.digest(profile)
    return profile


def capabilities(cfg=None) -> dict:
    """Probe a configured OpenAI-compatible model listing using read-only GET."""
    import json
    import urllib.error
    import urllib.request

    base = (_get(cfg, 'openai_base_url') or _get(cfg, 'llm_endpoint') or
            (_get(cfg, 'ollama_base_url') if _get(cfg, 'llm_provider') == 'ollama' else None) or
            (_provider_endpoint(cfg) if _get(cfg, 'llm_provider') in ('openai', 'anthropic') else None))
    endpoint = _safe_endpoint(base)
    result = {'endpoint': endpoint, 'available': False, 'models': [],
              'model_advertised': None, 'embedding_dimensions': None,
              'measurement_origin': 'server_model_listing',
              'context_limit_tokens': None, 'server_version': None,
              'limitations': ['model listing does not advertise dimensions or context limits']}
    if not endpoint:
        result['error'] = 'no configured HTTP endpoint'
        return result
    # _safe_endpoint retains harmless API prefixes such as /v1/tenant.
    url = endpoint.rstrip('/') + '/models'
    headers = {}
    key = _get(cfg, 'llm_api_key') or _get(cfg, 'openai_api_key')
    if key:
        headers['Authorization'] = 'Bearer ' + str(key)
    req = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read(1024 * 1024))
            models = data.get('data', []) if isinstance(data, dict) else []
            ids = sorted({str(item['id']) for item in models if isinstance(item, dict) and item.get('id')})
            selected = next((item for item in models if isinstance(item, dict) and
                             item.get('id') == _get(cfg, 'openai_model')), None)
            selected = selected or (models[0] if len(models) == 1 and isinstance(models[0], dict) else {})
            meta = selected.get('meta') if isinstance(selected, dict) else None
            if isinstance(meta, dict):
                selected = {**selected, **meta}
            for field in ('context_limit_tokens', 'n_ctx', 'max_model_len', 'context_length'):
                value = selected.get(field) if isinstance(selected, dict) else None
                if type(value) is int and value > 0:
                    result['context_limit_tokens'] = value
                    break
            dimension = (selected.get('embedding_dimensions') or selected.get('n_embd')) if isinstance(selected, dict) else None
            if type(dimension) is int and dimension > 0:
                result['embedding_dimensions'] = dimension
            result.update(available=True, models=ids,
                          model_advertised=_get(cfg, 'openai_model') in ids if _get(cfg, 'openai_model') else None,
                          server_version=response.headers.get('X-Server-Version'))
    except Exception as exc:
        result['error'] = type(exc).__name__
        status = getattr(exc, 'code', None)
        if isinstance(status, int):
            result['http_status'] = status
    return result
