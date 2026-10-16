"""Trace/profile invariants using synthetic inputs and mocked collectors."""
import json

import pytest

from central_park import benchmark_context as bench, care_jobs, main, telemetry
from central_park.config import load
from test_benchmark_jobs import job_store


@pytest.mark.parametrize('key,value', [
    ('CP_LLM_BACKEND', 'unsupported'), ('CP_LLM_TIMEOUT_SECONDS', 'nan'),
    ('CP_LLM_MAX_RETRIES', '-1'), ('CP_LLM_TOP_P', '1.1'),
    ('CP_LLM_TEMPERATURE', '-0.1'), ('CP_LLM_RETRY_BACKOFF_SECONDS', '31'),
    ('CP_LLM_MAX_OUTPUT_TOKENS', '0'),
    ('CP_SERVING_METRICS_URL', 'http://user:secret@example/metrics'),
    ('CP_HOST_METRICS_URL', 'file:///etc/passwd'),
    ('CP_SERVING_METADATA', '{"api_key":"secret"}'),
    ('CP_SERVING_METADATA', '{"context_limit_tokens":0}'),
])
def test_invalid_measurement_configuration_fails_early(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        load()


def test_nested_spans_keep_parent_ids_and_error_types_without_content():
    token = bench.EVENTS.set([])
    correlation = bench.CORRELATION.set({'run_id': 'synthetic-run'})
    try:
        with pytest.raises(ValueError):
            with telemetry.span('operation') as outer:
                with telemetry.span('parse'):
                    raise ValueError('sensitive patient narrative must not be stored')
        events = bench.EVENTS.get()
        inner = next(e for e in events if e['stage'] == 'parse.finished')
        assert inner['parent_span_id'] == outer['span_id']
        assert inner['duration_seconds'] >= 0
        assert inner['error_type'] == 'ValueError' and inner['status'] == 'error'
        assert inner['run_id'] == 'synthetic-run'
        assert 'sensitive patient' not in json.dumps(events)
    finally:
        bench.EVENTS.reset(token)
        bench.CORRELATION.reset(correlation)


def test_failure_summary_does_not_copy_provider_response_or_credentials():
    import httpx
    request = httpx.Request('POST', 'https://provider.example/v1/chat/completions')
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError('private server body with api_key=hidden', request=request, response=response)
    summary = care_jobs.failure_reason(exc)
    assert 'HTTP 503' in summary and 'HTTPStatusError' in summary
    assert 'hidden' not in summary and 'private' not in summary


@pytest.mark.parametrize('key,value', [
    ('CP_LLM_STREAM', 'true'), ('CP_LLM_TEMPERATURE', '0.8'),
    ('CP_LLM_TIMEOUT_SECONDS', '90'), ('CP_SERVING_METADATA', '{"model_revision":"different"}'),
    ('CP_EMBEDDING_DIMENSIONS', '1024'),
])
def test_queue_freezes_full_generation_profile(monkeypatch, job_store, key, value):
    store, _ = job_store
    monkeypatch.setenv('CP_LLM_STREAM', 'false')
    monkeypatch.setenv('CP_EMBEDDING_DIMENSIONS', '1536')
    queued = care_jobs.enqueue('p', 'q', 'a')
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(care_jobs, 'generate', lambda c: pytest.fail('Changed profile executed'))
    care_jobs.process(store['Task/' + queued['job_id']])
    result = care_jobs.detail(queued['job_id'])
    assert result['status'] == 'failed' and 'configuration changed' in result['reason']
    assert result['queue_wait_seconds'] is None or result['queue_wait_seconds'] >= 0
    assert result['trace_ready'] is True


def test_serving_apis_are_disabled_by_default(monkeypatch):
    monkeypatch.setenv('CP_BENCHMARK_API_ENABLED', 'false')
    for fn in (main.serving_profile, main.serving_capabilities, main.serving_metric_snapshot):
        with pytest.raises(main.HTTPException) as error:
            fn()
        assert error.value.status_code == 404


def test_serving_http_endpoints_return_profile_and_mocked_collector(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv('CP_BENCHMARK_API_ENABLED', 'true')
    monkeypatch.setenv('CP_LLM_API_KEY', 'never-export-this-key')
    monkeypatch.setattr(main.serving_metrics, 'collect', lambda cfg: {
        'serving': {'available': False, 'scope': 'server_aggregate'},
        'host': {'available': False}})
    api = TestClient(main.app)
    profile = api.get('/benchmark/serving/profile')
    assert profile.status_code == 200 and profile.json()['profile_id']
    assert 'never-export' not in profile.text
    metrics = api.get('/benchmark/serving/metrics')
    assert metrics.status_code == 200 and metrics.json()['serving']['scope'] == 'server_aggregate'
