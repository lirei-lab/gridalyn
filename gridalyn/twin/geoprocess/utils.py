"""
Utility functions for GeoJSON data processing.

This module provides helper functions for:
- Calculating polygon areas
- Computing centroids
- Validating GeoJSON data
"""

import json
from typing import Any, Dict, List, Tuple, Union

from shapely.geometry import Polygon, shape
from shapely.validation import explain_validity, make_valid


def _validate_json_format(
    data: Union[str, Dict[str, Any]]
) -> Tuple[Union[Dict[str, Any], None], str]:
    """
    Helper function to validate JSON format.
    """
    if isinstance(data, str):
        try:
            return json.loads(data), ""  # Return parsed JSON and empty message
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON format: {str(e)}"
    return data, ""  # Already a dict, return as is


def _validate_geojson_structure(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Helper function to validate basic GeoJSON structure.
    """
    if not isinstance(data, dict):
        return False, "GeoJSON must be a dictionary"

    if data.get("type") != "FeatureCollection":
        return False, "GeoJSON must be a FeatureCollection"

    features = data.get("features", [])
    if not isinstance(features, list):
        return False, "Features must be a list"

    if not features:
        return False, "No features found in GeoJSON"

    return True, ""  # Valid structure, no error message


def _validate_geojson_feature(
    feature: Dict[str, Any], feature_index: int
) -> Tuple[bool, str]:
    """
    Helper function to validate a single GeoJSON feature.
    """
    if not isinstance(feature, dict):
        return False, f"Feature {feature_index}: Not a dictionary"

    if feature.get("type") != "Feature":
        return False, f"Feature {feature_index}: Not a Feature type"

    geometry = feature.get("geometry", {})
    if not geometry:
        return False, f"Feature {feature_index}: No geometry"

    return True, ""  # Valid feature, no error message


def _validate_geojson_geometry(
    geometry: Dict[str, Any], feature_index: int
) -> Tuple[bool, str]:
    """
    Helper function to validate GeoJSON geometry using shapely.
    """
    if not geometry:
        return False, f"Feature {feature_index}: No geometry"

    try:
        geom = shape(geometry)
        if not geom.is_valid:
            reason = explain_validity(geom)
            return False, f"Feature {feature_index}: Invalid geometry - {reason}"
    except Exception as e:
        return False, f"Feature {feature_index}: Error validating geometry - {str(e)}"

    return True, ""  # Valid geometry, no error message


def calculate_area(coordinates: List[List[float]]) -> float:
    """
    Calculate the area of a polygon in square meters.

    Args:
        coordinates: List of [lon, lat] coordinates forming a polygon

    Returns:
        float: Area in square meters

    Note:
        Uses the Shoelace formula (also known as surveyor's formula)
        for calculating the area of a simple polygon.
    """
    try:
        # Convert to shapely polygon for accurate area calculation
        polygon = Polygon(coordinates)
        if not polygon.is_valid:
            polygon = make_valid(polygon)

        # Get area in square meters
        # Note: For more accurate results in specific regions,
        # consider using a local projection
        area = polygon.area * 111000 * 111000  # Approximate conversion to square meters
        return abs(area)  # Return absolute value to handle clockwise/counterclockwise
    except Exception as e:
        print(f"Error calculating area: {str(e)}")
        return 0.0


def calculate_centroid(coordinates: List[List[float]]) -> Tuple[float, float]:
    """
    Calculate the centroid of a polygon.

    Args:
        coordinates: List of [lon, lat] coordinates forming a polygon

    Returns:
        tuple: (longitude, latitude) of the centroid
    """
    try:
        # Convert to shapely polygon for centroid calculation
        polygon = Polygon(coordinates)
        if not polygon.is_valid:
            polygon = make_valid(polygon)

        # Get centroid coordinates
        centroid = polygon.centroid
        return (centroid.x, centroid.y)
    except Exception as e:
        print(f"Error calculating centroid: {str(e)}")
        return (0.0, 0.0)


def validate_geojson(data: Union[str, Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Validate GeoJSON data structure and geometry.

    Args:
        data: GeoJSON data as string or dictionary

    Returns:
        tuple: (is_valid, message)
            - is_valid: Boolean indicating if the GeoJSON is valid
            - message: Description of any validation issues
    """
    # Validate JSON format
    json_data, json_error_message = _validate_json_format(data)
    if json_error_message:
        return False, json_error_message

    if json_data is None:
        return False, "Invalid JSON data after format validation"

    # Validate GeoJSON structure
    is_valid_structure, structure_error_message = _validate_geojson_structure(json_data)
    if not is_valid_structure:
        return False, structure_error_message

    # Validate each feature
    invalid_features = []
    features = json_data.get("features", [])  # Define features here
    for i, feature in enumerate(features):
        is_valid_feature, feature_error_message = _validate_geojson_feature(feature, i)
        if not is_valid_feature:
            invalid_features.append(feature_error_message)
            continue

        geometry = feature.get("geometry", {})
        is_valid_geometry, geometry_error_message = _validate_geojson_geometry(
            geometry, i
        )
        if not is_valid_geometry:
            invalid_features.append(geometry_error_message)

    if invalid_features:
        return False, "Invalid features found:\n" + "\n".join(invalid_features)

    return True, "Valid GeoJSON"


def extract_building_data(geojson: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract building data from GeoJSON features.

    Args:
        geojson: GeoJSON data as dictionary

    Returns:
        list: List of dictionaries containing building data:
            - id: Building identifier
            - coordinates: Building polygon coordinates
            - area: Building area in square meters
            - centroid: (longitude, latitude) of building centroid
    """
    buildings: List[Dict[str, Any]] = []

    try:
        features = geojson.get("features", [])
        for feature in features:
            # Skip invalid features
            if not isinstance(feature, dict):
                continue

            geometry = feature.get("geometry", {})
            if not geometry or geometry.get("type") != "Polygon":
                continue

            # Get coordinates
            coordinates = geometry.get("coordinates", [[]])[0]  # Get outer ring
            if not coordinates:
                continue

            # Calculate area and centroid
            area = calculate_area(coordinates)
            centroid = calculate_centroid(coordinates)

            # Get building ID from properties or generate one
            properties = feature.get("properties", {})
            building_id = properties.get("id", len(buildings))

            buildings.append(
                {
                    "id": building_id,
                    "coordinates": coordinates,
                    "area": area,
                    "centroid": centroid,
                }
            )

    except Exception as e:
        print(f"Error extracting building data: {str(e)}")

    return buildings
