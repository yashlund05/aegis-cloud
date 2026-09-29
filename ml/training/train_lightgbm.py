"""
Quantile regression training module for Aegis ML pipeline.
Trains gradient boosted decision tree models for quantile forecasts (p10, p50, p90)
across horizons (5, 10, 15 minutes).
Supports LightGBM with scikit-learn HistGradientBoosting quantile fallback.
"""

import argparse
import json
import logging
import os
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
import joblib

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from sklearn.ensemble import HistGradientBoostingRegressor
from ml.models.registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class QuantileModelWrapper:
    """
    Unified model wrapper providing a predict() method across LightGBM Booster
    or Scikit-learn HistGradientBoostingRegressor.
    """

    def __init__(self, model_obj, backend: str, feature_names: List[str]):
        self.model = model_obj
        self.backend = backend
        self.feature_names = feature_names

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.backend == "lightgbm":
            return self.model.predict(X[self.feature_names])
        else:
            return self.model.predict(X[self.feature_names])

    def save(self, filepath: str):
        if self.backend == "lightgbm":
            self.model.save_model(filepath)
        else:
            joblib.dump(self.model, filepath)


def train_quantile_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    quantile: float,
    params: dict = None,
) -> QuantileModelWrapper:
    """
    Trains a quantile regression tree for a specific quantile (e.g. 0.1, 0.5, 0.9).
    Uses LightGBM if installed, otherwise uses Scikit-learn HistGradientBoosting.
    """
    feature_names = list(X_train.columns)

    if lgb is not None:
        default_params = {
            "objective": "quantile",
            "alpha": quantile,
            "num_leaves": 31,
            "learning_rate": 0.08,
            "n_estimators": 300,
            "metric": "quantile",
            "verbose": -1,
        }
        if params:
            default_params.update(params)

        n_estimators = default_params.pop("n_estimators", 300)
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        callbacks = [lgb.early_stopping(stopping_rounds=30, verbose=False)]

        booster = lgb.train(
            params=default_params,
            train_set=train_data,
            num_boost_round=n_estimators,
            valid_sets=[val_data],
            callbacks=callbacks,
        )
        return QuantileModelWrapper(booster, backend="lightgbm", feature_names=feature_names)
    else:
        logger.info(f"Using scikit-learn HistGradientBoosting quantile solver for q={quantile}")
        model = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=quantile,
            learning_rate=0.08,
            max_iter=200,
            early_stopping=True,
            random_state=42,
        )
        model.fit(X_train, y_train)
        return QuantileModelWrapper(model, backend="sklearn_hist", feature_names=feature_names)


def export_to_onnx(
    model_wrapper: QuantileModelWrapper,
    feature_names: List[str],
    output_path: str,
) -> bool:
    """
    Exports a trained quantile regression model to ONNX format.
    Supports onnxmltools for LightGBM and skl2onnx for Scikit-Learn.
    If ONNX dependencies are not installed, logs a warning and gracefully skips.
    """
    try:
        import onnx
        if model_wrapper.backend == "lightgbm":
            import onnxmltools
            from onnxmltools.convert.common.data_types import FloatTensorType
            initial_type = [("float_input", FloatTensorType([None, len(feature_names)]))]
            onnx_model = onnxmltools.convert_lightgbm(model_wrapper.model, initial_types=initial_type)
            onnx.save_model(onnx_model, output_path)
            logger.info(f"Exported LightGBM model to ONNX: {output_path}")
            return True
        else:
            from skl2onnx import convert_sklearn
            from skl2onnx.common.data_types import FloatTensorType
            initial_type = [("float_input", FloatTensorType([None, len(feature_names)]))]
            onnx_model = convert_sklearn(model_wrapper.model, initial_types=initial_type)
            with open(output_path, "wb") as f:
                f.write(onnx_model.SerializeToString())
            logger.info(f"Exported scikit-learn model to ONNX: {output_path}")
            return True
    except ImportError as e:
        logger.warning(f"ONNX export skipped: required packages not installed ({e})")
        return False
    except Exception as e:
        logger.error(f"Failed to export model to ONNX: {e}")
        return False


