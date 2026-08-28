"""Resolving where a base network snapshot sits, and how honestly it says so.

The catalog previously named only per-scenario timeseries artifacts, so a
geo-centred consumer had to hardcode the base paths and guess the CRS. These
tests pin the three claims that replaced the guessing: coordinates are resolved
through the declared column contract, an absent CRS is reported as *assumed*
rather than silently presented as fact, and line/transformer geometry is
declared derived rather than left to be discovered by reading a file.
"""

from __future__ import annotations

import unittest

import pandas as pd

from gridalyn.twin.network.geography import (
    CRS_ASSUMED,
    CRS_DECLARED,
    DEFAULT_GEOGRAPHIC_CRS,
    BoundingBox,
    resolve_network_geography,
)
from gridalyn.twin.network.schema import (
    BUILDINGS,
    GRID_BUSES,
    GRID_LINES,
    GRID_TRANSFORMERS,
    ROLE_LATITUDE,
    ROLE_LONGITUDE,
    table_schema,
)


def _buses(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class DeclaredCoordinateContractTest(unittest.TestCase):
    """Coordinates are a declared role, not a spelling a reader hunts for."""

    def test_located_tables_declare_both_coordinate_roles(self):
        for artifact in (GRID_BUSES, BUILDINGS):
            with self.subTest(artifact=artifact):
                schema = table_schema(artifact)
                self.assertIn(ROLE_LATITUDE, schema.roles)
                self.assertIn(ROLE_LONGITUDE, schema.roles)

    def test_coordinates_are_not_required(self):
        """An electrical model without geography is unlocated, not invalid.

        Making the coordinate roles required would turn every base snapshot
        that never claimed to be located into an integrity failure, which is a
        different and wrong statement.
        """
        for artifact in (GRID_BUSES, BUILDINGS):
            with self.subTest(artifact=artifact):
                schema = table_schema(artifact)
                self.assertFalse(schema.spec(ROLE_LATITUDE).required)
                self.assertFalse(schema.spec(ROLE_LONGITUDE).required)

    def test_only_the_spelling_producers_actually_write_is_declared(self):
        """`latitude`/`longitude` is a CIM *read* alias, never a written one.

        The schema module's own rule is that alias sets are evidence rather
        than tolerance, so the written spelling is the only one carried.
        """
        schema = table_schema(GRID_BUSES)
        self.assertEqual(schema.spellings(ROLE_LATITUDE), ("lat",))
        self.assertEqual(schema.spellings(ROLE_LONGITUDE), ("lon",))

    def test_topology_tables_declare_no_coordinates(self):
        """Lines and transformers hold no geometry; that is why it is derived."""
        for artifact in (GRID_LINES, GRID_TRANSFORMERS):
            with self.subTest(artifact=artifact):
                self.assertNotIn(ROLE_LATITUDE, table_schema(artifact).roles)


class ResolveNetworkGeographyTest(unittest.TestCase):
    def test_extent_spans_every_located_artifact(self):
        geography = resolve_network_geography(
            frames={
                GRID_BUSES: _buses(
                    [
                        {"bus_id": "bus:0", "lat": 46.33, "lon": -72.62},
                        {"bus_id": "bus:1", "lat": 46.35, "lon": -72.60},
                    ]
                ),
                BUILDINGS: _buses(
                    [{"building_id": "b:0", "lat": 46.36, "lon": -72.58}]
                ),
            }
        )
        self.assertTrue(geography.located)
        self.assertEqual(
            geography.bounding_box,
            BoundingBox(min_lon=-72.62, min_lat=46.33, max_lon=-72.58, max_lat=46.36),
        )

    def test_absent_crs_is_reported_as_assumed(self):
        geography = resolve_network_geography(
            frames={GRID_BUSES: _buses([{"bus_id": "b", "lat": 1.0, "lon": 2.0}])},
            metadata={"report_id": "digital_twin_base_metadata"},
        )
        self.assertEqual(geography.crs, DEFAULT_GEOGRAPHIC_CRS)
        self.assertEqual(geography.crs_source, CRS_ASSUMED)

    def test_declared_crs_wins_and_is_reported_as_declared(self):
        geography = resolve_network_geography(
            frames={GRID_BUSES: _buses([{"bus_id": "b", "lat": 1.0, "lon": 2.0}])},
            metadata={"crs": "EPSG:32618"},
        )
        self.assertEqual(geography.crs, "EPSG:32618")
        self.assertEqual(geography.crs_source, CRS_DECLARED)

    def test_crs_nested_under_model_version_is_found(self):
        geography = resolve_network_geography(
            frames={GRID_BUSES: _buses([{"bus_id": "b", "lat": 1.0, "lon": 2.0}])},
            metadata={"model_version": {"crs": "EPSG:2950"}},
        )
        self.assertEqual(geography.crs, "EPSG:2950")
        self.assertEqual(geography.crs_source, CRS_DECLARED)

    def test_a_snapshot_without_coordinates_is_unlocated_not_an_error(self):
        geography = resolve_network_geography(
            frames={GRID_BUSES: _buses([{"bus_id": "bus:0"}])}
        )
        self.assertFalse(geography.located)
        self.assertIsNone(geography.bounding_box)
        self.assertEqual(geography.located_artifacts, {})

    def test_rows_missing_a_coordinate_are_dropped_not_read_as_zero(self):
        """A null must not drag the extent to null island.

        Treating a missing coordinate as 0.0 would put the corner of every
        partially-located network in the Gulf of Guinea, and the resulting
        viewport would be silently wrong rather than absent.
        """
        geography = resolve_network_geography(
            frames={
                GRID_BUSES: _buses(
                    [
                        {"bus_id": "bus:0", "lat": 46.33, "lon": -72.62},
                        {"bus_id": "bus:1", "lat": None, "lon": None},
                    ]
                )
            }
        )
        assert geography.bounding_box is not None
        self.assertEqual(geography.bounding_box.min_lat, 46.33)
        self.assertEqual(geography.bounding_box.max_lat, 46.33)

    def test_derived_geometry_names_the_endpoint_roles_to_join_on(self):
        geography = resolve_network_geography(frames={})
        self.assertEqual(geography.derived_geometry[GRID_LINES], ("from_bus", "to_bus"))
        self.assertEqual(
            geography.derived_geometry[GRID_TRANSFORMERS], ("hv_bus", "lv_bus")
        )

    def test_center_is_the_extent_midpoint(self):
        box = BoundingBox(min_lon=-2.0, min_lat=10.0, max_lon=2.0, max_lat=20.0)
        self.assertEqual(box.center, (0.0, 15.0))
        self.assertEqual(box.to_list(), [-2.0, 10.0, 2.0, 20.0])


if __name__ == "__main__":
    unittest.main()
