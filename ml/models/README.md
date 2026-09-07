Model artifact conventions:
- Naming: {model_name}_h{horizon}_q{quantile}_v{version}.txt (LightGBM native)
- Naming: {model_name}_h{horizon}_q{quantile}_v{version}.onnx (ONNX format)
- Metadata: {model_name}_h{horizon}_q{quantile}_v{version}_meta.json
- Metadata fields: model_name, version, training_dataset, training_timestamp, features (list), quantile, horizon_minutes, metrics (wmape, pinball_loss, coverage), status (training/shadow/active/retired), artifact_path, git_commit
- Never commit large model files to git
- Store in ml/models/artifacts/ (gitignored)
