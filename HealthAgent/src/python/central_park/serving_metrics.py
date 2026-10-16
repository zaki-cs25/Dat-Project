"""Read-only serving and host metrics collectors.

Values from Prometheus are server aggregates. Request-level attribution is never
inferred from process-wide counters.
"""
from __future__ import annotations

import math
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

_SAMPLE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|NaN|[+-]?Inf)(?:\s+\d+)?$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')
_SAFE_LABELS = {'device', 'gpu', 'model_name', 'model', 'le', 'cpu', 'mode', 'engine',
                'engine_id', 'quantile'}


def _get(cfg, name, default=None):
    if cfg is None:
        return default
    return cfg.get(name, default) if isinstance(cfg, dict) else getattr(cfg, name, default)


def _metrics_url(cfg):
    value = _get(cfg, 'serving_metrics_url')
    if value:
        return value
    base = (_get(cfg, 'openai_base_url') or _get(cfg, 'llm_endpoint') or
            (_get(cfg, 'ollama_base_url') if _get(cfg, 'llm_provider') == 'ollama' else None))
    if not base or _get(cfg, 'llm_backend', 'generic') not in ('vllm', 'llamacpp'):
        return None
    parsed = urlsplit(str(base))
    host = f'[{parsed.hostname}]' if parsed.hostname and ':' in parsed.hostname else parsed.hostname
    if not parsed.scheme or not host:
        return None
    # Both backends expose metrics at server root, outside the OpenAI /v1 path.
    return urlunsplit((parsed.scheme, host + (f':{parsed.port}' if parsed.port else ''), '/metrics', '', ''))


def _parse_prometheus(text):
    definitions, samples = {}, []
    for line in text.splitlines():
        if line.startswith('# HELP '):
            parts = line.split(' ', 3)
            if len(parts) == 4:
                definitions.setdefault(parts[2], {})['description'] = parts[3]
            continue
        if line.startswith('# TYPE '):
            parts = line.split()
            if len(parts) >= 4:
                definitions.setdefault(parts[2], {})['type'] = parts[3]
            continue
        match = _SAMPLE.match(line.strip())
        if not match:
            continue
        name, raw_labels, raw_value = match.groups()
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        labels = {}
        for key, raw in _LABEL.findall(raw_labels or ''):
            if key in _SAFE_LABELS:
                labels[key] = raw.replace('\\"', '"').replace('\\\\', '\\')[:120]
        samples.append({'name': name, 'value': value, 'labels': labels})
    return definitions, samples


def _unit(name):
    n = name.lower()
    if n.endswith(('_count', '_bucket')):
        return 'count'
    if n.endswith('_seconds') or '_seconds_' in n:
        return 'seconds'
    if n.endswith('_bytes') or '_bytes_' in n:
        return 'bytes'
    if n.endswith('_ratio'):
        return 'ratio'
    return 'unknown'


def _normalized_sample(sample):
    output = {**sample, 'unit': _unit(sample['name'])}
    if sample['name'].endswith('_bucket') and 'le' in sample['labels']:
        bound_unit = _unit(sample['name'][:-len('_bucket')])
        if bound_unit in ('seconds', 'bytes', 'ratio'):
            output['bucket_bound_unit'] = bound_unit
    return output


def _fetch(url, cfg, *, use_serving_credential=True):
    import urllib.request
    headers = {}
    key = (_get(cfg, 'llm_api_key') or _get(cfg, 'openai_api_key')) if use_serving_credential else None
    if key:
        headers['Authorization'] = 'Bearer ' + str(key)
    request = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read(2 * 1024 * 1024).decode('utf-8', errors='replace')


def collect(cfg=None) -> dict:
    """Collect configured Prometheus and local host samples without inference."""
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    out = {'serving': {'available': False, 'scope': 'server_aggregate', 'definitions': {}, 'samples': []},
           'embedding': {'available': False, 'scope': 'embedding_server_aggregate',
                         'definitions': {}, 'samples': []},
           'host': {'available': False, 'scope': 'collector_host', 'location': None, 'samples': []},
           'limitations': ['server metrics are aggregate and cannot be attributed to an individual request',
                           'unsupported or unadvertised metrics remain unknown']}
    url = _metrics_url(cfg)
    if url:
        # Protect credentials and avoid unsafe schemes before making a request.
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                raise ValueError('invalid metrics URL')
            model_base = (_get(cfg, 'openai_base_url') or _get(cfg, 'llm_endpoint') or
                          (_get(cfg, 'ollama_base_url') if _get(cfg, 'llm_provider') == 'ollama' else None))
            model_parsed = urlsplit(str(model_base)) if model_base else None
            same_origin = bool(model_parsed and model_parsed.scheme == parsed.scheme and
                               model_parsed.hostname == parsed.hostname and model_parsed.port == parsed.port)
            raw = _fetch(url, cfg, use_serving_credential=same_origin)
            definitions, samples = _parse_prometheus(raw)
            valid = bool(definitions or samples)
            out['serving'].update(available=valid, endpoint=f'{parsed.scheme}://{parsed.hostname}' +
                                  (f':{parsed.port}' if parsed.port else ''), definitions=definitions,
                                  samples=[_normalized_sample(s) for s in samples])
            if not valid:
                out['serving']['error'] = 'unrecognized_metrics_format'
        except Exception as exc:
            out['serving']['error'] = type(exc).__name__
            status = getattr(exc, 'code', None)
            if isinstance(status, int):
                out['serving']['http_status'] = status
    host_url = _get(cfg, 'host_metrics_url')
    if host_url:
        out['host'] = collect_external_host(host_url)
    else:
        out['host'] = collect_host(cfg)
    embedding_url = _get(cfg, 'embedding_metrics_url')
    if embedding_url:
        out['embedding'] = collect_embedding_metrics(embedding_url)
    out['collected_at'] = started_at
    out['collection_duration_seconds'] = max(0.0, time.perf_counter() - started)
    return out


