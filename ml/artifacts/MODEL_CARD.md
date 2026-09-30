# Rakshak spoilage model card

> **Trained entirely on SIMULATED shipments.** Nothing here has been validated against real spoilage outcomes.
> The FPO pilot is meant to collect real outcomes to retrain and validate these models.

Generated 2026-09-30T13:25:00+00:00 by `python -m rakshak_ml.train` (seed 42, 150 simulated shipments per food type and profile).

## What the models predict

| Output | Meaning |
|---|---|
| `spoilage_risk` (0-100) | fraction of shelf life consumed plus a small term for the *current* degradation rate. SAFE < 30, WARNING 30-70, CRITICAL >= 70. Driven by accumulated exposure, so a short spike does not alarm but a long excursion escalates. |
| `remaining_safe_life_hours` | hours until the food is spoiled **if conditions stay as they are now**, capped at 240 h (real profile). |

Both are defined by the simulator's hidden quality model (see `ml/rakshak_ml/sim.py`). They are *assumptions*, not measurements: per-food Q10 factors, chilling-injury, humidity, ethylene, over-ripeness and shock-damage terms, and a nominal shelf life per food that is a simulator assumption.

## Two model pairs

* **real** - physical time scale; trips of 1-4 days, a record every 5 minutes. Use this for anything real.
* **demo** - the same physics with time compressed 24x (trips of 1.5-5 h, a record every minute), so the risk moves visibly in a short live demo. **Not for real use.**

Each pair is two scikit-learn `RandomForestRegressor`s (risk, remaining life). Hyper-parameters: `{"n_estimators": 80, "max_depth": 14, "min_samples_leaf": 20, "max_features": 0.5, "n_jobs": -1}`.

## Features (33)

`min_temp`, `max_temp`, `min_humidity`, `max_humidity`, `ethylene_sensitive`, `ethylene_producer`, `nominal_shelf_life_h`, `temperature`, `humidity`, `ethylene_index`, `shock_g`, `temperature_deviation`, `humidity_deviation`, `temperature_rate_of_change`, `ethylene_rate_of_change`, `time_outside_temp_range`, `time_outside_humidity_range`, `max_temp_deviation`, `cumulative_temp_exposure`, `cumulative_humidity_exposure`, `temperature_excursion_count`, `time_since_first_excursion`, `cumulative_ethylene_exposure`, `max_ethylene_index`, `shock_count`, `max_shock`, `elapsed_minutes`, `external_temperature`, `external_humidity`, `rain_probability`, `wind_speed`, `flap_position`, `scrubber_on`

Same code path in training and serving (`rakshak_ml.features.FeatureEngine`). `cooling_status` is **not** a feature (it leaked the label in the MedRakshak demo model); actuator state is only `flap_position` and `scrubber_on`.

## Food bands

| Food | Temp band (C) | RH band (%) | Ethylene sens./prod. | Source | Status |
|---|---|---|---|---|---|
| mango | 10.0-13.0 | 85.0-90.0 | yes/yes | USDA Agriculture Handbook 66 (mango) - chilling-sensitive below ~10 C; mature-green around 13 C | **TODO-verify** |
| banana | 13.0-14.0 | 90.0-95.0 | yes/yes | USDA Agriculture Handbook 66 (banana, green) - chilling injury below ~13 C | **TODO-verify** |
| tomato | 10.0-13.0 | 90.0-95.0 | yes/yes | USDA Agriculture Handbook 66 (tomato, mature-green to ripe) - band simplified to one range | **TODO-verify** |
| leafy_vegetables | 0.0-2.0 | 95.0-100.0 | yes/no | USDA Agriculture Handbook 66 (leafy greens, e.g. lettuce/spinach) - near 0 C, very high RH | **TODO-verify** |
| milk | 2.0-4.0 | 0.0-100.0 | no/no | General dairy cold-chain practice (chilled milk at or below about 4 C); no citation - TODO-verify against FSSAI / dairy guidance | **TODO-verify** |

## Evaluation (held-out *shipments*, never seen in training)

### real profile

Rows: train 54,065 / val 11,217 / test 11,587 (split by shipment, stratified by food type).

