import unittest
from unittest.mock import patch

from gridalyn.interfaces.cli import flexibility
from gridalyn.workflows.flexibility import locational_verification


class LocationalVerificationWorkflowTest(unittest.TestCase):
    def test_example_wrapper_imports_workflow_main(self):
        import examples.compat.generate_locational_clearing_verification_report as wrapper

        self.assertIs(wrapper.main, locational_verification.main)

    def test_flexibility_cli_routes_verify_clearing_to_workflow(self):
        with patch.object(locational_verification, "main", return_value=0) as main:
            result = flexibility.main(["verify-clearing", "--scenario-id", "S4"])

        self.assertEqual(result, 0)
        main.assert_called_once_with(["--scenario-id", "S4"])


if __name__ == "__main__":
    unittest.main()
