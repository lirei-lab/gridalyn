from gridalyn.data import datasets


def test_installation() -> None:
    try:
        print("Testing gridalyn installation...")
        dataset_path = datasets.get_dataset_path("example_buildings.geojson")
        print("Dataset path:", dataset_path)
        print("Installation test successful!")
    except Exception as e:
        print("Installation test failed:", str(e))


if __name__ == "__main__":
    test_installation()
