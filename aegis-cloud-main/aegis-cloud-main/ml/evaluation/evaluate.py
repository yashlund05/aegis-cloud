"""
Evaluation module for Aegis ML pipeline.
"""
import json
import logging
import os
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

def walk_forward_validation(model_fn, df: pd.DataFrame, feature_cols: list,
                            target_col: str, n_splits: int = 5,
                            quantile: float = 0.5) -> dict:
    """
    Rolling-origin walk-forward cross-validation for time series.
    Never shuffles. Returns metrics per fold and averaged.
    
    Args:
        model_fn: Callable(X_train, y_train, X_val, y_val, quantile) -> model
        df: DataFrame with features and target (must be time-sorted).
        feature_cols: List of feature column names.
        target_col: Target column name.
        n_splits: Number of walk-forward folds.
        quantile: Quantile for pinball loss.
    """
    results = {'folds': [], 'average_metrics': {}}
    fold_size = len(df) // (n_splits + 1)

    if fold_size < 10:
        logger.warning("Fold size too small for meaningful evaluation")
        return results

    logger.info(f"Running walk-forward validation with {n_splits} splits, fold_size={fold_size}")

    all_wmape = []
    all_pinball = []

    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        val_end = train_end + fold_size

        if val_end > len(df):
            break

        train_df = df.iloc[:train_end]
        val_df = df.iloc[train_end:val_end]

        X_train = train_df[feature_cols]
        y_train = train_df[target_col]
        X_val = val_df[feature_cols]
        y_val = val_df[target_col]

        try:
            model = model_fn(X_train, y_train, X_val, y_val, quantile)
            y_pred = model.predict(X_val)

            fold_wmape = wmape(y_val.values, y_pred)
            fold_pinball = pinball_loss(y_val.values, y_pred, quantile)

            fold_result = {
                'fold': i + 1,
                'train_size': len(X_train),
                'val_size': len(X_val),
                'wmape': float(fold_wmape),
                'pinball_loss': float(fold_pinball),
            }
            results['folds'].append(fold_result)
            all_wmape.append(fold_wmape)
            all_pinball.append(fold_pinball)

            logger.info(f"Fold {i+1}: WMAPE={fold_wmape:.4f}, Pinball={fold_pinball:.4f}")

        except Exception as e:
            logger.error(f"Fold {i+1} failed: {e}")
            results['folds'].append({'fold': i + 1, 'error': str(e)})

    if all_wmape:
        results['average_metrics'] = {
            'mean_wmape': float(np.mean(all_wmape)),
            'std_wmape': float(np.std(all_wmape)),
            'mean_pinball': float(np.mean(all_pinball)),
            'std_pinball': float(np.std(all_pinball)),
        }

    return results

def evaluate_model(model, X_test: pd.DataFrame, y_test: pd.Series, quantile: float) -> dict:
    """Compute all metrics for a given model."""
    y_pred = model.predict(X_test)

    return {
        'wmape': wmape(y_test.values, y_pred),
        'pinball_loss': pinball_loss(y_test.values, y_pred, quantile)
    }

def generate_evaluation_report(results: dict, output_path: str) -> None:
    """Save evaluation report as JSON + optional plots."""
    try:
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        json_path = output_path if output_path.endswith('.json') else f"{output_path}.json"
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"Saved evaluation report to {json_path}")

        # Generate plots if matplotlib is available
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            folds = results.get('folds', [])
            if folds and all('wmape' in f for f in folds if 'error' not in f):
                valid_folds = [f for f in folds if 'error' not in f]
                fold_nums = [f['fold'] for f in valid_folds]
                fold_wmape = [f['wmape'] for f in valid_folds]

                fig, ax = plt.subplots(1, 1, figsize=(8, 4))
                ax.bar(fold_nums, fold_wmape, color='steelblue')
                ax.set_xlabel('Fold')
                ax.set_ylabel('WMAPE')
                ax.set_title('Walk-Forward Validation: WMAPE per Fold')
                ax.axhline(y=np.mean(fold_wmape), color='red', linestyle='--', label=f'Mean: {np.mean(fold_wmape):.4f}')
                ax.legend()
                fig.tight_layout()

                plot_path = json_path.replace('.json', '_wmape.png')
                fig.savefig(plot_path, dpi=150)
                plt.close(fig)
                logger.info(f"Saved WMAPE plot to {plot_path}")

        except ImportError:
            logger.info("matplotlib not available, skipping plot generation")

    except Exception as e:
        logger.error(f"Error saving report: {e}")
