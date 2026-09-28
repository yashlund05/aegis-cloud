# Database and Data Schema

## 1. Relational Schema (PostgreSQL + TimescaleDB)

### `users`
- `id`: UUID (PK)
- `username`: VARCHAR (UNIQUE)
- `email`: VARCHAR
- `password_hash`: VARCHAR
- `role`: ENUM ('admin', 'operator', 'viewer')
- `created_at`: TIMESTAMPTZ
- `updated_at`: TIMESTAMPTZ
- `last_login`: TIMESTAMPTZ

### `workloads`
- `id`: UUID (PK)
- `name`: VARCHAR
- `namespace`: VARCHAR
- `kind`: VARCHAR (Deployment/StatefulSet)
- `target_cpu`: INT
- `target_memory`: INT
- `min_replicas`: INT
- `max_replicas`: INT
- `slo_target_ms`: INT
- `policy`: JSONB
- `created_at`: TIMESTAMPTZ
- `updated_at`: TIMESTAMPTZ

### `nodes`
- `id`: UUID (PK)
- `name`: VARCHAR (UNIQUE)
- `cpu_capacity`: INT
- `memory_capacity`: BIGINT
- `gpu_capacity`: INT
- `p_idle`: FLOAT
- `p_max`: FLOAT
- `alpha`: FLOAT
- `labels`: JSONB
- `status`: VARCHAR
- `created_at`: TIMESTAMPTZ
- `updated_at`: TIMESTAMPTZ

### `metrics_raw` (TimescaleDB Hypertable)
- `ts`: TIMESTAMPTZ (Part of PK)
- `workload_id`: UUID (FK to workloads)
- `node_id`: UUID (FK to nodes)
- `cpu_usage`: FLOAT
- `memory_usage`: BIGINT
- `network_rx`: BIGINT
- `network_tx`: BIGINT
- `disk_iops`: INT
- `request_rate`: FLOAT
- `pod_count`: INT
- `latency_p50`: FLOAT
- `latency_p95`: FLOAT
- `latency_p99`: FLOAT

### `predictions`
- `id`: UUID (PK)
- `ts`: TIMESTAMPTZ
- `workload_id`: UUID (FK to workloads)
- `model_version`: UUID (FK to model_registry)
- `horizon_minutes`: INT
- `quantile`: FLOAT
- `predicted_value`: FLOAT
- `actual_value`: FLOAT (Nullable, filled by async process)
- `created_at`: TIMESTAMPTZ

### `decisions`
- `id`: UUID (PK)
- `ts`: TIMESTAMPTZ
- `cycle_id`: UUID
- `solver_type`: ENUM ('cpsat', 'ffd')
- `objective_value`: FLOAT
- `solve_time_ms`: INT
- `plan`: JSONB
- `status`: ENUM ('planned', 'executing', 'completed', 'failed', 'rejected')
- `created_at`: TIMESTAMPTZ

### `actions`
- `id`: UUID (PK)
- `decision_id`: UUID (FK to decisions)
- `action_type`: ENUM ('scale', 'place', 'power', 'rightsizing')
- `target`: VARCHAR
- `details`: JSONB
- `status`: ENUM ('pending', 'executing', 'completed', 'failed')
- `error_message`: TEXT
- `created_at`: TIMESTAMPTZ
- `completed_at`: TIMESTAMPTZ

### `alerts`
- `id`: UUID (PK)
- `ts`: TIMESTAMPTZ
- `alert_type`: ENUM ('drift', 'anomaly', 'slo_breach', 'saturation', 'stale_telemetry')
- `severity`: VARCHAR
- `workload_id`: UUID (FK nullable)
- `node_id`: UUID (FK nullable)
- `message`: TEXT
- `metadata`: JSONB
- `acknowledged`: BOOLEAN
- `created_at`: TIMESTAMPTZ

### `model_registry`
- `id`: UUID (PK)
- `model_name`: VARCHAR
- `version`: VARCHAR
- `training_dataset`: VARCHAR
- `training_timestamp`: TIMESTAMPTZ
- `features`: JSONB
- `quantile`: FLOAT
- `horizon_minutes`: INT
- `metrics`: JSONB (wmape, pinball_loss, coverage)
- `status`: ENUM ('training', 'shadow', 'active', 'retired')
- `artifact_path`: VARCHAR
- `created_at`: TIMESTAMPTZ

## 2. Indexes and Foreign Keys
- **Indexes:** 
  - `metrics_raw(workload_id, ts DESC)`
  - `predictions(ts, workload_id)`
  - `decisions(ts)`
  - `model_registry(model_name, status)`
- **FK Rules:** `ON DELETE CASCADE` for metrics/predictions tied to workloads.

## 3. Data Retention & Aggregation
- `metrics_raw`: 30 days retention (for retraining window).
- **Continuous Aggregation:** Downsample `metrics_raw` to 5-minute rollups after 7 days via TimescaleDB policies.
- `decisions` / `actions`: Indefinite retention for audit purposes.

## 4. Redis Schema
- **Feature Hashes:** `workload:{id}:features` (TTL: 1h). Stores latest feature vectors.
- **Prediction Cache:** `workload:{id}:predictions` (TTL: 1h).
- **Decision Cache:** `cycle:latest:decision` (TTL: 10m).
- **Pub/Sub Channels:** `aegis.events.telemetry`, `aegis.events.alerts`.

## 5. Security / RBAC
- **Authentication:** JWT (HS256 signed).
- **Roles:**
  - `admin`: Full cluster mutation rights.
  - `operator`: Can trigger retrains, clear caches.
  - `viewer`: Read-only dashboard access.
