import os
import sys
import unittest


def run_tests() -> int:
    """Run all tests in the tests directory"""
    # Add project root to Python path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    # Get absolute path to tests directory
    tests_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        loader = unittest.TestLoader()
        suite = loader.discover(tests_dir, pattern="test_*.py")
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        if result.wasSuccessful():
            print("\nAll tests passed successfully!")
            return 0
        else:
            print("\nSome tests failed!")
            return 1

    except Exception as e:
        print(f"Error running tests: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(run_tests())
