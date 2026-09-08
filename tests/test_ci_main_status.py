"""Gate the CI-status notifier that ``ci.yml`` runs on pushes to ``main``.

This module is tested here rather than trusted because of an asymmetry the
job cannot escape: ``report-main-failure`` runs ONLY on pushes to ``main``, so
the pull request that changes it can never exercise it. Its first real
execution is always in production, on a day something else is already broken.

The logic therefore lives in ``tools/ci_main_status.mjs`` instead of inline in
the workflow YAML, where nothing could reach it, and these tests drive it
against a mocked octokit on every pull request.

Why that matters more than making the job blocking: a job that blocks turns
``main`` red when the NOTIFIER breaks, and the mechanism that reports a red
``main`` is the broken job -- so the red goes unreported and every subsequent
push stays red with no issue ever opened. The evidence that "someone will
investigate a red main" is false is the ten days it stayed red behind a badge
on the repository front page (syntgrid-d6f, syntgrid-di6).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "ci_main_status.mjs"

# `node` is provisioned in CI's `test` job (actions/setup-node). Locally it may
# be absent; skipping there is fine, skipping in CI would make this a gate that
# does not run, which is the failure this file exists to prevent elsewhere.
# Applied to the driving classes, NOT to the module. A module-level
# `pytestmark` would also skip `test_this_gate_cannot_be_silently_disabled_in_ci`
# below -- the one check whose whole job is to fire when node is missing. A
# guard that skips under the condition it guards against proves nothing.
_needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def test_this_gate_cannot_be_silently_disabled_in_ci() -> None:
    """Removing `setup-node` must fail the pull request that removes it.

    The skip above is the right behaviour locally and the wrong behaviour in
    CI: without `node` the whole module skips, the notifier ships ungated, and
    the only trace is a skip reason in a summary nobody reads. That is passive
    signal -- the precise defect ``syntgrid-di6`` exists to remove, reappearing
    one level up in the guard for it.

    GitHub Actions always sets ``CI``, so this converts that silent degradation
    into a failure on the change that causes it. It deliberately sits OUTSIDE
    the ``skipif`` above, because a check that skips under the condition it is
    checking for proves nothing.
    """
    if os.environ.get("CI") and shutil.which("node") is None:
        pytest.fail(
            "node is absent in CI, so tests/test_ci_main_status.py skipped and "
            "tools/ci_main_status.mjs would ship ungated. Restore the "
            "`Set up Node` step in the `test` job of .github/workflows/ci.yml."
        )


_DRIVER = """
import {{ run }} from {module};

const calls = [];
const issues = {issues};
const github = {{ rest: {{ issues: {{
  createLabel:   async (a) => {{ calls.push(['createLabel', a.name]);
                                 if ({label_status}) {{ const e = new Error('x');
                                   e.status = {label_status}; throw e; }} }},
  listForRepo:   async () => ({{ data: issues }}),
  create:        async (a) => {{ calls.push(['create', a.title, a.body]);
                                 return {{ data: {{ number: 99 }} }}; }},
  createComment: async (a) => {{ calls.push(['comment', a.issue_number, a.body]); }},
  update:        async (a) => {{ calls.push(['update', a.issue_number, a.state]); }},
}} }} }};
const context = {{ sha: 'deadbeefcafe0000', serverUrl: 'https://github.com',
                   repo: {{ owner: 'lirei-lab', repo: 'gridalyn' }}, runId: 42 }};
const core = {{ info: () => {{}}, notice: () => {{}}, warning: () => {{}} }};

