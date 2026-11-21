"""Single-process durable FHIR Task worker. Run exactly one uvicorn worker."""
import hashlib
import json
import logging
import threading
from time import perf_counter
from datetime import datetime, timezone
from central_park import care_context as fhir
from central_park.careplan import generate
from central_park.config import load
from central_park import benchmark_context as bench
from central_park import telemetry, serving_profiles

META = 'https://centralpark.example/fhir/StructureDefinition/care-plan-data'
CODE = 'care-plan-generation'
LOCK = threading.RLock()
LOG = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def failure_reason(exc):
    """Keep persisted diagnostics useful without copying provider response bodies."""
    message = str(exc)
    for prefix in ('Serving configuration changed since enqueue',
                   'Frozen care-plan context hash mismatch',
                   'Supplemental clinical context hash mismatch',
                   'Supplemental clinical input hash mismatch',
                   'Model context window exceeded',
                   'Draft failed validation after one repair'):
        if message.startswith(prefix):
            return prefix + '.'
    status = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
    return 'Care-plan operation failed (' + type(exc).__name__ + (f', HTTP {status}' if isinstance(status, int) else '') + ').'


def key(patient, questionnaire, generation_id=None):
    identity = f'{patient}/{questionnaire}' + (f'/{generation_id}' if generation_id else '')
    return 'cp-' + hashlib.sha256(identity.encode()).hexdigest()[:40]


def metadata(resource):
    return next((json.loads(e['valueString']) for e in resource.get('extension', []) if e.get('url') == META), {})


def attach(resource, data):
    resource['extension'] = [e for e in resource.get('extension', []) if e.get('url') != META] + [{'url': META, 'valueString': json.dumps(data)}]
    return resource


def serving_identity():
    """Freeze the full effective serving profile; preserve legacy identity fields."""
    cfg = load()
    from urllib.parse import urlsplit, urlunsplit
    endpoint = getattr(cfg, cfg.llm_provider + '_base_url', None)
    if endpoint:
        parsed = urlsplit(endpoint)
        endpoint = urlunsplit((parsed.scheme, parsed.hostname + (':' + str(parsed.port) if parsed.port else ''), parsed.path, '', ''))
    identity = {'provider': cfg.llm_provider, 'model': getattr(cfg, cfg.llm_provider + '_model'),
                'endpoint': endpoint, 'json_mode': cfg.openai_json_mode,
                'token_limit_param': cfg.openai_token_limit_param,
                'chat_template_kwargs': cfg.openai_chat_template_kwargs}
    profile = serving_profiles.snapshot(cfg)
    # The profile retains only a digest of arbitrary template extras.
    identity.pop('chat_template_kwargs')
    identity.update(profile_id=profile['profile_id'], profile=profile)
    return identity


def identity_matches(saved):
    current = serving_identity()
    if saved.get('profile_id'):
        return saved['profile_id'] == current['profile_id']
    # Existing Step 2 tasks have a smaller profile; retain their original check.
    for k, value in saved.items():
        if k == 'chat_template_kwargs':
            if value != load().openai_chat_template_kwargs:
                return False
        elif current.get(k) != value:
            return False
    return True


