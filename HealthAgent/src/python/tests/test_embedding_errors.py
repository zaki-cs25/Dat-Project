import httpx
import pytest

from central_park import care_evidence


def test_reindex_reason_reaches_generation_without_hiding_service_failure(monkeypatch):
    message = 'Embedding model changed; republish reviewed care documents to reindex before searching'
    response = httpx.Response(503, json={'error': message}, request=httpx.Request('POST', 'http://iris/centralpark/care-guidelines/search'))
    monkeypatch.setattr(care_evidence.httpx, 'post', lambda *args, **kwargs: response)
    with pytest.raises(httpx.HTTPStatusError, match=message) as caught:
        care_evidence.retrieve({'asthma': ['established-condition']}, 'Synthetic concern')
    assert caught.value.response.status_code == 503


def test_non_json_embedding_service_error_remains_http_failure(monkeypatch):
    response = httpx.Response(502, text='Synthetic gateway failure', request=httpx.Request('POST', 'http://iris/centralpark/care-guidelines/search'))
    monkeypatch.setattr(care_evidence.httpx, 'post', lambda *args, **kwargs: response)
    with pytest.raises(httpx.HTTPStatusError) as caught:
        care_evidence.retrieve({'asthma': ['established-condition']}, 'Synthetic concern')
    assert caught.value.response.status_code == 502
