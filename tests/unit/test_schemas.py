import pytest
from services.shared.schemas import (
    WorkloadInfo, NodeInfo, MetricPoint, PredictionResult,
    DecisionPlan, ReplicaChange, PlacementDecision, NodePowerChange
)
from datetime import datetime
from uuid import uuid4

class TestSchemas:
    def test_workload_info_creation(self):
        w = WorkloadInfo(
            id=uuid4(), name='web-app', namespace='default',
            kind='Deployment', target_cpu=0.7, target_memory=0.8,
            min_replicas=2, max_replicas=20, slo_target_ms=200.0
        )
        assert w.name == 'web-app'
        assert w.min_replicas == 2

    def test_workload_min_max_validation(self):
        """min_replicas must be <= max_replicas."""
        with pytest.raises(Exception):
            WorkloadInfo(
                id=uuid4(), name='test', namespace='default',
                kind='Deployment', target_cpu=0.7, target_memory=0.8,
                min_replicas=20, max_replicas=2, slo_target_ms=200.0
            )

    def test_decision_plan_creation(self):
        plan = DecisionPlan(
            id=uuid4(), timestamp=datetime.utcnow(), cycle_id=uuid4(),
            solver_type='cpsat', objective_value=42.5, solve_time_ms=150.0,
            replica_changes=[], placement_decisions=[], node_power_changes=[],
            status='planned'
        )
        assert plan.solver_type == 'cpsat'

    def test_replica_change(self):
        rc = ReplicaChange(
            workload_id=uuid4(), current_replicas=3,
            target_replicas=5, reason='predicted demand increase'
        )
        assert rc.target_replicas == 5

    def test_metric_point(self):
        mp = MetricPoint(
            timestamp=datetime.utcnow(), workload_id=uuid4(),
            cpu_usage=0.65, memory_usage=0.45,
            network_rx=1000.0, network_tx=500.0,
            disk_iops=50.0, request_rate=100.0,
            pod_count=3
        )
        assert 0 <= mp.cpu_usage <= 1.0