@telemetry.timed('care_job.enqueue')
def enqueue(patient_id, questionnaire_response_id, assessment_id, *, options=None, correlation=None,
            supplemental_clinical_context=None, generation_id=None):
    fhir.valid_id(patient_id)
    fhir.linked(patient_id, questionnaire_response_id, assessment_id)
    if generation_id is not None:
        from uuid import UUID
        generation_id = str(UUID(str(generation_id)))
    job_id = key(patient_id, questionnaire_response_id, generation_id)
    with LOCK:
        existing = fhir.read('Task', job_id, optional=True)
        if existing:
            saved = metadata(existing)
            if saved['assessment_id'] != assessment_id:
                raise ValueError('Existing job references a different assessment')
            if options is not None and saved.get('care_options') != options:
                raise ValueError('Existing job has different care-generation options; use a fresh submission')
            if supplemental_clinical_context is not None and saved.get('clinical_input_sha256') != bench.digest(supplemental_clinical_context):
                raise ValueError('Existing job has different supplemental clinical input; use a fresh submission')
            telemetry.event('care_job.saved_result', job_id=job_id, status=saved.get('status'),
                            reuse_kind='existing_job')
            return view(existing)
        effective_options = {'mode': load().care_generation_mode, 'use_icmr_context': True,
                             **(options or {})}
        if effective_options['mode'] not in ('enriched', 'grounded') or type(effective_options['use_icmr_context']) is not bool:
            raise ValueError('Invalid care-generation options')
        frozen = fhir.context(patient_id, questionnaire_response_id, assessment_id)
        if supplemental_clinical_context is not None:
            packet = bench.ClinicalPacket.model_validate(supplemental_clinical_context).model_dump()
            if frozen.get('clinical_input_sha256') and frozen['clinical_input_sha256'] != bench.digest(packet):
                raise ValueError('Supplemental input differs from completed interview')
            if fhir.age_years(frozen['patient']) != packet['patient']['age']:
                raise ValueError('Supplemental age conflicts with the authoritative patient age')
            frozen.update(supplemental_clinical_context=packet, clinical_input_sha256=bench.digest(packet))
        identity = serving_identity()
        task = {'resourceType': 'Task', 'id': job_id, 'status': 'requested', 'intent': 'proposal',
                'code': {'text': CODE, 'coding': [{'system': 'https://centralpark.example/fhir/CodeSystem/tasks', 'code': CODE}]}, 'for': {'reference': f'Patient/{patient_id}'},
                'focus': {'reference': f'QuestionnaireResponse/{questionnaire_response_id}'},
                'authoredOn': now(), 'lastModified': now()}
        attach(task, {'patient_id': patient_id, 'questionnaire_response_id': questionnaire_response_id,
                      'assessment_id': assessment_id, 'status': 'queued', 'attempt': now(),
                      'generation_id': generation_id,
                      'care_options': effective_options, 'frozen_context': frozen,
                      'clinical_input_sha256': frozen.get('clinical_input_sha256'),
                      'context_sha256': bench.digest(frozen), 'serving_identity': identity,
                      'correlation': {**bench.CORRELATION.get(), **(correlation or {}), 'job_id': job_id},
                      'enqueued_at': task['authoredOn'], 'queued_at': task['authoredOn'],
                      'trace': [], 'trace_ready': False})
        fhir.put(task)
        return view(task)


def record_enqueue_failure(assessment_id, reason):
    if not assessment_id:
        return
    try:
        assessment = fhir.read('ServiceRequest', assessment_id)
        notes = [n for n in assessment.get('note', []) if not n.get('text', '').startswith('Care-plan enqueue failure: ')]
        assessment['note'] = notes + [{'text': 'Care-plan enqueue failure: ' + reason}]
        fhir.put(assessment)
    except Exception:
        LOG.exception('Could not record enqueue failure; completed questionnaire remains visible as unqueued')


def view(task):
    data = metadata(task)
    return {'job_id': task['id'], **{k: v for k, v in data.items()
                                   if k not in ('frozen_context', 'trace', 'attempt_diagnostics', 'upstream_fact_conflicts')}}


def transition(task, status, reason=None):
    task['status'] = {'queued': 'requested', 'running': 'in-progress', 'completed': 'completed',
                      'failed': 'failed', 'insufficient-evidence': 'failed'}[status]
    task['lastModified'] = now()
    data = metadata(task)
    data.update(status=status, reason=reason)
    attach(task, data)
    fhir.put(task)


def save_plan(task, draft, ctx):
    data = metadata(task)
    cfg = load()
    identity = data.get('serving_identity') or serving_identity()
    saved = {**draft, 'model': identity['provider'] + ':' + identity['model'],
             'generated_at': now(), 'questionnaire_response_id': data['questionnaire_response_id'],
             'assessment_id': data['assessment_id'], 'attempt': data.get('attempt'),
             'clinical_input_sha256': data.get('clinical_input_sha256'),
             'care_options': data.get('care_options'), 'serving_identity': identity}
    resource = {'resourceType': 'CarePlan', 'id': task['id'], 'status': 'draft', 'intent': 'proposal',
                'title': draft['title'], 'subject': {'reference': 'Patient/' + data['patient_id']},
                'created': saved['generated_at'],
                'supportingInfo': [{'reference': 'QuestionnaireResponse/' + data['questionnaire_response_id']},
                                   {'reference': 'ServiceRequest/' + data['assessment_id']}],
                'activity': [{'detail': {'status': 'not-started', 'description': a['description']}} for a in draft['activities']]}
    if draft['condition_ids']:
        resource['addresses'] = [{'reference': 'Condition/' + i} for i in draft['condition_ids']]
    if ctx['assessment'].get('encounter'):
        resource['encounter'] = ctx['assessment']['encounter']
    return fhir.put(attach(resource, saved))


