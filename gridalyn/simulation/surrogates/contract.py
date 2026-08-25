"""Contract for fast surrogates that stand in for a physical model.

``docs/platform/platform-layer-model.md`` (layer 4) states the rule this module
enforces: *"market logic may use fast estimates, but final operational claims
must be explainable against physical validation or a calibrated surrogate with
known error."* Before this module no surrogate in the tree carried a known
error -- ``physics_model.py`` contained zero matches for
``mae|rmse|error|tolerance`` -- so a screening decision taken on a surrogate
estimate could not be traced to an accuracy.

A :class:`SurrogateDescriptor` therefore carries a mandatory
:class:`ErrorBound`, and the registry refuses to register a descriptor without
one. An :class:`ErrorBound` is either ``measured`` (a real number, its sample
size and the protocol that produced it) or ``unmeasured`` (no number at all,
plus a located reason). There is deliberately no third state: an aspirational
target dressed as a measurement is the failure mode this type exists to
prevent, so a bound cannot be constructed with a value and no method, nor with
a status of ``measured`` and no sample.

Resolution is by explicit ID only -- see
:mod:`gridalyn.simulation.surrogates.registry`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd

ErrorBoundStatus = Literal["measured", "unmeasured"]

#: A bound backed by a real evaluation: value, sample size and protocol.
#: Annotated, not inferred: without the annotation mypy widens it to ``str``
#: and every ``status=MEASURED`` argument becomes a type error.
MEASURED: ErrorBoundStatus = "measured"

#: A bound that has not been evaluated. Carries no value, only a reason.
UNMEASURED: ErrorBoundStatus = "unmeasured"

#: Physics-label column holding constraint relief per curtailed kW, in
#: percentage points of transformer loading. Emitted by
#: ``perturbation_sampler.build_physics_labels``.
RELIEF_LABEL_COLUMN = "relief_pct_per_kw"

#: Prediction column holding the surrogate's signed loading change per kW. Its
#: negation is the surrogate's predicted relief, directly comparable to
#: :data:`RELIEF_LABEL_COLUMN`.
PREDICTED_DELTA_LOADING_COLUMN = "predicted_delta_loading_pct_per_kw"

#: Column marking a physics label whose perturbation actually landed. Samples
#: with a zero perturbation carry a relief of exactly 0.0 by construction, not
#: by measurement, so they are excluded from every bound.
ACTUAL_PERTURBATION_COLUMN = "actual_perturbation_kw"

#: Join keys tying a prediction row to its physics label.
_LABEL_JOIN_KEYS = ["provider_id", "scenario_id", "constraint_id"]

#: Units of the network-impact bound. Not the module's only units: any
#: surrogate/reference pair states its own through :func:`measure_error_bound`.
RELIEF_ERROR_UNITS = "transformer_loading_pct_point_per_kw"

#: Metric name of the network-impact bound. See :data:`RELIEF_ERROR_UNITS` for
#: why this is one metric among several rather than the module's only one.
RELIEF_ERROR_METRIC = "mae_relief_pct_per_kw"


@dataclass(frozen=True)
class ErrorBound:
    """A surrogate's accuracy against the physical model it approximates.

    Attributes:
        metric: Name of the statistic, e.g. ``mae_relief_pct_per_kw``.
        units: Physical units of ``value``, so a number is never quoted bare.
        value: The measured statistic, or ``None`` when ``status`` is
            ``unmeasured``. Never a target, never a placeholder.
        sample_size: Number of label rows the statistic was computed over.
            Zero only when ``status`` is ``unmeasured``.
        method: How the number was produced -- the evaluation protocol and the
            dataset -- in enough detail to re-run it.
        reference: The physical model the surrogate was compared against.
        status: ``measured`` or ``unmeasured``.
        reason: Why no measurement exists. Required when ``status`` is
            ``unmeasured``, and must be located enough to act on.
    """

    metric: str
    units: str
    value: float | None
    sample_size: int
    method: str
    reference: str
    status: ErrorBoundStatus = MEASURED
    reason: str | None = None

    def __post_init__(self) -> None:
        """Reject bounds that state more, or less, than was measured.

        Raises:
            ValueError: If the status is unknown, or the fields contradict it.
        """
        for name in ("metric", "units", "reference"):
            if not str(getattr(self, name)).strip():
                raise ValueError(
                    f"ErrorBound.{name} must be a non-empty string "
                    f"(metric={self.metric!r}, reference={self.reference!r})"
                )
        if self.status == MEASURED:
            self._validate_measured()
        elif self.status == UNMEASURED:
            self._validate_unmeasured()
        else:
            raise ValueError(
                f"unknown ErrorBound status {self.status!r} "
                f"(known: {MEASURED!r}, {UNMEASURED!r})"
            )

    def _validate_measured(self) -> None:
        """Check that a measured bound carries a real number and a sample.

        Raises:
            ValueError: If the value is absent or non-finite, the sample is
                empty, or the protocol is undocumented.
        """
        if self.value is None or not math.isfinite(float(self.value)):
            raise ValueError(
                f"ErrorBound {self.metric!r} is status={MEASURED!r} but its "
                f"value is {self.value!r}; state a finite measured number, or "
                f"use status={UNMEASURED!r} with a reason"
            )
        if self.sample_size <= 0:
            raise ValueError(
                f"ErrorBound {self.metric!r} is status={MEASURED!r} with "
                f"sample_size={self.sample_size}; a statistic over no samples "
                "is not a measurement"
            )
        if not self.method.strip():
            raise ValueError(
                f"ErrorBound {self.metric!r} is status={MEASURED!r} with no "
                "method; record the evaluation protocol and the dataset so "
                "the number can be re-derived"
            )

    def _validate_unmeasured(self) -> None:
        """Check that an unmeasured bound states no number and names a reason.

        Raises:
            ValueError: If a value or sample is present, or no reason is given.
        """
        if self.value is not None or self.sample_size != 0:
            raise ValueError(
                f"ErrorBound {self.metric!r} is status={UNMEASURED!r} but "
                f"carries value={self.value!r}, sample_size={self.sample_size}; "
                "an unmeasured bound must state no number at all"
            )
        if not (self.reason or "").strip():
            raise ValueError(
                f"ErrorBound {self.metric!r} is status={UNMEASURED!r} with no "
                "reason; name what is missing and where, so the gap is "
                "actionable rather than silent"
            )

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the bound for reports and manifests.

        Returns:
            A ``dict`` of JSON-native values only, so it embeds in a governed
            report without a custom encoder.
        """
        return {
            "metric": self.metric,
            "units": self.units,
            "value": None if self.value is None else float(self.value),
            "sample_size": int(self.sample_size),
            "method": self.method,
            "reference": self.reference,
            "status": self.status,
            "reason": self.reason,
        }


