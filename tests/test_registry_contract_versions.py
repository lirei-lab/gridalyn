"""Contract-version rejection across the shipped per-role registries (Phase 14).

Every registry now rejects a descriptor whose ``contract_version`` is not in
the Phase 13 engine's ``SUPPORTED_CONTRACT_VERSIONS``, raising
``UnsupportedContractVersionError`` (a ``ValueError``) with a located,
remediating message. This pins that behaviour for all five roles so an
incompatible external extension can never be registered silently.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from gridalyn.foundation.platform.extensions import UnsupportedContractVersionError
from gridalyn.simulation.backends.contract import PowerFlowBackendDescriptor
from gridalyn.simulation.backends.registry import PowerFlowBackendRegistry
from gridalyn.simulation.policies.contract import PolicyDescriptor
from gridalyn.simulation.policies.registry import PolicyRegistry
from gridalyn.simulation.surrogates.contract import ErrorBound, SurrogateDescriptor
from gridalyn.simulation.surrogates.registry import SurrogateRegistry
from gridalyn.twin.adapters.network import NetworkAdapterDescriptor
from gridalyn.twin.adapters.registry import NetworkAdapterRegistry
from gridalyn.twin.observation.registry import (
    ObservationProducerDescriptor,
    ObservationProducerRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _measured_bound() -> ErrorBound:
    return ErrorBound(
        metric="mae_relief_pct_per_kw",
        units="transformer_loading_pct_point_per_kw",
        value=0.5,
        sample_size=100,
        method="holdout evaluation on the training scenarios",
        reference="network-impact physics model",
    )


def _assert_located_rejection(
    testcase: unittest.TestCase, message: str, declared: str = "2"
) -> None:
    """Assert a rejection message is located, names the set and the remedy."""
    testcase.assertIn("contract version", message)
    testcase.assertIn(repr(declared), message)
    testcase.assertIn("supported", message)
    testcase.assertIn("upgrade or pin the extension", message)


class PowerFlowBackendContractVersionTest(unittest.TestCase):
    def test_unsupported_contract_version_is_rejected_with_located_error(
        self,
    ) -> None:
        registry = PowerFlowBackendRegistry()
        with self.assertRaises(UnsupportedContractVersionError) as ctx:
            registry.register(
                lambda: None,
                descriptor=PowerFlowBackendDescriptor(
                    backend_id="future-backend",
                    name="future",
                    contract_version="2",
                ),
            )
        _assert_located_rejection(self, str(ctx.exception))

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = PowerFlowBackendRegistry()
        registry.register(
            lambda: None,
            descriptor=PowerFlowBackendDescriptor(
                backend_id="v1-backend",
                name="v1",
                contract_version="1",
            ),
        )
        self.assertEqual(registry.get_descriptor("v1-backend").contract_version, "1")


class SurrogateContractVersionTest(unittest.TestCase):
    def test_unsupported_contract_version_is_rejected_with_located_error(
        self,
    ) -> None:
        registry = SurrogateRegistry()
        with self.assertRaises(UnsupportedContractVersionError) as ctx:
            registry.register(
                lambda: None,
                descriptor=SurrogateDescriptor(
                    surrogate_id="future-surrogate",
                    name="future",
                    physical_model="network-impact",
                    error_bound=_measured_bound(),
                    contract_version="2",
                ),
            )
        _assert_located_rejection(self, str(ctx.exception))

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = SurrogateRegistry()
        registry.register(
            lambda: None,
            descriptor=SurrogateDescriptor(
                surrogate_id="v1-surrogate",
                name="v1",
                physical_model="network-impact",
                error_bound=_measured_bound(),
                contract_version="1",
            ),
        )
        self.assertEqual(registry.get_descriptor("v1-surrogate").contract_version, "1")


class PolicyContractVersionTest(unittest.TestCase):
    def test_unsupported_contract_version_is_rejected_with_located_error(
        self,
    ) -> None:
        registry = PolicyRegistry()
        with self.assertRaises(UnsupportedContractVersionError) as ctx:
            registry.register(
                lambda: None,
                descriptor=PolicyDescriptor(
                    policy_id="future-policy",
                    name="future",
                    paradigm="reinforcement_learning",
                    contract_version="2",
                ),
            )
        _assert_located_rejection(self, str(ctx.exception))

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = PolicyRegistry()
        registry.register(
            lambda: None,
            descriptor=PolicyDescriptor(
                policy_id="v1-policy",
                name="v1",
                paradigm="reinforcement_learning",
                contract_version="1",
            ),
        )
        self.assertEqual(registry.get_descriptor("v1-policy").contract_version, "1")


class ObservationProducerContractVersionTest(unittest.TestCase):
    def test_unsupported_contract_version_is_rejected_with_located_error(
        self,
    ) -> None:
        registry = ObservationProducerRegistry()
        with self.assertRaises(UnsupportedContractVersionError) as ctx:
            registry.register(
                lambda: None,
                descriptor=ObservationProducerDescriptor(
                    producer_id="future-producer",
                    provenance="measured",
                    summary="future",
                    contract_version="2",
                ),
            )
        _assert_located_rejection(self, str(ctx.exception))

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = ObservationProducerRegistry()
        registry.register(
            lambda: None,
            descriptor=ObservationProducerDescriptor(
                producer_id="v1-producer",
                provenance="measured",
                summary="v1",
                contract_version="1",
            ),
        )
        self.assertEqual(registry.get_descriptor("v1-producer").contract_version, "1")


class NetworkAdapterContractVersionTest(unittest.TestCase):
    def test_unsupported_contract_version_is_rejected_with_located_error(
        self,
    ) -> None:
        registry = NetworkAdapterRegistry()
        with self.assertRaises(UnsupportedContractVersionError) as ctx:
            registry.register(
                lambda: None,
                descriptor=NetworkAdapterDescriptor(
                    adapter_id="future-adapter",
                    adapter_name="future",
                    source_standard="cim",
                    source_format="parquet",
                    capabilities=(),
                    contract_version="2",
                ),
            )
        _assert_located_rejection(self, str(ctx.exception))

    def test_supported_contract_version_is_accepted(self) -> None:
        registry = NetworkAdapterRegistry()
        registry.register(
            lambda: None,
            descriptor=NetworkAdapterDescriptor(
                adapter_id="v1-adapter",
                adapter_name="v1",
                source_standard="cim",
                source_format="parquet",
                capabilities=(),
                contract_version="1",
            ),
        )
        self.assertEqual(registry.get_descriptor("v1-adapter").contract_version, "1")


class HostRegistrationSurfaceTest(unittest.TestCase):
    """The register_<role>_extension host conveniences actually register."""

    def test_backend_host_registration_resolves(self) -> None:
        from gridalyn.simulation.backends.registry import (
            register_powerflow_backend_extension,
        )

        registry = PowerFlowBackendRegistry()
        register_powerflow_backend_extension(
            lambda: None,
            descriptor=PowerFlowBackendDescriptor(
                backend_id="host-backend", name="host", contract_version="1"
            ),
            registry=registry,
        )
        self.assertEqual(
            registry.get_descriptor("host-backend").backend_id, "host-backend"
        )

    def test_observation_producer_host_registration_resolves(self) -> None:
        from gridalyn.twin.observation.registry import (
            register_observation_producer_extension,
        )

        registry = ObservationProducerRegistry()
        register_observation_producer_extension(
            lambda: None,
            descriptor=ObservationProducerDescriptor(
                producer_id="host-producer",
                provenance="measured",
                summary="host",
                contract_version="1",
            ),
            registry=registry,
        )
        self.assertEqual(
            registry.get_descriptor("host-producer").producer_id, "host-producer"
        )

    def test_surrogate_host_registration_resolves(self) -> None:
        from gridalyn.simulation.surrogates.registry import register_surrogate_extension

        registry = SurrogateRegistry()
        register_surrogate_extension(
            lambda: None,
            descriptor=SurrogateDescriptor(
                surrogate_id="host-surrogate",
                name="host",
                physical_model="pandapower",
                error_bound=_measured_bound(),
                contract_version="1",
            ),
            registry=registry,
        )
        self.assertEqual(
            registry.get_descriptor("host-surrogate").surrogate_id, "host-surrogate"
        )

    def test_policy_host_registration_resolves(self) -> None:
        from gridalyn.simulation.policies.registry import register_policy_extension

        registry = PolicyRegistry()
        register_policy_extension(
            lambda: None,
            descriptor=PolicyDescriptor(
                policy_id="host-policy",
                name="host",
                paradigm="sensitivity_dispatch",
                contract_version="1",
            ),
            registry=registry,
        )
        self.assertEqual(
            registry.get_descriptor("host-policy").policy_id, "host-policy"
        )

    def test_network_adapter_host_registration_resolves(self) -> None:
        from gridalyn.twin.adapters.registry import register_network_adapter_extension

        registry = NetworkAdapterRegistry()
        register_network_adapter_extension(
            lambda: None,
            descriptor=NetworkAdapterDescriptor(
                adapter_id="host-adapter",
                adapter_name="host",
                source_standard="cim",
                source_format="parquet",
                capabilities=(),
                contract_version="1",
            ),
            registry=registry,
        )
        self.assertEqual(
            registry.get_descriptor("host-adapter").adapter_id, "host-adapter"
        )

    def test_host_conveniences_reachable_from_layer_facades(self) -> None:
        import gridalyn.simulation
        import gridalyn.twin

        self.assertTrue(
            callable(gridalyn.simulation.register_powerflow_backend_extension)
        )
        self.assertTrue(callable(gridalyn.simulation.register_surrogate_extension))
        self.assertTrue(callable(gridalyn.simulation.register_policy_extension))
        self.assertTrue(callable(gridalyn.twin.register_network_adapter_extension))
        self.assertTrue(callable(gridalyn.twin.register_observation_producer_extension))

    def test_facade_exports_are_the_role_module_functions(self) -> None:
        """The layer facades re-export the same functions the resolve tests use."""
        from gridalyn.simulation import (
            register_policy_extension,
            register_powerflow_backend_extension,
            register_surrogate_extension,
        )
        from gridalyn.simulation.backends.registry import (
            register_powerflow_backend_extension as role_backend,
        )
        from gridalyn.simulation.policies.registry import (
            register_policy_extension as role_policy,
        )
        from gridalyn.simulation.surrogates.registry import (
            register_surrogate_extension as role_surrogate,
        )
        from gridalyn.twin import (
            register_network_adapter_extension,
            register_observation_producer_extension,
        )
        from gridalyn.twin.adapters.registry import (
            register_network_adapter_extension as role_adapter,
        )
        from gridalyn.twin.observation.registry import (
            register_observation_producer_extension as role_producer,
        )

        self.assertIs(register_powerflow_backend_extension, role_backend)
        self.assertIs(register_surrogate_extension, role_surrogate)
        self.assertIs(register_policy_extension, role_policy)
        self.assertIs(register_network_adapter_extension, role_adapter)
        self.assertIs(register_observation_producer_extension, role_producer)


# A child-process probe that registers through the DEFAULT path (no
# ``registry=``) and resolves each role through its default registry. The
# default registries are process-global singletons, so this must run in a
# subprocess to avoid polluting every "exactly the shipped set" assertion in
# the same pytest run.
_DEFAULT_PATH_PROBE = r"""
import json
import sys

