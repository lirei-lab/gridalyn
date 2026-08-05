"""Suite-wide pytest configuration for ``tests/``.

Skip visibility
---------------
Several tests in this suite skip when a gitignored artifact is absent - the
heavy-study reproduce-and-pin tests most of all. By default pytest reports
those only as a bare ``s`` and a count, so a green summary cannot tell an
operator whether the expensive verification actually ran or was silently
stepped over. That is exactly the gap this project's verification net closes.

``pytest_terminal_summary`` below prints every skipped test with its reason at
the end of a plain ``pytest -q`` run, so the operator does not have to
remember ``-rs``. Reasons are grouped, because one absent artifact typically
skips many tests at once.

The companion gate ``tests/test_skip_visibility.py`` enforces that those
reasons are specific enough to act on.
"""

from __future__ import annotations

from typing import Any

_SKIPPED_PREFIX = "Skipped: "


def _skip_reason(report: Any) -> str:
    """Extract the reason string from a skipped test report."""
    longrepr = getattr(report, "longrepr", None)
    # For a skipped test pytest sets longrepr to (fspath, lineno, message),
    # where message is usually "Skipped: <reason>".
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        message = str(longrepr[2])
        if message.startswith(_SKIPPED_PREFIX):
            return message[len(_SKIPPED_PREFIX) :].strip()
        return message.strip()
    if longrepr:
        return str(longrepr).strip()
    return "<no reason recorded>"


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: int,
    config: Any,
) -> None:
    """Print every skipped test with its reason, without requiring ``-rs``."""
    skipped = terminalreporter.stats.get("skipped", [])
    if not skipped:
        return

    grouped: dict[str, list[str]] = {}
    for report in skipped:
        reason = _skip_reason(report)
        nodeid = str(getattr(report, "nodeid", "") or "<unknown test>")
        grouped.setdefault(reason, []).append(nodeid)

    terminalreporter.write_sep(
        "=",
        f"{len(skipped)} test(s) SKIPPED - verification did not run",
        yellow=True,
    )
    for reason in sorted(grouped):
        nodeids = grouped[reason]
        terminalreporter.write_line(f"[{len(nodeids)}] {reason}")
        for nodeid in sorted(nodeids):
            terminalreporter.write_line(f"      {nodeid}")
