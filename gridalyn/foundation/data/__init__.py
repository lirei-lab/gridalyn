"""Demo dataset discovery helpers. :no-index:

Production workflows should declare inputs in ``project.yaml``. This package
only resolves bundled tutorial/demo files and preserves old dataset class names
through lazy deprecation shims.
"""

from __future__ import annotations

import warnings

from .datasets import get_dataset_path, list_available_datasets

__all__ = [
    "get_dataset_path",
    "list_available_datasets",
]

_LEGACY_DATASET_EXPORTS = {"PowerGridDataset", "CIMDataset", "GeoJSONDataset"}


def __getattr__(name: str):
    if name in _LEGACY_DATASET_EXPORTS:
        warnings.warn(
            f"gridalyn.foundation.data.{name} is a legacy dataset stub. Use "
            "get_dataset_path/list_available_datasets for bundled demo data, "
            "or project.yaml for reproducible workflow inputs.",
            DeprecationWarning,
            stacklevel=2,
        )
        from . import datasets

        return getattr(datasets, name)
    raise AttributeError(f"module 'gridalyn.foundation.data' has no attribute {name!r}")