from gridalyn.simulation.backends.contract import PowerFlowBackendDescriptor
from gridalyn.simulation.backends.registry import (
    default_powerflow_backend_registry,
    register_powerflow_backend_extension,
)
from gridalyn.simulation.policies.contract import PolicyDescriptor
from gridalyn.simulation.policies.registry import (
    default_policy_registry,
    register_policy_extension,
)
from gridalyn.simulation.surrogates.contract import (
    SurrogateDescriptor,
    unmeasured_error_bound,
)
from gridalyn.simulation.surrogates.registry import (
    default_surrogate_registry,
    register_surrogate_extension,
)
from gridalyn.twin.adapters.network import NetworkAdapterDescriptor
from gridalyn.twin.adapters.registry import (
    default_network_adapter_registry,
    register_network_adapter_extension,
)
from gridalyn.twin.observation.registry import (
    ObservationProducerDescriptor,
    default_observation_producer_registry,
    register_observation_producer_extension,
)

register_powerflow_backend_extension(
    lambda: None,
    descriptor=PowerFlowBackendDescriptor(
        backend_id="default_path_probe_backend", name="probe"
    ),
)
register_surrogate_extension(
    lambda: None,
    descriptor=SurrogateDescriptor(
        surrogate_id="default_path_probe_surrogate",
        name="probe",
        physical_model="pandapower",
        error_bound=unmeasured_error_bound(
            metric="mae_relief_pct_per_kw",
            units="transformer_loading_pct_point_per_kw",
            reference="pandapower",
            reason="default-path probe",
        ),
    ),
)
register_policy_extension(
    lambda: None,
    descriptor=PolicyDescriptor(
        policy_id="default_path_probe_policy",
        name="probe",
        paradigm="sensitivity_dispatch",
    ),
)
register_observation_producer_extension(
    lambda: None,
    descriptor=ObservationProducerDescriptor(
        producer_id="default_path_probe_producer",
        provenance="measured",
        summary="probe",
    ),
)
register_network_adapter_extension(
    lambda: None,
    descriptor=NetworkAdapterDescriptor(
        adapter_id="default_path_probe_adapter",
        adapter_name="probe",
        source_standard="cim",
        source_format="parquet",
        capabilities=(),
    ),
)

