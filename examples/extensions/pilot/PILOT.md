# External Pilot (Phase 18)

The flagship R21 claim — *components register without editing gridalyn while
preserving provenance* — is proven end-to-end here with an extension **outside**
the gridalyn codebase.

## What the pilot proves

1. **An external power-flow backend serves a role.** `examples/extensions/
   pilot_backend/` is a conformant `powerflow_backend` extension (a thin
   wrapper delegating to the shipped pandapower-native solver) with a distinct
   `backend_id` (`pilot_native_backend`). It registers through the declared
   host mechanism (`register_powerflow_backend_extension`), and when a study
   resolves it, the run manifest records
   `provenance.powerflow_backend.extension_id` / `extension_source="host"`.
2. **An external generic extension participates.** A host-registered
   `data_source` extension (or the committed `hello_world` extension loaded
   through the `gridalyn.extensions` entry-point group) lands in the run
   manifest's `provenance.extensions` with its `source` (`"host"` or
   `"entry_point"`).
3. **The run is reproducible.** The pilot below is deterministic: running it
   twice yields identical manifest provenance, and
   `tests/test_extension_pilot.py::EndToEndPilotTest` pins that output.

## How to reproduce

From the repository root, using the project's virtualenv:

```text
.venv/bin/python examples/extensions/pilot/run_pilot.py              # host source
.venv/bin/python examples/extensions/pilot/run_pilot.py --entry-point  # entry_point source
```

Each run scaffolds a throwaway `grid-study`, registers the external components
into the runner's process, runs the study (dry-run — no heavy solvers), and
prints a JSON summary of `provenance.extensions` plus
`provenance.powerflow_backend.extension_id`/`extension_source`. The host
variant shows `source="host"`; the `--entry-point` variant shows
`source="entry_point"` for the committed `hello_world` extension. Both name
`pilot_native_backend` as the role-level extension.

## Why this matters

Before Milestone 8, a solver or data source outside gridalyn could only run by
editing the SDK, and nothing recorded that it had. Now a third party ships a
conformant component, registers it through a declared API, and the governed
manifest says exactly which extension served which role — no edit to gridalyn
required, `projects/` untouched (R7).
