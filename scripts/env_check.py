"""Fail fast on a broken or misconfigured environment.

Run: python scripts/env_check.py    (exit 0 = ready)
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK ' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(label)


def warn(label: str, detail: str = "") -> None:
    print(f"[WARN] {label}{' — ' + detail if detail else ''}")
    WARNINGS.append(label)


# 1. interpreter
check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
pin_file = ROOT / ".python-version"
if pin_file.exists():
    pin = pin_file.read_text(encoding="utf-8").strip()
    check(f".python-version matches ({pin})", sys.version.split()[0].startswith(pin),
          f"running {sys.version.split()[0]}")
else:
    warn(".python-version missing", 'add "3.11" to pin the interpreter')

# 2. hard dependencies of the core package
for mod in ("aiohttp", "langgraph", "langchain_core", "fastapi", "sqlalchemy", "numpy"):
    try:
        importlib.import_module(mod)
        check(f"import {mod}", True)
    except Exception as exc:  # noqa: BLE001
        check(f"import {mod}", False, repr(exc))

# 3. aiohttp file integrity (catches an interrupted install)
try:
    import aiohttp  # noqa: F401

    pkg = Path(aiohttp.__file__).parent
    missing = [n for n in ("hdrs.py", "client.py", "web.py") if not (pkg / n).exists()]
    check("aiohttp package complete", not missing, f"missing {missing}" if missing else "")
except Exception:  # noqa: BLE001
    pass

# 4. project packages
for mod in ("open_deep_research", "server.app"):
    try:
        importlib.import_module(mod)
        check(f"import {mod}", True)
    except Exception as exc:  # noqa: BLE001
        check(f"import {mod}", False, repr(exc))

# 5. .env + required settings
env_file = ROOT / ".env"
if not env_file.exists():
    warn(".env missing", "cp .env.example .env")
else:
    check(".env present", True)
    try:
        from dotenv import dotenv_values

        vals = dotenv_values(env_file)
    except Exception:  # noqa: BLE001
        vals = {}

    def val(key: str) -> str:
        return (os.environ.get(key) or vals.get(key) or "").strip()

    dsn = val("DATABASE_URL")
    check("DATABASE_URL set", bool(dsn), dsn or "empty")
    if dsn:
        check("DATABASE_URL matches compose (port 5433)", ":5433/" in dsn, dsn)
        check("DATABASE_URL db name is nodr", dsn.rstrip("/").endswith("nodr"), dsn)

    search_api = (val("SEARCH_API") or "tavily").lower()
    if search_api == "tavily":
        # Credential presence is a runtime concern, not a structural one: CI has
        # no keys. Run with --strict before a real research session to promote
        # every warning to a failure.
        if val("TAVILY_API_KEY"):
            check("TAVILY_API_KEY set (SEARCH_API=tavily)", True)
        else:
            warn("TAVILY_API_KEY empty (SEARCH_API=tavily)",
                 "set it, or use SEARCH_API=none + EXTRA_RETRIEVERS=duckduckgo")
    if not val("EXTRA_RETRIEVERS"):
        warn("EXTRA_RETRIEVERS empty", "extra retrievers stay disabled")

    roles = ("RESEARCH_MODEL", "COMPRESSION_MODEL", "FINAL_REPORT_MODEL", "SUMMARIZATION_MODEL")
    if val("OPENAI_BASE_URL"):
        warn("OPENAI_BASE_URL is set",
             "the *_MODEL values must exist on that endpoint: " + ", ".join(roles))
    if val("OPENAI_BASE_URL") and not val("OPENAI_API_KEY").startswith("sk-"):
        warn("OPENAI_API_KEY looks empty/unset",
             "openai:* models read OPENAI_API_KEY — a custom base URL still needs it")

# 6. frontend artifact
dist = ROOT / "web" / "dist" / "index.html"
check("web/dist built", dist.exists(), "" if dist.exists() else "run: cd web && npm run build")

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s) — " + "; ".join(FAILURES))
    sys.exit(1)

STRICT = "--strict" in sys.argv
if STRICT and WARNINGS:
    print(f"STRICT: {len(WARNINGS)} warning(s) treated as failures — " + "; ".join(WARNINGS))
    sys.exit(1)

print(f"Environment ready ({len(WARNINGS)} warning(s)).")
if WARNINGS:
    print("Hint: run with --strict before a real research session.")