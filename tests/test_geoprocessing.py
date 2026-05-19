from gridalyn.data import datasets
from gridalyn.adapters.geojson import GeoProcessor


def test_geoprocessing() -> None:
    try:
        print("1. Creating GeoProcessor instance...")
        processor = GeoProcessor()

        print("2. Loading example buildings data...")
        path = datasets.get_dataset_path("trois_rivieres_buildings.geojson")
        success, message = processor.load_geojson(str(path))
        if not success:
            raise Exception(f"Failed to load buildings data: {message}")

        print("3. Processing buildings data...")
        success, message = processor.process_buildings()
        if not success:
            raise Exception(f"Failed to process buildings data: {message}")
        processed = processor.get_building_data()

        print("4. Results:")
        if processed is not None:
            print(processed.head())
        else:
            print("No processed data to display.")

        print("\nGeoProcessing test successful!")
    except Exception as e:
        print("\nGeoProcessing test failed!")
        print("Error details:")
        print(str(e))


if __name__ == "__main__":
    test_geoprocessing()
