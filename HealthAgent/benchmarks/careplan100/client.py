from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4
from threading import RLock
import httpx


def utcnow(): return datetime.now(timezone.utc).isoformat()


class ApiError(RuntimeError):
    def __init__(self, status=None, kind="APIError"):
        self.status, self.kind = status, kind
        super().__init__(kind + (f" HTTP {status}" if status else ""))


class API:
    def __init__(self, url, artifacts, timeout=180, token=None):
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError("App URL must be HTTP(S), without credentials, query or fragment")
        self.url, self.artifacts = url.rstrip("/"), artifacts
        self.attempt_ids=set(); self.attempt_lock=RLock()
        headers = {"Authorization": "Bearer " + token} if token else {}
        self.client = httpx.Client(timeout=timeout, headers=headers)

    def close(self): self.client.close()

    def call(self, method, path, *, body=None, kind, context=None, trace=True):
        context = context or {}
        rec = {"request_record_id": str(uuid4()), "method": method, "path": path, "kind": kind,
               "started_at": utcnow(), **context, "http_status": None, "error_type": None, "request_id": None}
        t = perf_counter(); data = None; failure = None
        try:
            r = self.client.request(method, self.url + path, json=body)
            rec["http_status"] = r.status_code; rec["request_id"] = r.headers.get("X-Request-ID")
            if not r.is_success: raise ApiError(r.status_code)
            data = r.json()
            if not isinstance(data, dict): raise ApiError(r.status_code, "InvalidAPIResponse")
        except ApiError as e:
            rec["error_type"] = e.kind; failure = e
        except (httpx.HTTPError, ValueError) as e:
            rec["error_type"] = type(e).__name__; failure = ApiError(rec["http_status"], type(e).__name__)
        finally:
            rec["duration_seconds"] = perf_counter() - t
            self.artifacts.append("requests.jsonl", rec)
        if trace and rec.get("request_id"):
            try:
                tr = self.call("GET", f"/benchmark/requests/{rec['request_id']}/trace", kind="trace", context=context, trace=False)
                events=tr.get("trace",[])
                self.artifacts.append("request_traces.jsonl", {"scope": "request", "request_id": rec["request_id"], **context, "events": events})
                self.record_attempts(events,{**context,"request_id":rec["request_id"]},source="request_trace")
            except ApiError as e: self.artifacts.append("trace_errors.jsonl", {"request_id": rec["request_id"], **context, "error_type": e.kind, "http_status": e.status})
        elif trace: self.artifacts.append("trace_errors.jsonl", {"request_record_id": rec["request_record_id"], **context, "error_type": "MissingRequestID"})
        if failure: raise failure
        return data

    def record_attempts(self,events,context,source):
        for event in events if isinstance(events,list) else []:
            if not isinstance(event,dict) or event.get("stage")!="llm.attempt.finished": continue
            ident=event.get("http_attempt_id") or (event.get("logical_call_id"),event.get("attempt"),event.get("generation_attempt"))
            with self.attempt_lock:
                if ident in self.attempt_ids: continue
                self.attempt_ids.add(ident)
                native=event.get("native_metrics") if isinstance(event.get("native_metrics"),dict) else {}
                timings=event.get("native_timings") if isinstance(event.get("native_timings"),dict) else {}
                self.artifacts.append("llm_attempts.jsonl",{**context,**event,**native,**timings,
                    "source_trace_scope":source,"prompt_tokens":event.get("prompt_tokens"),
                    "completion_tokens":event.get("completion_tokens"),"tokens_per_second_scope":event.get("tokens_per_second_scope")})
