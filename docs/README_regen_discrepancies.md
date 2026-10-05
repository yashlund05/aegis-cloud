# README Regeneration — Discrepancy Report

**Task**: regenerate `README.md` so that every number is derived by script
(`eval/generate_readme.py`) from committed result files, with no hand-typed values.
**Date of audit**: 2026-10-05. **Supersession basis**: Decision D-10
(`eval/headline_results_v5.json` is the final headline file; v1/v3/v4 are superseded),
Decision D-8 (retraction of untrusted historical numbers).

Items a–g were explicitly requested by the regeneration task; h–k are additional
findings made during the audit. Machine-checkable invariants (repro equality,
cross-file rolling-arm equality, tertile counts, floor/capacity derivations,
CI-vs-p claim consistency) are re-verified on every `make readme` run and printed
by `eval/generate_readme.py`.

---

## a) CP-SAT objective: what is actually implemented

- `docs/IMPLEMENTATION_STATUS.md` Phase 5 claims the solver minimizes "cluster energy **and scaling churn**".
- The IEEE paper (per the task brief) says idle power only.
- **Code** (`services/decision-engine/solver.py`): the objective is built at
  `model.Minimize(sum(objective_terms))` from exactly two term families —
  `active_vars[n] * p_idle * weight_energy` (active-node idle power) and
  `placement_vars[p][n] * cpu_request * weight_energy` (pod CPU-allocation energy).
  A `weight_churn` constructor parameter exists (default `0.5`) but is **never used**
  in the objective.
- **Verdict**: the implemented objective is *idle power of active nodes + pod CPU
  allocation energy*. Neither document describes it exactly: the scaling-churn claim
  in IMPLEMENTATION_STATUS is wrong, and "idle power only" omits the CPU-allocation term.

## b) What the `no_cpsat_ffd` arm actually does

- `docs/DECISIONS.md` D-11 says the arm replaces the joint optimizer with "the
  First-Fit-Decreasing (FFD) consolidation fallback (`has_placement_opt=False`,
  uniform/unoptimized spreading)" — self-contradictory (FFD consolidation vs. uniform spreading).
- **Code** (`ml/evaluation/ablation.py`): `has_placement_opt` is True only for
  `full_aegis` / `full_aegis_conformal` / `forecast_placement` / `oracle`. The
  `no_cpsat_ffd` study arm routes as `forecast_plus_power_no_placement` →
  `_pack_pods(..., opt=False)`, documented as *"kube-scheduler style even spreading"*.
  FFD bin-packing is the `opt=True` path.
- **Verdict**: the arm is *forecast + node power with even-spreading placement*; its
  historical label "No CP-SAT / FFD Consolidation Fallback" is a misnomer. README §7
  calls it "No CP-SAT (spreading placement)".

## c) Tertile counts

- Old README §E: 7 / 6 / 7 (low / mid / high) with fixed mean-core cut-offs (≤0.83 c, 0.83–1.28 c, >1.28 c).
- `eval/headline_results_v5.json` → `app_partition.tertiles` and
  `eval/baselines_results_v1.json` → same structure: **7 / 7 / 6**, assigned by rank
  (`sorted test apps by mean cores` → `[:7] / [7:14] / [14:]`, `eval/headline_study_v4.py:394`),
  i.e. no fixed core thresholds.
- **Resolution**: README §9 uses 7 / 7 / 6 from the JSON. The generator asserts the
  partition counts match the `n_apps` fields of every matched-target tertile table.

## d) Old README numbers vs. the v5 JSON (old → new)

Headline Pareto table (CA median / Aegis median / mean paired ΔE / % cheaper):

