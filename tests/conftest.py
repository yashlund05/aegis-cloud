import sys
from pathlib import Path
import importlib.util

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

service_mappings = {
    'services.api_gateway': 'services/api-gateway',
    'services.orchestrator': 'services/orchestrator',
    'services.telemetry_collector': 'services/telemetry-collector',
    'services.predictor': 'services/predictor',
    'services.decision_engine': 'services/decision-engine',
    'services.autoscaler_controller': 'services/autoscaler-controller',
    'services.node_power_controller': 'services/node-power-controller',
    'services.recommendation_engine': 'services/recommendation-engine',
    'services.energy_module': 'services/energy-module',
    'services.shared': 'services/shared',
}

for mod_name, rel_path in service_mappings.items():
    pkg_dir = ROOT_DIR / rel_path
    if pkg_dir.exists():
        init_file = pkg_dir / '__init__.py'
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
