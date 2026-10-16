"""Coding agent adapter — spins qwen-code as a subprocess."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from harness.adapters.base import AgentAdapter
from harness.types import Case, AdapterResult, TargetConfig, CallRecord, Timing

_QWEN_CODE_ROOT = Path(__file__).resolve().parents.joinpath("Coding_agent/qwen-code-main")


class CodingAdapter(AgentAdapter):
    """Runs qwen-code as a subprocess for each case.
    
    Dataset format (in metadata):
    - repo_path: path to the repo (or temp checkout) to work on
    - instruction: the coding task/bug description (if different from case.input)
    """

    async def run(self, case: Case, config: TargetConfig) -> AdapterResult:
        start_time = time.time()

        meta = case.metadata
        repo_path = meta.get("repo_path", "")
        instruction = meta.get("instruction", case.input)

        # Build qwen-code command.
        # qwen-code accepts a prompt and works in a directory.
        cmd = self._build_cmd(config, instruction, repo_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path or str(_QWEN_CODE_ROOT),
                env=self._env(config),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=meta.get("timeout_seconds", 300),
            )
            output_text = stdout.decode("utf-8", errors="replace").strip()
            error_text = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0 and not output_text:
                output_text = f"[exit {process.returncode}] {error_text}"

        except asyncio.TimeoutError:
            output_text = "[timeout] Coding agent did not complete in time"
        except FileNotFoundError:
            output_text = f"[error] qwen-code executable not found at {_QWEN_CODE_ROOT}"

        end_time = time.time()

        # Coding agents don't expose token counts via subprocess.
        # Record a single call with 0 tokens (override with --price-table if needed).
        calls = [CallRecord(
            model_used=config.model,
            input_tokens=0,
            output_tokens=0,
        )]

        return AdapterResult(
            final_output=output_text,
            calls=calls,
            timing=Timing(start_time=start_time, end_time=end_time),
        )

    def _build_cmd(self, config: TargetConfig, instruction: str, repo_path: str) -> list[str]:
        """Build the subprocess command for qwen-code."""
        # Default: node-based qwen-code CLI
        # Adjust this to match your actual qwen-code invocation.
        cmd = [
            "node",
            str(_QWEN_CODE_ROOT / "bin/qwen-code"),  # adjust path as needed
            "--prompt", instruction,
            "--non-interactive",
        ]
        if repo_path:
            cmd.extend(["--repo", repo_path])
        return cmd

    def _env(self, config: TargetConfig) -> dict | None:
        """Env vars to pass to the subprocess."""
        import os
        env = os.environ.copy()
        env["OPENAI_BASE_URL"] = config.endpoint
        env["OPENAI_API_KEY"] = config.api_key
        env["OPENAI_MODEL"] = config.model
        return env
