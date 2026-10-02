"""
Diagnosis: why does services CPSolver.solve exceed its 10 s limit?

Instrumented replica of the frozen solver's exact phase sequence (the real
constraint functions from services.decision_engine.constraints are imported and
called in the same order; solver.py itself is NOT modified). Phases timed:
  1 predict+plan   (prediction mapping, replica planning, pod dicts - python)
  2 vars           (placement_vars + active_vars creation - python)
  3 assign/cap/link/ha  (the four real constraint calls)
  4 objective
  5 setup+solve    (CpSolver setup + Solve with max_time_in_seconds=10,
                    log_search_progress=True; presolve+search are inside Solve)

Model size = len(model.proto.variables) / len(model.proto.constraints).
num_workers = 4 (frozen value) for all steps; the three catastrophic models are
additionally re-run with num_workers=1 for comparison. Each diagnostic solve
runs in a child process hard-killed at 90 s so a live reproduction of the
multi-hour overshoot cannot hang the diagnosis.

Usage: python eval/diagnose_solver_phases.py
"""

import json
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))

import services  # noqa: F401  hyphen aliasing
from services.decision_engine.constraints import (
    apply_assignment_constraints,
    apply_capacity_constraints,
    apply_active_node_linking,
    apply_ha_spread_constraints,
)

from eval.system_in_loop import git_state  # noqa: E402

TARGET_APP = "737e31dddf54"
TIME_LIMIT_S = 10.0
DIAG_KILL_S = 90.0
OUTPUT_JSON = "eval/solver_phase_diagnosis.json"


