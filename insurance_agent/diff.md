# Diff Summary

## Overview

This repo was originally hardcoded to **Azure OpenAI** with an optional Supabase database. These changes decouple it from any specific provider, making it work with **any OpenAI-compatible API endpoint** (vLLM, Ollama, LocalAI, OpenRouter, LiteLLM, etc.) via a central YAML-driven router.

---

## Original Functionality

| File | What it did |
|---|---|
| `backend/agent.py` | Built a LangGraph agent using `AzureChatOpenAI`. Fell back to Hugging Face router hardcoded to `openai/gpt-oss-20b:nebius`. |
| `backend/agents/claims_agent.py` | Created an `AzureChatOpenAI` instance at **module import time** — no fallback. Required Azure env vars to be set or the entire app would crash on startup. |
| `backend/supabase_client.py` | Imported `supabase` unconditionally at top of file. Even if you didn't use Supabase, the package had to be installed. |
| `backend/requirements.txt` | Listed `fastapi`, `uvicorn`, `langchain`, `langgraph`, `langchain-openai`, `python-dotenv`. No `pyyaml`. |
| `backend/.env` | **Did not exist.** No documented env var setup. |
| `run.sh` | **Did not exist.** Manual steps in `readme.md`. |

### Problems with the original

1. **Tied to Azure** — couldn't swap to any other provider without editing code.
2. **No multi-backend / failover** — one endpoint, one shot.
3. **Module-level LLM init** in `claims_agent.py` — the LLM object was created when the module was first imported, which meant the app crashed at import time if Azure env vars were missing.
4. **Hard dependency on `supabase` package** — imported at top of file even when Supabase was unused.
5. **No documented quick-start** — `readme.md` had manual venv + pip steps, nothing for tmux or uv.

---

## New Files

### `backend/router.py` — Central LLM Router

| Feature | Detail |
|---|---|
| **Config-first** | Reads `router_config.yaml` for a prioritized list of backends |
| **Failover** | Tries each backend in order; on failure, falls through to the next |
| **Health check** | Sends a lightweight `ping` call before committing to a backend |
| **Env var substitution** | Supports `${ENV_VAR}` syntax inside YAML for secrets |
| **.env fallback** | If `router_config.yaml` is missing or pyyaml isn't installed, falls back to `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` env vars |
| **Cached config** | Loads once, caches in `_config_cache` |
| **Public API** | `get_llm(temperature=...)` — used everywhere; `chat(prompt, temperature=...)` — convenience helper |

### `backend/router_config.yaml` — Backend Configuration

```yaml
backends:
  - name: "vllm-local"
    base_url: "http://127.0.0.1:9000/v1"
    api_key: "key"
    model: "Qwen3.6-27B"
  # Add more backends below as fallbacks...
defaults:
  temperature: 0.7
  max_retries: 2
```

This is the **single place** you add, remove, or reorder LLM backends — no code changes needed.

### `backend/.env` — Environment Template

```bash
LLM_BASE_URL=http://127.0.0.1:9000/v1
LLM_API_KEY=key
LLM_MODEL=Qwen3.6-27B
SUPABASE_URL=
SUPABASE_KEY=
```

Pre-filled for the vLLM endpoint. Also serves as fallback if `router_config.yaml` is absent.

### `run.sh` — tmux Quick-Start

Launches a tmux session `ema` with two windows:
- **backend** — `uv venv`, install deps, `uvicorn main:app --reload` (port 8000)
- **frontend** — `npm install`, `npm run dev` (port 3000)

---

## Modified Files

### `backend/agent.py`

| What changed | Before | After | Why |
|---|---|---|---|
| Import | `from langchain_openai import AzureChatOpenAI` | `from backend.router import get_llm` | Decouple from Azure |
| `get_llm()` function | ~22 lines: try Azure, fallback to hardcoded Hugging Face | **Removed entirely** | Router handles this |
| `call_model()` | Called its own `get_llm()` | Calls `get_llm()` from `backend.router` | Single source of truth |
| `os` import | Present (used for env vars in `get_llm`) | **Removed** | No longer needed |

**Net effect:** ~22 fewer lines. The chat agent no longer cares which LLM it talks to.

---

### `backend/agents/claims_agent.py`

| What changed | Before | After | Why |
|---|---|---|---|
| Import | `from langchain_openai import AzureChatOpenAI` | `from backend.router import get_llm` | Decouple from Azure |
| LLM init | `llm = AzureChatOpenAI(...)` at **module level** | **Removed** | Was crashing on import if Azure envs missing |
| `analyze_claim_document()` | Used module-level `llm` | Calls `get_llm(temperature=0)` inside function | Lazy init — only when a request comes in |
| `dotenv` import | `from dotenv import load_dotenv` + `load_dotenv()` | **Removed** | Router handles config loading |

**Net effect:** The LLM is now created **on-demand** per request, not at module import time. No more startup crashes from missing env vars.

---

### `backend/supabase_client.py`

| What changed | Before | After | Why |
|---|---|---|---|
| Import | `from supabase import create_client, Client` at **top of file** | Moved `from supabase import create_client` **inside** `if url and key:` block | No hard dependency — app starts fine without `supabase` installed |
| Type hint | `supabase: Client = None` | `supabase = None` | `Client` type only available if `supabase` is installed |
| Fallback message | `"Supabase credentials not found in environment variables."` | `"Supabase credentials not found in environment variables. Using mock data."` | Clearer messaging |

**Net effect:** You don't need to `pip install supabase` to run the app with mock data.

---

### `backend/requirements.txt`

| What changed | Detail |
|---|---|
| Added `pyyaml` | Required for parsing `router_config.yaml` |

---

## Architecture Before vs After

### Before

```
agent.py ──► AzureChatOpenAI ──► Azure (or Hugging Face hardcoded)
     │
claims_agent.py ──► AzureChatOpenAI (module-level, no fallback) ──► Azure
```

### After

```
agent.py ─────────────────┐
                          ├──► router.get_llm() ──► router_config.yaml
claims_agent.py ──────────┘                       │
                                                  ├──► Backend #1 (vLLM) — fail?
                                                  ├──► Backend #2 (fallback) — fail?
                                                  └──► Backend #3 (.env fallback)
```

---

## How to Add a New LLM Backend

**Zero code changes needed.** Just edit `router_config.yaml`:

```yaml
backends:
  - name: "my-new-router"
    base_url: "http://new-server:8080/v1"
    api_key: "${MY_NEW_KEY}"    # pulls from env var
    model: "gpt-4o"
```

Export the env var, restart, done. The router tries it in order and falls back if it's unreachable.
