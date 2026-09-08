// Keeps ONE tracker issue in step with `main`'s CI conclusion.
//
// Invoked from `ci.yml`'s `report-main-failure` job through
// `actions/github-script`, which supplies the authenticated `github` client.
// The logic lives here rather than inline in the YAML for one reason: inline
// workflow JavaScript cannot be tested, and this repository treats a gate that
// is not run as not a gate. `tests/test_ci_main_status.py` exercises every
// branch below against a mocked octokit on every pull request -- which matters
// more here than for most code, because this job runs ONLY on pushes to `main`
// and so cannot be exercised by the pull request that changes it.
//
// The precedent for a Node tool under `tools/` wired into a workflow is
// `check_mermaid_diagrams.mjs`; see `tools/README.md`.

export const MARKER = "<!-- ci-main-status -->";
export const LABEL = "ci-failure";

/** Map the `needs` context to `{job: conclusion}`. */
export function jobResults(needsJson) {
  const raw = JSON.parse(needsJson || "{}");
  return Object.fromEntries(
    Object.entries(raw).map(([job, v]) => [job, v && v.result]),
  );
}

/**
 * A job is red only when it concluded `failure`.
 *
 * `skipped` and `cancelled` are not failures. The `changes` job skips the
 * study loop on docs-only pushes and `dashboard` skips whenever the SPA is
 * untouched; counting either as red would make this cry wolf on the majority
 * of pushes and earn exactly the ignoring the README badge earned.
 */
export function failedJobs(results) {
  return Object.entries(results)
    .filter(([, r]) => r === "failure")
    .map(([job]) => job);
}

export function issueBody({ sha, runUrl, broken }) {
  return [
    MARKER,
    `\`main\` is failing at **${sha}**.`,
    "",
    `Jobs that failed: ${
      broken.length ? broken.map((j) => `\`${j}\``).join(", ") : "see the run"
    }`,
    "",
    runUrl,
    "",
    "This issue is opened and closed automatically by the `report-main-failure`",
    "job in `ci.yml`. It closes itself when `main` goes green. Do not close it",
    "by hand while `main` is red -- it will reopen on the next push and you will",
    "have lost the history in this one.",
  ].join("\n");
}

/**
 * Create the label if it is missing.
 *
 * Without this the job fails on its FIRST invocation -- at exactly the moment
 * it is needed, on a day someone is already debugging something else -- and a
 * fork or fresh clone would hit the same wall. A 422 means it already exists
 * and is the expected steady state; anything else (a 403 from a permission
 * misconfiguration, say) is rethrown, so a broken grant fails loudly instead
 * of quietly doing nothing.
 */
export async function ensureLabel(github, repo) {
  try {
    await github.rest.issues.createLabel({
      ...repo,
      name: LABEL,
      color: "b60205",
      description:
        "Opened automatically when CI fails on main; closes when it goes green.",
    });
    return "created";
  } catch (e) {
    if (e.status !== 422) throw e;
    return "exists";
  }
}

export async function findOpenIssue(github, repo) {
  const { data } = await github.rest.issues.listForRepo({
    ...repo,
    state: "open",
    labels: LABEL,
    per_page: 100,
  });
  return data.find((i) => (i.body || "").includes(MARKER));
}

/**
 * Move the tracker issue to match `main`'s conclusion.
 *
 * Returns the action taken, as a string, so the caller and the tests agree on
 * what happened: `opened`, `updated`, `closed`, or `noop`.
 */
export async function run({ github, context, core, env }) {
  const repo = { owner: context.repo.owner, repo: context.repo.repo };
  const sha = context.sha.slice(0, 8);
  const runUrl = `${context.serverUrl}/${repo.owner}/${repo.repo}/actions/runs/${context.runId}`;
  const failed = env.FAILED === "true";

  await ensureLabel(github, repo);
  const existing = await findOpenIssue(github, repo);

  if (!failed) {
    // Closing matters as much as opening. An issue that opens on failure and
    // never resolves becomes the same ignored ornament the badge became, one
    // indirection further out.
    if (!existing) {
      core.info("main is green and no CI-status issue is open.");
      return "noop";
    }
    await github.rest.issues.createComment({
      ...repo,
      issue_number: existing.number,
      body: `\`main\` is green again at ${sha}. Closing.\n\n${runUrl}`,
    });
    await github.rest.issues.update({
      ...repo,
      issue_number: existing.number,
      state: "closed",
    });
    core.notice(`main is green; closed #${existing.number}`);
    return "closed";
  }

  const body = issueBody({
    sha,
    runUrl,
    broken: failedJobs(jobResults(env.NEEDS_JSON)),
  });

  if (existing) {
    await github.rest.issues.createComment({
      ...repo,
      issue_number: existing.number,
      body,
    });
    core.warning(`main still red; updated #${existing.number}`);
    return "updated";
  }

  const { data: made } = await github.rest.issues.create({
    ...repo,
    title: `CI is failing on main (${sha})`,
    body,
    labels: [LABEL],
  });
  core.warning(`main went red; opened #${made.number}`);
  return "opened";
}
