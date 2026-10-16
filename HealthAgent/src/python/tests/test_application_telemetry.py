import pytest

from central_park import benchmark_context as bench
from central_park import interview
from central_park.telemetry import model_stage, span


def test_nested_model_stage_labels_are_correlated_and_metadata_only():
    events = []
    token = bench.EVENTS.set(events)
    try:
        with span('assessment'):
            with model_stage('assessment.review', input_chars=73, generation_attempt=1):
                pass
    finally:
        bench.EVENTS.reset(token)

    started = [event for event in events if event['stage'].endswith('.started')]
    assert [event['stage'] for event in started] == [
        'assessment.started', 'assessment.review.started'
    ]
    assert started[1]['parent_span_id'] == started[0]['span_id']
    assert started[1]['input_chars'] == 73
    assert started[1]['generation_attempt'] == 1


def test_interview_parse_failure_records_safe_error_span():
    events = []
    token = bench.EVENTS.set(events)
    try:
        with pytest.raises(Exception, match='malformed JSON'):
            interview._loads('{"answer":"private transcript phrase"')
    finally:
        bench.EVENTS.reset(token)

    finished = [event for event in events if event['stage'] == 'interview.parse.finished']
    assert len(finished) == 1
    assert finished[0]['status'] == 'error'
    assert finished[0]['error_type'] == 'ModelOutputError'
    assert 'private transcript phrase' not in repr(finished[0])