def unmeasured_error_bound(
    *,
    metric: str,
    units: str,
    reference: str,
    reason: str,
) -> ErrorBound:
    """Build a bound that honestly states no measurement exists.

    Args:
        metric: The statistic that *would* have been measured.
        units: Units that statistic would carry.
        reference: The physical model it would have been measured against.
        reason: Located explanation of what blocked the measurement.

    Returns:
        An ``unmeasured`` :class:`ErrorBound`.
    """
    return ErrorBound(
        metric=metric,
        units=units,
        value=None,
        sample_size=0,
        method="",
        reference=reference,
        status=UNMEASURED,
        reason=reason,
    )


def measure_error_bound(
    predicted: pd.Series,
    observed: pd.Series,
    *,
    metric: str,
    units: str,
    reference: str,
    method: str,
) -> ErrorBound:
    """Measure any surrogate against any physical reference, elementwise.

    The rule this module exists to enforce -- a decision taken on a fast
    estimate must be traceable to a known accuracy -- is not specific to
    network impact. A thermal surrogate checked against a building-physics
    model needs exactly the same guarantee, in different units. This function
    is that rule with the network-impact schema factored out:
    :func:`measure_relief_error_bound` is now one caller of it, not the only
    way to obtain a bound.

    Pairing is the caller's job. Two aligned series arrive already joined,
    because how a prediction is matched to an observation is domain knowledge
    -- join keys for a tabular impact frame, a shared timestamp for a dispatch
    replay -- and guessing it here would be the specialisation this function
    removes.

    Args:
        predicted: The surrogate's estimate, already aligned to ``observed``.
        observed: The physical model's value for the same rows.
        metric: Name of the statistic, e.g. ``mae_relief_pct_per_kw``.
        units: Physical units of the result, so the number is never bare.
        reference: The physical model ``observed`` came from.
        method: The evaluation protocol and dataset, recorded on the bound.

    Returns:
        A ``measured`` :class:`ErrorBound`, or an ``unmeasured`` one when no
        rows survive alignment -- an empty comparison is a missing
        measurement, never an accuracy of zero.

    Raises:
        ValueError: If the two series differ in length, which means the
            caller's pairing is wrong and any number computed here would be
            meaningless.
    """
    if len(predicted) != len(observed):
        raise ValueError(
            "predicted and observed must be aligned before measuring a bound "
            f"(predicted has {len(predicted)} rows, observed has "
            f"{len(observed)}); join them on the domain's own keys first"
        )
    paired = pd.DataFrame(
        {
            "predicted": predicted.astype(float).to_numpy(),
            "observed": observed.astype(float).to_numpy(),
        }
    ).dropna()
    if paired.empty:
        return unmeasured_error_bound(
            metric=metric,
            units=units,
            reference=reference,
            reason=(
                "no rows survived alignment between the surrogate's "
                "predictions and the reference's observations, so there is "
                "nothing to measure"
            ),
        )
    return ErrorBound(
        metric=metric,
        units=units,
        value=float((paired["predicted"] - paired["observed"]).abs().mean()),
        sample_size=int(len(paired)),
        method=method,
        reference=reference,
    )