| Target | Method | CA median | Aegis median | Mean ΔE | % cheaper |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 0.0% | Scale-Aware | 183.1 → **356.44** | 130.5 → **198.96** | −16.74 → **−114.42** | 70.0 → **85.0** |
| 0.0% | Rolling | 183.1 → **356.44** | 114.1 → **159.30** | −38.83 → **−133.30** | 85.0 → **85.0** |
| 0.0% | ACI γ=0.005 | 183.1 → **356.44** | 103.6 → **108.85** | −56.32 → **−188.76** | 90.0 → **95.0** |
| 0.1% | Scale-Aware | 154.8 → **159.71** | 123.0 → **139.89** | −31.18 → **−55.95** | 70.0 → **60.0** |
| 0.1% | Rolling | 154.8 → **159.71** | 99.2 → **125.73** | −35.73 → **−66.77** | 70.0 → **65.0** |
| 0.1% | ACI γ=0.005 | 154.8 → **159.71** | 95.9 → **97.45** | −48.60 → **−96.97** | 75.0 → **75.0** |
| 1.0% | Scale-Aware | 122.2 → **121.79** | 92.4 → **96.23** | −38.22 → **−64.53** | 70.0 → **70.0** |
| 1.0% | Rolling | 122.2 → **121.79** | 84.2 → **86.92** | **−39.30 → −75.13** | 70.0 → **70.0** |
| 1.0% | ACI γ=0.005 | 122.2 → **121.79** | 82.9 → **81.38** | −44.01 → **−79.10** | 70.0 → **70.0** |

- The 0.0% CA median changed most (183.1 → 356.44 kWh) because the v1 grid
  (U ∈ 30–80%) could not reach zero shortfall without frontier clamping; the widened
  grid (D-5, U down to 0.10) exposes the true conservative anchor.
- The −39.30 → **−75.13** kWh rolling ΔE at 1.0% is the headline correction mandated
  by D-8/D-10.
- Coverage medians (old → v5 at 1 dp): raw 86.8 → 86.8; static 100.0 → 100.0 (v5 raw value 99.99);
  scale-aware 97.6 → 97.6; **rolling 90.0 → 90.1** (v5 raw value 90.06); ACI 0.005: 89.9 → 89.9;
  ACI 0.020: 90.0 → 90.0.
- "(720 simulation runs)" → widened grids per D-5: 18 CA utilizations × 13 τ values ×
  20 apps = **4,680 frontier points per target**.
- Tertile narrative (98.6% churn reduction, "12 vs 848 actions", "1,060 → 0 min",
  "307 vs 2,759", "994 → 7 min", "−1,328.86 min, p = 0.0156", "62.5%"): these came from
  the superseded v1 study and have **no counterpart fields in v5** (v5 tertile tables are
  energy-only); replaced by v5 tertile energies at the matched 1.0% target plus natural-
  operating-point shortfall medians (item i).
- Headroom control arm: "+35 kWh more energy, 3.2× churn" → script-derived from v5
  `equal_headroom_control`: 238.55 − 203.57 = **+34.98 kWh**; 274.5 vs 85.0 median
  scaling events = **3.23×** (same conclusion, exact provenance).
- "84 tests passing" → live-run count: **109 passed** at regen time (the README build
  re-runs pytest and go test each time; the count self-updates).
- "N = 20 Apps, 14 Days" (ambiguous) → 14-day trace with a scored window of
  **18,720 minutes (13.0 days)**; the first day is feature warm-up.
- The 20 "Test" apps (user-reported staleness): every evaluation-app reference in the
  README now says **validation** apps; the W4 expanded-test partition is described as
  reserved and untouched.

## e) Google / Alibaba / Azure-2017 trace references

`datasets/README.md` §3 marks Google Cluster Trace 2019, Alibaba 2018, and Azure Public
Dataset 2017 as **[Not Implemented]**. No claim that these traces were used exists in the
current README, TRD.md, PRD.md, or docs/IMPLEMENTATION_STATUS.md (grep-checked). Any
future mention must preserve the not-implemented status.

## f) Claims in IMPLEMENTATION_STATUS.md / TRD.md requiring caveats

1. **"20 Test apps"** (Phase 13) — renamed to *validation* apps under the Split Protocol
   (Entry 1); README §12 note added.
