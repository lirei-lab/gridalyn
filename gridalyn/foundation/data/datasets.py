"""Dataset discovery helpers for bundled example data. :no-index:

The core ``gridalyn`` package should not own real case-study GeoJSON files.
Those files live under ``examples/tutorials/data`` and are resolved here for
backward compatibility with existing tutorials and tests.
"""

from importlib.resources import files
from pathlib import Path
from typing import Iterable, List, Union
import warnings


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_DATA_DIR = REPO_ROOT / "examples" / "tutorials" / "data"
LEGACY_PACKAGE_DATA = Path(str(files("gridalyn.foundation.data")))
NON_DATA_SUFFIXES = {".md", ".py", ".pyc"}


def _dataset_dirs() -> Iterable[Path]:
    """Return dataset search locations in preferred order."""
    yield EXAMPLE_DATA_DIR
    yield LEGACY_PACKAGE_DATA


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


# Add new class-based dataset handling
class PowerGridDataset:
    """Base class for power grid datasets. :no-index:"""

    def __init__(self, name: str, description: str) -> None:
        """
        Initialize a new power grid dataset.

        Args:
            name: Name of the dataset
            description: Description of the dataset contents
        """
        warnings.warn(
            f"{self.__class__.__name__} is a legacy dataset stub. Use "
            "get_dataset_path/list_available_datasets for demo data or project.yaml "
            "for workflow inputs.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.name = name
        self.description = description
        self.data: Union[str, None] = None

    def load(self, file_path: str) -> None:
        """
        Load dataset from file.

        Args:
            file_path: Path to dataset file
        """
        raise NotImplementedError("Subclasses must implement load method")

    def validate(self) -> None:
        """Validate dataset integrity."""
        raise NotImplementedError("Subclasses must implement validate method")


class CIMDataset(PowerGridDataset):
    """Class for handling CIM (Common Information Model) datasets. :no-index:"""

    def __init__(self) -> None:
        super().__init__(
            name="CIM Dataset", description="Power grid data in CIM format"
        )

    def load(self, file_path: str) -> None:
        """Load CIM dataset from XML file."""
        # Implementation would go here
        pass

    def validate(self) -> None:
        """Validate CIM dataset structure."""
        # Implementation would go here
        pass


class GeoJSONDataset(PowerGridDataset):
    """Class for handling GeoJSON formatted power grid data. :no-index:"""

    def __init__(self) -> None:
        super().__init__(
            name="GeoJSON Dataset", description="Power grid data in GeoJSON format"
        )

    def load(self, file_path: str) -> None:
        """Load GeoJSON dataset."""
        # Implementation would go here
        pass

    def validate(self) -> None:
        """Validate GeoJSON dataset structure."""
        # Implementation would go here
        pass
