# admm_thermal_consensus

Network-validated distributed ADMM coordination of cold-climate electric-heating
homes with ML imputation of communication-failed agents, validated on the
IEEE-33 feeder with pandapower.

Run the full study:

    uv run gridalyn-project run projects/admm_thermal_consensus

Methodology adapted from the reja MAS/ADMM thesis; extended with power-flow
validation (the reja work coordinated only an aggregate signal). See the design
spec in `docs/superpowers/specs/2026-06-25-admm-thermal-consensus-design.md`.
