"""
LightGBM training module for Aegis ML pipeline.
"""

import argparse
import json
import logging
import os
import pandas as pd
import lightgbm as lgb
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def train_quantile_model(X_train: pd.DataFrame, y_train: pd.Series, 
                        X_val: pd.DataFrame, y_val: pd.Series, 
                        quantile: float, params: dict = None) -> lgb.Booster:
    """
    Trains a LightGBM model for a specific quantile.
    """
    default_params = {
        'objective': 'quantile',
        'alpha': quantile,
        'num_leaves': 31,
        'learning_rate': 0.1,
        'n_estimators': 500,
        'metric': 'quantile'
    }
    
    if params:
        default_params.update(params)
        
    n_estimators = default_params.pop('n_estimators', 500)
    
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    callbacks = [lgb.early_stopping(stopping_rounds=50)]
    
    booster = lgb.train(
        params=default_params,
        train_set=train_data,
        num_boost_round=n_estimators,
        valid_sets=[val_data],
        callbacks=callbacks
    )
    
    return booster

def train_all_models(df: pd.DataFrame, horizons: List[int], quantiles: List[float], output_dir: str) -> Dict[str, Any]:
    """
    Trains models for each horizon and quantile combination.
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    
    target_col = 'cpu_usage'  
    feature_cols = [c for c in df.columns if c != target_col]
    
    train_size = int(len(df) * 0.8)
    train_df = df.iloc[:train_size]
    val_df = df.iloc[train_size:]
    
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]
    
    for h in horizons:
        y_train_h = train_df[target_col].shift(-h)
        y_val_h = val_df[target_col].shift(-h)
        
        valid_train = y_train_h.notna()
        valid_val = y_val_h.notna()
        
        X_t, y_t = X_train[valid_train], y_train_h[valid_train]
        X_v, y_v = X_val[valid_val], y_val_h[valid_val]
        
        for q in quantiles:
            logger.info(f"Training model for horizon {h}min, quantile {q}")
            booster = train_quantile_model(X_t, y_t, X_v, y_v, quantile=q)
            
            model_name = f"model_{h}min_q{q}"
            model_path = os.path.join(output_dir, f"{model_name}.txt")
            meta_path = os.path.join(output_dir, f"{model_name}_meta.json")
            
            booster.save_model(model_path)
            
            metadata = {
                "horizon_minutes": h,
                "quantile": q,
                "features": feature_cols,
                "model_path": model_path
            }
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)
                
            results[model_name] = {
                "model_path": model_path,
                "metadata_path": meta_path
            }
            
    return results

def export_to_onnx(model: lgb.Booster, feature_names: List[str], output_path: str) -> None:
    """
    Convert LightGBM model to ONNX format.
    """
    try:
        from onnxmltools import convert_lightgbm
        from skl2onnx.common.data_types import FloatTensorType
        
        initial_types = [('float_input', FloatTensorType([None, len(feature_names)]))]
        onnx_model = convert_lightgbm(model, initial_types=initial_types, target_opset=12)
        
        with open(output_path, "wb") as f:
            f.write(onnx_model.SerializeToString())
            
        logger.info(f"Exported model to ONNX at {output_path}")
    except ImportError:
        logger.warning("onnxmltools or skl2onnx not installed, skipping ONNX export.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train LightGBM models.")
    parser.add_argument("--data", required=True, help="Path to preprocessed features data")
    parser.add_argument("--output-dir", required=True, help="Directory to save models")
    parser.add_argument("--horizons", type=str, default="5,10,15", help="Comma-separated horizons in minutes")
    parser.add_argument("--quantiles", type=str, default="0.1,0.5,0.9", help="Comma-separated quantiles")
    
    args = parser.parse_args()
    
    df = pd.read_csv(args.data) if args.data.endswith('.csv') else pd.read_parquet(args.data)
    horizons = [int(h) for h in args.horizons.split(',')]
    quantiles = [float(q) for q in args.quantiles.split(',')]
    
    train_all_models(df, horizons, quantiles, args.output_dir)
