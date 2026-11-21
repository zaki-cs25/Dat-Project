from __future__ import annotations

import argparse, json, os, sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from .dataset import load_dataset, sha
from .runner import Runner
from .grading import grade_run
from .lifecycle import start_and_wait

HERE=Path(__file__).resolve().parent

def parser():
    p=argparse.ArgumentParser(description="CarePlan100 single-command API benchmark")
    p.add_argument("command",nargs="?",choices=("run","grade","validate"),default="run")
    p.add_argument("--config",type=Path,default=HERE/"config.example.json")
    p.add_argument("--split",choices=("development","evaluation","all"))
    p.add_argument("--cases",nargs="*")
    p.add_argument("--limit",type=int)
    p.add_argument("--skip-startup",action="store_true",help="Use an already running app")
    p.add_argument("--dry-run",action="store_true",help="Offline validation and planned workload only")
    p.add_argument("--run-dir",type=Path,help="Existing measurement directory for grade")
    p.add_argument("--retry-invalid-from",type=Path,help="Prior grade revision: retain valid grades and retry only invalid judgments")
    return p

def main(argv=None):
    a=parser().parse_args(argv)
    try:
        cfg=json.loads(a.config.read_text(encoding="utf-8"))
        cfg["_config_sha256"]=sha(a.config.read_bytes())
        if a.split: cfg["split"]=a.split
        if a.cases is not None: cfg["cases"]=a.cases
        if a.limit is not None: cfg["limit"]=a.limit
        base=Path(a.config).resolve().parent
        dataset_path=(base/cfg.get("dataset_dir","../../data")).resolve()
        data=load_dataset(dataset_path)
        if a.command=="validate":
            print(json.dumps({"valid":True,"case_count":len(data["cases"]),"rubric_count":len(data["rubrics"]),"dataset_sha256":data["fingerprint"]},indent=2)); return 0
        selected=[c for c in data["cases"].values() if cfg.get("split","all")=="all" or c["split"]==cfg["split"]]
        if cfg.get("cases"):
            wanted=set(cfg["cases"]); selected=[c for c in selected if c["case_id"] in wanted]
            if wanted-{c["case_id"] for c in selected}: raise ValueError("Unknown case ID or case outside selected split")
        if cfg.get("limit"): selected=selected[:int(cfg["limit"])]
        if cfg.get("limit") is not None and int(cfg["limit"]) < 1: raise ValueError("--limit must be positive")
        if not selected: raise ValueError("No cases selected for the configured split/case filter")
        if a.command=="grade":
            run_dir=a.run_dir.resolve() if a.run_dir else Path(cfg.get("output_dir","../../benchmark-runs/careplan100"))
            if not run_dir.is_absolute(): run_dir=(base/run_dir).resolve()
            if not a.run_dir and not (run_dir/"manifest.json").exists():
                candidates=sorted((p for p in run_dir.iterdir() if (p/"manifest.json").is_file()),key=lambda p:p.stat().st_mtime) if run_dir.exists() else []
                if not candidates: raise ValueError("No saved run found; pass --run-dir")
                run_dir=candidates[-1]
            target,rows=grade_run(run_dir,data,cfg,retry_from=a.retry_invalid_from)
            print(json.dumps({"revision_dir":str(target),"graded_rows":len(rows),"graded":sum(r.get("rubric_status")=="graded" for r in rows)},indent=2)); return 0
        if a.dry_run:
            reps=int(cfg.get("run",{}).get("repetitions",1))
            if not 1<=reps<=100: raise ValueError("run.repetitions must be between 1 and 100")
            print(json.dumps({"dry_run":True,"selected_cases":len(selected),"repetitions":reps,"interview_requests":4*len(selected)*reps,"careplan_jobs":len(selected)*reps,"dataset_sha256":data["fingerprint"],"cases":[c["case_id"] for c in selected]},indent=2)); return 0
        out=Path(cfg.get("output_dir","../../benchmark-runs/careplan100"))
        if not out.is_absolute(): out=(base/out).resolve()
        out=out/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+str(uuid4())[:8])
        startup=start_and_wait(cfg,skip_startup=a.skip_startup)
        cfg["_startup_result"]=startup
        runner=Runner(cfg,data,out); runner.run()
        grade_dir,grade_rows=grade_run(out,data,cfg)
        print(json.dumps({"run_dir":str(out),"run_id":runner.run_id,"status":runner.manifest.get("status"),
            "protocol_valid":runner.manifest.get("protocol_valid"),"grade_revision":str(grade_dir),
            "graded_rows":sum(r.get("rubric_status")=="graded" for r in grade_rows)},indent=2)); return 0
    except (OSError,ValueError,RuntimeError,KeyError) as e:
        print(f"careplan100: {type(e).__name__}: {e}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
