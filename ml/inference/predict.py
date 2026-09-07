"""
Inference pipeline for Aegis.
"""
import glob
try:
    import lightgbm as lgb
except ImportError:
    lgb = None
import logging

logger = logging.getLogger(__name__)

class AegisPredictor:
    def __init__(self, model_dir: str, horizons: list[int], quantiles: list[float]):
        self.model_dir = model_dir
        self.horizons = horizons
        self.quantiles = quantiles
        self.models = {}
        self.model_info = {}
        
    def load_models(self) -> None:
        """Load all LightGBM models from model_dir."""
        logger.info(f"Loading models from {self.model_dir}")
        for h in self.horizons:
            self.models[h] = {}
            for q in self.quantiles:
                model_pattern = os.path.join(self.model_dir, f"model_{h}min_q{q}*.txt")
                matches = glob.glob(model_pattern)
                if matches:
                    model_path = matches[0]
                    self.models[h][q] = lgb.Booster(model_file=model_path)
                    self.model_info[f"{h}_{q}"] = {"path": model_path, "status": "loaded"}
                else:
                    logger.warning(f"No model found for horizon {h}min, quantile {q}")

    def predict(self, features: dict) -> dict:
        """Run all models, return {horizon: {quantile: value}}"""
        import pandas as pd
        df = pd.DataFrame([features])
        result = {}
        for h in self.horizons:
            result[h] = {}
            for q in self.quantiles:
                if h in self.models and q in self.models[h]:
                    pred = self.models[h][q].predict(df)
                    result[h][q] = float(pred[0])
        return result

    def predict_batch(self, feature_list: list[dict]) -> list[dict]:
        """Run batch predictions."""
        import pandas as pd
        df = pd.DataFrame(feature_list)
        results = [{} for _ in range(len(feature_list))]
        
        for h in self.horizons:
            for q in self.quantiles:
                if h in self.models and q in self.models[h]:
                    preds = self.models[h][q].predict(df)
                    for i, p in enumerate(preds):
                        if h not in results[i]:
                            results[i][h] = {}
                        results[i][h][q] = float(p)
        return results

    def get_model_info(self) -> dict:
        """Return loaded model metadata."""
        return self.model_info