def measure_relief_error_bound(
    predictions: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    reference: str,
    method: str,
) -> ErrorBound:
    """Measure a surrogate's relief prediction against physics labels.

    The comparison is schema-defined rather than per-surrogate: a surrogate's
    predicted relief per kW is the negation of
    :data:`PREDICTED_DELTA_LOADING_COLUMN`, and the physical model's is
    :data:`RELIEF_LABEL_COLUMN`. Both are percentage points of constraint
    transformer loading per curtailed kW, so the difference is meaningful
    without a unit conversion.

    Args:
        predictions: A surrogate prediction frame carrying the join keys and
            :data:`PREDICTED_DELTA_LOADING_COLUMN`.
        labels: Finite-difference physics labels from
            ``perturbation_sampler.build_physics_labels``.
        reference: The physical model the labels came from.
        method: The evaluation protocol and dataset, recorded on the bound.

    Returns:
        A ``measured`` :class:`ErrorBound`, or an ``unmeasured`` one when the
        join leaves no labelled rows -- an empty overlap is a missing
        measurement, not an accuracy of zero.

    Raises:
        ValueError: If either frame is missing a column the comparison needs.
            The message names the frame and the missing columns.
    """
    _require_columns(
        predictions,
        [*_LABEL_JOIN_KEYS, PREDICTED_DELTA_LOADING_COLUMN],
        "predictions",
    )
    _require_columns(
        labels,
        [*_LABEL_JOIN_KEYS, RELIEF_LABEL_COLUMN, ACTUAL_PERTURBATION_COLUMN],
        "labels",
    )
    landed = labels.loc[labels[ACTUAL_PERTURBATION_COLUMN].astype(float) > 0.0]
    paired = landed.merge(
        predictions[[*_LABEL_JOIN_KEYS, PREDICTED_DELTA_LOADING_COLUMN]],
        on=_LABEL_JOIN_KEYS,
        how="inner",
        validate="many_to_one",
    )
    if paired.empty:
        return unmeasured_error_bound(
            metric=RELIEF_ERROR_METRIC,
            units=RELIEF_ERROR_UNITS,
            reference=reference,
            reason=(
                "no physics label joined to a prediction on "
                f"{_LABEL_JOIN_KEYS} with "
                f"{ACTUAL_PERTURBATION_COLUMN} > 0; generate labels with "
                "perturbation_sampler before measuring the bound"
            ),
        )
    return measure_error_bound(
        -paired[PREDICTED_DELTA_LOADING_COLUMN].astype(float),
        paired[RELIEF_LABEL_COLUMN].astype(float),
        metric=RELIEF_ERROR_METRIC,
        units=RELIEF_ERROR_UNITS,
        reference=reference,
        method=method,
    )


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    """Raise when ``frame`` lacks any of ``columns``.

    Args:
        frame: The frame to check.
        columns: Columns the caller needs.
        label: Name of the frame, so the message locates the problem.

    Raises:
        ValueError: If any column is missing. Lists both what is missing and
            what is present.
    """
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{label} is missing required columns: {missing} "
            f"(present columns: {sorted(frame.columns)})"
        )


