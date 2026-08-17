# Project Development

The concise mechanic for building and validating a Gridalyn project. A project
is *bound*, not hand-wired: its components are declared in `project.yaml`,
resolved once through `ProjectScript`, and driven from thin stage scripts. This
page is the surface for the developer experience; the contracts underneath live
in `gridalyn/projects/scripting.py` and `gridalyn/projects/developer.py`.

## The shape of a stage script

```python
from gridalyn.projects.developer import bind_project_components
from gridalyn.projects.scripting import project_script

def main() -> int:
    script = project_script()
    components = bind_project_components(script)   # specs + backend resolved once
    net = components.build_feeder()                # SDK builder, declared spec
    ...
    script.write_json("outputs/data/result.json", result)   # governed JSON
    script.write_report("result_report", summary=result.summary())
    return 0
```

The same four steps — find the project, resolve declared components, write
artifacts, write the report — are what every stage does. The helpers below
remove the boilerplate the heavy studies used to repeat.

## ProjectScript fills

`project_script()` returns a frozen `ProjectScript` bound to the surrounding
`project.yaml`. Its fills replace the two most common hand-rolled patterns:

- **Governed JSON IO** — `script.read_json(relative)` /
  `script.write_json(relative, payload)`. `write_json` writes deterministic
  JSON (`sort_keys=True`, `indent=2`, trailing newline) and returns the
  `file_reference` provenance record (`path` / `bytes` / `sha256`). Missing and
  malformed files raise located errors naming the resolved path.
- **Project-module import** — `script.load_project_module("scripts.config")`
  imports a dotted project-relative module without `sys.path` mutation or
  `Path(__file__).parents[N]` boilerplate, and caches it. It is the
  *programmatic* import path (a stage that wants the module as a Python
  object). Heavy-study stages run as modules instead —
  `{python} -m projects.<study>.scripts.<module>` — which keeps module
  identity for pickled artifacts and binds the interpreter via the runner's
  `{python}` placeholder; both are sanctioned, and neither needs
  `sys.path`/`parents[N]` boilerplate.

Plus the existing surface: typed input loaders (`load_radial_feeder_spec`,
`load_generated_load_profiles`, …), `simulation_seed(stream)`,
`powerflow_backend_id()`, `powerflow_backend()`, `write_report()` and the
`outputs/*` path properties.

## Bind, don't hand-wire

`bind_project_components(script)` is the sanctioned way a project declares its
model / observer / controller. It resolves the declared `sourceNetwork` feeder
spec, the `loadGeneration` profiles and the declared power-flow backend through
the `ProjectScript` typed loaders — once, never by re-deriving `project.yaml`
literals. It returns a frozen `ProjectComponents` bundle:

- `components.build_feeder()` — constructs the network through the SDK builder
  from the bound feeder spec (no implicit solve).
- `components.consume(role, component_id)` — resolves a project-defined
  component registered through the per-role extension registries by explicit
  ID (never ambient). Currently wired: `backend`
  (`register_powerflow_backend_extension` → `consume("backend", id)`). The
  `observation_producer` / `surrogate` / `policy` roles are declared follow-up
  surface — their registries do not yet expose a `registration_source`
  discriminator, so the bind cannot tell a project-registered component from a
  core default for them.
- `components.to_dict()` — a JSON-native summary for reports and manifests.

A project registers its own components through the per-role extension
registries before the bind (`register_powerflow_backend_extension`, … — see
[the extension framework](extensions.md)); the bind records every non-core
**backend** registration by ID so it is visible, declared and in provenance.
Declared-but-malformed inputs are contract violations: the bind lets the
loader's located `ValueError` propagate rather than silently degrading the
component to `None`.

## Uniform validation

Every project declares `validation.senseChecker` + `objectiveArtifacts` in
`project.yaml` (the pattern the six thin fixtures use), so
`gridalyn project sense-check` runs the same objective checks on every project:

```yaml
validation:
  senseChecker: scripts/sense_checks.py:check
  objectiveArtifacts:
    - outputs/reports/<report_id>.json
    - outputs/data/<table>.csv
```

A registered checker (`scripts/sense_checks.py` exporting `check(project)`)
returns error/warning records; any **error**-severity failure makes
`validation.valid` false. A project with neither a registered checker nor
declarative checks fails the `project_has_registered_sense_checks` gate — a
study cannot pass vacuously.

## The SDK builders behind it

The binding surface builds on SDK functions the flagship used to re-implement:

- `gridalyn.simulation.analytics.topology` — `thermal_ratings_kw` (per-line /
  per-transformer kW rating), `downstream_bus_map` (radial BFS downstream sets,
  transformer-hop aware), `size_feeder_subtree_kw`,
  `assert_radial_no_generation`.
- `gridalyn.assets.modeling.feeders.lv_feeder_spec` — a declared
  `RadialFeederSpec` LV-feeder variant (a spec constructor; a net is built from
  it via `build_radial_pandapower_feeder`).
- `build_radial_pandapower_feeder` — turns a `RadialFeederSpec` into a net.

When a stage needs a piece of network construction or analytics, prefer these
SDK functions over a project-local re-implementation — that is what makes the
heavy studies thin and the fixtures canonical.
