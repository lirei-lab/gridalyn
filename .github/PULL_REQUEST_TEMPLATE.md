## What this changes

## Why

## Evidence

Claims about behaviour should carry the output that supports them — a test, a
table, a measurement. If this changes a physical or numerical result, show the
comparison rather than describing it.

## Checklist

- [ ] `pytest -q` passes with the environment activated (stage subprocesses call
      `python`, so a bare run from outside the venv fails with exit 127)
- [ ] `mkdocs build --strict -f docs/mkdocs.yml` is clean, if docs changed
- [ ] Pinned baselines still verify, or the re-base is deliberate and explained
      here and in the study's `CALIBRATION.md`
- [ ] Generator changes that must not move existing results are opt-in, and the
      default path was verified byte-identical rather than assumed
