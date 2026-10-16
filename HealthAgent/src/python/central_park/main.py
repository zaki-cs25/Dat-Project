"""Patient interview and durable care-plan API; exactly one background worker."""

from __future__ import annotations

import logging
from time import perf_counter
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

import threading
import httpx
from fastapi import HTTPException, Query
from central_park.agent import run_interview
from central_park.interview import next_question
from central_park import care_jobs
from central_park import benchmark_context as bench, interview_completion
from central_park.config import load
from central_park.errors import ModelServiceError, ModelOutputError, ClinicalContextError
from central_park import telemetry, serving_profiles, serving_metrics
from central_park.tools.fhir import PatientNotFoundError
from central_park.patients import PatientRegistration, RegisteredPatient, RegistrationConflictError, register
from central_park.seed_module import (
    seed_demo_patients,
    seed_guidelines,
    seed_questionnaire,
    wait_for_fhir,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed IRIS on startup. All steps are idempotent and non-fatal so the agent
    # still boots in degraded states (no API key, IRIS not yet ready, etc.).
    #
    # Wait for the FHIR endpoint first so a single `docker compose up` seeds
    # cleanly even when the agent wins the boot race against IRIS's ~90s start.
    #
    # The fast FHIR seeds (Questionnaire, demo patients) run first so the intake
    # form and clinician worklist populate quickly; seed_guidelines() embeds 30
    # snippets serially via OpenAI and can take 30-60s, so it goes last.
    try:
        wait_for_fhir()
    except Exception:
        logging.getLogger("central_park.startup").exception("wait_for_fhir failed (non-fatal)")
    try:
        seed_questionnaire()
    except Exception:
        logging.getLogger("central_park.startup").exception("seed_questionnaire failed (non-fatal)")
    try:
        seed_demo_patients()
    except Exception:
        logging.getLogger("central_park.startup").exception("seed_demo_patients failed (non-fatal)")
    try:
        seed_guidelines()
    except Exception:
        logging.getLogger("central_park.startup").exception("seed_guidelines failed (non-fatal)")
    stop = threading.Event()
    thread = threading.Thread(target=care_jobs.worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=5)


app = FastAPI(title="ICMR Care Plans", version="0.2.0", lifespan=lifespan)


class CorrelationMiddleware:
    """Time the complete ASGI operation, including response body emission."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        token = bench.CORRELATION.set({'request_id': request_id})
        events_token = bench.EVENTS.set([])
        started, status_code = perf_counter(), 500
        try:
            with telemetry.span('api.operation', method=scope['method'], path=scope['path']) as operation:
                bench.emit('api.request.started', method=scope['method'], path=scope['path'])

                async def send_response(message):
                    nonlocal status_code
                    if message['type'] == 'http.response.start':
                        status_code = message['status']
                        message = {**message, 'headers': [*message.get('headers', []),
                                   (b'x-request-id', request_id.encode('ascii'))]}
                        operation.update(http_status=status_code,
                                         status='error' if status_code >= 400 else 'ok')
                    await send(message)

                await self.app(scope, receive, send_response)
        finally:
            bench.emit('api.request.finished', duration_ms=(perf_counter() - started) * 1000,
                       status_code=status_code, measurement_origin='application_asgi_operation')
            if load().benchmark_api_enabled:
                bench.remember_request(request_id, bench.EVENTS.get() or [])
            bench.EVENTS.reset(events_token)
            bench.CORRELATION.reset(token)


app.add_middleware(CorrelationMiddleware)


class InterviewRequest(BaseModel):
    patient_id: str
    questionnaire_response_id: str


class QAItem(BaseModel):
    link_id: str
    question: str
    answer: str


class NextQuestionRequest(BaseModel):
    patient_id: str
    answers: list[QAItem] = []
    language: str = "English"
    correlation: bench.Correlation | None = None


class NextQuestionResponse(BaseModel):
    done: bool
    question: dict | None = None
    stop_reason: str | None = None


class CarePlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_id: str
    questionnaire_response_id: str
    assessment_id: str
    generation_id: UUID | None = None
    supplemental_clinical_context: bench.ClinicalPacket | None = None
    care_options: bench.CareOptions | None = None
    correlation: bench.Correlation | None = None


class InterviewCompletionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    submission_id: UUID
    patient_id: str
    transcript: list[QAItem] = Field(min_length=1, max_length=50)
    supplemental_clinical_context: bench.ClinicalPacket | None = None
    care_options: bench.CareOptions = Field(default_factory=bench.CareOptions)
    correlation: bench.Correlation = Field(default_factory=bench.Correlation)
    enqueue_care_plan: bool = True


class FixtureRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fixture_id: UUID
    clinical_input: bench.ClinicalPacket


class HandoffResponse(BaseModel):
    submission_id: str | None = None
    clinical_input_sha256: str | None = None
    care_plan_job_id: str | None = None
    care_plan_status: str | None = None

    triage_level: str | None
    chief_complaint: str | None
    hpi: str | None
    red_flags: list[str]
    recommended_actions: list[str]
    citations: list[dict]
    detected_issues: list[dict] = []
    questionnaire_response_id: str | None
    encounter_id: str | None = None
    service_request_id: str | None = None
    observation_ids: list[str] = []
    detected_issue_ids: list[str] = []


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "central-park-agent"}


@app.post('/patients', response_model=RegisteredPatient)
def register_patient(req: PatientRegistration):
    return api_call(register, req)


@app.post("/interview", response_model=HandoffResponse)
def run_interview_endpoint(req: InterviewRequest) -> dict:
    result = api_call(run_interview,
        patient_id=req.patient_id,
        questionnaire_response_id=req.questionnaire_response_id,
    )
    try:
        job = care_jobs.enqueue(req.patient_id, req.questionnaire_response_id, result.get('service_request_id') or '')
        result.update(care_plan_job_id=job['job_id'], care_plan_status=job['status'])
    except Exception as exc:
        care_jobs.record_enqueue_failure(result.get('service_request_id'), care_jobs.failure_reason(exc))
        logging.getLogger(__name__).exception('Care-plan enqueue failed; interview remains completed')
        result.update(care_plan_job_id=care_jobs.key(req.patient_id, req.questionnaire_response_id), care_plan_status='unqueued')
    return result


@app.post("/interview/next", response_model=NextQuestionResponse)
def next_question_endpoint(req: NextQuestionRequest) -> dict:
    """Adaptive intake: return the next question to ask, or that we're done."""
    if req.correlation:
        bench.CORRELATION.set({**bench.CORRELATION.get(), **req.correlation.model_dump(exclude_none=True)})
    bench.emit('interview.next', patient_id=req.patient_id, answer_count=len(req.answers))
    return api_call(next_question,
        patient_id=req.patient_id,
        answers=[a.model_dump() for a in req.answers],
        language=req.language,
    )


def api_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, 'Care-plan job not found') from exc
    except PatientNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RegistrationConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ModelOutputError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (ModelServiceError, ClinicalContextError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(404 if exc.response.status_code == 404 else 502, 'FHIR request failed') from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, 'FHIR service unavailable') from exc