2. **"exact 90.0% median coverage on unseen test apps"** (Phase 15) — the "unseen" claim
   is inconsistent with the Split Protocol (these apps informed design decisions); the
   value is restated from the v5 coverage table (90.06% median → 90.1% at 1 dp).
3. **"50.59% energy reduction"** (Phase 9, 24-hour HPA ablation): the committed
   `eval/ablation_results.json` contains only the `full_aegis_conformal` arm and an
   **empty `improvements` block** — there is no `stock_hpa` arm, so the 50.59% figure
   (and the companion "100% SLO breach reduction") cannot be recomputed from committed
   results. The requested caveat "HPA keeps 20 nodes active" therefore cannot be
   verified either way from committed data; the README Phase 9 row states the
   non-reproducibility instead of repeating the figure.
4. **Kepler**: TRD.md's architecture sections include Kepler as a runtime monitoring
   component (design intent) and its energy-model section correctly notes the
   `kepler.py` stub; IMPLEMENTATION_STATUS Phase 2 carries the same transparency note.
   No "validated against Kepler" claim survives in the docs (removed by W0 / Entry 1).
5. The synthetic multi-pattern results (`eval/HEADLINE_PROVENANCE.txt`) show Aegis
   consuming **more** energy than CA on single-pattern synthetic traces (diurnal +12.02,
   steady +7.15, bursty +6.79, structured_burst +8.54, flash_crowd +6.96 kWh paired
   ΔE) with CA keeping shortfall near zero on steady/diurnal patterns. The old README
   did not mention this context; it remains available in the provenance file and is
   recorded here so the Azure-trace results are not over-generalized.

## g) Phase numbering

`docs/IMPLEMENTATION_STATUS.md` heading says "Complete System Implementation
(**Phases 1 through 10**)" but the document lists **Phases 1–16**. README §12 notes
this and lists all 16 phases plus the W-task records.

## h) Node power profile (found during audit)

`docs/threats_to_validity.md` §3, Decision D-11, and the old README state a nominal
uniform profile "P_idle = 100 W, P_max = 300 W". The committed simulator
(`ml/evaluation/ablation.py::get_default_nodes(scale="large")`, used by both the v5
headline and W3 baselines studies) actually builds **heterogeneous** nodes:
p_idle = 85 + 5·(i mod 5) → **85–105 W**; p_max = 240 + 10·(i mod 5) → **240–280 W**;
α = 1.5. The 62.4 kWh energy floor corresponds to the nominal 100 W
(`eval/headline_study_v4.py`: "2 nodes * 100W * 312 hours"). README §4.2 states the
code values; the docs should be corrected to match.

## i) Tertile shortfall at matched targets

The task asked for tertile "energy and shortfall values at matched targets". The v5
JSON's matched-target tertile tables contain **energy only** (no shortfall fields);
shortfall medians exist only in the natural-operating-point tertile tables. README §9
reports matched-target energy and NOP (τ=0.90, CA U=50%) shortfall, each with its
source labelled. Notably, at the NOP the Aegis median shortfall **exceeds** CA's on
low- and mid-load apps (16.0 vs 7.0 min; 162.0 vs 86.0 min) — reported as-is.

## j) Makefile defects (fixed during regeneration)

`make test-go` / `make lint-go` referenced a non-existent `scheduler-plugin`
directory; the plugin lives at `scheduler/aegis-scheduler`. Fixed, and a `make readme`
target was added (`python eval/generate_readme.py`).

## k) Baselines report renderer defects (informational)

`eval/reports/baselines_report.md` (the auto-rendered W3 report) has an empty coverage
table, zeroed dominance counts, and one-sided Wilcoxon p-values shown as 1.0. The
committed JSON is correct; the README therefore reads the JSONs directly and cross-checks
the rolling arm byte-for-byte between `headline_results_v5.json` and
`baselines_results_v1.json` on every build.

---

**Superseded files** (never read by the generator): `eval/scale_aware_pareto_results.json`
(v1), `eval/scale_aware_pareto_results_v3.json` (v3), `eval/headline_results_v4.json` (v4).
