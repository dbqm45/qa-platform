"""Combined summary of several ``qa test --json`` runs, for CI (TASK-128).

A pipeline usually runs ``qa test`` once per scenario file; ``qa summary``
reads those JSON summaries and prints one overview, as plain text or as
Markdown (e.g. for ``$GITHUB_STEP_SUMMARY``).
"""

from collections import Counter
from collections.abc import Sequence

from qa_schemas.summary import RunSummary, SpecificationSummary

ORDER = ("passed", "failed", "error", "cancelled", "not_executed")
MAX_MESSAGE = 300


def totals(summaries: Sequence[RunSummary]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for summary in summaries:
        counts.update(summary.counts)
    return counts


def all_ok(summaries: Sequence[RunSummary]) -> bool:
    return bool(summaries) and all(s.ok for s in summaries)


def _counts(counts: Counter[str] | dict[str, int]) -> str:
    keys = [k for k in ORDER if counts.get(k)] + sorted(set(counts) - set(ORDER))
    return ", ".join(f"{counts[k]} {k.replace('_', ' ')}" for k in keys) or "nothing ran"


def _status(spec: SpecificationSummary) -> str:
    return spec.status.value if spec.status else "not_executed"


def _short(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= MAX_MESSAGE else one_line[: MAX_MESSAGE - 1] + "…"


def _problems(summary: RunSummary) -> list[tuple[str, str, str]]:
    """(where, classification or status, message) of everything that did not pass."""
    found = [(e.location, e.code, e.message) for e in summary.errors]
    for spec in summary.specifications:
        if spec.status is None:
            found.append((spec.source, "not_executed", spec.problem or ""))
        for failure in spec.failures:
            where = failure.test_case_id or spec.id
            if failure.step is not None:
                where += f", step {failure.step}"
            found.append((where, failure.classification.value, failure.message))
    return found


def render_text(summaries: Sequence[RunSummary]) -> str:
    lines = []
    for summary in summaries:
        mocked = f" (mocked: {', '.join(summary.mocked)})" if summary.mocked else ""
        mark = "OK  " if summary.ok else "FAIL"
        lines.append(
            f"{mark}  {summary.scenario} on {summary.environment}{mocked}: "
            f"{'validation errors' if summary.errors else _counts(summary.counts)}"
        )
        for where, kind, message in _problems(summary):
            lines.append(f"      {where}: {kind}: {_short(message)}")
    verdict = "all passed" if all_ok(summaries) else "NOT all passed"
    lines.append(
        f"\n{len(summaries)} scenario file{'s' if len(summaries) != 1 else ''}: "
        f"{_counts(totals(summaries))} -- {verdict}"
    )
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return _short(text).replace("|", "\\|")


def render_markdown(summaries: Sequence[RunSummary]) -> str:
    ok = all_ok(summaries)
    lines = [
        f"## QA results: {'all passed' if ok else 'NOT all passed'}",
        "",
        f"{len(summaries)} scenario file{'s' if len(summaries) != 1 else ''}: "
        f"{_counts(totals(summaries))}",
        "",
        "| | Scenario file | Environment | Result |",
        "|---|---|---|---|",
    ]
    for summary in summaries:
        env = summary.environment + (
            f" (mocked: {', '.join(summary.mocked)})" if summary.mocked else ""
        )
        result = "validation errors" if summary.errors else _counts(summary.counts)
        lines.append(
            f"| {'✅' if summary.ok else '❌'} | `{summary.scenario}` | {_cell(env)} | {result} |"
        )
    problems = [(s, p) for s in summaries for p in _problems(s)]
    if problems:
        lines += ["", "### Problems", "", "| Scenario file | Where | Kind | Message |",
                  "|---|---|---|---|"]  # fmt: skip
        for summary, (where, kind, message) in problems:
            lines.append(f"| `{summary.scenario}` | `{_cell(where)}` | {kind} | {_cell(message)} |")
    reports = [
        (spec.id, spec.report)
        for s in summaries
        for spec in s.specifications
        if spec.report and spec.status is not None and spec.status.value != "passed"
    ]
    if reports:
        lines += ["", "Reports of what did not pass (in the uploaded artifact):", ""]
        lines += [f"- `{spec_id}`: `{report}`" for spec_id, report in reports]
    return "\n".join(lines) + "\n"
