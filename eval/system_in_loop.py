"""
System-in-the-loop: run the REAL Aegis services code inside the simulation loop
(frozen simulator tag sim-frozen untouched; this file is new).

Real code executed per simulated control step (loaded via importlib through the
services package aliasing in services/__init__.py, which maps hyphenated
directories to importable module names):
  1. services.decision_engine.solver.CPSolver.solve()   - CP-SAT, 10 s timeout,
     FFD fallback on timeout/infeasible/exception (ortools 9.15 present)
  2. services.orchestrator.validator.validate_decision_plan()
  3. services.autoscaler_controller.safety.SafetyChecker.should_scale()
     - REAL defaults: dead zone +-10%, cooldown 300 s, max step 10 replicas;
       the simulated clock is injected via the `now` argument (t * 60 s)
  4. services.node_power_controller.safety.PowerSafetyChecker.can_modify_node()

Frozen physics reuse (imported, not copied): the per-step decisions of the real
chain are encoded into a per-step p90 stream (approved_replicas[t] * 0.5 * 0.70,
with a 1e-9 guard so ceil() round-trips exactly - verified below) and executed by
the frozen AblationStudy._simulate_configuration, which supplies node boot
latency, pod capacity dynamics, energy accounting (idle/dynamic/boot), shortfall
accounting and the 60-min warm start. Constructor arguments of the harness study
(dead_zone_pct=0, stabilization_window_steps=1, max_scale_step=10**9) make the
frozen control law a pass-through so the real chain's decisions are applied
verbatim; K_min=2 and wake latency stay frozen physics.

Known, documented consequences of the real code (reported, not tuned away):
  - the real solver sizes replicas as ceil(p90 / target_cpu) with target_cpu=0.5,
    i.e. WITHOUT the frozen configs' 0.70 utilization headroom;
  - the real SafetyChecker max step is 10 replicas/min (service default), not the
    HPA-realistic policy;
  - solver cordons gated by the real node-power checker are advisory for the
    physics replay: the frozen node state machine derives node states from the
    approved replicas (K_min enforced there); cordon refusals are counted.

Test (per instructions): one app (737e31dddf54 from the 68-core real set),
first 2 days of its test window (2880 control steps). Full experiment NOT run.

Usage: python eval/system_in_loop.py
"""

import glob
import importlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath("."))

from eval.run_real_trace import prepare_streams, git_state  # noqa: E402
from ml.evaluation.ablation import AblationStudy, get_default_nodes  # noqa: E402

# --- real services, loaded through importlib (hyphenated directories) ---
import services  # noqa: F401  # triggers the hyphen->underscore package aliasing

solver_mod = importlib.import_module("services.decision_engine.solver")
validator_mod = importlib.import_module("services.orchestrator.validator")
autoscaler_safety_mod = importlib.import_module("services.autoscaler_controller.safety")
node_power_safety_mod = importlib.import_module("services.node_power_controller.safety")

CPSolver = solver_mod.CPSolver
validate_decision_plan = validator_mod.validate_decision_plan
SafetyChecker = autoscaler_safety_mod.SafetyChecker
PowerSafetyChecker = node_power_safety_mod.PowerSafetyChecker

TARGET_APP = "737e31dddf54"
TEST_DAYS = 2
WINDOW = TEST_DAYS * 1440
HORIZON = 10
TAU = 0.90
PER_REPLICA_CPU = 0.5
TARGET_UTIL = 0.70
MIN_REPLICAS = 1
MAX_REPLICAS = 250
K_MIN = 2
OUTPUT_JSON = "eval/system_in_loop_results.json"


def confal_level(m: int, tau: float) -> float:
    return min(1.0, np.ceil((m + 1) * tau) / m)


