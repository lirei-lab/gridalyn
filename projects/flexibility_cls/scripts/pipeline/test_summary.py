"""Tests for the stage-boundary ``summarize_array`` helper.

Asserts the five behaviors the golden-master baseline relies on: a
JSON-plain stats+hash dict, no leaked numpy scalar types, a rounding-stable
content hash (stable below the floor, sensitive at/above it), a canonical
hash layout, and loud failure on empty/NaN input.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.flexibility_cls.scripts.pipeline._summary import summarize_array


def test_returns_expected_keys_and_shapes() -> None:
    arr = np.array([1.0, 2.0, 3.0, 4.0], dtype=float)
    out = summarize_array(arr, round_decimals=6)

    assert out["shape"] == [4]
    assert out["sum"] == pytest.approx(10.0)
    assert out["mean"] == pytest.approx(2.5)
    assert out["min"] == pytest.approx(1.0)
    assert out["max"] == pytest.approx(4.0)
    assert set(out["quantiles"]) == {"p5", "p25", "p50", "p75", "p95"}
    assert isinstance(out["content_sha256"], str)
    assert len(out["content_sha256"]) == 64
    assert out["round_decimals"] == 6


def test_all_values_are_json_plain_no_numpy_scalars() -> None:
    arr = np.linspace(0.0, 1.0, 10, dtype=float)
    out = summarize_array(arr, round_decimals=4)

    # numpy scalar types are NOT plain float/int; assert none leaked.
    for key in ("sum", "mean", "min", "max"):
        assert type(out[key]) is float
    for value in out["quantiles"].values():
        assert type(value) is float
    assert type(out["round_decimals"]) is int
    for dim in out["shape"]:
        assert type(dim) is int

    # json.dumps must succeed on the whole payload.
    json.dumps(out)


def test_hash_stable_below_floor_changes_at_or_above_floor() -> None:
    base = np.array([1.234567, 2.345678, 3.456789], dtype=float)
    decimals = 3

    # Two equal arrays -> identical hash.
    assert (
        summarize_array(base.copy(), round_decimals=decimals)["content_sha256"]
        == summarize_array(base.copy(), round_decimals=decimals)["content_sha256"]
    )

    # A perturbation strictly BELOW the rounding floor -> SAME hash.
    below = base + 1e-6
    assert (
        summarize_array(below, round_decimals=decimals)["content_sha256"]
        == summarize_array(base, round_decimals=decimals)["content_sha256"]
    )

    # A perturbation AT/ABOVE the rounding floor -> DIFFERENT hash.
    above = base + 1e-2
    assert (
        summarize_array(above, round_decimals=decimals)["content_sha256"]
        != summarize_array(base, round_decimals=decimals)["content_sha256"]
    )


def test_hash_layout_is_canonical_across_noncontiguous_input() -> None:
    # A non-contiguous / transposed view must hash identically to its
    # contiguous equal-valued counterpart (np.ascontiguousarray canonicalizes).
    contiguous = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=float)
    view = np.array([[1.0, 3.0], [2.0, 4.0]], dtype=float).T  # non-contiguous, == contiguous
    assert not view.flags["C_CONTIGUOUS"]
    assert (
        summarize_array(view, round_decimals=6)["content_sha256"]
        == summarize_array(contiguous, round_decimals=6)["content_sha256"]
    )


def test_raises_on_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        summarize_array(np.array([], dtype=float), round_decimals=6)


def test_raises_on_nan_input() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        summarize_array(np.array([1.0, np.nan, 3.0], dtype=float), round_decimals=6)


def test_raises_on_inf_input() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        summarize_array(np.array([1.0, np.inf, 3.0], dtype=float), round_decimals=6)
    with pytest.raises(ValueError, match="non-finite"):
        summarize_array(np.array([1.0, -np.inf, 3.0], dtype=float), round_decimals=6)


def test_signed_zero_is_hash_canonical() -> None:
    # IEEE-754 +0.0 and -0.0 are numerically equal but have different byte
    # patterns; the content hash must collapse them so sub-floor jitter across
    # a zero crossing cannot flip the cross-environment tripwire (CR-01).
    pos = summarize_array(np.array([0.0, 1.5, 2.5], dtype=float), round_decimals=6)
    neg = summarize_array(np.array([-0.0, 1.5, 2.5], dtype=float), round_decimals=6)

    # The hash is identical despite the -0.0 vs +0.0 difference...
    assert pos["content_sha256"] == neg["content_sha256"]
    # ...and every descriptive stat is identical too.
    assert pos["sum"] == neg["sum"]
    assert pos["mean"] == neg["mean"]
    assert pos["min"] == neg["min"]
    assert pos["max"] == neg["max"]
    assert pos["quantiles"] == neg["quantiles"]

    # A value that rounds to -0.0 (tiny negative residual) must hash identically
    # to the same value computed as a tiny positive residual at the same floor.
    rounds_neg = summarize_array(np.array([-1e-10], dtype=float), round_decimals=6)
    rounds_pos = summarize_array(np.array([1e-10], dtype=float), round_decimals=6)
    assert rounds_neg["content_sha256"] == rounds_pos["content_sha256"]
