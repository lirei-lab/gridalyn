# Platform Configurations

This directory stores reusable platform and study input configurations. It is
source-controlled because these files define reproducible model assumptions.

- `grid/`: synthetic grid, load, line, transformer, and simulation defaults.
- `geography/`: small geographic boundary examples used by project manifests
  and data-acquisition tutorials.

Tutorial examples may read these files, but `examples/` should not own
operational configuration for projects or digital-twin workflows.
