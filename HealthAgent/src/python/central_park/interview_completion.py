"""Durable interview submissions with successful-result reuse and frozen inputs."""
from threading import Lock
from uuid import UUID

from central_park import benchmark_context as bench, care_context as fhir, care_jobs
from central_park.agent import run_interview
from central_park.patients import RegistrationConflictError
from central_park import telemetry, serving_profiles
from central_park.config import load

_GUARD = Lock()
_LOCKS = {}
CODE = 'interview-completion'


@telemetry.timed('interview.completion')
def complete(submission_id: UUID, patient_id: str, transcript: list[dict], *,
             supplemental_clinical_context=None, options=None, correlation=None,
             enqueue_care_plan=True):
    sid = 'int-' + submission_id.hex
    qr_id = 'qr-' + submission_id.hex
    request = {'patient_id': patient_id, 'transcript': transcript,
               'supplemental_clinical_context': supplemental_clinical_context,
               'care_options': options, 'correlation': correlation or {}}
    if not enqueue_care_plan:
        request['enqueue_care_plan'] = False
    # Transport/run identifiers do not change the clinical operation being retried.
    request_hash = bench.digest({k: v for k, v in request.items() if k != 'correlation'})
    with _GUARD:
        lock = _LOCKS.setdefault(sid, Lock())
    if not lock.acquire(blocking=False):
        raise RegistrationConflictError('Interview submission is already in progress; retry the same UUID later')
    try:
        task = fhir.read('Task', sid, optional=True)
        if task:
            data = care_jobs.metadata(task)
            if data.get('request_sha256') != request_hash:
                raise RegistrationConflictError('Submission UUID already exists with different input or options')
            if not data.get('result'):
                raise RegistrationConflictError('Submission has an unfinished or failed assessment; inspect its trace before using a new UUID')
            result = bench.snapshot(data['result'])
            telemetry.event('interview.saved_result', submission_id=sid, model_execution_skipped=True)
        else:
            patient = fhir.read('Patient', fhir.valid_id(patient_id))
            if supplemental_clinical_context is not None:
                packet = supplemental_clinical_context
                if fhir.age_years(patient) != packet['patient']['age']:
                    raise ValueError('Supplemental age conflicts with patient birth date')
                gender = {'woman': 'female', 'man': 'male'}.get(packet['patient']['sex'], packet['patient']['sex'])
                if patient.get('gender') not in (gender, 'unknown', None):
                    raise ValueError('Supplemental sex conflicts with patient record')
            task = {'resourceType': 'Task', 'id': sid, 'status': 'in-progress', 'intent': 'proposal',
                    'code': {'text': CODE}, 'for': {'reference': 'Patient/' + patient_id},
                    'focus': {'reference': 'QuestionnaireResponse/' + qr_id},
                    'authoredOn': care_jobs.now(), 'lastModified': care_jobs.now()}
            data = {'status': 'assessing', 'request_sha256': request_hash, 'request': request,
                    'questionnaire_response_id': qr_id, 'patient_id': patient_id,
                    'correlation': {**bench.CORRELATION.get(), **(correlation or {})},
                    'clinical_input_sha256': bench.digest(supplemental_clinical_context) if supplemental_clinical_context is not None else None,
                    'serving_profile': serving_profiles.snapshot(load()), 'trace': []}
            fhir.put(care_jobs.attach(task, data))
            try:
                qr = {'resourceType': 'QuestionnaireResponse', 'id': qr_id, 'status': 'completed',
                      'subject': {'reference': 'Patient/' + patient_id}, 'authored': care_jobs.now(),
                      'item': [{'linkId': qa['link_id'], 'text': qa['question'],
                                'answer': [{'valueString': qa['answer']}]} for qa in transcript]}
                fhir.put(bench.attach_packet(qr, supplemental_clinical_context))
                bench.emit('interview.assessment.started', submission_id=sid)
                result = run_interview(patient_id, qr_id)
                if not result.get('service_request_id'):
                    raise RuntimeError('Assessment was not persisted; submission cannot be marked completed')
                result.update(submission_id=str(submission_id), clinical_input_sha256=data['clinical_input_sha256'])
                data.update(status='assessed', result=result)
                data['trace'] = list(bench.EVENTS.get() or [])
                fhir.put(care_jobs.attach(task, data))
            except Exception as exc:
                data.update(status='assessment-failed', error=type(exc).__name__,
                            trace=list(bench.EVENTS.get() or []))
                task['status'] = 'failed'
                fhir.put(care_jobs.attach(task, data))
                raise
        if not enqueue_care_plan:
            result.update(care_plan_job_id=None, care_plan_status='not-requested')
            data.update(status='completed', result=result)
            task.update(status='completed', lastModified=care_jobs.now())
            fhir.put(care_jobs.attach(task, data))
            return result
        # A successful assessment is already stored before enqueue is attempted.
        # A lost enqueue response can safely reuse both the assessment and job.
        try:
            job = care_jobs.enqueue(patient_id, qr_id, result['service_request_id'],
                                    options=options, correlation=correlation)
            result.update(care_plan_job_id=job['job_id'], care_plan_status=job['status'])
            data.update(status='completed', result=result)
            task['status'] = 'completed'
        except Exception as exc:
            care_jobs.record_enqueue_failure(result.get('service_request_id'), care_jobs.failure_reason(exc))
            result.update(care_plan_job_id=care_jobs.key(patient_id, qr_id), care_plan_status='unqueued')
            data.update(status='assessed', result=result, enqueue_error=type(exc).__name__)
        task['lastModified'] = care_jobs.now()
        fhir.put(care_jobs.attach(task, data))
        return result
    finally:
        lock.release()


def trace(submission_id: UUID):
    resource = fhir.read('Task', 'int-' + submission_id.hex)
    if resource.get('code', {}).get('text') != CODE:
        raise KeyError('Interview submission not found')
    data = care_jobs.metadata(resource)
    return {k: data.get(k) for k in ('status', 'request_sha256', 'clinical_input_sha256', 'correlation', 'trace', 'error', 'serving_profile')}
