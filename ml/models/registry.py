"""
Model registry module for Aegis.
"""
import json
import os
import uuid
from typing import List

class ModelRegistry:
    def __init__(self, registry_path: str = 'ml/models/registry.json'):
        self.registry_path = registry_path
        self._ensure_registry_exists()
        
    def _ensure_registry_exists(self):
        if not os.path.exists(self.registry_path):
            os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
            with open(self.registry_path, 'w') as f:
                json.dump({"models": {}}, f)
                
    def _load_registry(self) -> dict:
        with open(self.registry_path, 'r') as f:
            return json.load(f)
            
    def _save_registry(self, data: dict):
        with open(self.registry_path, 'w') as f:
            json.dump(data, f, indent=2)

    def register_model(self, model_info: dict) -> str:
        """Add model to registry, return version ID."""
        data = self._load_registry()
        version_id = str(uuid.uuid4())
        model_info['version_id'] = version_id
        if 'status' not in model_info:
            model_info['status'] = 'training'
            
        data['models'][version_id] = model_info
        self._save_registry(data)
        return version_id

    def get_active_model(self, model_name: str, quantile: float, horizon: int) -> dict:
        """Get currently active model."""
        data = self._load_registry()
        for v_id, m in data['models'].items():
            if m.get('model_name') == model_name and \
               m.get('quantile') == quantile and \
               m.get('horizon_minutes') == horizon and \
               m.get('status') == 'active':
                return m
        return None

    def promote_model(self, version_id: str):
        """Set model status to active, retire previous."""
        data = self._load_registry()
        if version_id not in data['models']:
            raise ValueError("Model not found in registry")
            
        target = data['models'][version_id]
        # Retire current active
        for v_id, m in data['models'].items():
            if m.get('model_name') == target.get('model_name') and \
               m.get('quantile') == target.get('quantile') and \
               m.get('horizon_minutes') == target.get('horizon_minutes') and \
               m.get('status') == 'active':
                m['status'] = 'retired'
                
        target['status'] = 'active'
        self._save_registry(data)

    def retire_model(self, version_id: str):
        data = self._load_registry()
        if version_id in data['models']:
            data['models'][version_id]['status'] = 'retired'
            self._save_registry(data)

    def list_models(self, model_name: str = None, status: str = None) -> List[dict]:
        data = self._load_registry()
        results = []
        for v_id, m in data['models'].items():
            if model_name and m.get('model_name') != model_name:
                continue
            if status and m.get('status') != status:
                continue
            results.append(m)
        return results
