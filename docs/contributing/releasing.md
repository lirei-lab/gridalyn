# Releasing

A release is a tagged commit whose version agrees everywhere it is written and
whose citation resolves to it. What the release claims to be is described in
[What Is Gridalyn?](../start/what-is-gridalyn.md); this page covers the
mechanics.

## Before you tag

Tag a commit on `main` whose CI run is green in every job (see
[What CI checks](developer-workflow.md#what-ci-checks-on-your-pull-request)).
Then close the gaps CI leaves: run the [Operator Verification](verification.md)
command, and confirm with `python tools/verification_receipt.py --check` that
the receipts for the operator-verified studies are current at that commit.

## The version

The version lives in three files and is bumped in all three together:

- `pyproject.toml` — `version` under `[project]`;
- `CITATION.cff` — `version`;
- `.zenodo.json` — `version`.

`tests/test_citation_metadata.py` asserts that `CITATION.cff` names the
`pyproject.toml` version and that `.zenodo.json` agrees with `CITATION.cff` on
title, version and licence, so the three cannot drift apart silently. The tag
is the version with a `v` prefix: `v0.1.0` for `0.1.0`.

## Citation and DOI

`CITATION.cff` is the citable record, and `.zenodo.json` is the deposition
metadata Zenodo reads when a GitHub release is archived. Minting the DOI is
the one step that cannot be done from inside the repository, and it is done
once.

Development happens in the private `github.com/lirei-lab/gridalyn-dev`; the public
<https://github.com/lirei-lab/gridalyn> carries only the documentation until
publication. Zenodo archives public repositories only, so the release is cut
**in the public repository**, after the citable snapshot (the code, the study
YAMLs and their pinned baselines, at the tagged commit) has been pushed to it:

1. Sign in at <https://zenodo.org> with the GitHub account that owns
   <https://github.com/lirei-lab/gridalyn>, and enable the repository under
   *GitHub → Repositories*. Zenodo archives only releases created **after**
   the switch is on.
2. Push the snapshot to the public repository, then cut a GitHub release
   there whose tag matches the version. Zenodo archives the
   tarball and mints two DOIs: a **concept DOI** that always resolves to the
   newest version, and a **version DOI** for that release alone.
3. Put the **concept DOI** in `CITATION.cff` as a bare `doi:` field — the
   identifier, not a URL:

   ```yaml
   doi: 10.5281/zenodo.XXXXXXX
   ```

   `test_doi_when_present_is_well_formed` skips while the field is absent and
   asserts its shape once it is present.
4. Re-run `uv run pytest -q tests/test_citation_metadata.py` and confirm every
   test passes with none skipped.

On every later release, bump the version in the three files and leave the
concept DOI unchanged: it is what a reference manager resolves.
