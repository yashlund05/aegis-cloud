# Aegis Clean Headline Benchmark Evaluation Report (v4)

**Source JSON**: `eval/headline_results_v5.json`  
**Git Commit**: `c5f99c22a22d925fff49e0444a1a7e351b701223`  
**Working Tree Dirty Flag**: `False`  
**Config SHA-256**: `af9326cf96472bfec6cf7b33e8f0c18cd7303ddd63fc95d71f1909e19b0da40a`  
**Timestamp UTC**: `2026-10-04T08:59:36.857514+00:00`  
**Primary Aegis Arm**: `rolling` (per Decision D-7)  

## 1. Conformal Coverage Summary (20 Validation Apps)
*Source key path: `coverage_summary.median_iqr.<method>`*

| Method | Median Coverage (%) | IQR (%) | Role | Key Path |
| :--- | :---: | :---: | :---: | :--- |
| Raw Forecast (No Conformal) | 86.77% | 12.23% | Baseline | `coverage_summary.median_iqr.raw` |
| Static Conformal Offset | 99.99% | 0.33% | Ablation | `coverage_summary.median_iqr.static` |
| Scale-Aware Conformal (Normalized Residuals) | 97.60% | 5.08% | Ablation / Variant | `coverage_summary.median_iqr.scale_aware` |
| Per-App Rolling Conformal (W=1440, H=10) | 90.06% | 0.72% | **Primary Arm (D-7)** | `coverage_summary.median_iqr.rolling` |
| Adaptive Conformal (ACI gamma=0.005) | 89.94% | 0.80% | Ablation / Variant | `coverage_summary.median_iqr.aci_005` |
| Adaptive Conformal (ACI gamma=0.020) | 89.98% | 0.49% | Ablation / Variant | `coverage_summary.median_iqr.aci_020` |

## 2. Matched-Shortfall Pareto Frontier Evaluation
*Source key path: `matched_shortfall_pareto.<target_shortfall>.<method>`*

> [!NOTE]
> **Statistical Metric Disambiguation**:[^1]
> - **Diff of Medians (kWh)**: Marginal median difference across apps ($E_{\text{Aegis}}^{\text{med}} - E_{\text{CA}}^{\text{med}}$).
> - **All-App Mean DeltaE (kWh)**: Sample mean of individual per-app paired differences ($\frac{1}{N}\sum_{i=1}^N (E_{\text{Aegis}, i} - E_{\text{CA}, i})$), with 95% bootstrap percentile CI.
> - **Sign Convention**: $\Delta E = E_{\text{Aegis}} - E_{\text{CA}}$ (negative = Aegis cheaper).

