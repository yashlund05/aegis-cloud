# Contributors & Project Roles

This document recognizes all contributors to **Aegis Cloud**, detailing their respective contributions, engineering/research roles, and git commit history.

---

## Contributor Summary

| Contributor | GitHub / Email | Commits | Primary Role |
| :--- | :--- | :---: | :--- |
| **Ayush Vishwakarma** | [`@officialayush5839-arch`](https://github.com/officialayush5839-arch)<br>`officialayush5839@gmail.com` | **120** | **Systems Engineering & CI/CD Infrastructure Lead** |
| **Yash Lund** | [`@yashlund05`](https://github.com/yashlund05)<br>`yashlund05@gmail.com` | **42** | **Project Creator, Core Architect & Lead Researcher** |
| **Saim Kotkar** | [`@kotkarsaim-sketch`](https://github.com/kotkarsaim-sketch)<br>`kotkarsaim@gmail.com` | **4** | **Power Modeling & Evaluation Specialist** |
| **Sabiha Mulla** | `sabihamulla9999@gmail.com` | **1** | **Project Documentation & Progress Tracking** |

---

## Detailed Contributions by Member

### 1. Ayush Vishwakarma (`@officialayush5839-arch`)
**Role:** Systems Engineering & CI/CD Infrastructure Lead  
**Commit Count:** 120 commits  
**Key Contributions:**
- **Codebase-Wide Lint & Formatting Overhaul:** Diagnosed and resolved all 203 flake8 PEP8 lint and formatting errors (`F401` unused imports, `E302`/`E305` blank-line spacing, slice whitespace) across 87+ files in `services/`, `ml/`, and `tests/`.
- **CI/CD Pipeline Remediation:** Resolved GitHub Actions CI failures by fixing `golangci-lint` context loading timeouts with a 5-minute threshold in `.github/workflows/ci.yml`.
- **Microservices Docker Build Architecture:** Fixed Docker build contexts and shared requirements resolution (`-r ../shared/requirements.txt`) across all 9 microservices, `docker-compose.yml`, and `.github/workflows/docker.yml`.
- **Package Hierarchy & Namespace Fixes:** Initialized `datasets/__init__.py` and `eval/__init__.py` to resolve local package import conflicts with external third-party libraries.
- **Evaluation Sync & Verification:** Updated `eval/generate_readme.py` to parse calibrated alpha exponents, added environment fallback handling for test environments, and ensured 100% test pass rate across the full 106-unit-test suite.

---

### 2. Yash Lund (`@yashlund05`)
**Role:** Project Creator, Core Architect & Lead Researcher  
**Commit Count:** 42 commits  
**Key Contributions:**
- **System Architecture (Phases 1–8):** Conceived and built the core Aegis predictive orchestration architecture, microservices decomposition, and kind cluster infrastructure.
- **Machine Learning & Forecasting (Phase 3–4):** Implemented LightGBM multi-horizon quantile forecasting ($p_{10}, p_{50}, p_{90}$) and two-sample KS drift detection.
- **Joint Optimization Engine (Phase 5):** Formulated the OR-Tools CP-SAT Mixed-Integer Linear Program for joint scaling and placement with First-Fit Decreasing (FFD) fallback.
- **Custom Kubernetes Scheduler (Phase 6):** Developed the native Go scheduling framework plugin (`Filter` and `Score` extension points) with prediction caching.
- **Scientific Evaluation & Conformal Prediction (Phases 11–15):** Formulated the Split Protocol, 60-app Azure Functions 2019 waterfall filter, Scale-Aware Conformal Prediction, Adaptive Conformal Inference (ACI), and Matched-Shortfall Pareto analyses.

---

### 3. Saim Kotkar (`@kotkarsaim-sketch`)
**Role:** Power Modeling & Evaluation Specialist  
**Commit Count:** 4 commits  
**Key Contributions:**
- **Calibrated Power Modeling:** Integrated SPECpower-calibrated physical power model parameters (`CALIBRATED_ALPHA = 0.6696`) into the simulation engine (`ml/evaluation/ablation.py`).
- **Empirical Evaluation & Visualization:** Added real-trace evaluation results, benchmark metrics, and visual comparison graphs (`docs/real_data_results.md`).
- **Solver Ablation:** Developed ablation comparisons contrasting CP-SAT optimal placement against the First-Fit-Decreasing heuristic.

---

### 4. Sabiha Mulla
**Role:** Project Documentation & Progress Tracking  
**Commit Count:** 1 commit  
**Key Contributions:**
- **Milestone Tracking:** Initialized the chronological development log and updates tracking documentation (`updates.md`).

---

*Note: Commit counts and author attribution are tracked via git version control history (`git shortlog -sne --all`).*
