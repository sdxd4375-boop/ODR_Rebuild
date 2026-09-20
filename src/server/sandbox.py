"""Restricted Python execution sandbox for model-generated chart code.

Model-generated code NEVER runs in the server process: it is validated
against an import whitelist (AST-based), written to a temp workspace, and
executed in an isolated subprocess (python -I, no user site, cwd=jail) with a
hard timeout. Production deployments should additionally run this inside a
Docker container (--network none --memory 512m) — see TECHNICAL_SUMMARY §8.2.
"""

import ast
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

logger = logging.getLogger(__name__)

# Imports allowed in sandboxed chart code. Everything else is rejected.
ALLOWED_IMPORTS = {
    "math", "statistics", "random", "datetime", "json", "re",
    "matplotlib", "numpy", "pandas",
}

MAX_CODE_BYTES = 32_000
DEFAULT_TIMEOUT_SECONDS = 30


class SandboxViolation(Exception):
    """Raised when code requests imports outside the whitelist."""


def check_imports(code: str) -> list[str]:
    """Return disallowed top-level imports found via AST parsing."""
    tree = ast.parse(code)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    return [name for name in imported if name.split(".")[0] not in ALLOWED_IMPORTS]


def run_python_code(
    code: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    env_extra: dict[str, str] | None = None,
    trusted_preamble: str = "",
) -> dict[str, str]:
    """Execute code in a jailed subprocess. Returns {stdout, stderr}.

    `trusted_preamble` is engine-provided setup code prepended to the script;
    it is NOT subject to the import whitelist (only user `code` is validated).

    Raises SandboxViolation for whitelist breaches, subprocess.TimeoutExpired
    on timeout, and OSError for workspace problems.
    """
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise SandboxViolation(f"Code exceeds {MAX_CODE_BYTES} bytes")

    disallowed = check_imports(code)
    if disallowed:
        raise SandboxViolation(
            f"Imports not allowed in sandbox: {', '.join(sorted(set(disallowed)))}. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMPORTS))}"
        )

    workspace = tempfile.mkdtemp(prefix="odr_sandbox_")
    script = os.path.join(workspace, "snippet.py")
    try:
        with open(script, "w", encoding="utf-8") as f:
            f.write(trusted_preamble + code)

        env = {
            "PYTHONIOENCODING": "utf-8",
            "MPLBACKEND": "Agg",  # headless rendering
            "MPLCONFIGDIR": tempfile.mkdtemp(prefix="odr_mpl_"),  # writable font cache
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows: matplotlib needs it
        }
        if env_extra:
            env.update(env_extra)

        completed = subprocess.run(
            [sys.executable, "-I", script],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {"stdout": completed.stdout, "stderr": completed.stderr}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_python_code_collect_files(
    code: str,
    out_dir: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[str]:
    """Run chart code whose artifacts are saved into out_dir.

    The snippet is prepended with a preamble that points matplotlib's output
    at out_dir; the sandbox workspace itself is discarded. Returns absolute
    paths of files the snippet saved (must exist and be non-empty).
    """
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    preamble = (
        "import os\n"
        f"OUT_DIR = r\"{out_dir}\"\n"
        "os.makedirs(OUT_DIR, exist_ok=True)\n"
        "os.chdir(OUT_DIR)\n"
    )
    result = run_python_code(
        code, timeout_seconds=timeout_seconds, trusted_preamble=preamble
    )
    if result["stderr"] and not result["stdout"]:
        raise RuntimeError(f"Sandbox code failed: {result['stderr'][:2000]}")

    saved = []
    for name in os.listdir(out_dir):
        path = os.path.join(out_dir, name)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            saved.append(path)
    if not saved:
        raise RuntimeError("Sandbox code produced no output files")
    return saved


def new_chart_filename(prefix: str = "chart") -> str:
    """Collision-safe output filename for a generated chart."""
    return f"{prefix}_{uuid.uuid4().hex[:10]}.png"