resolved = {
    "backend": default_powerflow_backend_registry()
    .get_descriptor("default_path_probe_backend")
    .backend_id,
    "surrogate": default_surrogate_registry()
    .get_descriptor("default_path_probe_surrogate")
    .surrogate_id,
    "policy": default_policy_registry()
    .get_descriptor("default_path_probe_policy")
    .policy_id,
    "producer": default_observation_producer_registry()
    .get_descriptor("default_path_probe_producer")
    .producer_id,
    "adapter": default_network_adapter_registry()
    .get_descriptor("default_path_probe_adapter")
    .adapter_id,
}
print(json.dumps(resolved, sort_keys=True))
"""


class DefaultPathHostRegistrationTest(unittest.TestCase):
    """A host registration through the DEFAULT path persists and resolves.

    The Phase 14 design correction exists so ``register_<role>_extension``
    WITHOUT ``registry=`` lands in the cached default registry and stays
    resolvable via ``default_<role>_registry()`` -- the exact silent no-op the
    correction fixed. Subprocess isolation is mandatory: the default
    registries are process-global singletons, so registering into them
    in-process would pollute the "exactly the shipped set" assertions in this
    run.
    """

    def test_default_path_host_registration_persists_for_all_roles(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", _DEFAULT_PATH_PROBE],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=120,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr[-2000:])
        resolved = json.loads(completed.stdout)
        self.assertEqual("default_path_probe_backend", resolved["backend"])
        self.assertEqual("default_path_probe_surrogate", resolved["surrogate"])
        self.assertEqual("default_path_probe_policy", resolved["policy"])
        self.assertEqual("default_path_probe_producer", resolved["producer"])
        self.assertEqual("default_path_probe_adapter", resolved["adapter"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
