"""Phase-1 feasibility gate for the OCHRE Québec building reference calibrator.

**What this answers.** Can one Québec HOT2000 archetype travel the whole
route — ``.h2k`` → h2k-hpxml → HPXML on disk → OCHRE → per-end-use time
series — on this machine, with a measured wall-clock and a reproducible
result? That is open question Q1 of the research brief, and it is the
question every later phase is built on top of. Nothing downstream should be
written before this gate is green.

**Why two virtualenvs and not one.** ``h2k-hpxml`` pins ``numpy==1.26.2``;
``ochre-nrel==0.9.2`` pins ``numpy==1.26.4`` through ``nrel-pysam==6.0.1``.
Those pins are mutually exclusive, so the two tools cannot share an
environment, and the handover has to cross a process boundary through a file
on disk. The gate asserts the two resolved numpy versions actually differ —
if a future release made them agree, the premise of this design would have
changed and the gate should say so rather than quietly keep working.
gridalyn's own environment (numpy 2.x) is never touched by either.

**Why a real archetype and not a fixture.** The failure this gate exists to
catch is a semantic mismatch between what h2k-hpxml emits and what OCHRE
accepts. A hand-authored HPXML fixture would pass while the real route was
broken, which is the one outcome that would make this gate worthless.

Run it with ``uv run python tools/ochre_calibration/run_feasibility_gate.py
--report``. First run downloads roughly 1.7 GB of vendor tooling into
``~/.local/share`` and builds two virtualenvs; later runs reuse both.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

# --- Pinned inputs. Every one of these is load-bearing; see README.md. ------

# h2k-hpxml has no PyPI release and no git tags, so it is pinned by commit.
# This commit is deliberately NOT the newest: from 3f82ab4914 (2026-06-17)
# onward the translator emits HPXML schemaVersion 5.0, which OCHRE 0.9.2
# rejects outright (`assert version in ['4.0']`). This commit is the newest
# coherent pairing that emits HPXML 4.0 *and* pins an OpenStudio version
# matching the OpenStudio-HPXML release it asks for.
H2K_HPXML_COMMIT = "b7ac31f40b29f98ee465c0dcfaa32400d0f7651f"
_H2K_HPXML_REPO = "git+https://github.com/canmet-energy/h2k-hpxml.git"
H2K_HPXML_SPEC = f"h2k-hpxml @ {_H2K_HPXML_REPO}@{H2K_HPXML_COMMIT}"
OCHRE_SPEC = "ochre-nrel==0.9.2"

# The vendor toolchain h2k-hpxml shells out to. OpenStudio-HPXML v1.9.1
# refuses to run under any OpenStudio other than 3.9.0, and h2k-hpxml's own
# auto-installer will happily leave a mismatched pair in place.
OPENSTUDIO_VERSION = "3.9.0"
OPENSTUDIO_SHA = "c77fbb9569"
OS_HPXML_VERSION = "v1.9.1"

# The archetype. Selected from canmet-energy/housing-archetypes by a rule
# that is reproducible from the shipped CSV: province QUÉBEC, spaceHeatingFuel
# Electric, spaceHeatingEquipType Baseboards (973 dwellings), then the
# dwelling whose totFloorArea is closest to that cohort's median (186.2 m^2),
# ties broken by filename ascending. It resolves to a Mont-Joli dwelling at
# 5100 HDD18 — the closest of the median-area candidates to the 5500 HDD18
# the studies' own calibration assumes.
ARCHETYPE_REPO_COMMIT = "70e8fe245506f72bc6354b5aa37e51ead9bb88f3"
ARCHETYPE_NAME = "ERS-EX-26701.H2K"
ARCHETYPE_SHA256 = "90c4f24525356b425648404fe4fc7ce6ab0e053a2e1d98a991f3879cc809fdf3"
ARCHETYPE_URL = (
    "https://raw.githubusercontent.com/canmet-energy/housing-archetypes/"
    f"{ARCHETYPE_REPO_COMMIT}/data/h2k_files/existing-stock/sd_sa/{ARCHETYPE_NAME}"
)

# Determinism is judged at this relative tolerance, not bitwise. OCHRE's
# solver is not bit-reproducible across runs — see the README for the
# measured deviation and why the criterion is stated this way.
DETERMINISM_TOLERANCE = 1e-12

_VENDOR_ROOT = Path.home() / ".local" / "share"
_DRIVER = Path(__file__).resolve().parent / "ochre_driver.py"


class StageFailure(RuntimeError):
    """Raised when a gate stage cannot complete.

    The message is the stage's own diagnosis and is recorded verbatim in the
    report, because for this gate the *reason* a stage failed is the result.
    """


def _echo(message: str) -> None:
    """Print progress to stderr, keeping stdout free for the report.

    Args:
        message: Line to emit.
    """
    print(message, file=sys.stderr, flush=True)


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing text output.

    Args:
        cmd: Argument vector.
        **kwargs: Extra arguments forwarded to ``subprocess.run``.

    Returns:
        The completed process.
    """
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _download(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``, creating parents.

    Args:
        url: Source URL.
        dest: Destination file path.

    Raises:
        StageFailure: If the download cannot be completed.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310
            dest.write_bytes(response.read())
    except OSError as exc:
        raise StageFailure(f"could not download {url}: {exc}") from exc


def _sha256(path: Path) -> str:
    """Return the hex sha256 of a file.

    Args:
        path: File to digest.

    Returns:
        Hex digest string.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Stage 1: the two isolated virtualenvs ---------------------------------


def _ensure_venv(root: Path, spec: str) -> Path:
    """Create (or reuse) a virtualenv and install one pinned distribution.

    Args:
        root: Directory the virtualenv lives in.
        spec: A single pip requirement specifier.

    Returns:
        Path to the virtualenv's interpreter.

    Raises:
        StageFailure: If ``uv`` is unavailable or the install fails.
    """
    python = root / "bin" / "python"
    if python.exists():
        return python
    if shutil.which("uv") is None:
        raise StageFailure("uv is not on PATH; it is required to build the venvs")
    root.parent.mkdir(parents=True, exist_ok=True)
    created = _run(["uv", "venv", "--python", "3.12", str(root)])
    if created.returncode != 0:
        raise StageFailure(f"uv venv failed for {root}: {created.stderr.strip()}")
    env = dict(os.environ, VIRTUAL_ENV=str(root))
    installed = _run(["uv", "pip", "install", spec], env=env)
    if installed.returncode != 0:
        raise StageFailure(
            f"uv pip install {spec!r} failed: {installed.stderr.strip()}"
        )
    return python


def _numpy_version(python: Path) -> str:
    """Report the numpy version resolved inside one virtualenv.

    Args:
        python: Interpreter to interrogate.

    Returns:
        The version string.

    Raises:
        StageFailure: If numpy cannot be imported.
    """
    probe = _run([str(python), "-c", "import numpy; print(numpy.__version__)"])
    if probe.returncode != 0:
        raise StageFailure(f"numpy missing from {python}: {probe.stderr.strip()}")
    return probe.stdout.strip()


def stage_environments(workdir: Path) -> dict[str, Any]:
    """Build both virtualenvs and prove their numpy pins are incompatible.

    Args:
        workdir: Gate working directory.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If either environment is unusable, or if the two pins
            have converged — which would invalidate this design's premise.
    """
    translate = _ensure_venv(workdir / "venvs" / "translate", H2K_HPXML_SPEC)
    simulate = _ensure_venv(workdir / "venvs" / "simulate", OCHRE_SPEC)
    versions = {
        "translate_numpy": _numpy_version(translate),
        "simulate_numpy": _numpy_version(simulate),
    }
    if versions["translate_numpy"] == versions["simulate_numpy"]:
        raise StageFailure(
            "the translation and simulation environments resolved the same numpy "
            f"({versions['translate_numpy']}); this gate is built on the two pins "
            "being incompatible, so re-read the design before proceeding"
        )
    versions["translate_python"] = str(translate)
    versions["simulate_python"] = str(simulate)
    return versions


# --- Stage 2: the vendor toolchain h2k-hpxml shells out to -----------------


def _ensure_openstudio() -> Path:
    """Install the exact OpenStudio build OpenStudio-HPXML v1.9.1 demands.

    h2k-hpxml ships its own auto-installer, but that installer accepts any
    ``openstudio`` already on PATH and edits the user's shell profiles. This
    does neither: it installs the pinned build under its version-specific
    path, which is where h2k-hpxml looks first.

    Returns:
        Path to the OpenStudio CLI.

    Raises:
        StageFailure: If the download or extraction fails.
    """
    target = _VENDOR_ROOT / f"OpenStudio-{OPENSTUDIO_VERSION}"
    binary = target / "bin" / "openstudio"
    if binary.exists():
        return binary
    url = (
        "https://github.com/NREL/OpenStudio/releases/download/"
        f"v{OPENSTUDIO_VERSION}/OpenStudio-{OPENSTUDIO_VERSION}+"
        f"{OPENSTUDIO_SHA}-Ubuntu-22.04-x86_64.tar.gz"
    )
    _echo(f"[gate] downloading OpenStudio {OPENSTUDIO_VERSION} (~340 MB)")
    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / "openstudio.tar.gz"
        _download(url, tarball)
        with tarfile.open(tarball) as archive:
            archive.extractall(tmp)  # noqa: S202 - NREL release tarball
        # The tarball unpacks as usr/local/openstudio-<version>/; h2k-hpxml
        # expects that inner directory to be the install root.
        inner = Path(tmp) / "usr" / "local" / f"openstudio-{OPENSTUDIO_VERSION}"
        if not inner.is_dir():
            raise StageFailure(f"unexpected OpenStudio tarball layout under {tmp}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inner), str(target))
    if not binary.exists():
        raise StageFailure(f"OpenStudio CLI missing after install: {binary}")
    return binary


def _ensure_os_hpxml() -> Path:
    """Install the OpenStudio-HPXML workflow h2k-hpxml drives.

    Returns:
        Path to the OpenStudio-HPXML root.

    Raises:
        StageFailure: If the download or extraction fails.
    """
    target = _VENDOR_ROOT / f"OpenStudio-HPXML-{OS_HPXML_VERSION}"
    if (target / "workflow" / "run_simulation.rb").exists():
        return target
    url = (
        "https://github.com/NREL/OpenStudio-HPXML/releases/download/"
        f"{OS_HPXML_VERSION}/OpenStudio-HPXML-{OS_HPXML_VERSION}.zip"
    )
    _echo(f"[gate] downloading OpenStudio-HPXML {OS_HPXML_VERSION}")
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "os-hpxml.zip"
        _download(url, archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(tmp)  # noqa: S202 - NREL release archive
        extracted = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(extracted) != 1:
            raise StageFailure(f"unexpected OpenStudio-HPXML archive layout in {tmp}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted[0]), str(target))
    return target


def stage_toolchain() -> dict[str, Any]:
    """Ensure the pinned OpenStudio pair is present and self-consistent.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If the installed CLI is not the pinned build.
    """
    binary = _ensure_openstudio()
    os_hpxml = _ensure_os_hpxml()
    probe = _run([str(binary), "openstudio_version"])
    reported = probe.stdout.strip()
    if not reported.startswith(OPENSTUDIO_VERSION):
        raise StageFailure(
            f"OpenStudio at {binary} reports {reported!r}, expected "
            f"{OPENSTUDIO_VERSION}; OpenStudio-HPXML {OS_HPXML_VERSION} will "
            "refuse to run under any other build"
        )
    return {
        "openstudio_cli": str(binary),
        "openstudio_version": reported,
        "os_hpxml_root": str(os_hpxml),
    }


# --- Stage 3: the archetype ------------------------------------------------


def stage_archetype(workdir: Path) -> dict[str, Any]:
    """Fetch the pinned Québec archetype and verify its digest.

    Args:
        workdir: Gate working directory.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If the fetched file does not match the pinned digest.
    """
    source_dir = workdir / "archetype"
    target = source_dir / ARCHETYPE_NAME
    if not target.exists():
        _echo(f"[gate] fetching archetype {ARCHETYPE_NAME}")
        _download(ARCHETYPE_URL, target)
    digest = _sha256(target)
    if digest != ARCHETYPE_SHA256:
        raise StageFailure(
            f"{target} digest {digest} does not match the pinned "
            f"{ARCHETYPE_SHA256}; the upstream archetype set moved"
        )
    return {"path": str(target), "sha256": digest, "bytes": target.stat().st_size}


# --- Stage 4: translation, in the translation virtualenv -------------------


def stage_translate(workdir: Path, env_detail: dict[str, Any]) -> dict[str, Any]:
    """Translate the archetype to HPXML through h2k-hpxml.

    The full OpenStudio-HPXML workflow is run rather than ``--do-not-sim``.
    That is deliberate: the raw translator output leaves
    ``AverageCeilingHeight`` at a hardcoded 8 ft while
    ``ConditionedBuildingVolume / ConditionedFloorArea`` says otherwise, and
    OCHRE checks the two agree. Running the workflow makes OpenStudio-HPXML
    emit ``run/in.xml``, its own defaulted and internally consistent HPXML —
    which is also the flavour OCHRE is tested against.

    Args:
        workdir: Gate working directory.
        env_detail: Detail from :func:`stage_environments`.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If the translator fails or emits no ``in.xml``.
    """
    out_dir = workdir / "hpxml"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    translate_bin = Path(env_detail["translate_python"]).parent / "h2k-hpxml"
    started = time.perf_counter()
    result = _run(
        [str(translate_bin), str(workdir / "archetype"), "-o", str(out_dir)],
        cwd=str(workdir),
    )
    elapsed = time.perf_counter() - started
    candidates = sorted(out_dir.glob("*/run/in.xml"))
    if result.returncode != 0 or not candidates:
        tail = (result.stdout + result.stderr).strip().splitlines()[-12:]
        raise StageFailure(
            "h2k-hpxml produced no OpenStudio-HPXML in.xml "
            f"(exit {result.returncode}): " + " | ".join(tail)
        )
    hpxml = candidates[0]
    return {
        "hpxml": str(hpxml),
        "seconds": round(elapsed, 3),
        "schema_version": _hpxml_schema_version(hpxml),
        "epw": _hpxml_epw(hpxml),
        "sha256": _sha256(hpxml),
    }


def _hpxml_schema_version(path: Path) -> str:
    """Read the HPXML ``schemaVersion`` attribute from a file.

    Args:
        path: HPXML file.

    Returns:
        The declared schema version, or ``"unknown"``.
    """
    import xml.etree.ElementTree as ElementTree

    return str(ElementTree.parse(path).getroot().get("schemaVersion", "unknown"))


def _hpxml_epw(path: Path) -> str:
    """Read the EPW path the translator selected for this dwelling.

    Args:
        path: HPXML file.

    Returns:
        Absolute EPW path.

    Raises:
        StageFailure: If the HPXML names no EPW.
    """
    import xml.etree.ElementTree as ElementTree

    for element in ElementTree.parse(path).iter():
        if element.tag.endswith("}EPWFilePath") and element.text:
            return element.text.strip()
    raise StageFailure(f"{path} declares no EPWFilePath; OCHRE needs weather")


# --- Stage 5/6: simulation and determinism, in the simulation virtualenv ---


def _simulate(python: Path, hpxml: str, epw: str, out: Path) -> dict[str, Any]:
    """Invoke the OCHRE driver across the process boundary.

    Args:
        python: The simulation virtualenv's interpreter.
        hpxml: HPXML file to hand over.
        epw: Weather file.
        out: Output directory.

    Returns:
        The driver's summary payload.

    Raises:
        StageFailure: If the driver produced no parseable summary.
    """
    result = _run(
        [
            str(python),
            str(_DRIVER),
            "simulate",
            "--hpxml",
            hpxml,
            "--epw",
            epw,
            "--out",
            str(out),
        ]
    )
    summary_path = out / "summary.json"
    if not summary_path.exists():
        tail = (result.stdout + result.stderr).strip().splitlines()[-12:]
        raise StageFailure("OCHRE driver wrote no summary: " + " | ".join(tail))
    return json.loads(summary_path.read_text(encoding="utf-8"))


def stage_simulate(
    workdir: Path, env_detail: dict[str, Any], translate_detail: dict[str, Any]
) -> dict[str, Any]:
    """Run OCHRE on the translated HPXML and require a real time series.

    Args:
        workdir: Gate working directory.
        env_detail: Detail from :func:`stage_environments`.
        translate_detail: Detail from :func:`stage_translate`.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If OCHRE rejects the HPXML or yields nothing usable.
    """
    python = Path(env_detail["simulate_python"])
    summary = _simulate(
        python, translate_detail["hpxml"], translate_detail["epw"], workdir / "ochre_a"
    )
    if summary.get("status") != "ok":
        raise StageFailure(
            "OCHRE rejected the translated HPXML: "
            f"{summary.get('error_type')}: {summary.get('error') or '(no message)'} "
            "@ " + " | ".join(summary.get("traceback_tail", []))
        )
    if not summary.get("non_zero_end_uses"):
        raise StageFailure(
            "OCHRE ran but produced no non-zero per-end-use column; the "
            f"columns present were {summary.get('end_use_columns')}"
        )
    return summary


def stage_determinism(
    workdir: Path, env_detail: dict[str, Any], translate_detail: dict[str, Any]
) -> dict[str, Any]:
    """Re-run the same inputs and seed, and compare the two time series.

    Args:
        workdir: Gate working directory.
        env_detail: Detail from :func:`stage_environments`.
        translate_detail: Detail from :func:`stage_translate`.

    Returns:
        Stage detail for the report.

    Raises:
        StageFailure: If the two runs disagree beyond the stated tolerance.
    """
    python = Path(env_detail["simulate_python"])
    second = _simulate(
        python, translate_detail["hpxml"], translate_detail["epw"], workdir / "ochre_b"
    )
    if second.get("status") != "ok":
        raise StageFailure("the repeat OCHRE run failed where the first succeeded")
    compared = _run(
        [
            str(python),
            str(_DRIVER),
            "compare",
            "--left",
            str(workdir / "ochre_a" / "timeseries.parquet"),
            "--right",
            str(workdir / "ochre_b" / "timeseries.parquet"),
        ]
    )
    payload = json.loads(compared.stdout)
    deviation = payload.get("max_relative_deviation")
    if not payload.get("aligned") or deviation is None:
        raise StageFailure(f"the two runs are not comparable: {payload}")
    if deviation > DETERMINISM_TOLERANCE:
        raise StageFailure(
            f"two runs with identical inputs and seed diverged by "
            f"{deviation:.3e} relative, above the {DETERMINISM_TOLERANCE:.0e} "
            "tolerance"
        )
    payload["tolerance"] = DETERMINISM_TOLERANCE
    return payload


# --- Orchestration ---------------------------------------------------------

_STAGES = (
    "environments",
    "toolchain",
    "archetype",
    "translate",
    "simulate",
    "determinism",
)


def run_gate(workdir: Path) -> dict[str, Any]:
    """Run every stage in order, stopping at the first failure.

    Args:
        workdir: Gate working directory.

    Returns:
        The full report payload.
    """
    stages: list[dict[str, Any]] = []
    detail: dict[str, dict[str, Any]] = {}
    status = "passed"

    def record(name: str, fn: Any) -> bool:
        """Run one stage, recording its outcome.

        Args:
            name: Stage identifier.
            fn: Zero-argument callable performing the stage.

        Returns:
            True if the stage passed.
        """
        nonlocal status
        _echo(f"[gate] {name}")
        started = time.perf_counter()
        try:
            result = fn()
        except StageFailure as exc:
            status = "failed"
            stages.append(
                {
                    "stage": name,
                    "status": "failed",
                    "seconds": round(time.perf_counter() - started, 3),
                    "diagnosis": str(exc),
                }
            )
            _echo(f"[gate] {name} FAILED: {exc}")
            return False
        detail[name] = result
        stages.append(
            {
                "stage": name,
                "status": "passed",
                "seconds": round(time.perf_counter() - started, 3),
                "detail": result,
            }
        )
        return True

    ok = record("environments", lambda: stage_environments(workdir))
    ok = ok and record("toolchain", stage_toolchain)
    ok = ok and record("archetype", lambda: stage_archetype(workdir))
    ok = ok and record(
        "translate", lambda: stage_translate(workdir, detail["environments"])
    )
    ok = ok and record(
        "simulate",
        lambda: stage_simulate(workdir, detail["environments"], detail["translate"]),
    )
    ok = ok and record(
        "determinism",
        lambda: stage_determinism(workdir, detail["environments"], detail["translate"]),
    )
    for name in _STAGES:
        if not any(entry["stage"] == name for entry in stages):
            stages.append({"stage": name, "status": "not_reached"})
    return {
        "gate": "ochre_calibration_phase1_feasibility",
        "status": status,
        "workdir": str(workdir),
        "pins": {
            "h2k_hpxml_commit": H2K_HPXML_COMMIT,
            "ochre": OCHRE_SPEC,
            "openstudio": f"{OPENSTUDIO_VERSION}+{OPENSTUDIO_SHA}",
            "openstudio_hpxml": OS_HPXML_VERSION,
            "archetype": ARCHETYPE_NAME,
            "archetype_repo_commit": ARCHETYPE_REPO_COMMIT,
        },
        "stages": stages,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the gate and optionally write its report.

    Args:
        argv: Argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        0 if every stage passed, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="write feasibility_report.json into the working directory",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".ochre-calibration",
        help="where virtualenvs, inputs and outputs live (gitignored)",
    )
    args = parser.parse_args(argv)
    args.workdir.mkdir(parents=True, exist_ok=True)

    report = run_gate(args.workdir)
    if args.report:
        destination = args.workdir / "feasibility_report.json"
        destination.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _echo(f"[gate] report written to {destination}")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
