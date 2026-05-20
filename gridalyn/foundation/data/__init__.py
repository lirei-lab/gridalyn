"""Demo dataset discovery helpers. :no-index:

Production workflows should declare inputs in ``project.yaml``. This package
only resolves bundled tutorial/demo files.
"""

from __future__ import annotations

from .datasets import get_dataset_path, list_available_datasets

__all__ = [
    "get_dataset_path",
    "list_available_datasets",
]
