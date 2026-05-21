"""Generate synthetic load traces with the Gridalyn datagen facade."""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn.assets.datagen import GridLoadFacade, download_tmy, select_cold_day


OUTPUT_DIR = Path("examples/generated/outputs/datagen_serial")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    weather = select_cold_day(download_tmy())["temp_air"]
    heat_kw, background_kw = GridLoadFacade.generate_loads(
        "parametric",
        weather,
        n_houses=25,
        resolution_minutes=15,
        seed=42,
    )

    summary = {
        "house_count": 25,
        "resolution_minutes": 15,
        "heat_peak_kw": float(heat_kw.sum(axis=1).max()),
        "background_peak_kw": float(background_kw.sum(axis=1).max()),
    }
    report_path = OUTPUT_DIR / "datagen_load_summary.json"
    report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Datagen summary: {report_path}")


if __name__ == "__main__":
    main()
