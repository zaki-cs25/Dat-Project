"""Frozen supplemental packets and safe trace metadata for API-driven benchmarks."""
from __future__ import annotations

import hashlib
import json
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PACKET_EXT = 'https://centralpark.example/fhir/StructureDefinition/clinical-input'
CORRELATION: ContextVar[dict] = ContextVar('benchmark_correlation', default={})
EVENTS: ContextVar[list | None] = ContextVar('benchmark_events', default=None)
_REQUESTS = {}
_REQUEST_LOCK = threading.Lock()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class PacketPatient(Strict):
    age: int = Field(ge=18, le=120)
    sex: str = Field(min_length=1, max_length=40)


class PacketObservation(Strict):
    name: str = Field(min_length=1)
    value: str | int | float | bool
    unit: str
    when: str = Field(min_length=1)


class ClinicalPacket(Strict):
    patient: PacketPatient
    established_conditions: list[str] = Field(min_length=1, max_length=50)
    medications: list[str] = Field(max_length=100)
    allergies: list[str] = Field(max_length=100)
    observations: list[PacketObservation] = Field(max_length=200)
    narrative: str = Field(min_length=1, max_length=60000)
    missing_information: list[str] = Field(max_length=100)
    request: str = Field(min_length=1, max_length=4000)


class CareOptions(Strict):
    mode: Literal['enriched', 'grounded'] | None = None
    use_icmr_context: bool = True


class Correlation(Strict):
    run_id: str | None = Field(default=None, max_length=100)
    case_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)
    turn_id: str | None = Field(default=None, max_length=100)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def snapshot(value):
    return json.loads(canonical(value))


def emit(stage, **data):
    event = {'stage': stage, 'at': datetime.now(timezone.utc).isoformat(),
             **CORRELATION.get(), **data}
    events = EVENTS.get()
    if events is not None:
        events.append(event)
    return event


def remember_request(request_id, events):
    with _REQUEST_LOCK:
        _REQUESTS[request_id] = snapshot(events)
        while len(_REQUESTS) > 1000:
            _REQUESTS.pop(next(iter(_REQUESTS)))


def request_trace(request_id):
    with _REQUEST_LOCK:
        if request_id not in _REQUESTS:
            raise KeyError('Request trace is unavailable or has expired')
        return {'request_id': request_id, 'trace': snapshot(_REQUESTS[request_id])}


def audit_model_input(stage, payload, ctx):
    """Verify the actual serialized model payload includes the original packet."""
    packet = ctx.get('supplemental_clinical_context')
    if packet is None:
        return
    expected = ctx.get('clinical_input_sha256')
    if not expected or digest(packet) != expected:
        raise ValueError('Supplemental clinical input hash mismatch')
    # The generator uses a top-level packet as well as a full context snapshot.
    actual = payload.get('supplemental_clinical_context')
    if actual is None:
        actual = payload.get('context', {}).get('supplemental_clinical_context')
    if actual is None or digest(actual) != expected:
        raise ValueError('Model input omitted or changed supplemental clinical input')
    from central_park.telemetry import event
    event(stage, clinical_input_sha256=expected, payload_sha256=digest(payload),
          payload_chars=len(canonical(payload)), packet_verified=True)


def attach_packet(resource, packet):
    resource['extension'] = [e for e in resource.get('extension', []) if e.get('url') != PACKET_EXT]
    if packet is not None:
        resource['extension'].append({'url': PACKET_EXT, 'valueString': canonical({
            'clinical_input': packet, 'sha256': digest(packet)})})
    return resource


def read_packet(resource):
    records = [e for e in resource.get('extension', []) if e.get('url') == PACKET_EXT]
    if not records:
        return None
    if len(records) != 1:
        raise ValueError('Multiple supplemental clinical input records')
    saved = json.loads(records[0]['valueString'])
    if digest(saved['clinical_input']) != saved['sha256']:
        raise ValueError('Stored supplemental clinical input hash mismatch')
    return saved['clinical_input']
