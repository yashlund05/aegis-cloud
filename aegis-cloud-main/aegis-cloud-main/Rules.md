# Engineering Rules & Guidelines

## 1. General Principles
- **No Hallucinations:** Never invent requirements or substitute technologies defined in the PRD/TRD.
- **Strict Adherence:** Read PRD, TRD, Flow, Schema, and Phases before implementing major features. Consult source documents before architectural changes.
- **Architecture Integrity:** No duplicate services. No unnecessary dependencies.

## 2. Code Quality
- **Strong Typing:** Use type hints everywhere (Python `typing`, Go structs).
- **Modularity:** Keep modules small. Enforce single responsibility principle.
- **Structure:** Clear interfaces. No giant files. No circular dependencies.
- **State Management:** No hidden global state. Configuration must be passed through environment variables or config files.
- **Security:** No hard-coded secrets. Use `.env` (not committed) or secret managers.

## 3. API Standards
- **Versioning:** Version all APIs (e.g., `/api/v1/`).
- **Validation:** Strictly validate all inputs using tools like Pydantic.
- **Responses:** Return structured errors (JSON with error code and message).
- **Compatibility:** Maintain backwards compatibility for minor updates. Document all endpoints (OpenAPI/Swagger).

## 4. Machine Learning Ethics & Practices
- **Data Integrity:** NEVER train on test data. NEVER shuffle temporal data.
- **Splits:** Preserve train/val/test split by time chronologically (e.g., 70/15/15).
- **Tracking:** Track model versions, training hyperparameters, and evaluation metrics (WMAPE, Pinball loss).
- **Deployment:** Never silently promote an unvalidated model. Use shadow mode first.

## 5. Kubernetes & Execution Safety
- **Safety Checks:** Never perform destructive actions (scale down to 0, drain) without safety validations.
- **Capacity Validation:** Validate resource availability before placing workloads.
- **Stability:** Respect autoscaling dead-zones (±10%) and cooldown periods (≥5 mins) to avoid thrashing.
- **Audit:** Log all scaling and scheduling decisions.
- **Testing:** Maintain a dry-run capability for all execution controllers.

## 6. Energy Modeling
- **Truthfulness:** Distinguish clearly between *measured* energy and *estimated* energy.
- **Validation:** Never claim energy savings without measured validation from Kepler.
- **Configurability:** Keep energy model parameters ($P_{idle}$, $P_{max}$, $\alpha$) configurable.

## 7. Testing & Source Control
- **Testing:** No feature is considered complete without accompanying unit and integration tests.
- **Git Hygiene:** Clean, atomic commits. 
- **Exclusions:** NO secrets, NO `.env` files, NO generated binaries, NO model dumps, NO large datasets, and NO local cluster state in the repository.

## 8. AI Agent Rules
- Read project documentation before making changes.
- Follow established project patterns and naming conventions.
- Explicitly mark assumptions with `TODO:` or comments if clarification is needed.
