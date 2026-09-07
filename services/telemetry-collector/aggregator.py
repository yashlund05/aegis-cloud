class Aggregator:
    def __init__(self, outlier_percentile: float = 99.9):
        self.outlier_percentile = outlier_percentile

    def aggregate_workload(self, raw_metrics: dict) -> dict:
        # TODO: Per-workload aggregation, normalization
        # TODO: Outlier clipping at self.outlier_percentile
        return {}
