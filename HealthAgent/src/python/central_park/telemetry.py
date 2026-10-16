"""Correlated timing spans. Events carry metadata, never patient text or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4

from central_park import benchmark_context as bench

_PARENT = ContextVar('telemetry_parent', default=None)
_MODEL_STAGE = ContextVar('telemetry_model_stage', default='unspecified')
_MODEL_META = ContextVar('telemetry_model_metadata', default={})


def current_stage():
    return _MODEL_STAGE.get()


def current_model_metadata():
    return dict(_MODEL_META.get())


def event(name, **data):
    return bench.emit(name, parent_span_id=_PARENT.get(), **data)


@contextmanager
def span(stage, **metadata):
    parent = _PARENT.get()
    identifier = str(uuid4())
    data = {'span_id': identifier, 'parent_span_id': parent, 'status': 'ok', **metadata}
    token = _PARENT.set(identifier)
    started = perf_counter()
    bench.emit(stage + '.started', **data)
    try:
        yield data
    except BaseException as exc:
        data['status'] = 'error'
        data['error_type'] = type(exc).__name__
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if isinstance(status, int):
            data['http_status'] = status
        raise
    finally:
        data['duration_seconds'] = perf_counter() - started
        data['measurement_origin'] = 'application_monotonic_clock'
        bench.emit(stage + '.finished', **data)
        _PARENT.reset(token)


def timed(stage):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with span(stage):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


@contextmanager
def model_stage(stage, **metadata):
    stage_token = _MODEL_STAGE.set(stage)
    metadata_token = _MODEL_META.set(metadata)
    try:
        with span(stage, **metadata) as data:
            yield data
    finally:
        _MODEL_META.reset(metadata_token)
        _MODEL_STAGE.reset(stage_token)