### Target Shortfall: 0.0% (0.0 min / 18,720 min) ΓÇö *Supplementary Target (Zero Shortfall Lower Bound)*
*Source key path: `matched_shortfall_pareto['0.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 356.44 | 159.30 | -197.14 | -133.30 [-202.78, -68.16] | Underpowered (N=2/20) | Underpowered (N=1/20) | 85.0% | 10 [10B/0A] / 12 [12B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['rolling']` |
| Scale-Aware Conformal (Normalized Residuals) | 356.44 | 198.96 | -157.48 | -114.42 [-175.97, -60.45] | -118.10 [-180.98, -68.42] (N=10) | -121.07 [-191.16, -66.09] (N=9) | 85.0% | 10 [10B/0A] / 7 [7B/0A] | 1/20 | `matched_shortfall_pareto['0.0%']['scale_aware']` |
| Adaptive Conformal (ACI gamma=0.005) | 356.44 | 108.85 | -247.59 | -188.76 [-254.91, -127.93] | Underpowered (N=2/20) | Underpowered (N=1/20) | 95.0% | 10 [10B/0A] / 18 [18B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['aci_005']` |
| Adaptive Conformal (ACI gamma=0.020) | 356.44 | 121.23 | -235.21 | -171.46 [-235.19, -112.15] | Underpowered (N=2/20) | Underpowered (N=1/20) | 95.0% | 10 [10B/0A] / 16 [16B/0A] | 2/20 | `matched_shortfall_pareto['0.0%']['aci_020']` |
| Static Conformal Offset | 356.44 | 220.33 | -136.11 | -84.38 [-158.62, -13.93] | -104.13 [-172.79, -39.00] (N=10) | -105.54 [-184.13, -32.77] (N=9) | 65.0% | 10 [10B/0A] / 0 [0B/0A] | 1/20 | `matched_shortfall_pareto['0.0%']['static']` |

**Tertile Stratification for Primary Arm (Rolling Conformal) at 0.0% Shortfall**:
*Source key path: `matched_shortfall_pareto['0.0%']['rolling']['tertiles']`*

| Tertile | N Apps | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | Mean Paired DeltaE (kWh) [95% CI] | Cheaper Fraction (%) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| low_load | 7 | 132.76 | 58.42 | -74.34 | -76.67 [-98.15, -59.64] | 100.0% | `matched_shortfall_pareto['0.0%']['rolling']['tertiles']['low_load']` |
| mid_load | 7 | 412.27 | 162.70 | -249.57 | -196.87 [-331.52, -60.07] | 85.7% | `matched_shortfall_pareto['0.0%']['rolling']['tertiles']['mid_load']` |
| high_load | 6 | 608.55 | 450.75 | -157.80 | -125.20 [-261.09, 1.32] | 66.7% | `matched_shortfall_pareto['0.0%']['rolling']['tertiles']['high_load']` |

**Losing Apps for Rolling Conformal at 0.0% Shortfall (3/20 apps where $\Delta E > 0$)**:
- App `5d312706e735a36c...`: $\Delta E = +106.275\text{ kWh}$, Mean Cores = `0.894`, Peak = `30.96` (Normal Coverage)
- App `fe5c01bb7981a5dc...`: $\Delta E = +30.834\text{ kWh}$, Mean Cores = `7.212`, Peak = `53.50` (ΓÜá∩╕Å Poor Coverage)
- App `19cd74b6f9cd796c...`: $\Delta E = +75.125\text{ kWh}$, Mean Cores = `3.208`, Peak = `37.45` (Normal Coverage)

### Target Shortfall: 0.1% (18.72 min / 18,720 min) ΓÇö *Secondary Benchmark Target (Strict SLA)*
*Source key path: `matched_shortfall_pareto['0.1%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 159.71 | 125.73 | -33.98 | -66.77 [-132.38, -12.69] | -93.17 [-203.56, -9.46] (N=10) | -93.17 [-203.56, -9.46] (N=10) | 65.0% | 7 [6B/1A] / 4 [1B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['rolling']` |
| Scale-Aware Conformal (Normalized Residuals) | 159.71 | 139.89 | -19.82 | -55.95 [-119.53, -3.31] | -71.19 [-162.94, -0.72] (N=12) | -71.19 [-162.94, -0.72] (N=12) | 60.0% | 7 [6B/1A] / 3 [2B/1A] | 1/20 | `matched_shortfall_pareto['0.1%']['scale_aware']` |
| Adaptive Conformal (ACI gamma=0.005) | 159.71 | 97.45 | -62.26 | -96.97 [-158.28, -44.73] | Underpowered (N=6/20) | Underpowered (N=6/20) | 75.0% | 7 [6B/1A] / 13 [10B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['aci_005']` |
| Adaptive Conformal (ACI gamma=0.020) | 159.71 | 102.06 | -57.65 | -85.18 [-146.66, -33.88] | -105.02 [-220.95, -13.93] (N=9) | -105.02 [-220.95, -13.93] (N=9) | 70.0% | 7 [6B/1A] / 8 [5B/3A] | 2/20 | `matched_shortfall_pareto['0.1%']['aci_020']` |
| Static Conformal Offset | 159.71 | 182.74 | +23.03 | -7.03 [-79.73, 73.01] | -6.85 [-82.69, 70.92] (N=12) | -6.85 [-82.69, 70.92] (N=12) | 60.0% | 7 [6B/1A] / 1 [0B/1A] | 1/20 | `matched_shortfall_pareto['0.1%']['static']` |

**Tertile Stratification for Primary Arm (Rolling Conformal) at 0.1% Shortfall**:
*Source key path: `matched_shortfall_pareto['0.1%']['rolling']['tertiles']`*

| Tertile | N Apps | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | Mean Paired DeltaE (kWh) [95% CI] | Cheaper Fraction (%) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| low_load | 7 | 57.86 | 58.42 | +0.56 | -5.20 [-20.30, 6.78] | 42.9% | `matched_shortfall_pareto['0.1%']['rolling']['tertiles']['low_load']` |
| mid_load | 7 | 227.53 | 130.59 | -96.94 | -120.07 [-259.96, 3.80] | 85.7% | `matched_shortfall_pareto['0.1%']['rolling']['tertiles']['mid_load']` |
| high_load | 6 | 478.93 | 363.50 | -115.44 | -76.41 [-187.29, 0.76] | 66.7% | `matched_shortfall_pareto['0.1%']['rolling']['tertiles']['high_load']` |

**Losing Apps for Rolling Conformal at 0.1% Shortfall (7/20 apps where $\Delta E > 0$)**:
- App `a788ca3dd335b576...`: $\Delta E = +0.079\text{ kWh}$, Mean Cores = `0.591`, Peak = `2.57` (Normal Coverage)
- App `c89aaedc8b6ecd5a...`: $\Delta E = +19.988\text{ kWh}$, Mean Cores = `0.856`, Peak = `2.88` (Normal Coverage)
- App `9c5f550769c9c25b...`: $\Delta E = +0.646\text{ kWh}$, Mean Cores = `0.689`, Peak = `1.63` (Normal Coverage)
- App `ea400a14c46ff8b9...`: $\Delta E = +14.785\text{ kWh}$, Mean Cores = `5.618`, Peak = `27.48` (Normal Coverage)
- App `d514ebc393839b56...`: $\Delta E = +88.493\text{ kWh}$, Mean Cores = `1.350`, Peak = `9.65` (Normal Coverage)
- App `c48859281eb8efa5...`: $\Delta E = +1.062\text{ kWh}$, Mean Cores = `0.810`, Peak = `1.07` (Normal Coverage)
- App `fe5c01bb7981a5dc...`: $\Delta E = +11.422\text{ kWh}$, Mean Cores = `7.212`, Peak = `53.50` (ΓÜá∩╕Å Poor Coverage)

### Target Shortfall: 1.0% (187.2 min / 18,720 min) ΓÇö *Primary Benchmark Target (Lowest Extrapolation Rate per D-6)*
*Source key path: `matched_shortfall_pareto['1.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 121.79 | 86.92 | -34.87 | -75.13 [-132.46, -26.96] | -67.05 [-156.86, -7.56] (N=10) | -67.05 [-156.86, -7.56] (N=10) | 70.0% | 6 [4B/2A] / 6 [0B/6A] | 2/20 | `matched_shortfall_pareto['1.0%']['rolling']` |
| Scale-Aware Conformal (Normalized Residuals) | 121.79 | 96.23 | -25.56 | -64.53 [-124.08, -14.69] | -57.98 [-133.58, -9.06] (N=12) | -57.98 [-133.58, -9.06] (N=12) | 70.0% | 6 [4B/2A] / 3 [0B/3A] | 1/20 | `matched_shortfall_pareto['1.0%']['scale_aware']` |
| Adaptive Conformal (ACI gamma=0.005) | 121.79 | 81.38 | -40.41 | -79.10 [-137.39, -29.48] | -67.35 [-156.97, -7.86] (N=10) | -67.35 [-156.97, -7.86] (N=10) | 70.0% | 6 [4B/2A] / 7 [1B/6A] | 2/20 | `matched_shortfall_pareto['1.0%']['aci_005']` |
| Adaptive Conformal (ACI gamma=0.020) | 121.79 | 81.97 | -39.82 | -77.74 [-134.96, -29.43] | -61.96 [-143.94, -7.75] (N=11) | -61.96 [-143.94, -7.75] (N=11) | 70.0% | 6 [4B/2A] / 5 [0B/5A] | 2/20 | `matched_shortfall_pareto['1.0%']['aci_020']` |
| Static Conformal Offset | 121.79 | 94.51 | -27.28 | -54.90 [-129.06, 26.68] | -70.06 [-159.65, -10.00] (N=10) | -70.06 [-159.65, -10.00] (N=10) | 70.0% | 6 [4B/2A] / 5 [0B/5A] | 1/20 | `matched_shortfall_pareto['1.0%']['static']` |

**Tertile Stratification for Primary Arm (Rolling Conformal) at 1.0% Shortfall**:
*Source key path: `matched_shortfall_pareto['1.0%']['rolling']['tertiles']`*

| Tertile | N Apps | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | Mean Paired DeltaE (kWh) [95% CI] | Cheaper Fraction (%) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| low_load | 7 | 57.78 | 58.40 | +0.62 | +3.15 [-0.04, 8.91] | 28.6% | `matched_shortfall_pareto['1.0%']['rolling']['tertiles']['low_load']` |
| mid_load | 7 | 163.37 | 94.87 | -68.50 | -150.66 [-271.13, -40.24] | 100.0% | `matched_shortfall_pareto['1.0%']['rolling']['tertiles']['mid_load']` |
| high_load | 6 | 371.43 | 240.30 | -131.13 | -78.34 [-127.02, -25.69] | 83.3% | `matched_shortfall_pareto['1.0%']['rolling']['tertiles']['high_load']` |

**Losing Apps for Rolling Conformal at 1.0% Shortfall (6/20 apps where $\Delta E > 0$)**:
- App `a788ca3dd335b576...`: $\Delta E = +0.771\text{ kWh}$, Mean Cores = `0.591`, Peak = `2.57` (Normal Coverage)
- App `c89aaedc8b6ecd5a...`: $\Delta E = +19.988\text{ kWh}$, Mean Cores = `0.856`, Peak = `2.88` (Normal Coverage)
- App `9c5f550769c9c25b...`: $\Delta E = +0.756\text{ kWh}$, Mean Cores = `0.689`, Peak = `1.63` (Normal Coverage)
- App `ea400a14c46ff8b9...`: $\Delta E = +7.580\text{ kWh}$, Mean Cores = `5.618`, Peak = `27.48` (Normal Coverage)
- App `c48859281eb8efa5...`: $\Delta E = +1.062\text{ kWh}$, Mean Cores = `0.810`, Peak = `1.07` (Normal Coverage)
- App `cb34fd874e255dde...`: $\Delta E = +0.593\text{ kWh}$, Mean Cores = `0.547`, Peak = `2.03` (Normal Coverage)

### Target Shortfall: 5.0% (936.0 min / 18,720 min) ΓÇö *Supplementary Target (High Shortfall Upper Bound)*
*Source key path: `matched_shortfall_pareto['5.0%']`*

| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10) (Primary)** | 90.88 | 79.75 | -11.13 | -57.18 [-105.34, -16.09] | -118.30 [-208.89, -39.87] (N=8) | -118.30 [-208.89, -39.87] (N=8) | 55.0% | 8 [1B/7A] / 11 [0B/11A] | 2/20 | `matched_shortfall_pareto['5.0%']['rolling']` |
| Scale-Aware Conformal (Normalized Residuals) | 90.88 | 78.73 | -12.15 | -52.47 [-102.83, -8.78] | -96.76 [-176.90, -29.41] (N=10) | -96.76 [-176.90, -29.41] (N=10) | 55.0% | 8 [1B/7A] / 8 [0B/8A] | 1/20 | `matched_shortfall_pareto['5.0%']['scale_aware']` |
| Adaptive Conformal (ACI gamma=0.005) | 90.88 | 74.20 | -16.68 | -58.64 [-106.76, -17.87] | -120.36 [-210.28, -42.06] (N=8) | -120.36 [-210.28, -42.06] (N=8) | 55.0% | 8 [1B/7A] / 11 [0B/11A] | 2/20 | `matched_shortfall_pareto['5.0%']['aci_005']` |
| Adaptive Conformal (ACI gamma=0.020) | 90.88 | 74.45 | -16.43 | -58.18 [-106.25, -17.18] | -118.15 [-208.22, -39.67] (N=8) | -118.15 [-208.22, -39.67] (N=8) | 50.0% | 8 [1B/7A] / 11 [0B/11A] | 2/20 | `matched_shortfall_pareto['5.0%']['aci_020']` |
| Static Conformal Offset | 90.88 | 82.23 | -8.65 | -33.25 [-98.80, 41.97] | -108.79 [-193.76, -37.63] (N=9) | -108.79 [-193.76, -37.63] (N=9) | 60.0% | 8 [1B/7A] / 9 [0B/9A] | 1/20 | `matched_shortfall_pareto['5.0%']['static']` |

**Tertile Stratification for Primary Arm (Rolling Conformal) at 5.0% Shortfall**:
*Source key path: `matched_shortfall_pareto['5.0%']['rolling']['tertiles']`*

| Tertile | N Apps | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | Mean Paired DeltaE (kWh) [95% CI] | Cheaper Fraction (%) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| low_load | 7 | 57.38 | 58.36 | +0.98 | +3.65 [0.80, 9.15] | 0.0% | `matched_shortfall_pareto['5.0%']['rolling']['tertiles']['low_load']` |
| mid_load | 7 | 112.90 | 80.54 | -32.36 | -106.56 [-211.66, -16.03] | 85.7% | `matched_shortfall_pareto['5.0%']['rolling']['tertiles']['mid_load']` |
| high_load | 6 | 202.41 | 180.74 | -21.67 | -70.55 [-140.63, -10.59] | 83.3% | `matched_shortfall_pareto['5.0%']['rolling']['tertiles']['high_load']` |

**Losing Apps for Rolling Conformal at 5.0% Shortfall (9/20 apps where $\Delta E > 0$)**:
- App `a788ca3dd335b576...`: $\Delta E = +0.828\text{ kWh}$, Mean Cores = `0.591`, Peak = `2.57` (Normal Coverage)
- App `c89aaedc8b6ecd5a...`: $\Delta E = +19.988\text{ kWh}$, Mean Cores = `0.856`, Peak = `2.88` (Normal Coverage)
- App `9c5f550769c9c25b...`: $\Delta E = +0.756\text{ kWh}$, Mean Cores = `0.689`, Peak = `1.63` (Normal Coverage)
- App `2728cf1bdcbb17a3...`: $\Delta E = +4.203\text{ kWh}$, Mean Cores = `5.614`, Peak = `32.50` (Normal Coverage)
- App `c48859281eb8efa5...`: $\Delta E = +1.062\text{ kWh}$, Mean Cores = `0.810`, Peak = `1.07` (Normal Coverage)
- App `11a2f12e57bfa87a...`: $\Delta E = +0.981\text{ kWh}$, Mean Cores = `0.726`, Peak = `2.24` (Normal Coverage)
- App `cb34fd874e255dde...`: $\Delta E = +0.597\text{ kWh}$, Mean Cores = `0.547`, Peak = `2.03` (Normal Coverage)
- App `714e8fb561f4512b...`: $\Delta E = +0.182\text{ kWh}$, Mean Cores = `1.032`, Peak = `5.50` (Normal Coverage)
- App `58361d84c6f1d50c...`: $\Delta E = +1.356\text{ kWh}$, Mean Cores = `0.674`, Peak = `10.06` (Normal Coverage)

## 3. Natural Operating Point Benchmark Comparisons (Fixed tau=0.90)
*Source key path: `natural_operating_points.<method>.<ca_setting>`*

> [!NOTE]
> Compares Aegis operating at fixed nominal quantile $\tau=0.90$ directly against Cluster Autoscaler at target utilizations $U=50\%$ and $U=60\%$.

| Conformal Method | CA Target | CA Median Energy (kWh) | Aegis Median Energy (kWh) | Mean DeltaE (kWh) [95% CI] | Wilcoxon p (Two-Sided / One-Sided Less) | Holm-Bonf Adj p | Rank-Biserial $r_{rb}$ | CA Med Shortfall (min) | Aegis Med Shortfall (min) | Dominance (Dom / Dmd / Trade / Ident) | Key Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Per-App Rolling Conformal (W=1440, H=10)** | U=50% | 127.35 | 76.20 | -29.51 [-44.89, -15.60] | 3.9500e-04 / 1.9700e-04 | 3.5530e-03 | -0.8381 | 74.0 | 65.5 | 8 / 1 / 11 / 0 | `natural_operating_points['rolling']['ca_u_50']` |
| **Per-App Rolling Conformal (W=1440, H=10)** | U=60% | 117.06 | 76.20 | -15.77 [-31.00, 0.28] | 7.2960e-03 / 3.6480e-03 | 3.1948e-02 | -0.6667 | 164.0 | 65.5 | 11 / 3 / 6 / 0 | `natural_operating_points['rolling']['ca_u_60']` |
| Scale-Aware Conformal (Normalized Residuals) | U=50% | 127.35 | 101.17 | -19.42 [-41.00, -4.29] | 4.4054e-02 / 2.2027e-02 | 8.8108e-02 | -0.5143 | 74.0 | 20.0 | 11 / 2 / 7 / 0 | `natural_operating_points['scale_aware']['ca_u_50']` |
| Scale-Aware Conformal (Normalized Residuals) | U=60% | 117.06 | 101.17 | -5.69 [-30.73, 13.39] | 3.1179e-01 / 8.5287e-01 | 3.1179e-01 | +0.2667 | 164.0 | 20.0 | 5 / 3 / 12 / 0 | `natural_operating_points['scale_aware']['ca_u_60']` |
| Adaptive Conformal (ACI gamma=0.005) | U=50% | 127.35 | 77.03 | -33.69 [-51.30, -17.46] | 3.2200e-04 / 1.6100e-04 | 3.2230e-03 | -0.8476 | 74.0 | 93.0 | 8 / 1 / 11 / 0 | `natural_operating_points['aci_005']['ca_u_50']` |
| Adaptive Conformal (ACI gamma=0.005) | U=60% | 117.06 | 77.03 | -19.95 [-39.11, -1.56] | 6.3900e-03 / 3.1950e-03 | 3.1948e-02 | -0.6762 | 164.0 | 93.0 | 11 / 3 / 6 / 0 | `natural_operating_points['aci_005']['ca_u_60']` |
| Adaptive Conformal (ACI gamma=0.020) | U=50% | 127.35 | 77.70 | -29.89 [-45.30, -15.71] | 3.9500e-04 / 1.9700e-04 | 3.5530e-03 | -0.8381 | 74.0 | 68.0 | 8 / 1 / 11 / 0 | `natural_operating_points['aci_020']['ca_u_50']` |
| Adaptive Conformal (ACI gamma=0.020) | U=60% | 117.06 | 77.70 | -16.16 [-31.85, 0.42] | 7.2960e-03 / 3.6480e-03 | 3.1948e-02 | -0.6667 | 164.0 | 68.0 | 10 / 3 / 7 / 0 | `natural_operating_points['aci_020']['ca_u_60']` |
| Static Conformal Offset | U=50% | 127.35 | 203.57 | +64.61 [30.68, 90.16] | 8.5100e-04 / 9.9965e-01 | 5.1040e-03 | +0.8000 | 74.0 | 0.0 | 2 / 1 / 17 / 0 | `natural_operating_points['static']['ca_u_50']` |
| Static Conformal Offset | U=60% | 117.06 | 203.57 | +78.34 [43.90, 100.56] | 7.0800e-04 / 9.9971e-01 | 4.9530e-03 | +0.8095 | 164.0 | 0.0 | 1 / 0 / 19 / 0 | `natural_operating_points['static']['ca_u_60']` |

## 4. Equal-Headroom Reactive Baseline & Audit Control Comparison
*Source key path: `equal_headroom_control`*

- **Calibrated Static Headroom Margin**: `+8.6468 cores` (`equal_headroom_control.calibrated_static_headroom_cores`)
- **Control Arm (a) ΓÇö Reactive + Static Headroom**: Energy Median = `238.55` kWh (IQR 85.74), Shortfall Median = `0.0` min (IQR 2.5)
- **Control Arm (b) ΓÇö CA (U=70%, HPA Guards)**: Energy Median = `91.53` kWh (IQR 115.63), Shortfall Median = `300.0` min (IQR 1216.5)
- **Aegis Conformal Baseline (tau=0.90)**: Energy Median = `203.57` kWh (IQR 109.9), Shortfall Median = `0.0` min (IQR 6.25)

[^1]: **Statistical Footnote**: 'Diff of Medians' is the difference between marginal distribution medians ($E_{\text{Aegis}}^{\text{med}} - E_{\text{CA}}^{\text{med}}$). 'All-App Mean DeltaE' is the sample average of paired differences $\frac{1}{N}\sum (E_{\text{Aegis}, i} - E_{\text{CA}, i})$. Because workload demand and energy distributions exhibit skew across heterogeneous applications, the expectation of paired differences differs from the difference of marginal medians.