@app.post('/careplan')
def enqueue_careplan(req: CarePlanRequest):
    return api_call(care_jobs.enqueue, req.patient_id, req.questionnaire_response_id, req.assessment_id,
                    options=effective_options(req.care_options) if req.care_options else None,
                    correlation=req.correlation.model_dump(exclude_none=True) if req.correlation else None,
                    generation_id=req.generation_id,
                    supplemental_clinical_context=req.supplemental_clinical_context.model_dump() if req.supplemental_clinical_context else None)


def effective_options(options):
    return {'mode': options.mode or load().care_generation_mode, 'use_icmr_context': options.use_icmr_context}


@app.post('/interview/complete', response_model=HandoffResponse)
def complete_interview(req: InterviewCompletionRequest):
    correlation = req.correlation.model_dump(exclude_none=True)
    bench.CORRELATION.set({**bench.CORRELATION.get(), **correlation})
    return api_call(interview_completion.complete, req.submission_id, req.patient_id,
                    [qa.model_dump() for qa in req.transcript],
                    supplemental_clinical_context=req.supplemental_clinical_context.model_dump() if req.supplemental_clinical_context else None,
                    options=effective_options(req.care_options), correlation=correlation,
                    enqueue_care_plan=req.enqueue_care_plan)


def require_benchmark_api():
    if not load().benchmark_api_enabled:
        raise HTTPException(404, 'Benchmark API is disabled')


@app.post('/benchmark/fixtures')
def provision_fixture(req: FixtureRequest):
    require_benchmark_api()
    from central_park.benchmark_fixtures import provision
    return api_call(provision, req.fixture_id, req.clinical_input.model_dump())


@app.get('/benchmark/submissions/{submission_id}/trace')
def submission_trace(submission_id: UUID):
    require_benchmark_api()
    return api_call(interview_completion.trace, submission_id)


@app.get('/benchmark/careplans/{job_id}/trace')
def careplan_trace(job_id: str):
    require_benchmark_api()
    task = api_call(care_jobs.fhir.read, 'Task', job_id)
    if task.get('code', {}).get('text') != care_jobs.CODE:
        raise HTTPException(404, 'Care-plan job not found')
    data = care_jobs.metadata(task)
    return {k: data.get(k) for k in ('status', 'clinical_input_sha256', 'context_sha256',
                                   'care_options', 'serving_identity', 'correlation', 'trace',
                                   'enqueued_at', 'queued_at', 'started_at', 'finished_at',
                                   'queue_wait_seconds', 'processing_seconds', 'trace_ready')}


@app.get('/benchmark/requests/{request_id}/trace')
def request_trace(request_id: UUID):
    require_benchmark_api()
    return api_call(bench.request_trace, str(request_id))


@app.get('/benchmark/serving/profile')
def serving_profile():
    require_benchmark_api()
    return serving_profiles.snapshot(load())


@app.get('/benchmark/serving/capabilities')
def serving_capabilities():
    require_benchmark_api()
    return serving_profiles.capabilities(load())


@app.get('/benchmark/serving/metrics')
def serving_metric_snapshot():
    require_benchmark_api()
    with telemetry.span('collector.snapshot'):
        return serving_metrics.collect(load())


@app.get('/careplans')
def careplans(offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return api_call(care_jobs.worklist, offset, limit)


@app.get('/careplans/{job_id}')
def careplan_detail(job_id: str):
    return api_call(care_jobs.detail, job_id)


@app.post('/careplans/{job_id}/retry')
def retry_careplan(job_id: str):
    return api_call(care_jobs.retry, job_id)
