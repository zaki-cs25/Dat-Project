"""Narrow Docker lifecycle for the app and IRIS only; never starts model servers."""
from __future__ import annotations

import json, os, shutil, subprocess, time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def _run(command, *, timeout=3600, check=True, capture=True, env=None):
    p=subprocess.run(command,check=False,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.STDOUT if capture else None,timeout=timeout,env=env)
    if check and p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(command[:5])}")
    return p


def _http_ready(url, timeout=5):
    try:
        with httpx.Client(timeout=timeout) as c:
            health=c.get(url.rstrip("/")+"/health")
            if health.is_success and health.json().get("status")=="ok":
                cap=c.get(url.rstrip("/")+"/benchmark/serving/capabilities")
                prof=c.get(url.rstrip("/")+"/benchmark/serving/profile")
                return cap.is_success and cap.json().get("available") is True and cap.json().get("model_advertised") is True and prof.is_success and bool(prof.json().get("profile_id"))
    except Exception: pass
    return False


def _models_probe(endpoint, expected, key, *, embedding=False, dimensions=None, send_dimensions=False, timeout=20):
    if not endpoint: return {"configured":False,"ready":None}
    base=endpoint.rstrip("/")
    if base.endswith("/v1"): models_url=base+"/models"; embedding_url=base+"/embeddings"
    else: models_url=base+"/v1/models"; embedding_url=base+"/v1/embeddings"
    headers={"Authorization":"Bearer "+key} if key else {}
    try:
        with httpx.Client(timeout=timeout) as c:
            r=c.get(models_url,headers=headers); r.raise_for_status(); data=r.json()
            ids={x.get("id") for x in data.get("data",[]) if isinstance(x,dict)}
            exists=expected in ids if expected else bool(ids)
            result={"configured":True,"ready":exists,"model_listed":exists,"expected_model":expected}
            if not exists: return result
            if embedding:
                body={"model":expected,"input":"benchmark readiness probe"}
                if dimensions and send_dimensions: body["dimensions"]=int(dimensions)
                er=c.post(embedding_url,headers=headers,json=body); er.raise_for_status(); vec=er.json()["data"][0]["embedding"]
                result["embedding_dimensions"]=len(vec); result["ready"]=not dimensions or len(vec)==int(dimensions)
            return result
    except Exception as e: return {"configured":True,"ready":False,"error_type":type(e).__name__,"expected_model":expected}