def process(task):
    # Only claiming uses the enqueue lock. Model work must never block interview completion.
    operation_started = perf_counter()
    with LOCK:
        task = fhir.read('Task', task['id'])
        if metadata(task).get('status') not in ('queued', 'running'):
            return
        data = metadata(task)
        data.update(started_at=now(), trace_ready=False)
        try:
            wait = (datetime.fromisoformat(data['started_at']) - datetime.fromisoformat(data.get('queued_at') or task['authoredOn'])).total_seconds()
            data['queue_wait_seconds'] = wait if wait >= 0 else None
        except (KeyError, ValueError, TypeError):
            data['queue_wait_seconds'] = None
        attach(task, data)
        transition(task, 'running')
    ctx = None
    data = metadata(task)
    events = list(data.get('trace', []))
    correlation_token = bench.CORRELATION.set({**data.get('correlation', {}), 'job_id': task['id'],
                                             'attempt_id': data.get('attempt')})
    events_token = bench.EVENTS.set(events)
    bench.emit('care_job.started', queue_wait_seconds=data.get('queue_wait_seconds'),
               queue_measurement_origin='persisted_utc_timestamps',
               worker_concurrency=1, worker_poll_interval_seconds=3,
               profile_id=data.get('serving_identity', {}).get('profile_id'))
    try:
        saved = fhir.read('CarePlan', task['id'], optional=True)
        data = metadata(task)
        # A saved plan from the current attempt recovers even if the final Task write failed.
        if saved and (not data.get('regenerate') or metadata(saved).get('attempt') == data.get('attempt')):
            telemetry.event('care_job.saved_result', reuse_kind='saved_care_plan',
                            model_execution_skipped=True)
            data.update(regenerate=False, result=metadata(saved))
            attach(task, data)
            transition(task, metadata(saved).get('result_status', 'completed'))
            return
        if data.get('serving_identity') and not identity_matches(data['serving_identity']):
            raise ValueError('Serving configuration changed since enqueue; restore the queued model profile')
        ctx = bench.snapshot(data.get('frozen_context')) if data.get('frozen_context') else fhir.context(data['patient_id'], data['questionnaire_response_id'], data['assessment_id'])
        if data.get('context_sha256') and bench.digest(ctx) != data['context_sha256']:
            raise ValueError('Frozen care-plan context hash mismatch')
        ctx['care_options'] = data.get('care_options', {})
        draft = generate(ctx)
        if draft['activities']:
            save_plan(task, draft, ctx)
        data = metadata(task)
        data.update(regenerate=False, result=draft)
        attach(task, data)
        transition(task, draft['result_status'], None if draft['result_status'] == 'completed' else 'No applicable reviewed ICMR evidence.')
    except Exception as exc:
        LOG.exception('Care-plan generation failed for %s', task['id'])
        try:
            # A failed routine draft cannot erase the assessment's urgent recommendation.
            # Only application-owned content is saved here, never invalid model output.
            from central_park.careplan import urgent_activity
            if ctx and not fhir.read('CarePlan', task['id'], optional=True):
                urgent = urgent_activity(ctx['assessment'], ctx.get('supplemental_clinical_context'))
                if urgent:
                    save_plan(task, {'title': 'Urgent assessment draft', 'activities': [a.model_dump() for a in urgent],
                                     'condition_ids': [], 'evidence_sources': [], 'missing_information': [],
                                     'uncovered_conditions': [], 'review_notes': ['Routine generation failed; assessment instruction retained.'],
                                     'result_status': 'failed'}, ctx)
            transition(task, 'failed', failure_reason(exc))
        except Exception:
            LOG.exception('Could not persist failure; running Task will be recovered')
    finally:
        bench.emit('care_job.finished', status=metadata(task).get('status'),
                   processing_seconds=perf_counter() - operation_started,
                   measurement_origin='application_monotonic_clock')
        try:
            latest = metadata(task)
            latest.update(finished_at=now(), processing_seconds=perf_counter() - operation_started,
                          trace_ready=True)
            if ctx is not None and load().benchmark_api_enabled:
                latest['attempt_diagnostics'] = ctx.get('_care_attempt_diagnostics', [])
                latest['upstream_fact_conflicts'] = ctx.get('_care_upstream_conflicts', [])
            latest['trace'] = events
            attach(task, latest)
            fhir.put(task)
        except Exception:
            LOG.exception('Could not persist care-plan boundary trace')
        bench.EVENTS.reset(events_token)
        bench.CORRELATION.reset(correlation_token)


def worker(stop):
    while not stop.is_set():
        try:
            for task in fhir.search('Task', code=CODE):
                if task.get('code', {}).get('text') == CODE and metadata(task).get('status') in ('queued', 'running'):
                    if stop.is_set():
                        break
                    process(task)
        except Exception:
            LOG.exception('Care-plan worker polling failed; will retry')
        stop.wait(3)


