# feeder_criticality

A worked example of an extension that contributes a semantic capability to a
study that declares it (bd 4ky.8).

| File | What it is |
| --- | --- |
| `feeder_criticality.py` | The extension module: an `ExtensionDescriptor` with `role="semantic_capability"`, and a `factory` returning the capability |
| `pyproject.toml` | The `gridalyn.extensions` entry point an installation would expose |
| `study/` | A study that declares the extension in `spec.inputs.extensions` and builds its semantic graph with the capability |
| `run_example.py` | Runs the study for real, with or without its declaration |

The capability adds one `crit:CriticalityAssessment` per distribution
transformer, linked to the transformer it assesses and carrying how many
buildings that transformer serves. It is deliberately small: the example is
about the mechanism, not the metric.

## Run it

From the repository root:

- `python examples/extensions/feeder_criticality/run_example.py` runs the study
  and prints a JSON summary: the run completes, the graph carries two
  assessments, and `provenance.extensions` records the extension as
  `entry_point`.
- `python examples/extensions/feeder_criticality/run_example.py --without-declaration`
  runs the same study with the declaration removed and the extension still
  installed. The build fails with `UnknownSemanticCapabilityError`, because an
  extension that is not declared is never loaded.

`tests/test_extension_semantic_capability.py` pins both runs. The mechanism is
documented in the Extension Framework guide, under "Contributing a semantic
capability".