| Target | Model MAE | Model R2 | Mean-baseline MAE | 3-feature linear MAE | 3-feature linear R2 |
|---|---|---|---|---|---|
| risk (0-100) | 3.5 | 0.9657 | 27.596 | 9.274 | 0.8543 |
| remaining life (h) | 14.717 | 0.9136 | 60.036 | 37.763 | 0.5695 |

Alert-level accuracy 92.3%; CRITICAL recall 88.7%, CRITICAL precision 91.1%. True level mix: {'SAFE': 0.5507, 'WARNING': 0.2554, 'CRITICAL': 0.1939}.

Risk MAE per food: banana 3.13, leafy_vegetables 3.21, mango 3.54, milk 4.99, tomato 2.45.

Scripted scenarios in a cold room (no PCM, no scrubber, batch quality = nominal):

| Scenario | mean max risk | reaches WARNING | reaches CRITICAL |
|---|---|---|---|
| steady_in_band | 22.4 | 27% | 0% |
| short_spike_20min | 28.1 | 27% | 0% |
| long_heat_event | 78.8 | 100% | 73% |

Top risk features: `cumulative_temp_exposure` (0.49), `temperature_deviation` (0.16), `max_temp_deviation` (0.10), `time_outside_temp_range` (0.07), `time_since_first_excursion` (0.03), `cumulative_humidity_exposure` (0.03).

Leakage checks:

* PASS `no_shipment_in_two_splits` - 0 shared shipments
* PASS `no_forbidden_feature_columns` - none
* PASS `cooling_status_absent` - the MedRakshak leak
* PASS `features_are_exactly_the_declared_list` - 33 features
* PASS `no_single_feature_explains_label` - best linear single-feature R2 = 0.732 (temperature_deviation)
* PASS `shuffled_label_control` - R2 on test with shuffled training labels = -0.005 (real model: 0.966)

### demo profile

Rows: train 20,915 / val 4,349 / test 4,504 (split by shipment, stratified by food type).

| Target | Model MAE | Model R2 | Mean-baseline MAE | 3-feature linear MAE | 3-feature linear R2 |
|---|---|---|---|---|---|
| risk (0-100) | 3.504 | 0.9735 | 35.205 | 11.696 | 0.8439 |
| remaining life (h) | 0.493 | 0.9299 | 2.466 | 1.489 | 0.6022 |

Alert-level accuracy 92.7%; CRITICAL recall 95.4%, CRITICAL precision 95.3%. True level mix: {'SAFE': 0.3606, 'WARNING': 0.2176, 'CRITICAL': 0.4218}.

Risk MAE per food: banana 3.17, leafy_vegetables 2.36, mango 3.36, milk 4.57, tomato 3.94.

Scripted scenarios in a cold room (no PCM, no scrubber, batch quality = nominal):

| Scenario | mean max risk | reaches WARNING | reaches CRITICAL |
|---|---|---|---|
| steady_in_band | 36.0 | 53% | 13% |
| short_spike_20min | 49.6 | 90% | 17% |
| long_heat_event | 86.5 | 100% | 100% |

Top risk features: `cumulative_temp_exposure` (0.48), `temperature_deviation` (0.15), `max_temp_deviation` (0.11), `time_outside_temp_range` (0.08), `time_since_first_excursion` (0.05), `elapsed_minutes` (0.03).

Leakage checks:

* PASS `no_shipment_in_two_splits` - 0 shared shipments
* PASS `no_forbidden_feature_columns` - none
* PASS `cooling_status_absent` - the MedRakshak leak
* PASS `features_are_exactly_the_declared_list` - 33 features
* PASS `no_single_feature_explains_label` - best linear single-feature R2 = 0.704 (temperature_deviation)
* PASS `shuffled_label_control` - R2 on test with shuffled training labels = -0.006 (real model: 0.974)

## Limitations

* Labels come from the simulator's own quality model, so high scores measure how well the forest learned *that* model, not how well it predicts real spoilage. Real validation is future work (FPO pilot).
* Food bands are placeholders marked TODO-verify; the nominal shelf lives are simulator assumptions.
* The simulated ethylene index tracks concentration with a lag; real indicator strips are largely irreversible and need per-batch lab calibration against a reference sensor (pending).
* The crate is represented by the mean tag temperature; per-tag spread is not modelled.
* Remaining life assumes conditions persist; it does not forecast future excursions.
