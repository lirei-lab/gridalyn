"""The channel-model role's declaration -> resolution -> provenance contract.

``ChannelModelRegistry`` shipped (#38) with nowhere for a study to declare a
channel, so a run whose agents lost messages and a run whose agents lost none
were indistinguishable in the manifest. This module pins the contract that
closes that gap, mirroring the backend and surrogate roles:

* declaring nothing resolves the ideal channel, and records **nothing** in
  provenance, so every study that simulates no communication keeps its
  manifest bytes;
* declaring a channel resolves exactly that model, with parameters mapped to
  the factory's names and its seed taken from a named ``spec.simulation.seeds``
  stream -- never inline, so the seed provenance records is the one it draws;
* an unregistered id, an unsupported parameter, an inline seed or a missing
  seed stream is a located error naming what is supported;
* a channel served by an extension is never silent in provenance.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from gridalyn.projects import init_project, run_workflow
from gridalyn.projects.loader import load_project
from gridalyn.projects.model_inputs import (
    load_channel_model_id,
    load_channel_model_parameters,
)
from gridalyn.projects.runner import (
    _build_provenance,
    _channel_model_provenance,
    plan_stages,
)
from gridalyn.projects.scripting import project_script
from gridalyn.projects.validation import validate_project_file
from gridalyn.simulation.channels import (
    BERNOULLI_LOSS_CHANNEL_ID,
    DEFAULT_CHANNEL_MODEL_ID,
    BernoulliLossChannel,
    ChannelModelDescriptor,
    ChannelModelRegistry,
    Delivery,
    FixedOutageChannel,
    IdealChannel,
    default_channel_model_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNDECLARED = _REPO_ROOT / "projects" / "minimal_grid_project"

LOSSY = {
    "id": BERNOULLI_LOSS_CHANNEL_ID,
    "parameters": {"lossProbability": 0.2, "latency": 1.5},
    "seedStream": "channel",
}


def _declaring(channel, seeds=None):
    project = load_project(_UNDECLARED / "project.yaml")
    simulation = project.raw["spec"].setdefault("simulation", {})
    simulation["seeds"] = {"channel": 99} if seeds is None else seeds
    simulation["channelModel"] = channel
    return project


def _copy_declaring(tmp: str, channel, seeds=None) -> Path:
    target = Path(tmp) / "minimal_grid_project"
    shutil.copytree(_UNDECLARED, target, ignore=shutil.ignore_patterns("outputs"))
    path = target / "project.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["spec"]["simulation"]["seeds"] = {"channel": 99} if seeds is None else seeds
    data["spec"]["simulation"]["channelModel"] = channel
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


class _ProbeChannel:
    DESCRIPTOR = ChannelModelDescriptor(
        channel_model_id="probe_channel", name="probe", parameters={"latency": 0.0}
    )

    def __init__(self, latency: float = 0.0) -> None:
        self._latency = latency

    @property
    def descriptor(self) -> ChannelModelDescriptor:
        return self.DESCRIPTOR

    def transmit(self, *, key, sender, receiver, sent_at) -> Delivery:
        return Delivery(deliver_at=sent_at + self._latency)


def _registry_with_host_channel() -> ChannelModelRegistry:
    registry = ChannelModelRegistry()
    registry.register(IdealChannel)
    registry.register(_ProbeChannel, source="host", version="2.0.0")
    return registry


class ChannelModelDeclarationTests(unittest.TestCase):
    def test_undeclared_study_resolves_the_ideal_channel_without_parameters(self):
        self.assertEqual(DEFAULT_CHANNEL_MODEL_ID, load_channel_model_id(_UNDECLARED))
        self.assertEqual({}, load_channel_model_parameters(_UNDECLARED))

    def test_declared_channel_resolves_its_id_parameters_and_named_seed(self):
        project = _declaring(LOSSY)
        self.assertEqual(BERNOULLI_LOSS_CHANNEL_ID, load_channel_model_id(project))
        self.assertEqual(
            {"loss_probability": 0.2, "latency": 1.5, "seed": 99},
            load_channel_model_parameters(project),
        )

    def test_unregistered_id_is_a_located_error_listing_the_registered(self):
        with self.assertRaises(ValueError) as caught:
            load_channel_model_id(_declaring({"id": "carrier_pigeon"}))
        message = str(caught.exception)
        self.assertIn("spec.simulation.channelModel.id", message)
        self.assertIn("'carrier_pigeon'", message)
        self.assertIn("registered: bernoulli_loss, fixed_latency", message)

    def test_an_inline_seed_is_refused(self):
        channel = {**LOSSY, "parameters": {"lossProbability": 0.2, "seed": 3}}
        with self.assertRaisesRegex(ValueError, "declares a seed inline"):
            load_channel_model_parameters(_declaring(channel))

    def test_a_model_that_draws_randomness_needs_a_declared_seed_stream(self):
        without = {key: value for key, value in LOSSY.items() if key != "seedStream"}
        with self.assertRaisesRegex(ValueError, "draws randomness, so it needs"):
            load_channel_model_parameters(_declaring(without))
        with self.assertRaisesRegex(ValueError, r"declared streams: other"):
            load_channel_model_parameters(_declaring(LOSSY, seeds={"other": 1}))

    def test_a_seed_stream_on_a_model_without_randomness_is_refused(self):
        channel = {"id": "fixed_latency", "seedStream": "channel"}
        with self.assertRaisesRegex(ValueError, "draws no randomness"):
            load_channel_model_parameters(_declaring(channel))

    def test_unsupported_parameters_and_keys_are_located_errors(self):
        channel = {**LOSSY, "parameters": {"lossRate": 0.2}}
        with self.assertRaises(ValueError) as caught:
            load_channel_model_parameters(_declaring(channel))
        self.assertIn("unsupported keys: loss_rate", str(caught.exception))
        self.assertIn("latency, loss_probability", str(caught.exception))
        with self.assertRaisesRegex(ValueError, "unsupported keys: loss"):
            load_channel_model_id(_declaring({**LOSSY, "loss": 0.2}))
        with self.assertRaisesRegex(ValueError, "parameters must be a mapping"):
            load_channel_model_parameters(_declaring({**LOSSY, "parameters": [0.2]}))

    def test_schema_accepts_the_declaration_and_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid = validate_project_file(_copy_declaring(tmp, LOSSY) / "project.yaml")
            self.assertTrue(valid.valid, valid.errors)
        with tempfile.TemporaryDirectory() as tmp:
            target = _copy_declaring(tmp, {**LOSSY, "seed": 3})
            invalid = validate_project_file(target / "project.yaml")
            self.assertFalse(invalid.valid)


class ChannelModelResolutionTests(unittest.TestCase):
    def test_project_script_builds_the_declared_channel_with_its_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = project_script(root=_copy_declaring(tmp, LOSSY))
            channel = script.channel_model()
        self.assertIsInstance(channel, BernoulliLossChannel)
        self.assertEqual(99, channel.descriptor.parameters["seed"])
        self.assertEqual(0.2, channel.descriptor.parameters["loss_probability"])

    def test_runtime_parameters_complete_a_declaration_but_never_the_seed(self):
        channel = {"id": "fixed_outage", "parameters": {"outageFraction": 0.5}}
        channel["seedStream"] = "channel"
        with tempfile.TemporaryDirectory() as tmp:
            script = project_script(root=_copy_declaring(tmp, channel))
            model = script.channel_model(endpoints=["a", "b", "c", "d"])
            with self.assertRaisesRegex(ValueError, "do not pass seed= at run time"):
                script.channel_model(endpoints=["a"], seed=1)
            with self.assertRaisesRegex(ValueError, "cannot be built from parameters"):
                script.channel_model()
        self.assertIsInstance(model, FixedOutageChannel)


class ChannelModelProvenanceTests(unittest.TestCase):
    def test_an_undeclared_study_records_no_channel_model(self):
        project = load_project(_UNDECLARED / "project.yaml")
        self.assertIsNone(_channel_model_provenance(project))
        self.assertNotIn(
            "channel_model", _build_provenance(project, plan_stages(project))
        )

    def test_a_declared_channel_records_parameters_seed_and_source(self):
        record = _channel_model_provenance(_declaring(LOSSY))
        self.assertEqual(BERNOULLI_LOSS_CHANNEL_ID, record["channel_model_id"])
        self.assertEqual(
            {"loss_probability": 0.2, "latency": 1.5, "seed": 99}, record["parameters"]
        )
        self.assertEqual("channel", record["seed_stream"])
        self.assertEqual("spec.simulation.channelModel", record["declared_source"])
        self.assertEqual(
            sorted(
                descriptor.channel_model_id
                for descriptor in default_channel_model_registry().list_descriptors()
            ),
            record["registered"],
        )
        self.assertNotIn("extension_id", record)

    def test_the_run_manifest_records_the_declared_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_case"
            init_project(target, name="my_case", template="grid-study")
            path = target / "project.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            simulation = data["spec"].setdefault("simulation", {})
            simulation["seeds"] = {"channel": 99}
            simulation["channelModel"] = LOSSY
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            run_workflow(target, dry_run=True)
            manifest = json.loads(
                (
                    target / "outputs" / "manifests" / "project_run_manifest.json"
                ).read_text(encoding="utf-8")
            )
        provenance = manifest["provenance"]
        self.assertEqual(99, provenance["channel_model"]["parameters"]["seed"])
        self.assertEqual({"channel": 99}, provenance["seeds"]["streams"])

    def test_a_channel_served_by_an_extension_is_never_silent(self):
        with mock.patch(
            "gridalyn.simulation.channels.registry.default_channel_model_registry",
            return_value=_registry_with_host_channel(),
        ):
            record = _channel_model_provenance(
                _declaring({"id": "probe_channel", "parameters": {"latency": 0.5}})
            )
        self.assertEqual("probe_channel", record["extension_id"])
        self.assertEqual("host", record["extension_source"])
        self.assertEqual("2.0.0", record["extension_version"])
        self.assertEqual({"latency": 0.5}, record["parameters"])
        self.assertIsNone(record["seed_stream"])


if __name__ == "__main__":
    unittest.main()