def phased_solve(workloads, nodes, predictions, cycle_id, num_workers, time_limit_s=TIME_LIMIT_S,
                 log_progress=True):
    """Mirror of services/decision-engine/solver.py CPSolver.solve with per-phase
    timers. Returns (result_dict, log_text)."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return {"error": "ortools missing"}, ""
    import math
    from services.shared.schemas import DecisionPlan, PlacementDecision, ReplicaChange, NodePowerChange

    phases = {}
    t0 = time.monotonic()

    # phase 1: predictions + replica planning + pod dicts
    pred_map = {}
    for p in predictions:
        w_id = str(p.get("workload_id", ""))
        q = float(p.get("quantile", 0.5))
        val = float(p.get("predicted_value", 0.0))
        if q >= 0.85 or w_id not in pred_map:
            pred_map[w_id] = val
    replica_changes, pods_info, workload_pods_map = [], {}, {}
    for w in workloads:
        w_id = str(w.get("id", w.get("name", "workload")))
        w_name = w.get("name", w_id)
        target_cpu = float(w.get("target_cpu", 0.5))
        target_mem = float(w.get("target_memory", 1.0))
        curr = int(w.get("current_replicas", 1))
        min_r, max_r = int(w.get("min_replicas", 1)), int(w.get("max_replicas", 20))
        p90 = pred_map.get(w_id, pred_map.get(w_name, target_cpu * curr))
        target = max(min_r, min(max_r, math.ceil(p90 / max(target_cpu, 0.01))))
        replica_changes.append(ReplicaChange(workload_id=w_id, current_replicas=curr,
                                             target_replicas=target, reason="diag"))
        workload_pods_map[w_id] = []
        for idx in range(target):
            pod = f"{w_name}-pod-{idx}"
            workload_pods_map[w_id].append(pod)
            pods_info[pod] = {"cpu_request": target_cpu, "memory_request": target_mem, "workload_id": w_id}
    phases["1_predict_plan"] = time.monotonic() - t0

    t = time.monotonic()
    model = cp_model.CpModel()
    node_ids = [str(n.get("name", n.get("id", f"node-{i}"))) for i, n in enumerate(nodes)]
    nodes_info = {str(n.get("name", n.get("id", f"node-{i}"))):
                  {"cpu_capacity": float(n.get("cpu_capacity", 4.0)),
                   "memory_capacity": float(n.get("memory_capacity", 8.0)),
                   "p_idle": float(n.get("p_idle", 100.0)),
                   "p_max": float(n.get("p_max", 300.0))}
                  for i, n in enumerate(nodes)}
    pod_names = list(pods_info.keys())
    placement_vars, active_vars = {}, {}
    for p in pod_names:
        placement_vars[p] = {nid: model.NewBoolVar(f"x_{p}_{nid}") for nid in node_ids}
    for nid in node_ids:
        active_vars[nid] = model.NewBoolVar(f"y_{nid}")
    phases["2_vars"] = time.monotonic() - t

    t = time.monotonic()
    apply_assignment_constraints(model, placement_vars, pod_names, node_ids)
    phases["3a_assign"] = time.monotonic() - t
    t = time.monotonic()
    apply_capacity_constraints(model, placement_vars, active_vars, pods_info, nodes_info,
                              utilization_max=0.85)
    phases["3b_cap"] = time.monotonic() - t
    t = time.monotonic()
    apply_active_node_linking(model, placement_vars, active_vars, pod_names, node_ids,
                              min_active_nodes=1)
    phases["3c_link"] = time.monotonic() - t
    t = time.monotonic()
    apply_ha_spread_constraints(model, placement_vars, workload_pods_map, node_ids,
                                ha_max_ratio=0.50)
    phases["3d_ha"] = time.monotonic() - t

    t = time.monotonic()
    obj = []
    for nid, meta in nodes_info.items():
        obj.append(active_vars[nid] * int(meta["p_idle"] * 10))
    for p in pod_names:
        for nid in node_ids:
            obj.append(placement_vars[p][nid] * int(pods_info[p]["cpu_request"] * 100))
    model.Minimize(sum(obj))
    phases["4_objective"] = time.monotonic() - t

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = num_workers
    if log_progress:
        solver.parameters.log_search_progress = True

    class LogCapture:
        def __init__(self):
            self.lines = []

        def __call__(self, msg):
            self.lines.append(msg)

    capture = LogCapture()
    solver.log_callback = capture
    t = time.monotonic()
    status = solver.Solve(model)
    phases["5_setup_and_solve"] = time.monotonic() - t
    total = time.monotonic() - t0

    status_name = solver.StatusName(status)
    result = {
        "phases_s": {k: round(v, 4) for k, v in phases.items()},
        "total_s": round(total, 4),
        "status": status_name,
        "model_vars": len(model.proto.variables),
        "model_constraints": len(model.proto.constraints),
        "num_workers": num_workers,
        "time_limit_s": time_limit_s,
        "wall_limit_overshoot_s": round(total - time_limit_s, 3),
        "objective": float(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
    }
    return result, "\n".join(capture.lines)


def _child(step, current, target, num_workers, q):
    nodes = [{"name": f"node-{i}", "cpu_capacity": 4.0, "memory_capacity": 16.0,
              "p_idle": 90.0 + (i % 5) * 5.0, "p_max": 240.0 + (i % 5) * 10.0} for i in range(20)]
    wl = [{"id": TARGET_APP, "name": TARGET_APP, "target_cpu": 0.35, "target_memory": 2.0,
           "current_replicas": int(current), "min_replicas": 1, "max_replicas": 250}]
    p90 = target * 0.35  # reproduces the frozen solver's target exactly after ceil
    preds = [{"workload_id": TARGET_APP, "quantile": 0.1, "predicted_value": p90},
             {"workload_id": TARGET_APP, "quantile": 0.5, "predicted_value": p90},
             {"workload_id": TARGET_APP, "quantile": 0.9, "predicted_value": p90}]
    try:
        res, log_text = phased_solve(wl, nodes, preds, f"diag-{step}", num_workers)
        res["step"] = step
        res["log_excerpt"] = "\n".join(ln for ln in log_text.splitlines()
                                       if any(k in ln for k in ("Presolve", "presolve", "Starting", "Task timing",
                                                                "#Model", "walltime", "status", "Features")))
        q.put(res)
    except Exception as e:
        q.put({"step": step, "error": f"{type(e).__name__}: {e}", "num_workers": num_workers})


def main():
    d = json.load(open("eval/system_in_loop_aligned_results.json"))
    log = d["per_step_log"]
    slow = sorted(log, key=lambda r: -r["solve_time_ms"])[:20]
    print(f"diagnosing top-{len(slow)} slowest steps (reconstructed exact models, "
          f"hard diagnostic kill at {DIAG_KILL_S:.0f} s per step)")

    out = {"steps": [], "num_workers_frozen": 4, "time_limit_s": TIME_LIMIT_S}
    for r in slow:
        for workers in ([4, 1] if r["solve_time_ms"] > 60000 else [4]):
            q = mp.Queue()
            p = mp.Process(target=_child, args=(r["step"], r["approved_replicas"],
                                                r["desired_replicas"], workers, q))
            p.start()
            p.join(DIAG_KILL_S)
            if p.is_alive():
                p.terminate(); p.join(1)
                res = {"step": r["step"], "num_workers": workers,
                       "error": f"diagnostic kill at {DIAG_KILL_S:.0f}s (Solve still running - limit overshoot reproduced)"}
            else:
                res = q.get() if not q.empty() else {"step": r["step"], "error": "child died without result"}
            res["observed_solve_time_ms_in_run"] = r["solve_time_ms"]
            out["steps"].append(res)
            ph = res.get("phases_s", {})
            print(f"  step {r['step']:>4} w={workers} | build {ph.get('1_predict_plan',0)+ph.get('2_vars',0)+sum(v for k,v in ph.items() if k.startswith('3'))+ph.get('4_objective',0):>6.2f}s | "
                  f"Solve {ph.get('5_setup_and_solve',0):>8.2f}s | status {res.get('status','?'):<12} | "
                  f"vars {res.get('model_vars','?'):>5} cons {res.get('model_constraints','?'):>6} | "
                  f"run-measured {r['solve_time_ms']/1000:.1f}s"
                  + (f" | {res.get('error','')}" if res.get("error") else ""))

    # presolve-vs-limit evidence from a logged catastrophic re-run (workers=1 keeps logs readable)
    logs = [s for s in out["steps"] if s.get("num_workers") == 1 and s.get("log_excerpt")]
    out["presolve_note"] = ("ortools applies max_time_in_seconds to the whole Solve call (presolve + search); "
                            "the captured log_search_progress excerpts are in log_excerpt fields")
    payload = {**out, "git": git_state()}
    json.dump(payload, open(OUTPUT_JSON, "w"), indent=2)
    print(f"\nwrote {OUTPUT_JSON} (git: {payload['git']['commit'][:8]})")


if __name__ == "__main__":
    main()
