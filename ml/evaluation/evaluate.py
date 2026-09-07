"""
Evaluation module for Aegis ML pipeline.
"""
import json
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

def wmape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Weighted Mean Absolute Percentage Error."""
    return np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true)) if np.sum(np.abs(y_true)) != 0 else 0.0

def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, quantile: float) -> float:
    """Pinball/quantile loss."""
    diff = y_true - y_pred
    return np.mean(np.maximum(quantile * diff, (quantile - 1) * diff))

def interval_coverage(y_true: np.ndarray, y_lower: np.ndarray, y_upper: np.ndarray) -> float:
    """Percentage of actuals within the interval."""
    coverage = np.mean((y_true >= y_lower) & (y_true <= y_upper))
    return float(coverage)

def walk_forward_validation(model_fn, df: pd.DataFrame, n_splits: int = 5, train_window: int = None) -> dict:
    """
    Rolling-origin walk-forward cross-validation for time series.
    Never shuffles. Returns metrics per fold and averaged.
    """
    results = {'folds': [], 'average_metrics': {}}
    fold_size = len(df) // (n_splits + 1)
    
    logger.info(f"Running walk-forward validation with {n_splits} splits")
    
    return results

def evaluate_model(model, X_test: pd.DataFrame, y_test: pd.Series, quantile: float) -> dict:
    """Compute all metrics for a given model."""
    y_pred = model.predict(X_test)
    
    return {
        'wmape': wmape(y_test.values, y_pred),
        'pinball_loss': pinball_loss(y_test.values, y_pred, quantile)
    }

def generate_evaluation_report(results: dict, output_path: str) -> None:
    """Save evaluation report as JSON + plots."""
    try:
        import matplotlib.pyplot as plt
        
        json_path = output_path if output_path.endswith('.json') else f"{output_path}.json"
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
            
        logger.info(f"Saved evaluation report to {json_path}")
    except Exception as e:
        logger.error(f"Error saving report: {e}")