def train_all_models(
    df: pd.DataFrame,
    horizons: List[int] = None,
    quantiles: List[float] = None,
    output_dir: str = "ml/models/artifacts",
    target_col: str = "cpu_usage",
) -> Dict[str, Any]:
    """
    Trains models for each horizon (e.g. 5, 10, 15 min) and quantile (0.1, 0.5, 0.9).
    Saves models and metadata, and registers them in the model registry.
    """
    horizons = horizons or [5, 10, 15]
    quantiles = quantiles or [0.1, 0.5, 0.9]

    os.makedirs(output_dir, exist_ok=True)
    registry = ModelRegistry()
    results = {}

    # Identify feature columns (exclude non-features and target)
    exclude_cols = [target_col, "timestamp", "workload_id", "status"]
    feature_cols = [c for c in df.columns if c not in exclude_cols and pd.api.types.is_numeric_dtype(df[c])]

    # Chronological temporal 80/20 train/validation split
    train_size = int(len(df) * 0.8)
    train_df = df.iloc[:train_size].copy()
    val_df = df.iloc[train_size:].copy()

    for h in horizons:
        # Target for horizon h is the workload usage shifted forward by h periods
        y_train_h = train_df[target_col].shift(-h)
        y_val_h = val_df[target_col].shift(-h)

        valid_train = y_train_h.notna()
        valid_val = y_val_h.notna()

        X_t, y_t = train_df.loc[valid_train, feature_cols], y_train_h[valid_train]
        X_v, y_v = val_df.loc[valid_val, feature_cols], y_val_h[valid_val]

        for q in quantiles:
            logger.info(f"Training quantile model: horizon={h}m, quantile={q}...")
            wrapper = train_quantile_model(X_t, y_t, X_v, y_v, quantile=q)

            ext = "txt" if wrapper.backend == "lightgbm" else "joblib"
            model_name = f"aegis_h{h}m_q{int(q*100)}"
            model_filename = f"{model_name}.{ext}"
            model_path = os.path.join(output_dir, model_filename)
            meta_path = os.path.join(output_dir, f"{model_name}_meta.json")

            wrapper.save(model_path)

            # Evaluate on validation set
            y_pred = wrapper.predict(X_v)
            diff = y_v.values - y_pred
            pinball = float(np.mean(np.maximum(q * diff, (q - 1) * diff)))
            denom = float(np.sum(np.abs(y_v.values)))
            wmape = float(np.sum(np.abs(diff)) / denom) if denom > 0 else 0.0

            metadata = {
                "model_name": model_name,
                "horizon_minutes": h,
                "quantile": q,
                "backend": wrapper.backend,
                "features": feature_cols,
                "model_path": model_path,
                "metrics": {
                    "wmape": round(wmape, 4),
                    "pinball_loss": round(pinball, 4),
                },
                "status": "active",
            }

            with open(meta_path, "w") as f:
                json.dump(metadata, f, indent=2)

            # Register in ModelRegistry
            v_id = registry.register_model(metadata)
            registry.promote_model(v_id)

            results[model_name] = {
                "version_id": v_id,
                "model_path": model_path,
                "metadata": metadata,
            }

    logger.info(f"Successfully trained and registered {len(results)} quantile models in {output_dir}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LightGBM Quantile Models for Aegis.")
    parser.add_argument("--data", required=True, help="Path to preprocessed parquet/csv data")
    parser.add_argument("--output-dir", default="ml/models/artifacts", help="Directory to save models")
    parser.add_argument("--horizons", default="5,10,15", help="Comma-separated horizons in minutes")
    parser.add_argument("--quantiles", default="0.1,0.5,0.9", help="Comma-separated quantiles")

    args = parser.parse_args()

    df = pd.read_parquet(args.data) if args.data.endswith(".parquet") else pd.read_csv(args.data)
    h_list = [int(h) for h in args.horizons.split(",")]
    q_list = [float(q) for q in args.quantiles.split(",")]

    train_all_models(df, horizons=h_list, quantiles=q_list, output_dir=args.output_dir)
