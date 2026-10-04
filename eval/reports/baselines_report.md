# Aegis Clean Headline Benchmark Evaluation Report (v4)

**Source JSON**: `eval/baselines_results_v1.json`  
**Git Commit**: `7c4d9281e00ac7eaca0ceed24fefe91a16869df2`  
**Working Tree Dirty Flag**: `False`  
**Config SHA-256**: `4a4f57c934614635a211880997820fa55a536fadf1ee9d65861d97606ce8a20f`  
**Timestamp UTC**: `2026-10-04T17:49:52.451474+00:00`  
**Primary Aegis Arm**: `rolling` (per Decision D-7)  

## 1. Conformal Coverage Summary (20 Validation Apps)
*Source key path: `coverage_summary.median_iqr.<method>`*

| Method | Median Coverage (%) | IQR (%) | Role | Key Path |
| :--- | :---: | :---: | :---: | :--- |

## 2. Matched-Shortfall Pareto Frontier Evaluation
*Source key path: `matched_shortfall_pareto.<target_shortfall>.<method>`*

> [!NOTE]
> **Statistical Metric Disambiguation**:[^1]
> - **Diff of Medians (kWh)**: Marginal median difference across apps ($E_{\text{Aegis}}^{\text{med}} - E_{\text{CA}}^{\text{med}}$).
> - **All-App Mean DeltaE (kWh)**: Sample mean of individual per-app paired differences ($\frac{1}{N}\sum_{i=1}^N (E_{\text{Aegis}, i} - E_{\text{CA}, i})$), with 95% bootstrap percentile CI.
> - **Sign Convention**: $\Delta E = E_{\text{Aegis}} - E_{\text{CA}}$ (negative = Aegis cheaper).

