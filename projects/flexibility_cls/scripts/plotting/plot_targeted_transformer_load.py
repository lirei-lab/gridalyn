import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
from projects.flexibility_cls.scripts.config import N_BUILDINGS

def plot_targeted_transformer_load():
    b_path = ROOT / "projects" / "flexibility_cls" / "outputs" / "data" / "substation_baseline_mc.parquet"
    ev_path = ROOT / "projects" / "flexibility_cls" / "outputs" / "data" / "substation_ev_capability_mc.parquet"
    
    if not b_path.exists() or not ev_path.exists():
        print("[!] Parquet data not found. Please run `generate_substation_cls_data.py` first.")
        sys.exit(1)
        
    df_baseline = pd.read_parquet(b_path)
    df_ev_total = pd.read_parquet(ev_path)
    ts_index = df_baseline.index
    
    plt.figure(figsize=(10.0, 6.0))
    plt.plot(ts_index, df_baseline.mean(axis=1), label="Substation Mean Baseline (MW)", color='blue')
    plt.fill_between(ts_index, df_baseline.quantile(0.05, axis=1), df_baseline.quantile(0.95, axis=1), color='blue', alpha=0.2)
    
    total_mean = df_baseline.mean(axis=1) + df_ev_total.mean(axis=1)
    total_p5 = df_baseline.quantile(0.05, axis=1) + df_ev_total.quantile(0.05, axis=1)
    total_p95 = df_baseline.quantile(0.95, axis=1) + df_ev_total.quantile(0.95, axis=1)
    
    plt.plot(ts_index, total_mean, label="Aggregate Baseline + EV (MW)", color='red')
    plt.fill_between(ts_index, total_p5, total_p95, color='red', alpha=0.2)
    
    plt.title(f"Primary Distribution Substation ({N_BUILDINGS} Explicit Households | 30% EVs)")
    plt.ylabel("Demand (MW)")
    plt.xlabel("Time")
    plt.legend(loc="upper left", frameon=True, framealpha=1.0, facecolor="white", edgecolor="#CCCCCC").set_zorder(99)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    outputs_dir = ROOT / "projects" / "flexibility_cls" / "outputs" / "figures" / "02_stage1_stochastic_load"
    outputs_dir.mkdir(exist_ok=True, parents=True)
    out_file = outputs_dir / "targeted_transformer_load.png"
    plt.savefig(out_file)
    print(f"  -> Generated Figure: {out_file}")

if __name__ == "__main__":
    plot_targeted_transformer_load()
