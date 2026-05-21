"""Sandboxed execution of candidate parser code.

The self-heal agent emits patched scraper modules and we have to run them to
see if they work. We do that in a subprocess so a bad parser (infinite loop,
exception, memory hog, SystemExit) can't take the agent down with it. The
subprocess has the project venv on PYTHONPATH but no special privileges.

Contract:
- Input: full Python source for a replacement scraper module + the raw snapshot
- Output: SandboxResult with parsed rows OR a traceback string
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 30


@dataclass(slots=True)
class SandboxResult:
    ok: bool
    row_count: int = 0
    rows: list[dict] | None = None
    traceback: str | None = None
    timed_out: bool = False


def run_candidate(
    candidate_module_src: str,
    snapshot_bytes: bytes,
    state: str,
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    python_executable: str | None = None,
) -> SandboxResult:
    """Run candidate parser source against snapshot bytes, return parsed rows or traceback."""
    python = python_executable or sys.executable

    with tempfile.TemporaryDirectory(prefix="warn-heal-") as tmpdir:
        tmp = Path(tmpdir)
        module_path = tmp / "candidate_scraper.py"
        snapshot_path = tmp / "snapshot.bin"
        result_path = tmp / "result.json"

        module_path.write_text(candidate_module_src, encoding="utf-8")
        snapshot_path.write_bytes(snapshot_bytes)

        runner = _RUNNER_TEMPLATE.format(
            state=state.upper(),
            module_path=str(module_path).replace("\\", "\\\\"),
            snapshot_path=str(snapshot_path).replace("\\", "\\\\"),
            result_path=str(result_path).replace("\\", "\\\\"),
        )
        runner_path = tmp / "runner.py"
        runner_path.write_text(runner, encoding="utf-8")

        try:
            proc = subprocess.run(
                [python, str(runner_path)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                traceback=f"timed out after {timeout_s}s",
                timed_out=True,
            )

        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                return SandboxResult(
                    ok=False,
                    traceback=(
                        f"runner wrote invalid JSON: {e}\n"
                        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
                    ),
                )
            if payload.get("ok"):
                return SandboxResult(
                    ok=True,
                    row_count=payload["row_count"],
                    rows=payload["rows"],
                )
            return SandboxResult(ok=False, traceback=payload.get("traceback") or "")

        return SandboxResult(
            ok=False,
            traceback=(
                f"runner did not write result.json (exit={proc.returncode})\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            ),
        )


# The runner script imports the candidate module by path, instantiates the
# registered scraper for `state`, calls parse() on the snapshot bytes, and
# serializes the rows as JSON-safe dicts.
_RUNNER_TEMPLATE = textwrap.dedent(
    """\
    import importlib.util
    import json
    import sys
    import traceback
    from dataclasses import asdict, is_dataclass
    from datetime import date, datetime
    from pathlib import Path


    def _json_default(o):
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        if is_dataclass(o):
            return asdict(o)
        return repr(o)


    def main() -> None:
        result_path = Path(r"{result_path}")
        try:
            spec = importlib.util.spec_from_file_location(
                "candidate_scraper", r"{module_path}"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # The candidate is expected to register itself on import. Look it
            # up via the project registry rather than reaching into the module
            # directly so the contract stays uniform.
            from warn_v2.scrapers.registry import REGISTRY

            scraper = REGISTRY.get("{state}")
            if scraper is None:
                raise RuntimeError(
                    "candidate module did not register a scraper for {state}"
                )

            snapshot = Path(r"{snapshot_path}").read_bytes()
            rows = scraper.parse(snapshot)
            payload = {{
                "ok": True,
                "row_count": len(rows),
                "rows": [asdict(r) if is_dataclass(r) else r for r in rows],
            }}
        except Exception:
            payload = {{"ok": False, "traceback": traceback.format_exc()}}

        result_path.write_text(json.dumps(payload, default=_json_default))


    if __name__ == "__main__":
        main()
    """
)
