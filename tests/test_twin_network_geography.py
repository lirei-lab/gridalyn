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
from pathlib import Path

import pandas as pd

from gridalyn.twin.network.geography import (
    BUILDING_GEOMETRY_KIND,
    BUILDING_GEOMETRY_REASON,
    CRS_ASSUMED,
    CRS_DECLARED,
    DEFAULT_GEOGRAPHIC_CRS,
    GEOMETRY_DERIVED,
    GEOMETRY_POINT,
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

    def test_building_geometry_is_declared_points_with_its_reason(self):
        """Decided 2026-09-02, and the wrong outcome was silence.

        The GeoJSON ingest reads real Polygon/MultiPolygon footprints and keeps
        only the centroid and the area. A consumer holding the coordinate pair
        alone would reasonably draw a footprint layer the twin cannot support,
        so the twin says the shape rather than leaving it to be inferred.
        """
        geography = resolve_network_geography(
            frames={
                BUILDINGS: pd.DataFrame(
                    [
                        {
                            "building_id": "b:0",
                            "load_id": "l:0",
                            "lat": 46.3,
                            "lon": -72.6,
                        }
                    ]
                )
            }
        )
        declared = geography.geometry_kinds[BUILDINGS]
        self.assertEqual(GEOMETRY_POINT, declared["kind"])
        self.assertEqual(BUILDING_GEOMETRY_KIND, declared["kind"])
        self.assertEqual(BUILDING_GEOMETRY_REASON, declared["reason"])
        self.assertIn("retains only", declared["reason"])
        self.assertIn("go back to the source layer", declared["reason"])

    def test_a_bus_position_is_the_whole_geometry_so_it_needs_no_reason(self):
        """Only ``buildings`` is a REDUCTION of a richer source geometry."""
        geography = resolve_network_geography(
            frames={
                GRID_BUSES: _buses([{"bus_id": "bus:0", "lat": 46.3, "lon": -72.6}])
            }
        )
        self.assertEqual({"kind": GEOMETRY_POINT}, geography.geometry_kinds[GRID_BUSES])

    def test_derived_artifacts_declare_their_kind_too(self):
        geography = resolve_network_geography(frames={})
        self.assertEqual(GEOMETRY_DERIVED, geography.geometry_kinds[GRID_LINES]["kind"])
        self.assertEqual(
            GEOMETRY_DERIVED, geography.geometry_kinds[GRID_TRANSFORMERS]["kind"]
        )

    def test_geometry_kinds_reach_the_payload(self):
        payload = resolve_network_geography(
            frames={
                BUILDINGS: pd.DataFrame(
                    [
                        {
                            "building_id": "b:0",
                            "load_id": "l:0",
                            "lat": 46.3,
                            "lon": -72.6,
                        }
                    ]
                )
            }
        ).to_dict()
        self.assertEqual(GEOMETRY_POINT, payload["geometry_kinds"][BUILDINGS]["kind"])
        self.assertIn("reason", payload["geometry_kinds"][BUILDINGS])

    def test_center_is_the_extent_midpoint(self):
        box = BoundingBox(min_lon=-2.0, min_lat=10.0, max_lon=2.0, max_lat=20.0)
        self.assertEqual(box.center, (0.0, 15.0))
        self.assertEqual(box.to_list(), [-2.0, 10.0, 2.0, 20.0])


class AdapterDeclaredCrsTest(unittest.TestCase):
    """An adapter declares the CRS it PRODUCES, or declares nothing.

    Same epistemic status as ``source_standard`` and ``source_format``, which
    are already class-level contract declarations: a statement about the
    adapter's own output, not an inference about data it happened to read.
    """

    def test_the_synthetic_adapter_declares_lon_lat(self):
        from gridalyn.twin.adapters.network import SyntheticPandapowerAdapter

        self.assertEqual(
            SyntheticPandapowerAdapter.geographic_crs, DEFAULT_GEOGRAPHIC_CRS
        )

    def test_the_topology_adapter_declares_nothing_because_its_coords_are_schematic(
        self,
    ):
        """Its feeders sit at (0,0), (1,0.2), (2,0.4).

        `der_voltage_optimization`, `prosumer_battery_market` and
        `rl_voltage_control_lightsim` all go through this adapter and write
        layout coordinates, not geography. Declaring EPSG:4326 for them would
        put the feeder in the Gulf of Guinea -- the same failure
        `test_rows_missing_a_coordinate_are_dropped_not_read_as_zero` guards.
        """
        from gridalyn.twin.adapters.network import PandapowerTopologyAdapter

        self.assertIsNone(PandapowerTopologyAdapter.geographic_crs)

    def test_the_cim_adapter_defers_to_its_source(self):
        """The CRS of caller-supplied CIM parquet is the source's to declare."""
        from gridalyn.twin.adapters.cim import CimParquetAdapter

        self.assertIsNone(CimParquetAdapter.geographic_crs)
        located = CimParquetAdapter(source_dir=Path("."), geographic_crs="EPSG:2950")
        self.assertEqual(located.geographic_crs, "EPSG:2950")

    def test_the_descriptor_carries_the_declaration(self):
        from gridalyn.twin.adapters.network import (
            SyntheticPandapowerAdapter,
            describe_network_source_adapter,
        )

        descriptor = describe_network_source_adapter(SyntheticPandapowerAdapter)
        self.assertEqual(descriptor.geographic_crs, DEFAULT_GEOGRAPHIC_CRS)

    def test_an_adapter_that_declares_no_crs_still_describes_cleanly(self):
        """A third-party adapter predating this field must not break describe()."""
        from gridalyn.twin.adapters.network import describe_network_source_adapter

        class _Legacy:
            adapter_id = "legacy"
            source_adapter = "LegacyAdapter"
            source_standard = "custom"

        self.assertIsNone(describe_network_source_adapter(_Legacy).geographic_crs)


if __name__ == "__main__":
    unittest.main()
