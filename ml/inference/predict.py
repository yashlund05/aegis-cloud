"""
Inference pipeline for Aegis workload demand prediction.
Loads trained quantile models and generates p10/p50/p90 forecasts for 5, 10, 15 minute horizons.
"""

import os
import glob
import json
import logging
from typing import Dict, Any, List
import pandas as pd
import joblib

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

logger = logging.getLogger(__name__)


class AegisPredictor:
    """
    Loads quantile regression models from artifacts directory and serves predictions.
    """

    def __init__(
        self,
        model_dir: str = "ml/models/artifacts",
        horizons: List[int] = None,
        quantiles: List[float] = None,
    ):
        self.model_dir = model_dir
        self.horizons = horizons or [5, 10, 15]
        self.quantiles = quantiles or [0.1, 0.5, 0.9]
        self.models: Dict[int, Dict[float, Any]] = {}
        self.feature_lists: Dict[int, Dict[float, List[str]]] = {}
        self.model_info: Dict[str, Any] = {}

    def load_models(self) -> None:
        """
        Loads all model artifacts (.txt for LightGBM or .joblib for sklearn) and their metadata.
        """
        logger.info(f"Loading Aegis quantile models from '{self.model_dir}'...")
        if not os.path.exists(self.model_dir):
            logger.warning(f"Model directory '{self.model_dir}' does not exist.")
            return

        for h in self.horizons:
            self.models[h] = {}
            self.feature_lists[h] = {}
            for q in self.quantiles:
                q_tag = int(q * 100)
                # Look for model artifact
                pattern_lgb = os.path.join(self.model_dir, f"*h{h}m_q{q_tag}*.txt")
                pattern_joblib = os.path.join(
                    self.model_dir, f"*h{h}m_q{q_tag}*.joblib"
                )

                matches_lgb = glob.glob(pattern_lgb)
                matches_joblib = glob.glob(pattern_joblib)

                model_obj = None
                meta_obj = {}

                # Read metadata if present
                meta_pattern = os.path.join(
                    self.model_dir, f"*h{h}m_q{q_tag}*_meta.json"
                )
                meta_matches = glob.glob(meta_pattern)
                if meta_matches:
                    with open(meta_matches[0], "r") as f:
                        meta_obj = json.load(f)

                if matches_lgb and lgb is not None:
                    model_path = matches_lgb[0]
                    model_obj = lgb.Booster(model_file=model_path)
                    logger.info(f"Loaded LightGBM booster from {model_path}")
                elif matches_joblib:
                    model_path = matches_joblib[0]
                    model_obj = joblib.load(model_path)
                    logger.info(f"Loaded model from {model_path}")

                if model_obj:
                    self.models[h][q] = model_obj
                    self.feature_lists[h][q] = meta_obj.get("features", [])
                    self.model_info[f"{h}m_q{q}"] = {
                        "path": model_path,
                        "metadata": meta_obj,
                        "status": "loaded",
                    }
                else:
                    logger.debug(
                        f"No trained artifact found for horizon={h}m, quantile={q}"
                    )

    def predict(self, features: Dict[str, Any]) -> Dict[int, Dict[float, float]]:
        """
        Generates quantile predictions across horizons for a single feature vector.
        Returns: {5: {0.1: 0.32, 0.5: 0.45, 0.9: 0.62}, 10: {...}, 15: {...}}
        """
        df = pd.DataFrame([features])
        result = {}

        for h in self.horizons:
            result[h] = {}
            for q in self.quantiles:
                if h in self.models and q in self.models[h]:
                    model = self.models[h][q]
                    feature_names = self.feature_lists[h].get(q, [])

                    # Ensure all expected feature columns exist in the inference dataframe
                    if feature_names:
                        for col in feature_names:
                            if col not in df.columns:
                                if "cpu" in col or "lag" in col or "rolling" in col:
                                    df[col] = df.get("cpu_usage", 0.35)
                                else:
                                    df[col] = 0.0
                        cols = feature_names
                    else:
                        cols = df.columns

                    try:
                        pred = model.predict(df[cols])
                        val = float(pred[0])
                        result[h][q] = max(0.01, round(val, 4))
                    except Exception as e:
                        logger.warning(f"Model inference failed for h={h}, q={q}: {e}")
                        current_cpu = float(features.get("cpu_usage", 0.35))
                        margin = 0.0 if q == 0.5 else (-0.05 if q < 0.5 else 0.10)
                        result[h][q] = max(0.01, round(current_cpu + margin, 4))
                else:
                    # Safe fallback heuristic if model not loaded: use current CPU usage with quantile margin
                    current_cpu = float(features.get("cpu_usage", 0.35))
                    margin = 0.0 if q == 0.5 else (-0.05 if q < 0.5 else 0.10)
                    result[h][q] = max(0.01, round(current_cpu + margin, 4))

        return result

    def predict_batch(
        self, feature_list: List[Dict[str, Any]]
    ) -> List[Dict[int, Dict[float, float]]]:
        """
        Run batch predictions for a list of feature dictionaries.
        """
        return [self.predict(f) for f in feature_list]

    def get_model_info(self) -> Dict[str, Any]:
        """
        Returns metadata for all loaded models.
        """
        return {
            "loaded_models_count": sum(len(q_dict) for q_dict in self.models.values()),
            "horizons": self.horizons,
            "quantiles": self.quantiles,
            "models": self.model_info,
        }
