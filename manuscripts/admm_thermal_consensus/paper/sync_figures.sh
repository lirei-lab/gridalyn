#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../../../projects/admm_thermal_consensus/outputs/figures" && pwd)"
DST="$(cd "$(dirname "$0")/figures" && pwd)"
cp "$SRC"/fig_aggregate_profiles.pdf "$DST"/
cp "$SRC"/fig_peak_par_vs_rho.pdf "$DST"/
cp "$SRC"/fig_network_violation_vs_rho.pdf "$DST"/
cp "$SRC"/fig_uncertainty_loading.pdf "$DST"/
echo "synced 4 figures to $DST"
