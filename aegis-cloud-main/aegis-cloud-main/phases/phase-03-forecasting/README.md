# Phase 3: Forecasting

## Purpose
Train models to forecast resource utilization and energy consumption.

## Prerequisites
- Python 3.10+
- LightGBM, Prophet, pandas, scikit-learn

## Files
- train.sh
- evaluate.sh
- verify.sh

## Implementation
Completes ML feature engineering, model training, and evaluation.
Models use P10, P50, and P90 quantiles.

## How to run
\ash train.sh\

## How to test
\ash evaluate.sh\

## Expected output
Trained models stored in ml/models/artifacts.

## Verification
Returns PASS.

## Definition of Done
Quantile models are trained and evaluation metrics are computed successfully.

## Known limitations
None.
