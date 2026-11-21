"""HTML report of one execution (TASK-059).

The report is a single self-contained file (inline CSS, no scripts, no
external resources) placed next to the execution's evidence, so evidence
links are relative and the folder can be archived or shared as a whole.
It is built only from persisted data (``ExecutionReport``), so it can be
regenerated at any time without re-running tests.
"""

from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from qa_schemas.enums import ExecutionStatus
from qa_schemas.results import ExecutionReport, Failure, TestResult
from qa_schemas.specification import TestSpecification

REPORT_FILENAME = "report.html"

_CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5b6475;--line:#e2e5ea;--card:#f7f8fa;
--passed:#1a7f37;--failed:#c62828;--error:#b25e00;--cancelled:#6b7280;--pending:#6b7280}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e8eb;--muted:#9aa3b2;
--line:#2a2f37;--card:#1b1f26;--passed:#4ac26b;--failed:#ff6b6b;--error:#f0a24a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:64rem;margin:0 auto;padding:1.5rem 1rem 3rem}
h1{font-size:1.4rem;margin:.2rem 0 1rem}h2{font-size:1.1rem;margin:0}
.muted{color:var(--muted)}code{font-family:ui-monospace,monospace;font-size:.9em}
.status{display:inline-block;padding:.05rem .5rem;border-radius:1rem;font-size:.8rem;
font-weight:600;text-transform:uppercase;color:#fff}
.passed{background:var(--passed)}.failed{background:var(--failed)}.error{background:var(--error)}
.cancelled,.pending,.running{background:var(--cancelled)}
dl.summary{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:0 0 1.5rem}
dl.summary dt{color:var(--muted)}dl.summary dd{margin:0}
.counts span{margin-right:1rem}
section.case{border:1px solid var(--line);border-radius:.5rem;margin:1rem 0;background:var(--card)}
section.case>header{display:flex;gap:.75rem;align-items:center;padding:.75rem 1rem;flex-wrap:wrap}
section.case>div{padding:0 1rem 1rem}
table{width:100%;border-collapse:collapse}td{padding:.3rem .4rem;border-top:1px solid var(--line);
vertical-align:top}td.num{text-align:right;white-space:nowrap;color:var(--muted)}
.failure{border-left:4px solid var(--failed);padding:.5rem .75rem;margin:.75rem 0;
background:var(--bg);overflow-wrap:anywhere}
.failure.error{border-color:var(--error);background:var(--bg);color:inherit}
img.shot{max-width:100%;max-height:20rem;border:1px solid var(--line);border-radius:.25rem}
ul.evidence{margin:.5rem 0 0;padding-left:1.2rem}
"""


def render_html(report: ExecutionReport, specification: TestSpecification | None = None) -> str:
    execution = report.execution
    title = specification.id if specification else execution.specification_id
    counts = Counter(r.status for r in report.results)
    duration = _duration(execution.started_at, execution.finished_at)

    source = ""
    if specification is not None:
        src = specification.source
        line = f":{src.line}" if src.line else ""
        source = (
            f"<dt>Scenario</dt><dd>{escape(src.feature)} — {escape(src.scenario)} "
            f"<span class=muted>(<code>{escape(str(src.path))}{line}</code>)</span></dd>"
        )

    parts = [
        "<!doctype html><html lang=en><head><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>{escape(title)} — {escape(execution.status.value)}</title>",
        f"<style>{_CSS}</style></head><body><main>",
        f"<h1>{_badge(execution.status)} {escape(title)}</h1>",
        "<dl class=summary>",
        source,
        f"<dt>Execution</dt><dd><code>{escape(execution.id)}</code></dd>",
        f"<dt>Environment</dt><dd>{escape(execution.environment)}</dd>",
        f"<dt>Mode</dt><dd>{escape(execution.mode.value)} / ",
        f"{escape(execution.category.value)}</dd>",
        f"<dt>Started</dt><dd>{_time(execution.started_at)}</dd>",
        f"<dt>Duration</dt><dd>{duration}</dd>",
        "<dt>Test cases</dt><dd class=counts>",
        "".join(
            f"<span>{_badge(status)} {counts[status]}</span>"
            for status in ExecutionStatus
            if counts[status]
        ),
        "</dd></dl>",
    ]
    if report.failure is not None:
        parts.append(_failure(report.failure, "The execution could not run"))
    if report.cleanup_errors:
        items = "".join(f"<li>{escape(e)}</li>" for e in report.cleanup_errors)
        parts.append(
            f"<div class='failure error'><strong>Cleanup problems</strong><ul>{items}</ul></div>"
        )
    parts.extend(_case(result) for result in report.results)
    parts.append(
        f"<p class=muted>Generated from <code>results.json</code> · plan "
        f"<code>{escape(execution.plan_id)}</code></p></main></body></html>"
    )
    return "".join(parts)


def write_html_report(
    report: ExecutionReport, directory: Path, specification: TestSpecification | None = None
) -> Path:
    """Write ``report.html`` into the execution directory (next to its evidence)."""
    path = directory / REPORT_FILENAME
    path.write_text(render_html(report, specification), encoding="utf-8")
    return path


# --- Parts -------------------------------------------------------------------


def _case(result: TestResult) -> str:
    rows = "".join(
        f"<tr><td>{_badge(step.status)}</td>"
        f"<td><strong>{escape(step.keyword)}</strong> {escape(step.text)}"
        + (f" <span class=muted>line {step.line}</span>" if step.line else "")
        + f"</td><td class=num>{step.duration_ms} ms</td></tr>"
        for step in result.steps
    )
    skipped = result.steps_total - len(result.steps)
    if skipped:
        rows += (
            f"<tr><td></td><td class=muted>{skipped} step{'s' if skipped > 1 else ''} not run"
            "</td><td></td></tr>"
        )

    body = [f"<table>{rows}</table>"] if rows else []
    if result.failure is not None:
        body.append(_failure(result.failure))
    body.extend(f"<p class=muted>Note: {escape(note)}</p>" for note in result.notes)
    body.append(_evidence(result))

    return (
        f"<section class=case><header>{_badge(result.status)}<h2>{escape(result.name)}</h2>"
        f"<code class=muted>{escape(result.test_case_id)}</code>"
        f"<span class=muted>{result.duration_ms / 1000:.1f} s</span></header>"
        f"<div>{''.join(body)}</div></section>"
    )


def _failure(failure: Failure, heading: str | None = None) -> str:
    kind = "failure" if failure.classification.value == "application_bug" else "failure error"
    step = f" in step {failure.step_index + 1}" if failure.step_index is not None else ""
    title = escape(heading) if heading else f"{escape(failure.classification.value)}{step}"
    error_type = (
        f" <span class=muted>({escape(failure.error_type)})</span>" if failure.error_type else ""
    )
    message = escape(failure.message)
    return f"<div class='{kind}'><strong>{title}</strong>{error_type}<br>{message}</div>"


def _evidence(result: TestResult) -> str:
    if not result.evidence:
        return ""
    shots = "".join(
        f"<a href='{escape(str(ref.path))}'><img class=shot src='{escape(str(ref.path))}' "
        f"alt='{escape(ref.description or 'screenshot')}'></a>"
        for ref in result.evidence
        if ref.kind == "screenshot"
    )
    links = "".join(
        f"<li><a href='{escape(str(ref.path))}'>{escape(ref.kind)}</a>"
        + (f" <span class=muted>— {escape(ref.description)}</span>" if ref.description else "")
        + "</li>"
        for ref in result.evidence
    )
    return f"{shots}<ul class=evidence>{links}</ul>"


def _badge(status: ExecutionStatus) -> str:
    return f"<span class='status {status.value}'>{escape(status.value)}</span>"


def _time(value: datetime | None) -> str:
    return escape(value.strftime("%Y-%m-%d %H:%M:%S %Z")) if value else "—"


def _duration(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "—"
    return f"{(end - start).total_seconds():.1f} s"
