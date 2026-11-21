from __future__ import annotations

import csv, json, os, platform, statistics, threading, time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from .artifacts import Artifacts
from .client import API, ApiError, utcnow
from .dataset import canonical, sha
from .stats import distribution

TERMINAL = {"completed", "failed", "insufficient-evidence"}


def profile_hash(profile): return sha(canonical({k: v for k, v in profile.items() if k != "profile_id"}))


class Runner:
    def __init__(self, cfg, dataset, output):
        self.cfg, self.data = cfg, dataset
        self.out = Path(output); self.art = Artifacts(self.out)
        self.run_id, self.api = str(uuid4()), API(cfg["app"]["base_url"], self.art, cfg["app"].get("timeout_seconds", 180), os.environ.get(cfg["app"].get("token_env", "CP_BENCHMARK_APP_TOKEN")))
        self.stop = threading.Event(); self.profile = None
        self.selected = [c for c in dataset["cases"].values() if cfg["split"] == "all" or c["split"] == cfg["split"]]
        only = set(cfg.get("cases", []))
        if only:
            unknown = only - {c["case_id"] for c in self.selected}
            if unknown: raise ValueError(f"Unknown cases for split: {sorted(unknown)}")
            self.selected = [c for c in self.selected if c["case_id"] in only]
        if cfg.get("limit"): self.selected = self.selected[:int(cfg["limit"])]
        if not self.selected: raise ValueError("No selected cases")
        self.manifest = {"schema_version": 1, "harness_version": "1.0.0", "run_id": self.run_id,
            "created_at": utcnow(), "status": "prepared", "config": self._redact(cfg),
            "config_sha256":cfg.get("_config_sha256"),"dataset_sha256": dataset["fingerprint"],
            "source_index_policy":cfg.get("source_index_policy",{"mode":"reviewed-pinned-index","publish_check":"central_park.import_care_documents publish --directory /app/md_care_documents","frequency":"once-before-fixture-preflight","unchanged_version":"accepted-index-remains-in-use","cache_policy":"existing-serving/retrieval-cache-preserved"}),
            "source_code_sha256":self._source_fingerprint(),"python_version": platform.python_version(),
            "judge": {"status": "not_run"}, "startup":cfg.get("_startup_result",{}),
            "measurement": "four recorded interview prefixes plus one enriched care plan per case"}
        self.art.write("dataset-manifest.json", {"dataset_sha256": dataset["fingerprint"], "manifest": dataset["manifest"]})
        self.art.write("manifest.json", self.manifest)
        if cfg.get("_startup_result"): self.art.write("startup.json",cfg["_startup_result"])
        for case in self.selected:
            self.art.append("input_packets.jsonl", {"case_id":case["case_id"],"clinical_input":case["clinical_input"],
                "input_sha256":sha(canonical(case["clinical_input"])),"interview_script":case["interview_script"]})
            self.art.append("rubrics.jsonl",dataset["rubrics"][case["case_id"]])
        self.art.write("source-snapshot.json",dataset["sources"])

    @staticmethod
    def _source_fingerprint():
        root=Path(__file__).resolve().parents[2]
        files=[]
        for source_root in (root/"src/python/central_park",root/"benchmarks/careplan100",root/"src/cls"):
            if source_root.exists():
                files.extend((p.relative_to(root).as_posix(),sha(p.read_bytes())) for p in source_root.rglob("*") if p.is_file() and p.suffix in (".py",".txt",".json",".cls"))
        files.extend((p.relative_to(root).as_posix(),sha(p.read_bytes())) for p in root.glob("docker-compose*.yml") if p.is_file())
        requirements=root/"src/python/requirements.txt"
        if requirements.is_file(): files.append((requirements.relative_to(root).as_posix(),sha(requirements.read_bytes())))
        files=sorted(files)
        return sha(canonical(files))

    @staticmethod
    def _redact(x):
        if isinstance(x, dict):
            sensitive={"api_key","api_key_value","authorization","password","secret","token","access_token"}
            return {k:("<redacted>" if k.lower() in sensitive or k.lower().endswith(("_secret","_password","_api_key")) else Runner._redact(v)) for k,v in x.items()}
        if isinstance(x, list): return [Runner._redact(v) for v in x]
        return x

    def context(self, c, **extra): return {"run_id": self.run_id, "case_id": c["case_id"], **extra}

    def preflight(self):
        h = self.api.call("GET", "/health", kind="preflight", trace=False)
        cap = self.api.call("GET", "/benchmark/serving/capabilities", kind="preflight", trace=False)
        p = self.api.call("GET", "/benchmark/serving/profile", kind="preflight", trace=False)
        if h.get("status") != "ok" or cap.get("available") is not True or cap.get("model_advertised") is not True or not p.get("profile_id") or profile_hash(p) != p.get("profile_id"):
            raise ValueError("App health, capability or serving profile verification failed")
        llm=self.cfg.get("models",{}).get("llm",{}); expected_model=llm.get("model"); expected_endpoint=llm.get("container_base_url")
        if expected_model and p.get("model")!=expected_model: raise ValueError("Serving profile model does not match configured benchmark model")
        if expected_endpoint and p.get("api_endpoint")!=expected_endpoint.rstrip("/"): raise ValueError("Serving profile endpoint does not match configured container endpoint")
        emb=self.cfg.get("models",{}).get("embeddings",{}); profile_embedding=p.get("embedding") or {}
        if emb.get("model") and profile_embedding.get("model")!=emb.get("model"): raise ValueError("Embedding profile model does not match configured benchmark model")
        if emb.get("container_base_url") and profile_embedding.get("endpoint")!=emb["container_base_url"].rstrip("/"): raise ValueError("Embedding profile endpoint does not match configured container endpoint")
        if emb.get("dimensions") and profile_embedding.get("dimensions")!=emb.get("dimensions"): raise ValueError("Embedding dimensions do not match benchmark configuration")
        self.profile = p; self.art.write("profile.json", p); self.art.write("capabilities.json", cap)
        self.manifest.update(status="preflight_complete", profile_id=p["profile_id"]); self.art.write("manifest.json", self.manifest)
        # Provision and verify every selected FHIR fixture before any model-facing call.
        repetitions=int(self.cfg["run"].get("repetitions",1))
        if not 1<=repetitions<=100: raise ValueError("run.repetitions must be between 1 and 100")
        self.fixtures = {}
        for c in self.selected:
            for repetition in range(repetitions):
                packet = c["clinical_input"]; digest = sha(canonical(packet)); ctx = self.context(c, phase="fixture", repetition=repetition)
                fixture_id = str(uuid4())
                result = self.api.call("POST", "/benchmark/fixtures", kind="setup", context=ctx,
                                       body={"fixture_id": fixture_id, "clinical_input": packet})
                if result.get("clinical_input_sha256") != digest or not result.get("patient_id"):
                    raise ValueError(f"{c['case_id']}: FHIR fixture packet hash/identity check failed")
                fixture={"fixture_id": fixture_id, "patient_id": result["patient_id"], "input_sha256": digest}
                self.fixtures[(c["case_id"],repetition)] = fixture
                self.art.append("fixtures.jsonl", {**ctx, **fixture})
        self.art.write("preflight.json", {"health": h, "profile_id": p["profile_id"], "fixture_count": len(self.fixtures)})

    def metrics_sampler(self):
        while not self.stop.is_set():
            t=time.perf_counter()
            try: row={"sampled_at":utcnow(),"run_id":self.run_id,"snapshot":self.api.call("GET","/benchmark/serving/metrics",kind="metrics",trace=False)}
            except ApiError as e: row={"sampled_at":utcnow(),"run_id":self.run_id,"available":False,"error_type":e.kind,"http_status":e.status}
            row["client_collection_seconds"]=time.perf_counter()-t; self.art.append("metrics.jsonl",row)
            self.stop.wait(float(self.cfg["run"].get("metrics_interval_seconds",2)))

    def profile_check(self):
        p=self.api.call("GET","/benchmark/serving/profile",kind="profile_check",trace=False)
        if p.get("profile_id") != self.profile.get("profile_id"): raise ValueError("Serving profile changed during run")

    def _job(self,c,task_id,job_id,started,repetition=0):
        deadline=time.monotonic()+float(self.cfg["run"].get("job_timeout_seconds",900)); ctx=self.context(c,task_id=task_id,phase="measured",repetition=repetition)
        while time.monotonic()<deadline:
            detail=self.api.call("GET",f"/careplans/{job_id}",kind="poll",context=ctx,trace=False)
            if detail.get("status") in TERMINAL and detail.get("trace_ready"):
                tr=self.api.call("GET",f"/benchmark/careplans/{job_id}/trace",kind="job_trace",context=ctx,trace=False)
                self.art.append("job_traces.jsonl",{"job_id":job_id,**ctx,"trace":tr})
                packet=c["clinical_input"]; digest=sha(canonical(packet)); frozen=detail.get("context") or {}; events=tr.get("trace",[])
                calls={e.get("logical_call_id"):e for e in events if e.get("stage")=="llm.call.finished"}
                attempts=[e for e in events if e.get("stage")=="llm.attempt.finished"]
                valid=(tr.get("clinical_input_sha256")==digest and frozen.get("supplemental_clinical_context")==packet and sha(canonical(frozen))==tr.get("context_sha256"))
                audits=[e for e in events if e.get("packet_verified") is True]
                if attempts and not audits: valid=False
                for a in attempts:
                    call=calls.get(a.get("logical_call_id"))
                    role=a.get("parent_stage")
                    audit_stage={"careplan.generation":"generation","careplan.review":"review"}.get(role)
                    if not call or not audit_stage or not call.get("parent_span_id") or a.get("parent_span_id") != call.get("span_id"):
                        valid=False; continue
                    linked=[e for e in audits if e.get("stage")==audit_stage and e.get("parent_span_id")==call.get("parent_span_id") and e.get("clinical_input_sha256")==digest]
                    if len(linked)!=1: valid=False
                identity=tr.get("serving_identity") or {}; valid=valid and identity.get("profile_id")==self.profile["profile_id"]
                if any(a.get("profile_id")!=identity.get("profile_id") for a in attempts): valid=False
                if any(e.get("model_execution_skipped") is True for e in events): valid=False
                if tr.get("care_options")!={"mode":"enriched","use_icmr_context":True}: valid=False
                self.api.record_attempts(events,{**ctx,"job_id":job_id},source="care_job_trace")
                application_status=detail.get("status")
                status="completed" if application_status=="completed" and isinstance(detail.get("draft"),dict) else application_status or "failed"
                diagnostics=tr.get("attempt_diagnostics",[]); conflicts=tr.get("upstream_fact_conflicts",[])
                if diagnostics or conflicts:
                    self.art.append("attempt_diagnostics.jsonl",{**ctx,"job_id":job_id,"attempt_diagnostics":diagnostics,"upstream_fact_conflicts":conflicts})
                self.art.append("rejections.jsonl",{**ctx,"job_id":job_id,"events":[e for e in events if e.get("stage")=="careplan.attempt.rejected"]})
                return {**ctx,"job_id":job_id,"status":status,
                    "application_status":detail.get("status"),"reason":detail.get("reason"),"draft":detail.get("draft"),"input_sha256":digest,
                    "input_verified":valid,"profile_verified":identity.get("profile_id")==self.profile["profile_id"],"trace_ready":True,
                    "duration_seconds":time.monotonic()-started,"careplan_duration_seconds":time.monotonic()-started,
                    "queue_wait_seconds":detail.get("queue_wait_seconds"),"processing_seconds":detail.get("processing_seconds"),
                    "profile_id":identity.get("profile_id"),"stage_events":events,"attempt_diagnostics":diagnostics,
                    "upstream_fact_conflicts":conflicts,"repaired":bool(diagnostics)}
            time.sleep(float(self.cfg["run"].get("poll_seconds",1)))
        return {**ctx,"job_id":job_id,"status":"timeout","trace_ready":False,"input_verified":False,"duration_seconds":time.monotonic()-started}

    def run_case(self,c,repetition=0):
        self.profile_check()
        cid=c["case_id"]; fixture=self.fixtures[(cid,repetition)]; digest=fixture["input_sha256"]; script=c["interview_script"]
        transcript=[{"link_id":f"benchmark-{i+1}",**t} for i,t in enumerate(script)]
        case_started=time.monotonic(); submission=str(uuid4()); task_id=str(uuid4()); ctx=self.context(c,phase="measured",repetition=repetition); completion_ctx={**ctx,"task_id":task_id}; errors=[]
        for i in range(4):
            turn=str(i+1)
            try:
                result=self.api.call("POST","/interview/next",kind="interview",context={**ctx,"turn_id":turn},body={
                    "patient_id":fixture["patient_id"],"answers":transcript[:i+1],"correlation":{"run_id":self.run_id,"case_id":cid,"turn_id":turn}})
                self.art.append("interviews.jsonl",{**ctx,"turn_id":turn,"scripted_history_length":i+1,"response":result})
            except ApiError as e: errors.append({"turn_id":turn,"error_type":e.kind,"http_status":e.status})
        try:
            complete=self.api.call("POST","/interview/complete",kind="completion",context=completion_ctx,body={"submission_id":submission,"patient_id":fixture["patient_id"],"transcript":transcript,
                "supplemental_clinical_context":c["clinical_input"],"enqueue_care_plan":False,"care_options":{"mode":"enriched","use_icmr_context":True},
                "correlation":{"run_id":self.run_id,"case_id":cid,"task_id":task_id}})
            if complete.get("clinical_input_sha256")!=digest or not complete.get("service_request_id") or complete.get("care_plan_job_id"):
                raise ValueError("Assessment completion input/queue integrity check failed")
            self.art.append("completions.jsonl",{**completion_ctx,"response":complete})
        except (ApiError,ValueError) as e:
            row={**ctx,"result_id":task_id,"status":"failed","generation_error":type(e).__name__,"input_verified":False,"input_sha256":digest,
                 "split":c["split"],"group":c["group"],"condition":c["condition"],"scenario":c["scenario"],
                 "interview_errors":errors,"case_operation_seconds":time.monotonic()-case_started}
            self.art.append("results.jsonl",row); return row
        try:
            submission_trace=self.api.call("GET",f"/benchmark/submissions/{submission}/trace",kind="submission_trace",context=completion_ctx,trace=False)
            self.art.append("submission_traces.jsonl",{**completion_ctx,"trace":submission_trace})
        except ApiError as e:
            self.art.append("submission_trace_errors.jsonl",{**completion_ctx,"error_type":e.kind,"http_status":e.status})
        job_id=None; ambiguous=False; enqueue_pending=False; care_started=time.monotonic()
        try:
            enqueue_pending=True
            queued=self.api.call("POST","/careplan",kind="enqueue",context={**ctx,"task_id":task_id},body={"patient_id":fixture["patient_id"],
                "questionnaire_response_id":complete["questionnaire_response_id"],"assessment_id":complete["service_request_id"],"generation_id":str(uuid4()),
                "supplemental_clinical_context":c["clinical_input"],"care_options":{"mode":"enriched","use_icmr_context":True},
                "correlation":{"run_id":self.run_id,"case_id":cid,"task_id":task_id}})
            job_id=queued.get("job_id")
            if not isinstance(job_id,str) or not job_id: ambiguous=True; raise ValueError("Enqueue returned no job_id")
            enqueue_pending=False
            row=self._job(c,task_id,job_id,care_started,repetition)
        except ApiError as e:
            ambiguous=enqueue_pending and (e.status is None or e.status>=500 or (e.status is not None and 200<=e.status<300))
            row={**ctx,"task_id":task_id,"job_id":job_id,"status":"failed","generation_error":e.kind,"http_status":e.status,"input_verified":False,"ambiguous_post":ambiguous,"duration_seconds":time.monotonic()-care_started,"careplan_duration_seconds":time.monotonic()-care_started}
        except ValueError as e:
            row={**ctx,"task_id":task_id,"job_id":job_id,"status":"input_integrity_failed","generation_error":str(e),"input_verified":False,"ambiguous_post":ambiguous,"duration_seconds":time.monotonic()-care_started,"careplan_duration_seconds":time.monotonic()-care_started}
        row.update(repetition=repetition,phase="measured",case_id=cid,result_id=task_id,split=c["split"],group=c["group"],condition=c["condition"],scenario=c["scenario"],input_sha256=digest,
                   interview_errors=errors,ambiguous_post=ambiguous,case_operation_seconds=time.monotonic()-case_started)
        self.art.append("results.jsonl",row); return row

    def run(self):
        sampler=None
        try:
            self.preflight(); self.manifest.update(status="running",measured_started_at=utcnow()); self.art.write("manifest.json",self.manifest)
            if self.cfg["run"].get("metrics_interval_seconds",2)>0:
                sampler=threading.Thread(target=self.metrics_sampler,daemon=True); sampler.start()
            start=time.monotonic(); rows=[]
            # Default and reproducible concurrency is one. Config permits higher values.
            from concurrent.futures import ThreadPoolExecutor
            repetitions=int(self.cfg["run"].get("repetitions",1)); concurrency=int(self.cfg["run"].get("concurrency",1))
            if not 1<=repetitions<=100 or not 1<=concurrency<=32: raise ValueError("run repetitions/concurrency outside supported bounds")
            schedule=[(case,rep) for rep in range(repetitions) for case in self.selected]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                rows=list(pool.map(lambda pair:self.run_case(pair[0],pair[1]),schedule))
            elapsed=time.monotonic()-start; self.stop.set()
            if sampler: sampler.join()
            self.profile_check()
            requests=self.art.rows("requests.jsonl")
            ambiguous=[r for r in requests if r.get("method")=="POST" and r.get("kind") in ("completion","enqueue") and r.get("error_type") and
                       (r.get("http_status") is None or r.get("http_status",0)>=500 or 200<=r.get("http_status",0)<300)]
            outstanding=[r.get("job_id") for r in rows if r.get("job_id") and not r.get("trace_ready")]
            self.manifest.update(status="completed",measured_elapsed_seconds=elapsed,finished_at=utcnow(),
                protocol_valid=all(r.get("input_verified") for r in rows) and not ambiguous and not outstanding,
                ambiguous_post_requests=[{"request_record_id":r["request_record_id"],"kind":r["kind"],"case_id":r.get("case_id"),"http_status":r.get("http_status")} for r in ambiguous],
                outstanding_jobs=outstanding)
            return rows
        except Exception as e:
            self.manifest.update(status="failed",error_type=type(e).__name__,error=str(e),finished_at=utcnow()); raise
        finally:
            self.stop.set()
            if sampler and sampler.is_alive(): sampler.join()
            self.api.close(); self._export()
            self.manifest["artifact_sha256"]=self.art.file_hashes(); self.art.write("manifest.json",self.manifest)

    def _export(self):
        # Materialize all stable tabular views from append-only raw records.
        results=self.art.rows("results.jsonl"); attempts=self.art.rows("llm_attempts.jsonl")
        cases=[]
        for r in results:
            rub=self.data["rubrics"].get(r.get("case_id"),{}); crit=rub.get("criteria",[])
            row={k:r.get(k) for k in ("case_id","result_id","repetition","split","group","condition","scenario","status","input_sha256","input_verified","profile_verified","duration_seconds","careplan_duration_seconds","case_operation_seconds","queue_wait_seconds","processing_seconds","score","critical_failure","critical_unknown","rubric_status")}
            row["expected_input_sha256"]=sha(canonical(self.data["cases"][r["case_id"]]["clinical_input"])) if r.get("case_id") in self.data["cases"] else None
            row["input_fidelity_score"]=1.0 if r.get("input_verified") is True and row["input_sha256"]==row["expected_input_sha256"] else 0.0
            row["ambiguous_post"]=bool(r.get("ambiguous_post")); row["trace_ready"]=r.get("trace_ready")
            draft=r.get('draft') if isinstance(r.get('draft'),dict) else {}
            row['care_plan_title']=draft.get('title')
            row['care_plan_json']={k:draft.get(k) for k in ('title','activities','missing_information','uncovered_conditions','review_notes')}
            cases.append(row)
        self._csv("cases.csv",cases)
        self._csv("llm_attempts.csv",attempts)
        self._csv("failures.csv",[r for r in results if r.get("status")!="completed" or not r.get("input_verified") or r.get("attempt_diagnostics") or r.get("upstream_fact_conflicts")])
        self._csv("rubric_results.csv",self.art.rows("rubric_results.jsonl"))
        self._csv("infra_samples.csv",[{**r,"scope":"run_aggregate"} for r in self.art.rows("metrics.jsonl")])
        stages=[]; grouped={}
        metric_names=("time_to_first_token_seconds","mean_itl_seconds","generation_time_seconds","queue_time_seconds","tokens_per_second","prompt_tokens","completion_tokens","prompt_seconds","predicted_seconds","prompt_tokens_per_second","predicted_tokens_per_second")
        for attempt in attempts:
            grouped.setdefault((attempt.get("case_id"),attempt.get("repetition"),attempt.get("parent_stage")),[]).append(attempt)
        for (cid,rep,stage),attempt_rows in grouped.items():
            stages.append({"case_id":cid,"repetition":rep,"stage":stage,"metric":"attempt_count","count":len(attempt_rows),"mean":len(attempt_rows),"p50":len(attempt_rows),"p95":len(attempt_rows),"unit":"attempts","scope":"all_http_attempts"})
            for metric in metric_names:
                vals=[]
                for attempt in attempt_rows:
                    value=(attempt.get("native_metrics") or {}).get(metric,(attempt.get("native_timings") or {}).get(metric,attempt.get(metric)))
                    if isinstance(value,(int,float)): vals.append(float(value))
                if vals:
                    vals.sort(); unit="tokens_per_second" if "per_second" in metric else "tokens" if metric in ("prompt_tokens","completion_tokens") else "seconds"
                    stages.append({"case_id":cid,"repetition":rep,"stage":stage,"metric":metric,"count":len(vals),"mean":statistics.mean(vals),
                        "p50":distribution(vals)["p50"],"p95":distribution(vals)["p95"],"p99":distribution(vals)["p99"],"known_sum":sum(vals),"unit":unit,
                        "scope":next((a.get("tokens_per_second_scope") for a in attempt_rows if a.get("tokens_per_second_scope")),"unknown") if "per_second" in metric else "per_request"})
        self._csv("case_stage_metrics.csv",stages)
        durations=[r.get("duration_seconds") for r in results if isinstance(r.get("duration_seconds"),(int,float))]
        def dist(key):
            vals=sorted(float((a.get("native_metrics") or {}).get(key,(a.get("native_timings") or {}).get(key,a.get(key)))) for a in attempts if isinstance((a.get("native_metrics") or {}).get(key,(a.get("native_timings") or {}).get(key,a.get(key))),(int,float)))
            if not vals: return {key+"_count":0,key+"_mean":None,key+"_p50":None,key+"_p95":None}
            return {key+"_"+stat:value for stat,value in distribution(vals).items()}
        aggregates={}
        for key in ("time_to_first_token_seconds","mean_itl_seconds","generation_time_seconds","queue_time_seconds","tokens_per_second","prompt_tokens","completion_tokens","prompt_seconds","predicted_seconds","prompt_tokens_per_second","predicted_tokens_per_second"):
            aggregates.update(dist(key))
        request_rows=self.art.rows("requests.jsonl")
        summary=[{"run_id":self.run_id,"cases":len(results),"completed":sum(r.get("status")=="completed" for r in results),"failed":sum(r.get("status")!="completed" for r in results),
                  "input_verified":sum(r.get("input_verified") is True for r in results),"mean_careplan_seconds":statistics.mean(durations) if durations else None,
                  "metrics_sample_count":len(self.art.rows("metrics.jsonl")),"llm_attempt_count":len(attempts),
                  "repair_attempt_count":sum(int(a.get("generation_attempt",0) or 0)>0 for a in attempts),"request_count":len(request_rows),
                  "request_error_count":sum(bool(r.get("error_type")) for r in request_rows),"trace_error_count":len(self.art.rows("trace_errors.jsonl")),
                  "ambiguous_post_count":len(self.manifest.get("ambiguous_post_requests",[])),"protocol_valid":self.manifest.get("protocol_valid"),**aggregates}]
        summary[0]['completion_rate']=sum(r.get('status')=='completed' for r in results)/len(results) if results else None
        summary[0]['measured_elapsed_seconds']=self.manifest.get('measured_elapsed_seconds')
        summary[0]['completed_care_operations_per_second']=(sum(r.get('status')=='completed' for r in results)/self.manifest['measured_elapsed_seconds']) if self.manifest.get('measured_elapsed_seconds') else None
        for name,key in [('care_operation','duration_seconds'),('case_operation','case_operation_seconds'),('worker_processing','processing_seconds'),('worker_queue','queue_wait_seconds')]:
            summary[0].update({name+'_'+stat:value for stat,value in distribution(r.get(key) for r in results).items()})
        for kind in sorted({r.get('kind') for r in request_rows if r.get('kind')}):
            selected=[r for r in request_rows if r.get('kind')==kind]
            summary[0].update({kind+'_api_seconds_'+stat:value for stat,value in distribution(r.get('duration_seconds') for r in selected).items()})
            summary[0][kind+'_api_error_count']=sum(bool(r.get('error_type')) for r in selected)
        self._csv("summary.csv",summary)
        self.art.write("manifest.json",self.manifest)

    def _csv(self,name,rows):
        defaults={"cases.csv":["case_id","result_id","repetition","split","group","condition","scenario","status","input_sha256","expected_input_sha256","input_fidelity_score","input_verified","profile_verified","trace_ready","ambiguous_post"],
            "llm_attempts.csv":["run_id","case_id","task_id","parent_stage","generation_attempt","http_attempt_id","attempt","status","error_type","time_to_first_token_seconds","mean_itl_seconds","tokens_per_second","tokens_per_second_scope","prompt_tokens","completion_tokens"],
            "failures.csv":["case_id","result_id","status","generation_error","error_type","http_status","input_verified","ambiguous_post"],
            "rubric_results.csv":["case_id","result_id","rubric_status","score","critical_failure","critical_unknown","judge_error"],
            "infra_samples.csv":["sampled_at","run_id","scope","available","snapshot","error_type","http_status"],
            "case_stage_metrics.csv":["case_id","repetition","stage","metric","count","mean","p50","p95","unit","scope"]}
        keys=list(dict.fromkeys(k for row in rows for k in row)) if rows else defaults.get(name,["run_id","cases"])
        with (self.out/name).open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore"); w.writeheader()
            for row in rows: w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