def collect_host(cfg=None) -> dict:
    """Read local proc counters and optionally bounded nvidia-smi telemetry."""
    import os
    result = {'available': False, 'scope': 'collector_host',
              'location': _get(cfg, 'serving_metadata', {}).get('collector_location', 'container_or_process_namespace')
                          if isinstance(_get(cfg, 'serving_metadata', {}), dict) else 'container_or_process_namespace',
              'hostname': socket.gethostname(), 'pid': os.getpid(), 'cpu_available': False,
              'memory_available': False, 'gpu_available': False, 'gpu_error_type': None,
              'cpu_total_ticks': None,
              'cpu_idle_ticks': None, 'cpu_ticks_per_second': None,
              'memory_total_bytes': None, 'memory_available_bytes': None, 'gpu': []}
    try:
        with open('/proc/stat', encoding='ascii') as stream:
            fields = [int(value) for value in stream.readline().split()[1:9]]
            result['cpu_total_ticks'] = sum(fields)
            result['cpu_idle_ticks'] = fields[3] + (fields[4] if len(fields) > 4 else 0)
            result['cpu_ticks_per_second'] = os.sysconf('SC_CLK_TCK')
            result['cpu_available'] = True
    except (OSError, ValueError):
        pass
    try:
        with open('/proc/meminfo', encoding='ascii') as stream:
            memory = {}
            for line in stream:
                key, value = line.split(':', 1)
                if key in ('MemTotal', 'MemAvailable'):
                    memory[key] = int(value.strip().split()[0]) * 1024
            result['memory_total_bytes'] = memory.get('MemTotal')
            result['memory_available_bytes'] = memory.get('MemAvailable')
            result['memory_available'] = bool(memory)
    except (OSError, ValueError):
        pass
    try:
        run = subprocess.run(['nvidia-smi', '--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw',
                              '--format=csv,noheader,nounits'], capture_output=True, text=True,
                             timeout=1, check=True)
        result['gpu_available'] = True
        for line in run.stdout.splitlines():
            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 6:
                continue
            try:
                util = float(parts[1])
                mem_used = float(parts[2])
                mem_total = float(parts[3])
                result['gpu'].append({'index': int(parts[0]), 'utilization_percent': util,
                                      'utilization_ratio': util / 100.0,
                                      'memory_used_mib': mem_used, 'memory_total_mib': mem_total,
                                      'memory_used_bytes': int(mem_used * 1024 * 1024),
                                      'memory_total_bytes': int(mem_total * 1024 * 1024),
                                      'temperature_celsius': float(parts[4]), 'power_watts': float(parts[5]),
                                      'origin': 'host_nvidia_smi'})
            except ValueError:
                continue
    except (OSError, subprocess.SubprocessError) as exc:
        result['gpu_error_type'] = type(exc).__name__
    result['available'] = result['cpu_available'] or result['memory_available'] or result['gpu_available']
    return result


def collect_external_host(url: str) -> dict:
    """Fetch an explicitly configured host exporter without forwarding serving API keys."""
    result = {'available': False, 'scope': 'host_aggregate', 'collector_location': 'external_exporter',
              'definitions': {}, 'samples': []}
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('invalid host metrics URL')
        raw = _fetch(url, None, use_serving_credential=False)
        definitions, samples = _parse_prometheus(raw)
        result.update(available=bool(definitions or samples),
                      endpoint=f'{parsed.scheme}://{parsed.hostname}' + (f':{parsed.port}' if parsed.port else ''),
                      definitions=definitions, samples=[_normalized_sample(s) for s in samples])
        if not result['available']:
            result['error'] = 'unrecognized_metrics_format'
    except Exception as exc:
        result['error'] = type(exc).__name__
        status = getattr(exc, 'code', None)
        if isinstance(status, int):
            result['http_status'] = status
    return result


def collect_embedding_metrics(url: str) -> dict:
    """Fetch the configured embedding exporter without chat credentials."""
    result = {'available': False, 'scope': 'embedding_server_aggregate',
              'definitions': {}, 'samples': []}
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('invalid embedding metrics URL')
        raw = _fetch(url, None, use_serving_credential=False)
        definitions, samples = _parse_prometheus(raw)
        result.update(available=bool(definitions or samples),
                      endpoint=f'{parsed.scheme}://{parsed.hostname}' + (f':{parsed.port}' if parsed.port else ''),
                      definitions=definitions, samples=[_normalized_sample(s) for s in samples])
        if not result['available']:
            result['error'] = 'unrecognized_metrics_format'
    except Exception as exc:
        result['error'] = type(exc).__name__
        status = getattr(exc, 'code', None)
        if isinstance(status, int):
            result['http_status'] = status
    return result
