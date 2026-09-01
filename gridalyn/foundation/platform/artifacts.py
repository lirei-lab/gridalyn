"""Repository artifact policy checks for Gridalyn workspaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

DEFAULT_MAX_DEMO_DATASET_BYTES = 10 * 1024 * 1024

DEFAULT_FORBIDDEN_TRACKED_PATTERNS = (
    "_build/*",
    "site/*",
    "cache/*",
    ".roo/*",
    ".agents/*",
    ".codex/*",
    ".claude/*",
    ".cursor/*",
    ".windsurf/*",
    "manuscripts/*",
    "examples/generated/cache/*",
    "examples/generated/outputs/*",
    "projects/*/outputs/*",
    "dashboard/public/*",
    "instances/*/digital_twin/timeseries/*",
    "instances/*/digital_twin/**/*.parquet",
    "instances/*/digital_twin/**/*.pkl",
    "instances/*/digital_twin/**/*.npy",
    "instances/*/digital_twin/**/*.npz",
    "instances/*/digital_twin/models/**/*.parquet",
    "instances/*/digital_twin/semantic/*.parquet",
    "manuscripts/**/*.aux",
    "manuscripts/**/*.bbl",
    "manuscripts/**/*.bcf",
    "manuscripts/**/*.blg",
    "manuscripts/**/*.fdb_latexmk",
    "manuscripts/**/*.fls",
    "manuscripts/**/*.lof",
    "manuscripts/**/*.log",
    "manuscripts/**/*.lot",
    "manuscripts/**/*.out",
    "manuscripts/**/*.run.xml",
    "manuscripts/**/*.synctex.gz",
    "manuscripts/**/*.toc",
    "manuscripts/**/*.pdf",
    "*.h5",
    "*.hdf5",
    "*.pkl",
    "*.npy",
    "*.npz",
)

# Paths that LOOK like generated artifacts but are shipped package data. The
# blanket "*.pkl" above exists to keep run outputs out of the tree; the trained
# macro weights are neither generated per run nor optional -- pyproject declares
# them as package-data, and without them ParametricArxGenerator silently falls
# back to the analytical model, so a clone reproduces the fixture baselines 5.6%
# off. Shipping them is what makes the baselines mean anything.
DEFAULT_ALLOWED_TRACKED_PATTERNS = ("gridalyn/assets/datagen/models/weights/*.pkl",)

DEFAULT_REQUIRED_GITIGNORE_PATTERNS = (
    "_build/",
    "/site",
    "cache/",
    ".roo/",
    ".agents/",
    ".codex/",
    ".claude/",
    ".cursor/",
    ".windsurf/",
    "manuscripts/",
    "examples/generated/outputs/",
    "examples/generated/cache/",
    "projects/*/outputs/",
    "dashboard/public/",
    "instances/*/digital_twin/**/*.parquet",
    "instances/*/digital_twin/timeseries/",
    "manuscripts/**/*.aux",
    "manuscripts/**/*.fdb_latexmk",
    "manuscripts/**/*.synctex.gz",
    "manuscripts/**/*.pdf",
)

DEFAULT_MINIMAL_DATASET_FILES = (
    "manifest.json",
    "grid_nodes.geojson",
    "grid_edges.geojson",
    "buildings.geojson",
    "scenarios.json",
    "expected_summary.json",
)


@dataclass(frozen=True)
class ArtifactPolicy:
    """Small, serializable artifact policy for a Gridalyn repository."""

    minimal_dataset: str = "examples/tutorials/data/minimal"
    max_demo_dataset_bytes: int = DEFAULT_MAX_DEMO_DATASET_BYTES
    forbidden_tracked_patterns: tuple[str, ...] = DEFAULT_FORBIDDEN_TRACKED_PATTERNS
    allowed_tracked_patterns: tuple[str, ...] = DEFAULT_ALLOWED_TRACKED_PATTERNS
    required_gitignore_patterns: tuple[str, ...] = DEFAULT_REQUIRED_GITIGNORE_PATTERNS
    required_minimal_dataset_files: tuple[str, ...] = DEFAULT_MINIMAL_DATASET_FILES


@dataclass
class ArtifactPolicyReport:
    """Result of checking a repository against an artifact policy."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "summary": self.summary,
        }


