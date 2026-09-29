"""
Aegis services root package.
Maps hyphenated service directory names (e.g. services/decision-engine)
to valid Python module import paths (e.g. services.decision_engine).
"""

import sys
from pathlib import Path
import importlib.util

ROOT_DIR = Path(__file__).resolve().parent

service_mappings = {
    "services.api_gateway": "api-gateway",
    "services.orchestrator": "orchestrator",
    "services.telemetry_collector": "telemetry-collector",
    "services.predictor": "predictor",
    "services.decision_engine": "decision-engine",
    "services.autoscaler_controller": "autoscaler-controller",
    "services.node_power_controller": "node-power-controller",
    "services.recommendation_engine": "recommendation-engine",
    "services.energy_module": "energy-module",
    "services.shared": "shared",
}

for mod_name, rel_path in service_mappings.items():
    if mod_name not in sys.modules:
        pkg_dir = ROOT_DIR / rel_path
        if pkg_dir.exists():
            init_file = pkg_dir / "__init__.py"
            if init_file.exists():
                spec = importlib.util.spec_from_file_location(
                    mod_name, str(init_file), submodule_search_locations=[str(pkg_dir)]
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    try:
                        spec.loader.exec_module(mod)
                    except Exception:
                        pass