def main():
    paths = {os.path.basename(p).replace("real_", "").replace(".parquet", ""): p
             for p in glob.glob("datasets/real_*.parquet")}
    streams = prepare_streams(paths[TARGET_APP])
    a = streams["_arrays"]
    y_all, calib, test_mask = a["y_all"], a["calib_mask"], a["test_mask"]
    p10_raw, p50_raw, p90_raw = a["p10_raw_full"], a["p50_raw_full"], a["p90_raw_full"]

    # static conformal p10/p50/p90 (same formulas and calibration segment as the frozen runner)
    m = int(calib.sum())
    r90 = y_all[calib] - p90_raw[calib]
    r10 = p10_raw[calib] - y_all[calib]
    q90 = float(np.quantile(r90, confal_level(m, TAU)))
    q10 = float(np.quantile(r10, confal_level(m, 0.90)))
    p90_conf = np.maximum(p90_raw + q90, p50_raw)
    p10_conf = np.minimum(p10_raw - q10, p50_raw)

    test_idx = np.flatnonzero(test_mask)[:WINDOW]
    y_test = a["y_test"][:WINDOW]
    mem_test = a["mem_test"][:WINDOW]
    p10_t, p50_t, p90_t = p10_conf[test_idx], p50_raw[test_idx], p90_conf[test_idx]
    print(f"app {TARGET_APP} | window {WINDOW} control steps (first {TEST_DAYS} test days) | "
          f"demand mean {y_test.mean():.2f} / max {y_test.max():.2f} cores")

    # real service instances with REAL defaults
    solver = CPSolver(timeout_ms=10000)  # 10 s timeout, FFD fallback inside
    safety = SafetyChecker(dead_zone_percent=0.10, cooldown_seconds=300, max_scale_step=10)
    power_safety = PowerSafetyChecker(min_active_nodes=K_MIN, buffer_capacity_percent=15.0)
    all_nodes = get_default_nodes("large")
    node_names = [n["name"] for n in all_nodes]

    # sequential control loop: real chain decides, state advances, decisions recorded
    current_replicas = max(2, int(np.ceil(y_test[0] / (PER_REPLICA_CPU * TARGET_UTIL))))
    last_scaled_at = None
    approved_stream = np.zeros(WINDOW)
    approved_seq = []
    log_rows = []
    sample_step = None

    for t in range(WINDOW):
        now = t * 60.0  # simulated clock, seconds

        # 1. real solver input from simulation state
        workloads = [{
            "id": TARGET_APP, "name": TARGET_APP,
            "target_cpu": PER_REPLICA_CPU, "target_memory": 2.0,
            "current_replicas": current_replicas,
            "min_replicas": MIN_REPLICAS, "max_replicas": MAX_REPLICAS,
        }]
        predictions = [
            {"workload_id": TARGET_APP, "quantile": 0.1, "predicted_value": float(p10_t[t])},
            {"workload_id": TARGET_APP, "quantile": 0.5, "predicted_value": float(p50_t[t])},
            {"workload_id": TARGET_APP, "quantile": 0.9, "predicted_value": float(p90_t[t])},
        ]
        plan = solver.solve(workloads, all_nodes, predictions, cycle_id=f"step-{t}")

        # 2. real orchestrator validator
        validator_ok, validator_msg = True, "passed"
        try:
            validate_decision_plan(plan, min_active_nodes=K_MIN, max_replicas_limit=MAX_REPLICAS)
        except Exception as e:
            validator_ok, validator_msg = False, f"{type(e).__name__}: {e}"

        # 3. real autoscaler safety (simulated clock injected via now)
        desired = int(plan.replica_changes[0].target_replicas)
        if not validator_ok:
            can_scale, safety_reason, approved = False, f"validator rejected: {validator_msg}", current_replicas
        else:
            can_scale, safety_reason, approved = safety.should_scale(
                current_replicas=current_replicas, target_replicas=desired,
                last_scaled_at=last_scaled_at, now=now,
                min_replicas=MIN_REPLICAS, max_replicas=MAX_REPLICAS,
            )
        if can_scale and approved != current_replicas:
            last_scaled_at = now
        current_replicas = max(1, approved if can_scale else current_replicas)

        # 4. real node-power safety on the solver's cordon decisions (advisory for
        #    the physics replay; refusals counted)
        active_now = projected_active_nodes(t, approved_stream, current_replicas, node_names)
        cordon_refusals = 0
        for npc in plan.node_power_changes:
            if npc.action == "cordon" and npc.node_id in active_now:
                ok, reason = power_safety.can_modify_node(npc.node_id, "cordon", active_now, node_names)
                if not ok:
                    cordon_refusals += 1

        approved_stream[t] = current_replicas * PER_REPLICA_CPU * TARGET_UTIL * (1 - 1e-9)
        approved_seq.append(current_replicas)

        log_rows.append({
            "step": t, "engine": plan.solver_type, "status": plan.status,
            "solve_time_ms": plan.solve_time_ms,
            "desired_replicas": desired, "can_scale": can_scale,
            "approved_replicas": current_replicas, "safety_reason": safety_reason,
            "validator_ok": validator_ok, "cordon_refusals": cordon_refusals,
        })

        if sample_step is None and can_scale and approved != desired:
            sample_step = {"step": t, "workloads": workloads, "predictions": predictions,
                           "plan": json.loads(plan.model_dump_json()), "validator_ok": validator_ok,
                           "safety_reason": safety_reason, "approved": approved,
                           "applied_replicas": current_replicas}

    # --- encoding verification (ceil round-trip: stream must decode to the exact approved sequence) ---
    recomputed = np.ceil(approved_stream / (PER_REPLICA_CPU * TARGET_UTIL)).astype(int)
    approved_arr = np.array(approved_seq)
    mismatches = int(np.sum(recomputed != approved_arr))
    encoding_ok = mismatches == 0

    # --- frozen physics on the real chain's decisions (imported, not copied) ---
    study = AblationStudy(
        model_dir="ml/models/artifacts_real",
        dead_zone_pct=0.0, stabilization_window_steps=1, max_scale_step=10**9,
        min_active_nodes=K_MIN, wake_up_latency_steps=3, warm_start_steps=60,
    )
    sim = study._simulate_configuration(
        actual_demands=y_test, actual_mems=mem_test, p90_forecasts=approved_stream,
        config_name="full_aegis_conformal", forecast_horizon_minutes=HORIZON,
        return_series=True,
    )

    # --- aggregates ---
    times = np.array([r["solve_time_ms"] for r in log_rows])
    engines = [r["engine"] for r in log_rows]
    n_ffd = sum(1 for e in engines if e != "cpsat")
    n_validator_rej = sum(1 for r in log_rows if not r["validator_ok"])
    n_rejected = sum(1 for r in log_rows if not r["can_scale"])
    n_altered = sum(1 for r in log_rows if r["can_scale"] and r["approved_replicas"] != r["desired_replicas"])
    n_cordon_ref = sum(r["cordon_refusals"] for r in log_rows)

    print("=" * 112)
    print(f"  SYSTEM-IN-LOOP TEST: app {TARGET_APP}, {WINDOW} control steps (2 days), real services in the loop")
    print("=" * 112)
    qs = [50, 90, 95, 99]
    print(f"  solve time ms: mean {times.mean():.1f} | median {np.median(times):.1f} | "
          + " | ".join(f"p{q} {np.percentile(times, q):.1f}" for q in qs) + f" | max {times.max():.1f}")
    print(f"  engine: CPSAT {engines.count('cpsat')} / FFD-fallback {n_ffd} (fallback rate {n_ffd/WINDOW:.2%})")
    print(f"  plans: validator rejected {n_validator_rej} | safety rejected {n_rejected} | "
          f"safety altered (max-step clamp) {n_altered} | cordon refusals (node-power safety) {n_cordon_ref}")
    print(f"  encoding check: ceil round-trip {'OK' if encoding_ok else 'FAILED'} ({mismatches} mismatches)")
    print(f"  frozen physics on real decisions: energy {sim['energy_kwh']} kWh "
          f"(idle {sim['energy_idle_kwh']} / dyn {sim['energy_dynamic_kwh']} / boot {sim['energy_boot_kwh']}) | "
          f"shortfall {sim['capacity_shortfall_minutes']} min of {WINDOW - 60} scored | "
          f"events {sim['scaling_actions']} | replica delta {sim['scaling_churn']}")

    print("\n  ONE FULL STEP END-TO-END (first safety-altered step):")
    if sample_step:
        s = sample_step
        print(f"  step {s['step']}:")
        print(f"    solver input workloads : {json.dumps(s['workloads'])}")
        print(f"    solver input forecasts : p10 {s['predictions'][0]['predicted_value']:.3f} / "
              f"p50 {s['predictions'][1]['predicted_value']:.3f} / p90 {s['predictions'][2]['predicted_value']:.3f} cores")
        print(f"    solver input nodes     : {len(all_nodes)} nodes "
              f"(cpu {all_nodes[0]['cpu_capacity']}, mem {all_nodes[0]['memory_capacity']} GB, "
              f"p_idle {all_nodes[0]['p_idle']:.0f}-{all_nodes[-1]['p_idle']:.0f} W)")
        pl = s["plan"]
        print(f"    plan                   : type={pl['solver_type']} status={pl['status']} "
              f"objective={pl['objective_value']} solve_ms={pl['solve_time_ms']} "
              f"replicas {pl['replica_changes'][0]['current_replicas']}->{pl['replica_changes'][0]['target_replicas']} "
              f"placements={len(pl['placement_decisions'])} power_changes={len(pl['node_power_changes'])}")
        print(f"    sample placements      : {[(p['pod_name'], p['target_node']) for p in pl['placement_decisions'][:5]]}")
        cordons = [c['node_id'] for c in pl['node_power_changes'] if c['action'] == 'cordon']
        print(f"    cordoned by plan       : {len(cordons)} nodes {cordons[:6]}{'...' if len(cordons) > 6 else ''}")
        print(f"    validator              : {'PASSED' if s['validator_ok'] else 'REJECTED'}")
        print(f"    autoscaler safety      : {s['safety_reason']} -> approved {s['approved']}, "
              f"applied replicas {s['applied_replicas']}")

    payload = {
        "app": TARGET_APP, "window_steps": WINDOW, "test_days": TEST_DAYS,
        "solve_time_ms": {"mean": round(float(times.mean()), 2), "median": round(float(np.median(times)), 2),
                           "p95": round(float(np.percentile(times, 95)), 2), "max": round(float(times.max()), 2)},
        "engine_counts": {"cpsat": engines.count("cpsat"), "ffd_fallback": n_ffd},
        "infeasible_or_fallback_rate": round(n_ffd / WINDOW, 6),
        "validator_rejections": n_validator_rej,
        "safety_rejections": n_rejected, "safety_altered": n_altered,
        "cordon_refusals": n_cordon_ref,
        "encoding_check_ok": encoding_ok, "encoding_mismatches": mismatches,
        "physics_result": {k: v for k, v in sim.items() if k != "series"},
        "per_step_log": log_rows,
        "sample_step": sample_step,
        "real_code": {"solver": "services/decision-engine/solver.py CPSolver (10 s timeout, FFD fallback)",
                      "validator": "services/orchestrator/validator.py validate_decision_plan",
                      "autoscaler_safety": "services/autoscaler-controller/safety.py SafetyChecker "
                                           "(dead zone 0.10, cooldown 300 s, max step 10; clock via now)",
                      "node_power_safety": "services/node-power-controller/safety.py PowerSafetyChecker"},
        "physics_note": ("per-step approved replicas encoded into the p90 stream (x0.5x0.70, 1e-9 guard, "
                         "round-trip verified) and executed by the frozen _simulate_configuration "
                         "(boot latency, energy, shortfall, warm start imported, not copied); "
                         "harness study ctor args make the frozen control law a pass-through"),
        "protocol": {"app_source": "68-core real set", "conformal": "static tau=0.90 on the 15% calibration segment",
                     "min_replicas": MIN_REPLICAS, "max_replicas": MAX_REPLICAS, "k_min": K_MIN,
                     "per_replica_cpu": PER_REPLICA_CPU, "target_util": TARGET_UTIL},
    }
    study_ref = AblationStudy()
    payload["simulator_config_hash"] = study_ref.compute_config_hash(payload["protocol"])
    payload["git"] = git_state()
    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  wrote {OUTPUT_JSON} (git: {payload['git']['commit'][:8]}, tag: {payload['git']['tag_at_head']}, "
          f"config hash: {payload['simulator_config_hash'][:16]}...)")


_PROBE_STUDY = None


def projected_active_nodes(t: int, approved_stream: np.ndarray, current_replicas: int, node_names: list) -> list:
    """Project the active node set the frozen packer will hold for the current
    approved replica count (frozen AblationStudy packer, bare instance - no
    predictor load; the packer only needs the node inventory)."""
    global _PROBE_STUDY
    if _PROBE_STUDY is None:
        _PROBE_STUDY = AblationStudy.__new__(AblationStudy)
        _PROBE_STUDY.nodes = get_default_nodes("large")
    k = _PROBE_STUDY._pack_pods(max(current_replicas, 1), opt=True)
    return node_names[:max(K_MIN, k)]


if __name__ == "__main__":
    main()