def _repo_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)


def _tracked_files(root: Path) -> list[str]:
    """Return tracked files present in the working tree if Git metadata exists."""
    import subprocess

    if not (root / ".git").exists():
        return []
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    return [
        line for line in result.stdout.splitlines() if line and (root / line).exists()
    ]


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_artifact_policy(
    root: Path | str,
    *,
    policy: ArtifactPolicy | None = None,
    tracked_files: list[str] | None = None,
) -> ArtifactPolicyReport:
    """Check artifact policy without mutating the repository."""

    repo_root = Path(root)
    artifact_policy = policy or ArtifactPolicy()
    errors: list[str] = []
    warnings: list[str] = []

    gitignore_path = repo_root / ".gitignore"
    gitignore_text = (
        gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    )
    missing_gitignore = [
        pattern
        for pattern in artifact_policy.required_gitignore_patterns
        if pattern not in gitignore_text
    ]
    errors.extend(
        f".gitignore missing required pattern: {pattern}"
        for pattern in missing_gitignore
    )

    tracked = tracked_files if tracked_files is not None else _tracked_files(repo_root)
    forbidden_tracked = [
        path
        for path in tracked
        if _matches_any(path, artifact_policy.forbidden_tracked_patterns)
        and not _matches_any(path, artifact_policy.allowed_tracked_patterns)
    ]
    errors.extend(
        f"forbidden generated artifact is tracked: {path}" for path in forbidden_tracked
    )

    minimal_dir = repo_root / artifact_policy.minimal_dataset
    dataset_size = _directory_size(minimal_dir)
    if not minimal_dir.exists():
        errors.append(
            f"minimal dataset directory is missing: {artifact_policy.minimal_dataset}"
        )
    if dataset_size > artifact_policy.max_demo_dataset_bytes:
        errors.append(
            "minimal dataset exceeds size limit: "
            f"{dataset_size} > {artifact_policy.max_demo_dataset_bytes} bytes"
        )

    missing_dataset_files = [
        filename
        for filename in artifact_policy.required_minimal_dataset_files
        if not (minimal_dir / filename).exists()
    ]
    errors.extend(
        f"minimal dataset missing required file: {filename}"
        for filename in missing_dataset_files
    )

    manifest_path = minimal_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = _read_json(manifest_path)
        except json.JSONDecodeError as exc:
            errors.append(f"minimal dataset manifest is invalid JSON: {exc}")
        else:
            manifest_files = manifest.get("files", [])
            declared_paths = {
                item.get("path")
                for item in manifest_files
                if isinstance(item, dict) and item.get("path")
            }
            for filename in artifact_policy.required_minimal_dataset_files:
                if filename != "manifest.json" and filename not in declared_paths:
                    errors.append(
                        f"minimal dataset manifest does not declare: {filename}"
                    )

    summary = {
        "minimal_dataset": artifact_policy.minimal_dataset,
        "minimal_dataset_bytes": dataset_size,
        "minimal_dataset_limit_bytes": artifact_policy.max_demo_dataset_bytes,
        "required_gitignore_patterns": len(artifact_policy.required_gitignore_patterns),
        "missing_gitignore_patterns": len(missing_gitignore),
        "tracked_files_checked": len(tracked),
        "forbidden_tracked_files": len(forbidden_tracked),
        "minimal_dataset_manifest": manifest.get("dataset_id"),
    }
    return ArtifactPolicyReport(
        valid=not errors, errors=errors, warnings=warnings, summary=summary
    )


__all__ = [
    "ArtifactPolicy",
    "ArtifactPolicyReport",
    "check_artifact_policy",
]
