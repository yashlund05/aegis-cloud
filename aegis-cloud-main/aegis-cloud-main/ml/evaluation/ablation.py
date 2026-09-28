"""
Ablation study module for Aegis.
Supports Phase 9: HPA vs Aegis + Ablation experiments.
"""
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

@dataclass
class ExperimentConfig:
    """Configuration for a single ablation experiment."""
    name: str
    description: str
    enable_forecasting: bool = True
    enable_placement: bool = True
    enable_power_mgmt: bool = True
    duration_minutes: int = 30
    load_profile: str = "diurnal"  # diurnal, spike, steady

@dataclass
class ExperimentResult:
    """Results from a single experiment run."""
    config_name: str
    total_energy_kwh: float = 0.0
    avg_power_watts: float = 0.0
    slo_violations: int = 0
    slo_violation_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_cpu_util: float = 0.0
    scale_events: int = 0
    duration_minutes: float = 0.0
    raw_metrics: Dict[str, Any] = field(default_factory=dict)


# Pre-defined experiment configurations for Phase 9
ABLATION_CONFIGS = {
    "stock_hpa": ExperimentConfig(
        name="stock_hpa",
        description="Baseline: Stock Kubernetes HPA only",
        enable_forecasting=False,
        enable_placement=False,
        enable_power_mgmt=False,
    ),
    "forecast_only": ExperimentConfig(
        name="forecast_only",
        description="Ablation 1: Forecasting enabled, no optimal placement",
        enable_forecasting=True,
        enable_placement=False,
        enable_power_mgmt=False,
    ),
    "forecast_placement": ExperimentConfig(
        name="forecast_placement",
        description="Ablation 2: Forecasting + placement, no power management",
        enable_forecasting=True,
        enable_placement=True,
        enable_power_mgmt=False,
    ),
    "full_aegis": ExperimentConfig(
        name="full_aegis",
        description="Full Aegis system: Forecasting + placement + power management",
        enable_forecasting=True,
        enable_placement=True,
        enable_power_mgmt=True,
    ),
}


class AblationStudy:
    """
    Manages A/B comparisons for different Aegis configurations.
    Configurations: stock_hpa, forecast_only, forecast_placement, full_aegis.
    """
    def __init__(self, configs: Dict[str, ExperimentConfig] = None):
        self.configs = configs or ABLATION_CONFIGS
        self.results: Dict[str, ExperimentResult] = {}

    def run_comparison(self, config_name: str,
                       metrics_collector=None) -> ExperimentResult:
        """
        Run a single experiment with the given configuration.
        In production, this would:
          1. Configure the Aegis system per the ExperimentConfig
          2. Run a load profile for the specified duration
          3. Collect Prometheus metrics throughout
        """
        if config_name not in self.configs:
            raise ValueError(f"Unknown config: {config_name}. Available: {list(self.configs.keys())}")

        config = self.configs[config_name]
        logger.info(f"Starting experiment: {config.name} — {config.description}")
        logger.info(f"  Forecasting: {config.enable_forecasting}")
        logger.info(f"  Placement:   {config.enable_placement}")
        logger.info(f"  Power Mgmt:  {config.enable_power_mgmt}")

        # Placeholder: In reality, reconfigure the cluster, apply load, wait, collect
        result = ExperimentResult(config_name=config_name, duration_minutes=config.duration_minutes)

        if metrics_collector:
            raw = metrics_collector(config)
            result.total_energy_kwh = raw.get("total_energy_kwh", 0.0)
            result.avg_power_watts = raw.get("avg_power_watts", 0.0)
            result.slo_violations = raw.get("slo_violations", 0)
            result.avg_latency_ms = raw.get("avg_latency_ms", 0.0)
            result.p99_latency_ms = raw.get("p99_latency_ms", 0.0)
            result.avg_cpu_util = raw.get("avg_cpu_util", 0.0)
            result.scale_events = raw.get("scale_events", 0)
            result.raw_metrics = raw

        self.results[config_name] = result
        logger.info(f"Completed experiment: {config_name}")
        return result

    def run_all(self, metrics_collector=None) -> Dict[str, ExperimentResult]:
        """Run all configured experiments sequentially."""
        for name in self.configs:
            self.run_comparison(name, metrics_collector)
        return self.results

    def collect_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Return all collected results as dicts."""
        return {name: asdict(result) for name, result in self.results.items()}

    def generate_report(self, output_path: str = "ablation_report.json") -> Dict[str, Any]:
        """Generate a comparison report across all experiments."""
        if not self.results:
            logger.warning("No experiment results to report")
            return {}

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "experiments": {},
            "comparison": {}
        }

        for name, result in self.results.items():
            report["experiments"][name] = asdict(result)

        # Compute relative improvements vs baseline (stock_hpa)
        baseline = self.results.get("stock_hpa")
        if baseline and baseline.total_energy_kwh > 0:
            for name, result in self.results.items():
                if name == "stock_hpa":
                    continue
                energy_savings = ((baseline.total_energy_kwh - result.total_energy_kwh)
                                  / baseline.total_energy_kwh * 100)
                report["comparison"][name] = {
                    "energy_savings_pct": round(energy_savings, 2),
                    "slo_violation_delta": result.slo_violations - baseline.slo_violations,
                    "latency_delta_ms": round(result.avg_latency_ms - baseline.avg_latency_ms, 2),
                }

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Ablation report saved to {output_path}")

        return report
