from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from uuid import UUID

class WorkloadInfo(BaseModel):
    id: Union[UUID, str]
    name: str
    namespace: str
    kind: str
    target_cpu: float
    target_memory: float
    min_replicas: int = Field(default=1, ge=1)
    max_replicas: int = Field(default=50, ge=1)
    slo_target_ms: float = 200.0

    @model_validator(mode='after')
    def check_min_max(self):
        if self.min_replicas > self.max_replicas:
            raise ValueError("min_replicas must be less than or equal to max_replicas")
        return self

class NodeInfo(BaseModel):
    id: Union[UUID, str]
    name: str
    cpu_capacity: float
    memory_capacity: float
    p_idle: float
    p_max: float
    alpha: float
    status: str

class MetricPoint(BaseModel):
    timestamp: datetime
    workload_id: Union[UUID, str]
    node_id: Optional[Union[UUID, str]] = None
    cpu_usage: float
    memory_usage: float
    network_rx: float
    network_tx: float
    disk_iops: float
    request_rate: float
    pod_count: int
    latency_p50: Optional[float] = None
    latency_p95: Optional[float] = None
    latency_p99: Optional[float] = None

class PredictionResult(BaseModel):
    workload_id: Union[UUID, str]
    timestamp: datetime
    horizon_minutes: int
    quantile: Union[float, str]
    predicted_value: float
    model_version: str

class ReplicaChange(BaseModel):
    workload_id: Union[UUID, str]
    current_replicas: int
    target_replicas: int
    reason: str

class PlacementDecision(BaseModel):
    pod_name: str
    target_node: str
    score: float
    reason: str

class NodePowerChange(BaseModel):
    node_id: str
    action: str
    reason: str

class DecisionPlan(BaseModel):
    id: Union[UUID, str]
    timestamp: datetime
    cycle_id: Union[UUID, str]
    solver_type: str
    objective_value: float
    solve_time_ms: float
    replica_changes: List[ReplicaChange]
    placement_decisions: List[PlacementDecision]
    node_power_changes: List[NodePowerChange]
    status: str

class ActionResult(BaseModel):
    id: str
    decision_id: str
    action_type: str
    target: str
    status: str
    error_message: Optional[str] = None
    completed_at: datetime

class AlertInfo(BaseModel):
    id: str
    timestamp: datetime
    alert_type: str
    severity: str
    workload_id: Optional[str] = None
    node_id: Optional[str] = None
    message: str

class ModelInfo(BaseModel):
    id: str
    name: str
    version: str
    quantile: str
    horizon_minutes: int
    status: str
    metrics: Dict[str, Any]
    artifact_path: str
