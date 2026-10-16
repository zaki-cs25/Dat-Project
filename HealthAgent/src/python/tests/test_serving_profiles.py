from types import SimpleNamespace
from urllib.error import HTTPError

from central_park import serving_metrics, serving_profiles


def test_snapshot_is_stable_secret_free_and_hashes_content():
    cfg = SimpleNamespace(llm_provider='openai', openai_model='local-model',
                          openai_base_url='https://user:secret@inference.example/v1?token=secret',
                          llm_backend='vllm', llm_api_key='top-secret',
                          serving_metadata={'model_revision': 'abc', 'context_limit_tokens': 8192,
                                            'unknown': 'should not leak'})
    profile = serving_profiles.snapshot(cfg)
    assert profile['api_endpoint'] == 'https://inference.example/v1'
    assert profile['model_revision'] == 'abc'
    assert profile['context_limit_tokens'] == 8192
    assert 'secret' not in repr(profile)
    assert profile['profile_id'] == serving_profiles.snapshot(cfg)['profile_id']
    cfg.serving_metadata['model_revision'] = 'def'
    assert profile['profile_id'] != serving_profiles.snapshot(cfg)['profile_id']


def test_prometheus_parser_keeps_only_safe_labels_and_finite_values():
    definitions, samples = serving_metrics._parse_prometheus('''
# HELP vllm_request_success_total Number of requests
# TYPE vllm_request_success_total counter
vllm_request_success_total{model_name="m",request_id="patient-1"} 7
vllm_bad NaN
''')
    assert definitions['vllm_request_success_total']['type'] == 'counter'
    assert samples == [{'name': 'vllm_request_success_total', 'value': 7.0,
                        'labels': {'model_name': 'm'}}]


def test_free_form_error_reason_labels_are_omitted():
    _, samples = serving_metrics._parse_prometheus(
        'request_failures{reason="private failure details",engine="0"} 3')
    assert samples[0]['labels'] == {'engine': '0'}