@dataclass(frozen=True)
class SurrogateDescriptor:
    """Identity, physical reference and stated accuracy of a surrogate.

    Attributes:
        surrogate_id: Stable ID a caller resolves the surrogate by.
        name: Human-readable description for reports and manifests.
        physical_model: The physical model this surrogate approximates. Named,
            not implied, because the error bound is meaningless without it.
        error_bound: The surrogate's stated accuracy. Optional on the
            dataclass so an unbounded descriptor can be *constructed* and
            refused; the registry rejects ``None`` at registration.
    """

    surrogate_id: str
    name: str
    physical_model: str
    error_bound: ErrorBound | None = None
    contract_version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the descriptor for reports.

        Returns:
            A ``dict`` of JSON-native values only.
        """
        return {
            "surrogate_id": self.surrogate_id,
            "name": self.name,
            "physical_model": self.physical_model,
            "error_bound": (
                None if self.error_bound is None else self.error_bound.as_dict()
            ),
            "contract_version": self.contract_version,
        }


@runtime_checkable
class Surrogate(Protocol):
    """A fast estimator with a declared physical reference and known error.

    The three methods are a lifecycle, not a schema: fit a model (trivially,
    for a fit-free surrogate), predict whatever frame the surrogate's own
    domain defines, and verify it against that domain's physical labels.
    ``verify`` is what makes the stated bound falsifiable rather than prose.

    The network-impact surrogates this module shipped first predict a
    selector-compatible impact frame and verify against finite-difference
    physics labels, but that pairing is theirs, not the protocol's. A
    surrogate in another domain -- a thermal model checked against a
    building-physics reference, say -- implements the same three methods over
    its own frames and states its accuracy through
    :func:`measure_error_bound`.
    """

    @property
    def descriptor(self) -> SurrogateDescriptor:
        """Return the surrogate's identity and stated error bound.

        Declared read-only: implementations expose it as a ``property`` so a
        consumer cannot rebind the accuracy a decision was justified by.
        """

    def fit(
        self,
        training: pd.DataFrame,
        labels: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        """Fit the surrogate and return the model it will predict with.

        Args:
            training: Feature table from ``build_training_dataset``.
            labels: Physics labels, for surrogates that need supervision.

        Returns:
            The fitted model, passed back to :meth:`predict`.
        """

    def predict(
        self,
        training: pd.DataFrame,
        model: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Predict selector-compatible provider impact.

        Args:
            training: Feature table from ``build_training_dataset``.
            model: The model returned by :meth:`fit`, where one is needed.

        Returns:
            A prediction frame carrying
            :data:`PREDICTED_DELTA_LOADING_COLUMN`.
        """

    def verify(
        self,
        predictions: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> ErrorBound:
        """Re-measure this surrogate's accuracy against physics labels.

        Args:
            predictions: A frame returned by :meth:`predict`.
            labels: Finite-difference physics labels.

        Returns:
            A freshly measured :class:`ErrorBound`.
        """


def describe_surrogate(factory: Any) -> SurrogateDescriptor:
    """Return the descriptor a surrogate factory declares.

    Args:
        factory: A surrogate class or callable carrying a ``DESCRIPTOR``
            attribute of type :class:`SurrogateDescriptor`.

    Returns:
        The declared descriptor.

    Raises:
        TypeError: If ``factory`` declares no usable ``DESCRIPTOR``. The
            message names the factory and what to add, because a factory
            without a descriptor carries no error bound either.
    """
    descriptor = getattr(factory, "DESCRIPTOR", None)
    if not isinstance(descriptor, SurrogateDescriptor):
        name = getattr(factory, "__name__", type(factory).__name__)
        found = type(descriptor).__name__ if descriptor is not None else "nothing"
        raise TypeError(
            f"surrogate factory {name} declares no descriptor (found {found}); "
            "add a class attribute DESCRIPTOR: SurrogateDescriptor, or pass "
            "descriptor=... to SurrogateRegistry.register"
        )
    return descriptor


__all__ = [
    "ACTUAL_PERTURBATION_COLUMN",
    "MEASURED",
    "PREDICTED_DELTA_LOADING_COLUMN",
    "RELIEF_ERROR_METRIC",
    "RELIEF_ERROR_UNITS",
    "RELIEF_LABEL_COLUMN",
    "UNMEASURED",
    "ErrorBound",
    "ErrorBoundStatus",
    "Surrogate",
    "SurrogateDescriptor",
    "describe_surrogate",
    "measure_relief_error_bound",
    "unmeasured_error_bound",
]