### Target Shortfall: 0.0% (0.0 min / 18,720 min) — *Supplementary Target (Zero Shortfall Lower Bound)*
*Source key path: `matched_shortfall_pareto['0.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 356.44 | 159.30 | -197.14 | -133.30 [-202.78, -68.16] | Underpowered (N=0/20) | Underpowered (N=0/20) | 85.0% | 10 [10B/0A] / 12 [12B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['rolling']` |
| LightGBM Point + Rolling Conformal | 356.44 | 181.12 | -175.32 | -137.56 [-203.71, -75.02] | Underpowered (N=0/20) | Underpowered (N=0/20) | 85.0% | 10 [10B/0A] / 14 [14B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['lightgbm_point_rolling']` |
| Seasonal Naive + Rolling Conformal | 356.44 | 235.57 | -120.87 | -112.05 [-170.32, -56.87] | Underpowered (N=0/20) | Underpowered (N=0/20) | 85.0% | 10 [10B/0A] / 10 [10B/0A] | 1/20 | `matched_shortfall_pareto['0.0%']['seasonal_naive']` |
| Holt-Winters + Rolling Conformal | 356.44 | 165.42 | -191.02 | -140.92 [-209.16, -77.27] | Underpowered (N=0/20) | Underpowered (N=0/20) | 85.0% | 10 [10B/0A] / 15 [15B/0A] | 1/20 | `matched_shortfall_pareto['0.0%']['holt_winters']` |
| Quantile Linear + Rolling Conformal | 356.44 | 207.39 | -149.05 | -108.85 [-172.94, -49.72] | Underpowered (N=0/20) | Underpowered (N=0/20) | 80.0% | 10 [10B/0A] / 12 [12B/0A] | 6/20 | `matched_shortfall_pareto['0.0%']['quantile_linear']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | 356.44 | 180.85 | -175.59 | -150.61 [-211.92, -93.94] | Underpowered (N=0/20) | Underpowered (N=0/20) | 85.0% | 10 [10B/0A] / 8 [8B/0A] | 1/20 | `matched_shortfall_pareto['0.0%']['fixed_margin']` |
| No CP-SAT / FFD Consolidation Fallback | 356.44 | 179.59 | -176.85 | -124.42 [-193.00, -59.70] | Underpowered (N=0/20) | Underpowered (N=0/20) | 90.0% | 10 [10B/0A] / 12 [12B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['no_cpsat_ffd']` |
| vs_primary_aegis_rolling | 0.00 | 0.00 | +0.00 | +0.00 [0.00, 0.00] | Underpowered (N=0/20) | Underpowered (N=0/20) | 0.0% | 0 [0B/0A] / 0 [0B/0A] | 0/20 | `matched_shortfall_pareto['0.0%']['vs_primary_aegis_rolling']` |

### Target Shortfall: 0.1% (18.72 min / 18,720 min) — *Secondary Benchmark Target (Strict SLA)*
*Source key path: `matched_shortfall_pareto['0.1%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 159.71 | 125.73 | -33.98 | -66.77 [-132.38, -12.69] | Underpowered (N=0/20) | Underpowered (N=0/20) | 65.0% | 7 [6B/1A] / 4 [1B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['rolling']` |
| LightGBM Point + Rolling Conformal | 159.71 | 134.18 | -25.53 | -72.19 [-136.05, -16.13] | Underpowered (N=0/20) | Underpowered (N=0/20) | 65.0% | 7 [6B/1A] / 4 [1B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['lightgbm_point_rolling']` |
| Seasonal Naive + Rolling Conformal | 159.71 | 178.51 | +18.80 | -55.40 [-114.36, -6.15] | Underpowered (N=0/20) | Underpowered (N=0/20) | 60.0% | 7 [6B/1A] / 4 [1B/3A] | 1/20 | `matched_shortfall_pareto['0.1%']['seasonal_naive']` |
| Holt-Winters + Rolling Conformal | 159.71 | 126.21 | -33.50 | -70.14 [-137.28, -11.33] | Underpowered (N=0/20) | Underpowered (N=0/20) | 55.0% | 7 [6B/1A] / 3 [1B/2A] | 1/20 | `matched_shortfall_pareto['0.1%']['holt_winters']` |
| Quantile Linear + Rolling Conformal | 159.71 | 194.58 | +34.87 | -31.05 [-79.63, 8.97] | Underpowered (N=0/20) | Underpowered (N=0/20) | 40.0% | 7 [6B/1A] / 14 [1B/13A] | 6/20 | `matched_shortfall_pareto['0.1%']['quantile_linear']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | 159.71 | 136.77 | -22.94 | -85.12 [-151.22, -26.09] | Underpowered (N=0/20) | Underpowered (N=0/20) | 65.0% | 7 [6B/1A] / 7 [3B/4A] | 1/20 | `matched_shortfall_pareto['0.1%']['fixed_margin']` |
| No CP-SAT / FFD Consolidation Fallback | 159.71 | 154.10 | -5.61 | -54.42 [-117.81, -2.25] | Underpowered (N=0/20) | Underpowered (N=0/20) | 65.0% | 7 [6B/1A] / 4 [1B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['no_cpsat_ffd']` |
| vs_primary_aegis_rolling | 0.00 | 0.00 | +0.00 | +0.00 [0.00, 0.00] | Underpowered (N=0/20) | Underpowered (N=0/20) | 0.0% | 0 [0B/0A] / 0 [0B/0A] | 0/20 | `matched_shortfall_pareto['0.1%']['vs_primary_aegis_rolling']` |

### Target Shortfall: 1.0% (187.2 min / 18,720 min) — *Primary Benchmark Target (Lowest Extrapolation Rate per D-6)*
*Source key path: `matched_shortfall_pareto['1.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 121.79 | 86.92 | -34.87 | -75.13 [-132.46, -26.96] | Underpowered (N=0/20) | Underpowered (N=0/20) | 70.0% | 6 [4B/2A] / 6 [0B/6A] | 2/20 | `matched_shortfall_pareto['1.0%']['rolling']` |
| LightGBM Point + Rolling Conformal | 121.79 | 86.35 | -35.44 | -81.06 [-140.33, -29.87] | Underpowered (N=0/20) | Underpowered (N=0/20) | 70.0% | 6 [4B/2A] / 5 [0B/5A] | 2/20 | `matched_shortfall_pareto['1.0%']['lightgbm_point_rolling']` |
| Seasonal Naive + Rolling Conformal | 121.79 | 106.29 | -15.50 | -62.91 [-117.20, -16.41] | Underpowered (N=0/20) | Underpowered (N=0/20) | 50.0% | 6 [4B/2A] / 4 [0B/4A] | 1/20 | `matched_shortfall_pareto['1.0%']['seasonal_naive']` |
| Holt-Winters + Rolling Conformal | 121.79 | 91.30 | -30.49 | -78.62 [-141.85, -24.00] | Underpowered (N=0/20) | Underpowered (N=0/20) | 60.0% | 6 [4B/2A] / 2 [0B/2A] | 1/20 | `matched_shortfall_pareto['1.0%']['holt_winters']` |
| Quantile Linear + Rolling Conformal | 121.79 | 138.21 | +16.42 | -20.53 [-59.19, 14.20] | Underpowered (N=0/20) | Underpowered (N=0/20) | 30.0% | 6 [4B/2A] / 18 [0B/18A] | 6/20 | `matched_shortfall_pareto['1.0%']['quantile_linear']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | 121.79 | 98.91 | -22.88 | -77.91 [-139.17, -23.54] | Underpowered (N=0/20) | Underpowered (N=0/20) | 60.0% | 6 [4B/2A] / 13 [1B/12A] | 1/20 | `matched_shortfall_pareto['1.0%']['fixed_margin']` |
| No CP-SAT / FFD Consolidation Fallback | 121.79 | 96.26 | -25.53 | -65.43 [-119.69, -20.38] | Underpowered (N=0/20) | Underpowered (N=0/20) | 80.0% | 6 [4B/2A] / 6 [0B/6A] | 2/20 | `matched_shortfall_pareto['1.0%']['no_cpsat_ffd']` |
| vs_primary_aegis_rolling | 0.00 | 0.00 | +0.00 | +0.00 [0.00, 0.00] | Underpowered (N=0/20) | Underpowered (N=0/20) | 0.0% | 0 [0B/0A] / 0 [0B/0A] | 0/20 | `matched_shortfall_pareto['1.0%']['vs_primary_aegis_rolling']` |

### Target Shortfall: 5.0% (936.0 min / 18,720 min) — *Supplementary Target (High Shortfall Upper Bound)*
*Source key path: `matched_shortfall_pareto['5.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 90.88 | 79.75 | -11.13 | -57.18 [-105.34, -16.09] | Underpowered (N=0/20) | Underpowered (N=0/20) | 55.0% | 8 [1B/7A] / 11 [0B/11A] | 2/20 | `matched_shortfall_pareto['5.0%']['rolling']` |
| LightGBM Point + Rolling Conformal | 90.88 | 76.09 | -14.79 | -64.60 [-117.92, -18.88] | Underpowered (N=0/20) | Underpowered (N=0/20) | 60.0% | 8 [1B/7A] / 10 [0B/10A] | 2/20 | `matched_shortfall_pareto['5.0%']['lightgbm_point_rolling']` |
| Seasonal Naive + Rolling Conformal | 90.88 | 90.83 | -0.05 | -38.75 [-83.22, -1.36] | Underpowered (N=0/20) | Underpowered (N=0/20) | 45.0% | 8 [1B/7A] / 9 [0B/9A] | 1/20 | `matched_shortfall_pareto['5.0%']['seasonal_naive']` |
| Holt-Winters + Rolling Conformal | 90.88 | 79.37 | -11.51 | -61.43 [-116.71, -13.79] | Underpowered (N=0/20) | Underpowered (N=0/20) | 50.0% | 8 [1B/7A] / 2 [0B/2A] | 1/20 | `matched_shortfall_pareto['5.0%']['holt_winters']` |
| Quantile Linear + Rolling Conformal | 90.88 | 138.21 | +47.33 | +17.70 [-17.02, 47.62] | Underpowered (N=0/20) | Underpowered (N=0/20) | 15.0% | 8 [1B/7A] / 19 [0B/19A] | 6/20 | `matched_shortfall_pareto['5.0%']['quantile_linear']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | 90.88 | 83.53 | -7.35 | -48.60 [-99.71, -3.76] | Underpowered (N=0/20) | Underpowered (N=0/20) | 45.0% | 8 [1B/7A] / 17 [0B/17A] | 1/20 | `matched_shortfall_pareto['5.0%']['fixed_margin']` |
| No CP-SAT / FFD Consolidation Fallback | 90.88 | 82.47 | -8.41 | -48.55 [-95.32, -9.04] | Underpowered (N=0/20) | Underpowered (N=0/20) | 65.0% | 8 [1B/7A] / 11 [0B/11A] | 2/20 | `matched_shortfall_pareto['5.0%']['no_cpsat_ffd']` |
| vs_primary_aegis_rolling | 0.00 | 0.00 | +0.00 | +0.00 [0.00, 0.00] | Underpowered (N=0/20) | Underpowered (N=0/20) | 0.0% | 0 [0B/0A] / 0 [0B/0A] | 0/20 | `matched_shortfall_pareto['5.0%']['vs_primary_aegis_rolling']` |

## 3. Natural Operating Point Benchmark Comparisons (Fixed tau=0.90)
*Source key path: `natural_operating_points.<method>.<ca_setting>`*

> [!NOTE]
> Compares Aegis operating at fixed nominal quantile $\tau=0.90$ directly against Cluster Autoscaler at target utilizations $U=50\%$ and $U=60\%$.

| Conformal Method | CA Target | CA Median Energy (kWh) | Aegis Median Energy (kWh) | Mean DeltaE (kWh) [95% CI] | Wilcoxon p (Two-Sided / One-Sided Less) | Holm-Bonf Adj p | Rank-Biserial $r_{rb}$ | CA Med Shortfall (min) | Aegis Med Shortfall (min) | Dominance (Dom / Dmd / Trade / Ident) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10)** | U=50% | 127.35 | 76.20 | -29.51 [-44.89, -15.60] | 3.9500e-04 / 1.0000e+00 | 2.7640e-03 | -0.8381 | 74.0 | 65.5 | 0 / 0 / 0 / 0 | `natural_operating_points['rolling']['ca_u_50']` |
| **Per-App Rolling Conformal (W=1440, H=10)** | U=60% | 117.06 | 76.20 | -15.77 [-31.00, 0.28] | 7.2960e-03 / 1.0000e+00 | 3.1948e-02 | -0.6667 | 164.0 | 65.5 | 0 / 0 / 0 / 0 | `natural_operating_points['rolling']['ca_u_60']` |
| LightGBM Point + Rolling Conformal | U=50% | 127.35 | 67.26 | -44.40 [-67.92, -23.30] | 3.6000e-05 / 1.0000e+00 | 4.7100e-04 | -0.9333 | 74.0 | 141.5 | 0 / 0 / 0 / 0 | `natural_operating_points['lightgbm_point_rolling']['ca_u_50']` |
| LightGBM Point + Rolling Conformal | U=60% | 117.06 | 67.26 | -30.66 [-50.96, -13.75] | 2.6100e-04 / 1.0000e+00 | 2.3520e-03 | -0.8571 | 164.0 | 141.5 | 0 / 0 / 0 / 0 | `natural_operating_points['lightgbm_point_rolling']['ca_u_60']` |
| Seasonal Naive + Rolling Conformal | U=50% | 127.35 | 103.59 | -18.43 [-35.09, -4.18] | 4.8441e-02 / 1.0000e+00 | 9.6882e-02 | -0.5048 | 74.0 | 144.5 | 0 / 0 / 0 / 0 | `natural_operating_points['seasonal_naive']['ca_u_50']` |
| Seasonal Naive + Rolling Conformal | U=60% | 117.06 | 103.59 | -4.70 [-17.21, 6.56] | 1.0000e+00 / 1.0000e+00 | 1.0000e+00 | +0.0000 | 164.0 | 144.5 | 0 / 0 / 0 / 0 | `natural_operating_points['seasonal_naive']['ca_u_60']` |
| Holt-Winters + Rolling Conformal | U=50% | 127.35 | 76.40 | -48.06 [-75.50, -23.82] | 3.2200e-04 / 1.0000e+00 | 2.5790e-03 | -0.8476 | 74.0 | 286.5 | 0 / 0 / 0 / 0 | `natural_operating_points['holt_winters']['ca_u_50']` |
| Holt-Winters + Rolling Conformal | U=60% | 117.06 | 76.40 | -34.33 [-58.75, -13.57] | 1.9234e-02 / 1.0000e+00 | 5.7701e-02 | -0.5905 | 164.0 | 286.5 | 0 / 0 / 0 / 0 | `natural_operating_points['holt_winters']['ca_u_60']` |
| Quantile Linear + Rolling Conformal | U=50% | 127.35 | 133.64 | +17.34 [7.17, 30.13] | 1.3400e-04 / 1.0000e+00 | 1.4690e-03 | +0.8857 | 74.0 | 8.5 | 0 / 0 / 0 / 0 | `natural_operating_points['quantile_linear']['ca_u_50']` |
| Quantile Linear + Rolling Conformal | U=60% | 117.06 | 133.64 | +31.07 [15.27, 50.01] | 2.0000e-06 / 1.0000e+00 | 2.7000e-05 | +1.0000 | 164.0 | 8.5 | 0 / 0 / 0 / 0 | `natural_operating_points['quantile_linear']['ca_u_60']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | U=50% | 127.35 | 84.35 | -48.47 [-84.01, -21.95] | 3.6000e-05 / 1.0000e+00 | 4.7100e-04 | -0.9333 | 74.0 | 26.0 | 0 / 0 / 0 / 0 | `natural_operating_points['fixed_margin']['ca_u_50']` |
| Fixed Headroom Margin (Raw LGBM + Margin) | U=60% | 117.06 | 84.35 | -34.73 [-70.84, -11.42] | 7.0800e-04 / 1.0000e+00 | 4.2460e-03 | -0.8095 | 164.0 | 26.0 | 0 / 0 / 0 / 0 | `natural_operating_points['fixed_margin']['ca_u_60']` |
| No CP-SAT / FFD Consolidation Fallback | U=50% | 127.35 | 89.15 | -19.76 [-32.87, -7.91] | 2.1000e-04 / 1.0000e+00 | 2.0980e-03 | -0.8667 | 74.0 | 65.5 | 0 / 0 / 0 / 0 | `natural_operating_points['no_cpsat_ffd']['ca_u_50']` |
| No CP-SAT / FFD Consolidation Fallback | U=60% | 117.06 | 89.15 | -6.03 [-20.35, 9.96] | 6.3900e-03 / 1.0000e+00 | 3.1948e-02 | -0.6762 | 164.0 | 65.5 | 0 / 0 / 0 / 0 | `natural_operating_points['no_cpsat_ffd']['ca_u_60']` |

[^1]: **Statistical Footnote**: 'Diff of Medians' is the difference between marginal distribution medians ($E_{\text{Aegis}}^{\text{med}} - E_{\text{CA}}^{\text{med}}$). 'All-App Mean DeltaE' is the sample average of paired differences $\frac{1}{N}\sum (E_{\text{Aegis}, i} - E_{\text{CA}, i})$. Because workload demand and energy distributions exhibit skew across heterogeneous applications, the expectation of paired differences differs from the difference of marginal medians.
