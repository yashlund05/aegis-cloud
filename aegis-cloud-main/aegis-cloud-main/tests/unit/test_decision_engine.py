import pytest
from services.decision_engine.ffd import first_fit_decreasing

class TestFFDFallback:
    def test_single_pod_single_node(self):
        pods = [{'name': 'pod-1', 'cpu_request': 0.2, 'memory_request': 0.3}]
        nodes = [{'name': 'node-1', 'cpu_available': 1.0, 'memory_available': 1.0}]
        result = first_fit_decreasing(pods, nodes)
        assert len(result) == 1
        assert result[0]['pod_name'] == 'pod-1'
        assert result[0]['target_node'] == 'node-1'

    def test_multiple_pods_bin_packing(self):
        pods = [
            {'name': 'pod-1', 'cpu_request': 0.5, 'memory_request': 0.3},
            {'name': 'pod-2', 'cpu_request': 0.3, 'memory_request': 0.2},
            {'name': 'pod-3', 'cpu_request': 0.4, 'memory_request': 0.5},
        ]
        nodes = [
            {'name': 'node-1', 'cpu_available': 0.8, 'memory_available': 0.8},
            {'name': 'node-2', 'cpu_available': 0.8, 'memory_available': 0.8},
        ]
        result = first_fit_decreasing(pods, nodes)
        assert len(result) == 3
        # All pods should be placed
        placed_pods = {r['pod_name'] for r in result}
        assert placed_pods == {'pod-1', 'pod-2', 'pod-3'}

    def test_unplaceable_pod_marked(self):
        pods = [{'name': 'pod-1', 'cpu_request': 2.0, 'memory_request': 0.1}]
        nodes = [{'name': 'node-1', 'cpu_available': 1.0, 'memory_available': 1.0}]
        result = first_fit_decreasing(pods, nodes)
        assert len(result) == 1
        assert result[0]['target_node'] is None  # unplaceable

    def test_empty_inputs(self):
        assert first_fit_decreasing([], []) == []
        assert first_fit_decreasing([], [{'name': 'n1', 'cpu_available': 1.0, 'memory_available': 1.0}]) == []

    def test_pods_sorted_by_size_descending(self):
        """FFD should sort pods by size (descending) before placing."""
        pods = [
            {'name': 'small', 'cpu_request': 0.1, 'memory_request': 0.1},
            {'name': 'large', 'cpu_request': 0.9, 'memory_request': 0.9},
            {'name': 'medium', 'cpu_request': 0.5, 'memory_request': 0.5},
        ]
        nodes = [
            {'name': 'node-1', 'cpu_available': 1.0, 'memory_available': 1.0},
            {'name': 'node-2', 'cpu_available': 1.0, 'memory_available': 1.0},
        ]
        result = first_fit_decreasing(pods, nodes)
        assert len(result) == 3
