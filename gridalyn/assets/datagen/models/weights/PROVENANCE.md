# Packaged macro-model weights — provenance

`lgbm_heating_macro.pkl` and `lgbm_bg_macro.pkl` are the trained heart of
`ParametricArxGenerator`. Every one of the six governed CI-fixture studies
declares `generator: parametric`, so **every CI-verified baseline in this
repository depends on these two files.**

Until this file existed, nothing recorded what they were trained on. The run
manifest's `provenance.macro_model` records *which* macro model ran — trained
weights or the analytical fallback — and has never recorded what produced the
weights. A study could be re-run to the byte without anyone being able to say
where its load shapes came from.

## Training data

| | |
|---|---|
| Source | `datasets/hq/{consumption,heating,meteo}.h5` |
| Dwellings | 1 000 |
| Period | 2018-04-03 00:00 → 2019-04-03 00:00 |
| Load resolution | 15 min — `consumption.h5` and `heating.h5` are `(35041, 1000)` |
| Weather resolution | 5 min — `meteo.h5` is `(105121, 9)`, resampled to 15 min during training |
| Heating target | mean across the 1 000 homes of `heating.h5`, in kW |
| Background target | mean across the 1 000 homes of `consumption − heating`, in kW |

**This data is private and cannot be redistributed.** It is metered
Hydro-Québec consumption and is gitignored (`.gitignore:172`); `git ls-files
datasets/` returns nothing. That is a real limit on reproducibility and is
stated here rather than left to be discovered: an external party can re-run the
studies and get identical numbers, but cannot re-derive these weights.

## Model

| | |
|---|---|
| Estimator | `lightgbm.LGBMRegressor` |
| Features | `temperature`, `hour_sin`, `hour_cos`, `hour` |
| Hyper-parameters | `objective=regression`, `metric=rmse`, `num_leaves=128`, `learning_rate=0.05`, `n_estimators=300` |
| Temperature support | **−24.3667 … +36.1 °C** |
| Committed | 2026-08-04 (`189b017d`), never retrained since |

## Integrity

    lgbm_heating_macro.pkl  e8a2885a8643ae62ec0f0af6a57408cfcbc51cc279c6dd1ae50b948e33953f35
    lgbm_bg_macro.pkl       6753b0f4a2d5fab68142a997a93ff8ae2e0094e7e04090116a4eacf261de13fb

`tests/test_macro_weights_provenance.py` pins both digests, so a substitution
is a failing test rather than a silent change of every baseline's inputs.

## How this was established

The training driver that named these inputs was deleted before this file
existed, so the chain was reconstructed from the pickles and then confirmed
against the dataset. Each identity below was measured, not inferred:

| Check | Model | `datasets/hq` |
|---|---|---|
| tree-0 `leaf_count` sum = training rows | 35 041 | 35 041 rows |
| tree-0 weighted leaf mean, heating | 1.1317571561 | 1.1317571561 kW/home |
| tree-0 weighted leaf mean, background | 1.2929145180 | 1.2929145178 kW/home |
| `feature_infos` temperature max | 36.1 | 36.1 |
| `feature_infos` temperature min | −24.3666666667 | −24.3666666667 |

The temperature minimum is the detail that closes it. The raw 5-minute DryBulb
minimum is **−24.40 °C**, which does *not* match; the 15-minute resampled mean
is **−24.3666666667 °C**, which matches to the last digit. That is only true if
training resampled the weather exactly the way `ParametricArxGenerator.fit()`
still does.

`tools/train_macro_weights.py` restores a driver that names these inputs. It
cannot run without the private dataset, and says so — a script that fails with
a located error is more reproducible than no script.

## Known limit: the model is flat below −20.5 °C

The lowest `temperature` split threshold across all 300 trees is **−20.488 °C**.
Below it every sample falls in one leaf, so predicted heating is *identically*
4.055942 kW from −20.488 °C down to −∞ — measured at −21, −25 and −40 °C.

This is not a bug in the fit; it is the training envelope showing through. A
gradient-boosted tree cannot extrapolate past its support, and the support ends
at −24.37 °C because that is the coldest 15-minute mean in the 2018–19 record.

It matters because the target population is Québec all-electric heating, where
design temperatures reach −30 °C and colder. **A study using this generator
gets no additional load below −20.5 °C.** Tracked in the issue tracker as the cold-tail saturation defect. The RC
building agent used by the two heavy studies computes heating from physics
rather than from this macro model and is not affected; the six fixture studies
and any external SDK user are.