def start_and_wait(cfg, *, skip_startup=False):
    root=Path(__file__).resolve().parents[2]
    life=cfg.get("startup",{})
    app=cfg.get("app",{}); app_url=app.get("base_url","http://localhost:8003")
    ctx=life.get("docker_context","desktop-linux")
    compose=life.get("compose_files",["docker-compose.yml","docker-compose.benchmark.yml"])
    project=life.get("compose_project","cp-benchmark100")
    min_gb=float(life.get("minimum_free_disk_gb",12))
    free=shutil.disk_usage(root).free/(1024**3)
    if free<min_gb: raise RuntimeError(f"Disk preflight failed: {free:.1f} GiB free; need at least {min_gb:.1f} GiB")
    # Model servers are external prerequisites. Fail before a potentially expensive
    # build or app-readiness wait when one has stopped.
    llm=cfg.get("models",{}).get("llm",{}); emb=cfg.get("models",{}).get("embeddings",{})
    llm_key=os.environ.get(llm.get("api_key_env","")) if llm.get("api_key_env") else None
    llm_result=_models_probe(llm.get("base_url"),llm.get("model"),llm_key,timeout=llm.get("probe_timeout_seconds",20))
    if llm_result.get("configured") and llm_result.get("ready") is not True: raise RuntimeError("Configured LLM model endpoint is not ready; start the external model server before running the benchmark")
    emb_key=os.environ.get(emb.get("api_key_env","")) if emb.get("api_key_env") else None
    emb_result=_models_probe(emb.get("base_url"),emb.get("model"),emb_key,embedding=True,dimensions=emb.get("dimensions"),send_dimensions=emb.get("send_dimensions",False),timeout=emb.get("probe_timeout_seconds",30)) if emb.get("probe",False) else {"configured":bool(emb.get("base_url")),"ready":None,"probe_skipped":True}
    if emb_result.get("configured") and emb_result.get("ready") is False: raise RuntimeError("Configured embedding model endpoint is not ready")
    _run(["docker","context","inspect",ctx],timeout=20)
    docker_info=_run(["docker","--context",ctx,"info","--format","{{.DockerRootDir}}"],timeout=30).stdout.strip()
    docker_usage=_run(["docker","--context",ctx,"system","df"],timeout=60).stdout.strip()
    base=["docker","--context",ctx,"compose","-p",project]
    files=[]
    for item in compose:
        path=Path(item); path=path if path.is_absolute() else root/path
        if not path.is_file(): raise RuntimeError(f"Missing compose file: {path}")
        files.extend(["-f",str(path)])
    command=base+files
    compose_env=os.environ.copy()
    llm=cfg.get("models",{}).get("llm",{}); emb=cfg.get("models",{}).get("embeddings",{})
    compose_env.update({"CP_BENCHMARK_LLM_MODEL":str(llm.get("model","")),
        "CP_BENCHMARK_LLM_CONTAINER_URL":str(llm.get("container_base_url",llm.get("base_url",""))),
        "CP_BENCHMARK_EMBEDDING_MODEL":str(emb.get("model","")),
        "CP_BENCHMARK_EMBEDDING_CONTAINER_URL":str(emb.get("container_base_url",emb.get("base_url",""))),
        "CP_BENCHMARK_EMBEDDING_DIMENSIONS":str(emb.get("dimensions",1024))})
    llm_key=os.environ.get(llm.get("api_key_env","")) if llm.get("api_key_env") else None
    emb_key=os.environ.get(emb.get("api_key_env","")) if emb.get("api_key_env") else None
    if llm_key is not None: compose_env["CP_BENCHMARK_LLM_KEY"]=llm_key
    else: compose_env.pop("CP_BENCHMARK_LLM_KEY",None)
    if emb_key is not None: compose_env["CP_BENCHMARK_EMBEDDING_KEY"]=emb_key
    else: compose_env.pop("CP_BENCHMARK_EMBEDDING_KEY",None)
    if not skip_startup:
        # Request only the application and database services. No model services or volume operations.
        p=_run(command+["up","-d","--build","--wait","--wait-timeout",str(int(life.get("compose_wait_seconds",900))),"iris","agent"],timeout=int(life.get("compose_wait_seconds",900))+60,check=False,env=compose_env)
        if p.returncode:
            tail=(p.stdout or "")[-1800:]
            # Older Compose versions do not recognize --wait. Start the same two services, then poll health below.
            if "unknown flag: --wait" in tail or "unknown shorthand flag" in tail:
                _run(command+["up","-d","--build","iris","agent"],timeout=int(life.get("compose_wait_seconds",900)),env=compose_env)
            else: raise RuntimeError(f"Compose startup failed (exit {p.returncode}). Build output tail:\n{tail}")
        # Ensure the API process loads the just-built application/profile, while reusing the benchmark DB volume.
        _run(command+["restart","agent"],timeout=120,env=compose_env)

    deadline=time.monotonic()+int(life.get("readiness_timeout_seconds",900))
    while time.monotonic()<deadline:
        if _http_ready(app_url): break
        time.sleep(2)
    else: raise RuntimeError(f"Application did not become healthy at {app_url}")

    # Publish the pinned care-document index through the app container once for this invocation.
    if not skip_startup or life.get("publish_on_attach",True):
        command2=command+["exec","-T","agent","python","-m","central_park.import_care_documents","publish","--directory","/app/md_care_documents"]
        _run(command2,timeout=int(life.get("index_publish_timeout_seconds",600)),env=compose_env)

    # No tokens are included in this result or errors.
    return {"docker_context":ctx,"docker_root_dir":docker_info,"docker_disk_usage":docker_usage,"compose_project":project,"started":not skip_startup,"app_url":app_url,"free_disk_gib":round(free,2),
        "index_publish":"completed","database_volume":"reused; not deleted or pruned","cache_state":"reused; not cleared","llm_probe":llm_result,"embedding_probe":emb_result}
