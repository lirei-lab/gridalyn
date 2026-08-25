"""Build a diverse Quebec all-electric fleet from the open NRCan archetypes.

Diversity here has two independent sources and both are load-bearing:

* **Envelope and geometry** come from real EnerGuide audits. The sampler draws
  a stratified subset of the Quebec all-electric baseboard rows of NRCan's
  ``base_archetype_description.csv`` so the fleet spans vintage, floor area,
  air-tightness and heating-degree-days rather than cloning one house.
* **Occupant behaviour** comes from OpenStudio-HPXML's stochastic schedule
  generator, requested downstream with ``--add-stochastic-schedules``. Without
  it every dwelling shares one normalised appliance profile and the aggregate
  is coincident in a way no real feeder is.

The sample is a deterministic function of ``--seed``; the manifest records the
CSV digest, the archetype repository commit and every selected row, so a fleet
can be re-derived rather than merely re-downloaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

ARCHETYPE_REPO_COMMIT = "70e8fe245506f72bc6354b5aa37e51ead9bb88f3"
_RAW = (
    "https://raw.githubusercontent.com/canmet-energy/housing-archetypes/"
    f"{ARCHETYPE_REPO_COMMIT}/data/h2k_files/existing-stock/sd_sa/"
)
_TABLE = (
    "https://raw.githubusercontent.com/canmet-energy/housing-archetypes/"
    f"{ARCHETYPE_REPO_COMMIT}/data/tables/base_archetype_description.csv"
)

# The filter that defines "a Quebec all-electric baseboard dwelling".
_PROVINCE = "QU"
_FUEL = "Electric"
_EQUIP = "Baseboards"
_HOUSE_TYPE = "House"


def _echo(message: str) -> None:
    """Print progress to stderr, keeping stdout machine-readable."""
    print(message, file=sys.stderr, flush=True)


def _sha256(path: Path) -> str:
    """Return the hex sha256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_table(cache: Path) -> Any:
    """Return the NRCan archetype description table, downloading it once."""
    import pandas as pd

    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        _echo(f"downloading archetype table -> {cache}")
        urllib.request.urlretrieve(_TABLE, cache)
    return pd.read_csv(cache, low_memory=False)


def quebec_all_electric(frame: Any) -> Any:
    """Return the Quebec all-electric baseboard single-detached rows."""
    province = (
        frame["province"].astype(str).str.contains(_PROVINCE, case=False, na=False)
    )
    return frame[
        province
        & (frame["spaceHeatingFuel"] == _FUEL)
        & (frame["spaceHeatingEquipType"] == _EQUIP)
        & (frame["houseType"] == _HOUSE_TYPE)
    ].copy()


def stratified_sample(pool: Any, count: int, seed: int) -> Any:
    """Return ``count`` rows spanning vintage and floor-area strata.

    Sampling proportionally inside (decade, area-tercile) strata keeps the
    fleet's envelope spread close to the stock's own rather than to whatever
    a uniform draw happens to hit.
    """
    import pandas as pd

    pool = pool.dropna(subset=["totFloorArea", "decade"])
    pool["_area_band"] = pd.qcut(
        pool["totFloorArea"], 3, labels=["small", "mid", "large"]
    )
    pool["_decade_band"] = (pool["decade"] // 20) * 20  # 20-year vintage bands
    strata = pool.groupby(["_decade_band", "_area_band"], observed=True)

    # Largest-remainder allocation, and deliberately NO per-stratum floor.
    # An earlier version clipped every stratum to at least one dwelling, which
    # sounds harmless and is not: with a sample far smaller than the number of
    # strata the floor dominates the allocation and turns proportional sampling
    # into near-uniform sampling. Measured on this pool it put pre-1900 houses
    # at 21% of a 24-dwelling fleet against 4.8% of the stock -- and those are
    # the largest, leakiest dwellings, so the fleet's load ran roughly twice
    # what the stock supports. Rare strata must be allowed to draw zero.
    exact = strata.size() / len(pool) * count
    take = exact.astype(int)
    remainder = count - int(take.sum())
    if remainder > 0:
        order = (exact - take).sort_values(ascending=False).index[:remainder]
        for key in order:
            take[key] += 1
    picks = []
    for key, wanted in take.items():
        if wanted <= 0:
            continue
        group = strata.get_group(key)
        picks.append(group.sample(n=min(int(wanted), len(group)), random_state=seed))
    sample = pd.concat(picks).sample(frac=1.0, random_state=seed)
    return sample.head(count).sort_values("filename").reset_index(drop=True)


def fetch(sample: Any, dest: Path) -> list[dict[str, Any]]:
    """Download every sampled ``.h2k`` file and return per-dwelling records."""
    dest.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for position, row in enumerate(sample.itertuples()):  # noqa: B007
        name = str(row.filename)
        target = dest / name
        if not target.is_file():
            try:
                urllib.request.urlretrieve(_RAW + name, target)
            except urllib.error.HTTPError as exc:
                # The description table covers the whole archetype library;
                # only part of it lives under existing-stock/sd_sa. A row whose
                # file is not there is skipped, not fatal -- the caller
                # over-samples to absorb the loss and the manifest records the
                # count actually obtained.
                _echo(f"  skip {name}: HTTP {exc.code}")
                continue
        records.append(
            {
                "dwelling": len(records),
                "archetype": name,
                "location": str(row.location),
                "hdd": float(row.hdd),
                "floor_area_m2": float(row.totFloorArea),
                "decade": int(row.decade),
                "ach50": float(row.ach),
                "heating_capacity_kw": float(row.spaceHeatingCapacity),
                "basement_perimeter_m": float(row.basementPerimeter),
                "sha256": _sha256(target),
            }
        )
        _echo(f"  [{position + 1}/{len(sample)}] {name}")
    return records


def main(argv: list[str] | None = None) -> int:
    """Sample a fleet, download its archetypes and write the manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    args = parser.parse_args(argv)

    workdir = Path(args.workdir)
    table_cache = workdir / "base_archetype_description.csv"
    frame = load_table(table_cache)
    pool = quebec_all_electric(frame)
    _echo(f"pool: {len(pool)} Quebec all-electric baseboard houses")

    sample = stratified_sample(pool, args.count, args.seed)
    records = fetch(sample, workdir / "h2k")

    manifest = {
        "kind": "ochre-calibration-fleet",
        "seed": args.seed,
        "count": len(records),
        "pool_size": int(len(pool)),
        "filter": {
            "province": _PROVINCE,
            "spaceHeatingFuel": _FUEL,
            "spaceHeatingEquipType": _EQUIP,
            "houseType": _HOUSE_TYPE,
        },
        "archetype_repo_commit": ARCHETYPE_REPO_COMMIT,
        "table_sha256": _sha256(table_cache),
        "dwellings": records,
    }
    out = workdir / "fleet_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(out), "count": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
