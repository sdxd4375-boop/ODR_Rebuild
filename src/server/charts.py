"""Chart generation pipeline: report Markdown -> sandboxed matplotlib -> PNG.

An LLM extracts chart-worthy data from the final report and emits matplotlib
snippets; each snippet is executed in the restricted sandbox (see sandbox.py)
and successful charts are injected back into the Markdown. Failures are
non-fatal: the report is returned unchanged for any chart that cannot be
produced.
"""

import base64
import logging
import os
import re

from server.sandbox import new_chart_filename, run_python_code_collect_files

logger = logging.getLogger(__name__)

CHART_PROMPT = """You are a data-visualization assistant. Given a research report (Markdown),
extract 1 to 3 charts worth rendering. For each chart, write a SELF-CONTAINED Python snippet that:
1. Hardcodes the data (numbers copied verbatim from the report — never invent data; if the report
   has no numeric data suitable for a chart, return no charts).
2. Uses only matplotlib (import matplotlib.pyplot as plt) plus the stdlib (json/math/statistics).
3. Saves the figure to the relative path given in `filename` via plt.savefig(filename, dpi=150, bbox_inches="tight").
4. Uses English or Chinese labels as they appear in the report; add a title.
5. Does NOT call plt.show().

Respond with ONLY a JSON array, no markdown fence:
[{"title": "...", "filename": "chart_xxx.png", "code": "..."}]

Report:
{report}"""


def _get_llm(model: str | None = None):
    from langchain.chat_models import init_chat_model

    return init_chat_model(model or os.environ.get("CHART_MODEL", "openai:gpt-4.1-mini"))


def _parse_snippets(raw: str) -> list[dict]:
    """Parse the model's JSON array response, tolerating markdown fences."""
    text = raw.strip()
    fence = re.search(r"\[.*\]", text, re.DOTALL)
    if not fence:
        return []
    import json

    try:
        arr = json.loads(fence.group(0))
    except json.JSONDecodeError:
        logger.warning("Chart LLM returned non-JSON output")
        return []
    return [
        item
        for item in arr
        if isinstance(item, dict) and item.get("code") and item.get("filename")
    ]


def inject_chart(markdown: str, title: str, rel_path: str) -> str:
    """Insert the chart reference after the first heading, or append at end."""
    block = f"\n![{title}]({rel_path})\n"
    headings = list(re.finditer(r"^#{1,3} .+$", markdown, re.MULTILINE))
    if len(headings) >= 2:
        pos = headings[1].start()
        return markdown[:pos] + block + "\n" + markdown[pos:]
    return markdown.rstrip() + "\n" + block


def generate_charts(
    report_markdown: str,
    charts_dir: str,
    model: str | None = None,
    max_charts: int = 3,
) -> tuple[str, list[str]]:
    """Produce charts for a report. Returns (updated_markdown, chart_paths).

    Any failure (LLM error, sandbox violation, bad code) leaves the report
    unchanged — chart generation must never break report delivery.
    """
    if not report_markdown.strip():
        return report_markdown, []

    try:
        raw = _get_llm(model).invoke(
            CHART_PROMPT.format(report=report_markdown[:12000])
        ).content
        if isinstance(raw, list):  # content blocks
            raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))
        snippets = _parse_snippets(raw)[:max_charts]
    except Exception:  # noqa: BLE001 — charting is best-effort
        logger.exception("Chart LLM call failed")
        return report_markdown, []

    updated = report_markdown
    saved: list[str] = []
    for item in snippets:
        filename = new_chart_filename()
        try:
            paths = run_python_code_collect_files(item["code"], charts_dir)
        except Exception:  # noqa: BLE001 — per-chart isolation
            logger.warning("Chart snippet failed for '%s'", item.get("title"), exc_info=True)
            continue
        src = paths[0]
        final_name = filename if src.endswith(".png") else os.path.basename(src)
        final_path = os.path.join(charts_dir, final_name)
        if os.path.abspath(src) != os.path.abspath(final_path):
            os.replace(src, final_path)
        rel = f"charts/{final_name}"
        updated = inject_chart(updated, item.get("title", "chart"), rel)
        saved.append(final_path)
    return updated, saved


def chart_file_response(path: str) -> str:
    """Base64-encode a chart for inline delivery (kept for API symmetry)."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()
