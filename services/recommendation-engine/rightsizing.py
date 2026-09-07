class RightSizer:
    def __init__(self, target_quantile: float, history_days: int):
        self.target_quantile = target_quantile
        self.history_days = history_days

    def compute_suggestion(self, historical_usage: list) -> dict:
        # TODO: compute q95 of observed usage over 14 days
        # Suggest new requests/limits based on the quantile
        return {"cpu_requests": 0.0, "memory_requests": 0.0}
