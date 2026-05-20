"""Dataset discovery helpers for bundled example data. :no-index:

The core ``gridalyn`` package should not own real case-study GeoJSON files.
Those files live under ``examples/tutorials/data`` and are resolved here for
tutorials and tests.
"""

from importlib.resources import files
from pathlib import Path
from typing import Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DATA_DIR = REPO_ROOT / "examples" / "tutorials" / "data"
PACKAGE_DATA_DIR = Path(str(files("gridalyn.foundation.data")))
NON_DATA_SUFFIXES = {".md", ".py", ".pyc"}


def _dataset_dirs() -> Iterable[Path]:
    """Return dataset search locations in preferred order."""
    yield EXAMPLE_DATA_DIR
    yield PACKAGE_DATA_DIR


def _is_dataset_file(path: Path) -> bool:
    """Return true for data files, excluding Python package implementation files."""
    return path.is_file() and path.suffix not in NON_DATA_SUFFIXES


def get_dataset_path(filename: str) -> Path:
    """Get the full path to a dataset file. :no-index:

    Args:
        filename: Name of the dataset file (e.g. 'buildings_inside_polygon.geojson')

    Returns:
        Path object pointing to the dataset file

    Raises:
        FileNotFoundError: If the dataset file does not exist
    """
    for data_dir in _dataset_dirs():
        candidate = data_dir / filename
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(path) for path in _dataset_dirs())
    raise FileNotFoundError(f"Dataset file not found: {filename}. Searched: {searched}")


def list_available_datasets() -> List[str]:
    """List all available datasets in the data directory. :no-index:

    Returns:
        List of dataset filenames
    """
    names: set[str] = set()
    for data_dir in _dataset_dirs():
        if data_dir.exists():
            names.update(f.name for f in data_dir.iterdir() if _is_dataset_file(f))
    return sorted(names)