def detail(job_id):
    task = fhir.read('Task', job_id, optional=True)
    if not task:
        plan = fhir.read('CarePlan', job_id, optional=True)
        if plan:
            return {'job_id': job_id, 'status': 'legacy-draft', 'draft': {
                'title': plan.get('title', 'Legacy draft'), 'activities': [
                    {'description': a.get('detail', {}).get('description', ''), 'provenance': 'legacy'} for a in plan.get('activity', [])],
                'evidence_sources': [], 'review_notes': ['Legacy draft; no attributed ICMR evidence.']}}
        data = next((r for r in worklist(0, 1000000)['items'] if r['job_id'] == job_id), None)
        if not data:
            raise KeyError('Care-plan job not found')
    else:
        if task.get('code', {}).get('text') != CODE:
            raise KeyError('Care-plan job not found')
        data = view(task)
        plan = fhir.read('CarePlan', job_id, optional=True)
        data['draft'] = metadata(plan) if plan else data.get('result')
    if data.get('assessment_id'):
        try:
            data['context'] = metadata(task).get('frozen_context') if task else None
            if not data['context']:
                data['context'] = fhir.context(data['patient_id'], data['questionnaire_response_id'], data['assessment_id'])
        except Exception as exc:
            data['context_error'] = 'Supporting FHIR context unavailable: ' + str(exc)
    return data


def retry(job_id):
    with LOCK:
        task = fhir.read('Task', job_id, optional=True)
        if not task:
            data = detail(job_id)
            if data.get('assessment_id'):
                return enqueue(data['patient_id'], data['questionnaire_response_id'], data['assessment_id'])
            raise ValueError('No persisted assessment is available for generation')
        if task.get('code', {}).get('text') != CODE:
            raise KeyError('Care-plan job not found')
        data = metadata(task)
        if data.get('status') not in ('failed', 'insufficient-evidence'):
            return view(task)
        fhir.linked(data['patient_id'], data['questionnaire_response_id'], data['assessment_id'])
        # Regenerate an urgent-only insufficient-evidence plan; retain it until replacement succeeds.
        data['regenerate'] = bool(fhir.read('CarePlan', job_id, optional=True))
        data['attempt'] = now()
        data['queued_at'] = now()
        data['trace_ready'] = False
        attach(task, data)
        transition(task, 'queued')
        return view(task)


def worklist(offset=0, limit=25):
    patients = {p['id']: p for p in fhir.search('Patient')}
    def name(pid):
        names = patients.get(pid, {}).get('name', [])
        return (names[0].get('text') or ' '.join(names[0].get('given', []) + [names[0].get('family', '')]).strip() or pid) if names else pid
    assessments = fhir.search('ServiceRequest')
    tasks = {t['id']: t for t in fhir.search('Task', code=CODE) if t.get('code', {}).get('text') == CODE}
    rows = []
    for qr in fhir.search('QuestionnaireResponse', status='completed'):
        patient = qr.get('subject', {}).get('reference', '').removeprefix('Patient/')
        if not patient:
            continue
        job_id = key(patient, qr['id'])
        assessment = next((a for a in reversed(assessments) if a.get('subject') == qr.get('subject') and any(n.get('text') == 'QR: ' + qr['id'] for n in a.get('note', []))), None)
        row = {'job_id': job_id, 'patient_id': patient, 'patient_name': name(patient), 'questionnaire_response_id': qr['id'],
               'assessment_id': assessment['id'] if assessment else None, 'interview_date': qr.get('authored', ''),
               'urgency': assessment.get('priority', 'routine') if assessment else 'unknown',
               'status': 'unqueued' if assessment else 'assessment-missing',
               'reason': 'Generation was not queued.' if assessment else 'Assessment was not saved; interview must be reassessed.'}
        if assessment:
            failure = next((n['text'] for n in assessment.get('note', []) if n.get('text', '').startswith('Care-plan enqueue failure: ')), None)
            if failure:
                row['reason'] = failure
        if job_id in tasks:
            row.update(view(tasks[job_id]))
        rows.append(row)
    for plan in fhir.search('CarePlan'):
        if not metadata(plan):
            rows.append({'job_id': plan['id'], 'patient_id': plan.get('subject', {}).get('reference', '').removeprefix('Patient/'),
                         'interview_date': plan.get('created', ''), 'status': 'legacy-draft', 'urgency': 'unknown'})
    rows.sort(key=lambda r: r['interview_date'], reverse=True)
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'limit': limit}
