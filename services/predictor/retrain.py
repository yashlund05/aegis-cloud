"""
Model Retraining module for Aegis Predictor Service.
Executes scheduled or drift-triggered retraining, validates performance against baseline,
registers models in shadow mode, and promotes them upon passing quality gates.
"""

import os
import logging
from typing import Dict, Any, Optional
import pandas as pd

from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import train_all_models
from ml.evaluation.evaluate import walk_forward_validation
from services.predictor.registry import model_registry
from services.predictor.drift import drift_detector

logger = logging.getLogger(__name__)


async def trigger_model_retrain(
    workload_id: str,
    data_path: Optional[str] = "datasets/processed_sample_trace.parquet",
    output_dir: str = "ml/models/artifacts",
) -> Dict[str, Any]:
    """
    Executes automated model retraining pipeline:
    1. Loads historical telemetry dataset.
    2. Builds updated rolling and lag feature matrix.
    3. Trains quantile models across horizons (5, 10, 15m) and quantiles (0.1, 0.5, 0.9).
    4. Evaluates via walk-forward validation.
    5. Deploys to shadow mode, and promotes to active if quality gates pass.
    """
    logger.info(f"Initiating retraining pipeline for workload '{workload_id}'...")

    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Training dataset '{data_path}' not found.")

    df = (
        pd.read_parquet(data_path)
        if data_path.endswith(".parquet")
        else pd.read_csv(data_path)
    )
    if "workload_id" in df.columns:
        w_df = df[df["workload_id"] == workload_id].copy()
        if len(w_df) < 50:
            w_df = df.copy()  # Fallback to full trace if workload sample too small
    else:
        w_df = df.copy()

    # Step 1: Feature generation
    logger.info("Computing updated feature matrices...")
    feat_df = build_features(w_df)

    # Step 2: Train updated models
    logger.info("Fitting quantile models...")
    train_results = train_all_models(
        feat_df,
        horizons=[5, 10, 15],
        quantiles=[0.1, 0.5, 0.9],
        output_dir=output_dir,
    )

    # Step 3: Run walk-forward validation quality gate
    logger.info("Running walk-forward cross validation quality gate...")
    eval_report = walk_forward_validation(
        feat_df,
        horizon=10,
        quantiles=[0.1, 0.5, 0.9],
        n_splits=3,
    )

    avg_wmape = eval_report["average_metrics"]["mean_wmape_p50"]
    avg_cov = eval_report["average_metrics"]["mean_coverage_p10_p90"]

    # Quality Gate: WMAPE < 0.35
    passes_gate = avg_wmape < 0.35
    status = "promoted" if passes_gate else "held_in_shadow"

    if passes_gate:
        # Promote all newly trained models to active
        for model_name, info in train_results.items():
            v_id = info["version_id"]
            await model_registry.promote_model(v_id)
        # Reset drift detector error distribution baseline
        drift_detector.reset_reference(workload_id)
        logger.info(
            f"Retrained models successfully passed quality gate (WMAPE={avg_wmape:.4f}). Promoted to active."
        )
    else:
        logger.warning(
            f"Retrained models did not pass quality gate (WMAPE={avg_wmape:.4f}). Held in shadow mode."
        )

    return {
        "status": status,
        "workload_id": workload_id,
        "models_trained": list(train_results.keys()),
        "wmape_p50": avg_wmape,
        "coverage_p10_p90": avg_cov,
        "quality_gate_passed": passes_gate,
    }
