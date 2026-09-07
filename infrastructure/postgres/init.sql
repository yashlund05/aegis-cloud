CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workloads (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    kind VARCHAR(50) NOT NULL,
    target_cpu FLOAT,
    target_memory FLOAT,
    min_replicas INT DEFAULT 1,
    max_replicas INT DEFAULT 50,
    slo_target_ms FLOAT,
    policy JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, namespace)
);

CREATE TABLE IF NOT EXISTS nodes (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    cpu_capacity FLOAT,
    memory_capacity FLOAT,
    gpu_capacity FLOAT DEFAULT 0,
    p_idle FLOAT DEFAULT 100,
    p_max FLOAT DEFAULT 300,
    alpha FLOAT DEFAULT 1.5,
    labels JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics_raw (
    ts TIMESTAMPTZ NOT NULL,
    workload_id UUID REFERENCES workloads(id) ON DELETE CASCADE,
    node_id UUID REFERENCES nodes(id) ON DELETE SET NULL,
    cpu_usage FLOAT,
    memory_usage FLOAT,
    network_rx FLOAT,
    network_tx FLOAT,
    disk_iops FLOAT,
    request_rate FLOAT,
    pod_count INT,
    latency_p50 FLOAT,
    latency_p95 FLOAT,
    latency_p99 FLOAT
);

SELECT create_hypertable('metrics_raw', 'ts');

CREATE TABLE IF NOT EXISTS model_registry (
    id UUID PRIMARY KEY,
    model_name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    training_dataset VARCHAR(255),
    training_timestamp TIMESTAMPTZ,
    features JSONB,
    quantile FLOAT,
    horizon_minutes INT,
    metrics JSONB,
    status VARCHAR(20) DEFAULT 'training',
    artifact_path VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(model_name, version)
);

CREATE TABLE IF NOT EXISTS predictions (
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    workload_id UUID REFERENCES workloads(id),
    model_version UUID REFERENCES model_registry(id),
    horizon_minutes INT,
    quantile FLOAT,
    predicted_value FLOAT,
    actual_value FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    cycle_id UUID,
    solver_type VARCHAR(10) NOT NULL,
    objective_value FLOAT,
    solve_time_ms FLOAT,
    plan JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS actions (
    id UUID PRIMARY KEY,
    decision_id UUID REFERENCES decisions(id),
    action_type VARCHAR(20) NOT NULL,
    target VARCHAR(255),
    details JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    workload_id UUID REFERENCES workloads(id),
    node_id UUID REFERENCES nodes(id),
    message TEXT,
    metadata JSONB,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_metrics_raw_workload_ts ON metrics_raw(workload_id, ts DESC);
CREATE INDEX idx_predictions_ts_workload ON predictions(ts, workload_id);
CREATE INDEX idx_decisions_ts ON decisions(ts);
CREATE INDEX idx_model_registry_name_status ON model_registry(model_name, status);

SELECT add_retention_policy('metrics_raw', INTERVAL '30 days');

INSERT INTO users (username, password_hash, role) VALUES ('admin', 'changeme', 'admin');
