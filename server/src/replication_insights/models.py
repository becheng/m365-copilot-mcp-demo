from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ScenarioId = Literal["healthy", "lagging", "outage", "capacity"]
HealthStatus = Literal["healthy", "warning", "critical", "unknown"]
MetricName = Literal["lag_seconds", "throughput_mib_per_second", "storage_used_gib"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SnapshotRequest(Model):
    scenario_id: ScenarioId
    snapshot_id: str | None = Field(default=None, max_length=100)


class DatabaseQuery(SnapshotRequest):
    status: HealthStatus | None = None
    environment: Literal["production", "staging"] | None = None
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=100)


class HistoryQuery(SnapshotRequest):
    database_id: str = Field(min_length=1, max_length=80)
    metric: MetricName
    hours: Literal[1, 6, 24] = 24


class SnapshotContext(Model):
    scenario_id: ScenarioId
    snapshot_id: str
    as_of: AwareDatetime
    simulated: Literal[True] = True


class HealthDimension(Model):
    status: HealthStatus
    reason: str


class DatabaseRecord(Model):
    id: str
    name: str
    source: str
    target: str
    engine: str
    replication_method: str
    environment: Literal["production", "staging"]
    expected_sync_interval_seconds: int = Field(gt=0)
    last_success_at: AwareDatetime | None
    lag_seconds: float | None = Field(ge=0)
    service_health: Literal["running", "degraded", "failed", "unknown"]
    storage_used_gib: float | None = Field(ge=0)
    storage_allocated_gib: float | None = Field(ge=0)
    throughput_mib_per_second: float | None = Field(ge=0)
    failed_runs_24h: int = Field(ge=0)
    health: dict[str, HealthDimension] = Field(default_factory=dict)
    status: HealthStatus = "unknown"


class Incident(Model):
    id: str
    database_id: str
    at: AwareDatetime
    severity: HealthStatus
    title: str
    description: str


class Snapshot(SnapshotContext):
    databases: list[DatabaseRecord]
    incidents: list[Incident]


class EstateSummary(SnapshotContext):
    total_databases: int
    health_counts: dict[str, int]
    stale_databases: int
    failed_runs_24h: int


class DatabasePage(SnapshotContext):
    items: list[DatabaseRecord]
    total: int
    offset: int
    limit: int


class DatabaseDetails(SnapshotContext):
    database: DatabaseRecord
    incidents: list[Incident]


class MetricPoint(Model):
    at: datetime
    value: float | None


class MetricHistory(SnapshotContext):
    database_id: str
    metric: MetricName
    unit: str
    hours: int
    points: list[MetricPoint]


class IncidentPage(SnapshotContext):
    items: list[Incident]


class DashboardPayload(SnapshotContext):
    summary: EstateSummary
    databases: DatabasePage


class ScenarioDescriptor(Model):
    id: ScenarioId
    name: str
    description: str


class ScenarioCatalogue(Model):
    simulated: Literal[True] = True
    scenarios: list[ScenarioDescriptor]