def test_collect_without_config_never_probes_or_infers_gpu(monkeypatch):
    monkeypatch.setattr(serving_metrics.subprocess, 'run',
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    result = serving_metrics.collect({})
    assert result['serving']['available'] is False
    assert result['host']['gpu'] == []
    assert result['serving']['scope'] == 'server_aggregate'


def test_configured_capability_probe_uses_safe_v1_path_and_keeps_unknowns(monkeypatch):
    seen = {}

    class Response:
        headers = {'X-Server-Version': 'v1'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return b'{"data":[{"id":"m","meta":{"n_ctx":4096}}]}'

    def fake_open(request, timeout):
        seen['url'] = request.full_url
        assert request.get_header('Authorization') == 'Bearer secret'
        return Response()

    monkeypatch.setattr('urllib.request.urlopen', fake_open)
    cfg = SimpleNamespace(openai_base_url='https://user:pw@host.example/v1/tenant?token=bad',
                          openai_model='m', llm_api_key='secret', serving_metadata={})
    result = serving_profiles.capabilities(cfg)
    assert seen['url'] == 'https://host.example/v1/tenant/models'
    assert result['context_limit_tokens'] == 4096
    assert result['embedding_dimensions'] is None
    assert 'pw' not in repr(result)


def test_metrics_reject_html_and_external_host_does_not_receive_chat_key(monkeypatch):
    monkeypatch.setattr(serving_metrics, '_fetch',
                        lambda url, cfg, **kwargs: '<html>no metrics</html>')
    out = serving_metrics.collect_external_host('http://exporter.example/metrics')
    assert not out['available']
    assert out['error'] == 'unrecognized_metrics_format'

    calls = []

    def fetch(url, cfg, *, use_serving_credential=True):
        calls.append(use_serving_credential)
        return '# TYPE cpu_usage_ratio gauge\ncpu_usage_ratio 0.3\n'

    monkeypatch.setattr(serving_metrics, '_fetch', fetch)
    host = serving_metrics.collect_external_host('http://exporter.example/metrics')
    assert host['available']
    assert calls == [False]


def test_histogram_counts_do_not_claim_seconds_and_metadata_location_is_recorded():
    assert serving_metrics._unit('request_duration_seconds_bucket') == 'count'
    assert serving_metrics._unit('gpu_utilization_percent') == 'unknown'
    cfg = SimpleNamespace(serving_metadata={'collector_location': 'host'}, llm_backend='generic')
    assert serving_metrics.collect_host(cfg)['location'] == 'host'


def test_provider_endpoint_selection_and_generation_metadata_identity():
    openai_cfg = SimpleNamespace(llm_provider='openai', openai_model='gpt',
                                 ollama_base_url='http://ollama.internal:11434',
                                 openai_chat_template_kwargs={'enable_thinking': False})
    ollama_cfg = SimpleNamespace(llm_provider='ollama', ollama_model='local',
                                 ollama_base_url='http://ollama.internal:11434')
    assert serving_profiles.snapshot(openai_cfg)['api_endpoint'] == 'https://api.openai.com/v1'
    ollama_profile = serving_profiles.snapshot(ollama_cfg)
    assert ollama_profile['api_endpoint'] == 'http://ollama.internal:11434'
    assert serving_profiles.snapshot(openai_cfg)['thinking'] is False

    metrics_cfg = SimpleNamespace(llm_provider='openai', openai_model='gpt',
                                  serving_metrics_url='https://metrics.internal/prometheus?token=hidden',
                                  host_metrics_url='http://node.internal:9100/metrics')
    profile = serving_profiles.snapshot(metrics_cfg)
    assert profile['monitoring']['serving_metrics_endpoint'] == 'https://metrics.internal/prometheus'
    assert profile['monitoring']['host_metrics_endpoint'] == 'http://node.internal:9100/metrics'
    assert 'hidden' not in repr(profile)


def test_embedding_profile_prefers_runtime_config_and_hash_changes():
    cfg = SimpleNamespace(llm_provider='openai', openai_model='gpt',
                          serving_metadata={'embedding_model': 'stale', 'embedding_dimensions': 12,
                                            'embedding_endpoint': 'https://stale.example'},
                          embedding_provider='openai', embedding_model='text-embedding-3-small',
                          embedding_base_url='https://user:pw@embed.example/v1?key=x',
                          embedding_dimensions=1536, embedding_revision='rev-a',
                          embedding_metrics_url='http://embed.example/metrics?key=private')
    profile = serving_profiles.snapshot(cfg)
    assert profile['embedding'] == {'provider': 'openai', 'model': 'text-embedding-3-small',
                                    'endpoint': 'https://embed.example/v1',
                                    'dimensions': 1536, 'revision': 'rev-a'}
    assert profile['monitoring']['embedding_metrics_endpoint'] == 'http://embed.example/metrics'
    cfg.embedding_model = 'other-embed-model'
    assert profile['profile_id'] != serving_profiles.snapshot(cfg)['profile_id']


def test_embedding_metrics_collector_does_not_forward_chat_credentials(monkeypatch):
    calls = []

    def fetch(url, cfg, *, use_serving_credential=True):
        calls.append((url, cfg, use_serving_credential))
        return '# TYPE embed_queue_depth gauge\nembed_queue_depth 2\n'

    monkeypatch.setattr(serving_metrics, '_fetch', fetch)
    cfg = SimpleNamespace(embedding_metrics_url='http://embed.example/metrics',
                          llm_api_key='chat-secret', serving_metrics_url=None,
                          host_metrics_url='http://host.example/metrics',
                          serving_metadata={'collector_location': 'container'})
    monkeypatch.setattr(serving_metrics, 'collect_external_host',
                        lambda url: {'available': False, 'scope': 'host_aggregate'})
    out = serving_metrics.collect(cfg)
    assert out['embedding']['available']
    assert calls == [('http://embed.example/metrics', None, False)]
    assert 'collected_at' in out and out['collected_at'].endswith('+00:00')
    assert out['collection_duration_seconds'] >= 0


def test_http_501_is_reported_without_claiming_metrics_available(monkeypatch):
    def unavailable(*args, **kwargs):
        raise HTTPError('http://host.example/metrics', 501, 'disabled', None, None)

    monkeypatch.setattr('urllib.request.urlopen', unavailable)
    caps = serving_profiles.capabilities(SimpleNamespace(llm_provider='openai',
                                                           openai_base_url='http://host.example/v1'))
    assert caps['available'] is False
    assert caps['http_status'] == 501

    monkeypatch.setattr(serving_metrics, '_fetch', unavailable)
    embed = serving_metrics.collect_embedding_metrics('http://host.example/metrics')
    assert embed['available'] is False
    assert embed['http_status'] == 501


def test_collector_tracks_host_resource_availability_and_bucket_bound_units(monkeypatch):
    monkeypatch.setattr(serving_metrics.subprocess, 'run',
                        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    host = serving_metrics.collect_host({})
    assert host['cpu_available']
    assert host['memory_available']
    assert host['gpu_available'] is False
    assert host['gpu_error_type'] == 'FileNotFoundError'
    _, samples = serving_metrics._parse_prometheus(
        'request_duration_seconds_bucket{le="1.0",path="/patient/42"} 5')
    sample = serving_metrics._normalized_sample(samples[0])
    assert sample['unit'] == 'count'
    assert sample['bucket_bound_unit'] == 'seconds'
    assert 'path' not in sample['labels']
