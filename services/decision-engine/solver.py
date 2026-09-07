class CPSolver:
    def __init__(self, timeout_ms: int):
        self.timeout_ms = timeout_ms

    def solve(self, workloads, nodes, predictions):
        # TODO: Setup OR-Tools CP-SAT model
        # Add constraints from constraints.py
        # Optimize for energy
        pass