try {{
  const outcome = await run({{ github, context, core, env: {env} }});
  console.log(JSON.stringify({{ outcome, calls }}));
}} catch (e) {{
  console.log(JSON.stringify({{ threw: String(e.message), status: e.status ?? null }}));
}}
"""


def _drive(
    tmp_path: Path,
    *,
    failed: bool,
    needs: dict[str, str] | None = None,
    issues: list[dict[str, object]] | None = None,
    label_status: int = 0,
) -> dict[str, object]:
    """Run the notifier against a mocked octokit and return what it did.

    Args:
        tmp_path: pytest temporary directory for the driver script.
        failed: Whether the workflow's ``needs`` contained a failure.
        needs: Job id to conclusion, as the ``needs`` context carries it.
        issues: Open issues ``listForRepo`` should return.
        label_status: HTTP status ``createLabel`` should raise, or 0 to succeed.

    Returns:
        The parsed JSON the driver printed: the outcome and the calls made, or
        the error the module raised.
    """
    needs_json = json.dumps({job: {"result": r} for job, r in (needs or {}).items()})
    env = json.dumps(
        {"FAILED": "true" if failed else "false", "NEEDS_JSON": needs_json}
    )
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        _DRIVER.format(
            module=json.dumps(MODULE.as_uri()),
            issues=json.dumps(issues or []),
            env=env,
            label_status=label_status,
        ),
        encoding="utf-8",
    )
    out = subprocess.run(
        ["node", str(driver)], capture_output=True, text=True, check=True, cwd=ROOT
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


OPEN_ISSUE = [{"number": 7, "body": "<!-- ci-main-status -->\nold"}]
RED = {
    "changes": "success",
    "test": "failure",
    "projects": "failure",
    "dashboard": "skipped",
    "lint": "success",
    "docs": "success",
}
GREEN = {**RED, "test": "success", "projects": "success"}


@_needs_node
class TestTrackerIssueFollowsMain:
    """The four transitions the job exists to perform."""

    def test_red_with_no_issue_opens_one(self, tmp_path: Path) -> None:
        """A first failure files an issue rather than relying on the badge."""
        got = _drive(tmp_path, failed=True, needs=RED)
        assert got["outcome"] == "opened"
        assert [c[0] for c in got["calls"]] == ["createLabel", "create"]

    def test_the_opened_issue_names_the_failed_jobs(self, tmp_path: Path) -> None:
        """A reader must not have to open the run to learn what broke."""
        got = _drive(tmp_path, failed=True, needs=RED)
        body = got["calls"][-1][2]
        assert "`test`" in body and "`projects`" in body
        # skipped is not failure: the study loop and the SPA skip by design.
        assert "dashboard" not in body

    def test_red_with_an_issue_open_comments_instead_of_opening_a_second(
        self, tmp_path: Path
    ) -> None:
        """One issue, however many red pushes follow."""
        got = _drive(tmp_path, failed=True, needs=RED, issues=OPEN_ISSUE)
        assert got["outcome"] == "updated"
        assert [c[0] for c in got["calls"]] == ["createLabel", "comment"]

    def test_green_closes_the_open_issue(self, tmp_path: Path) -> None:
        """The close is what stops this becoming another ignored ornament."""
        got = _drive(tmp_path, failed=False, needs=GREEN, issues=OPEN_ISSUE)
        assert got["outcome"] == "closed"
        assert ["update", 7, "closed"] in [list(c) for c in got["calls"]]

    def test_green_with_nothing_open_writes_nothing(self, tmp_path: Path) -> None:
        """The common case must be silent, or the noise trains people to ignore it."""
        got = _drive(tmp_path, failed=False, needs=GREEN)
        assert got["outcome"] == "noop"
        assert [c[0] for c in got["calls"]] == ["createLabel"]


@_needs_node
class TestLabelBootstrap:
    """The job must work on its first invocation, and in a fork."""

    def test_a_missing_label_is_created(self, tmp_path: Path) -> None:
        """Without this the job fails the first time it is ever needed."""
        got = _drive(tmp_path, failed=True, needs=RED)
        assert got["calls"][0] == ["createLabel", "ci-failure"]

    def test_an_existing_label_is_not_an_error(self, tmp_path: Path) -> None:
        """422 is the steady state, not a failure."""
        got = _drive(tmp_path, failed=True, needs=RED, label_status=422)
        assert got["outcome"] == "opened"

    def test_a_permission_error_is_raised_not_swallowed(self, tmp_path: Path) -> None:
        """A missing `issues: write` grant must fail loudly, not do nothing."""
        got = _drive(tmp_path, failed=True, needs=RED, label_status=403)
        assert got.get("status") == 403, got
