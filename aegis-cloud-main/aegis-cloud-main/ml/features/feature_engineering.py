"""
Feature engineering module for Aegis ML pipeline.
"""

import pandas as pd
import numpy as np

def build_features(df: pd.DataFrame, feature_window: int = 60) -> pd.DataFrame:
    """
    Builds time, rolling, lag, and cross features for the dataset.
    Expects df to have a datetime index or a 'timestamp' column.
    """
    df_out = df.copy()
    
    if 'timestamp' in df_out.columns:
        df_out['timestamp'] = pd.to_datetime(df_out['timestamp'])
        df_out.set_index('timestamp', inplace=True)
        
    if not isinstance(df_out.index, pd.DatetimeIndex):
        raise ValueError("DataFrame must have a DatetimeIndex.")
        
    df_out['hour_of_day'] = df_out.index.hour
    df_out['day_of_week'] = df_out.index.dayofweek
    df_out['is_weekend'] = (df_out.index.dayofweek >= 5).astype(int)
    df_out['minute_of_hour'] = df_out.index.minute
    
    cpu_col = 'cpu_usage' if 'cpu_usage' in df_out.columns else None
    mem_col = 'memory_usage' if 'memory_usage' in df_out.columns else None
    
    if cpu_col:
        df_out['rolling_mean_15min'] = df_out[cpu_col].rolling('15min').mean()
        df_out['rolling_std_15min'] = df_out[cpu_col].rolling('15min').std()
        df_out['rolling_mean_60min'] = df_out[cpu_col].rolling('60min').mean()
        df_out['rolling_std_60min'] = df_out[cpu_col].rolling('60min').std()
        df_out['cpu_rolling_mean_15'] = df_out['rolling_mean_15min']
        df_out['cpu_rolling_std_15'] = df_out['rolling_std_15min']
        df_out['cpu_rolling_mean_60'] = df_out['rolling_mean_60min']
        df_out['cpu_rolling_std_60'] = df_out['rolling_std_60min']
        
        for i in range(1, 11):
            df_out[f'lag_{i}'] = df_out[cpu_col].shift(i)
            df_out[f'cpu_lag_{i}'] = df_out[f'lag_{i}']
            
        df_out['cpu_rate_of_change'] = df_out[cpu_col].diff()
        
    if mem_col:
        df_out['mem_rolling_mean_15min'] = df_out[mem_col].rolling('15min').mean()
        df_out['mem_rolling_std_15min'] = df_out[mem_col].rolling('15min').std()
        df_out['mem_rolling_mean_60min'] = df_out[mem_col].rolling('60min').mean()
        df_out['mem_rolling_std_60min'] = df_out[mem_col].rolling('60min').std()
        
        df_out['memory_rate_of_change'] = df_out[mem_col].diff()
        
    if cpu_col and mem_col:
        df_out['cpu_memory_ratio'] = df_out[cpu_col] / (df_out[mem_col] + 1e-9)
        
    df_out.dropna(inplace=True)
    
    return df_out

def get_feature_columns() -> list[str]:
    """
    Returns the list of all feature column names.
    """
    cols = [
        'hour_of_day', 'day_of_week', 'is_weekend', 'minute_of_hour',
        'rolling_mean_15min', 'rolling_std_15min', 'rolling_mean_60min', 'rolling_std_60min',
        'cpu_rolling_mean_15', 'cpu_rolling_std_15', 'cpu_rolling_mean_60', 'cpu_rolling_std_60',
        'cpu_rate_of_change', 'memory_rate_of_change', 'cpu_memory_ratio',
        'mem_rolling_mean_15min', 'mem_rolling_std_15min', 'mem_rolling_mean_60min', 'mem_rolling_std_60min'
    ]
    for i in range(1, 11):
        cols.append(f'lag_{i}')
        cols.append(f'cpu_lag_{i}')
    return cols

def get_target_column(metric: str = 'cpu_usage') -> str:
    """
    Returns the target column name based on metric.
    """
    return metric
