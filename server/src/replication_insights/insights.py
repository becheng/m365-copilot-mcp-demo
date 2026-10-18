import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .mock_data import make_snapshot
from .models import (
    DatabaseDetails,
    DatabasePage,
    DatabaseQuery,
    DatabaseRecord,
    EstateSummary,
    HealthDimension,
    HealthStatus,
    HistoryQuery,
    IncidentPage,
    MetricHistory,
    MetricPoint,
    Snapshot,
    SnapshotContext,
    SnapshotRequest,
)

SEVERITY: dict[HealthStatus, int] = {"healthy": 0, "unknown": 1, "warning": 2, "critical": 3}


def evaluate_health(record: DatabaseRecord, *, as_of: datetime) -> DatabaseRecord:
    def dimension(status: HealthStatus, reason: str) -> HealthDimension:
        return HealthDimension(status=status, reason=reason)

    lag = record.lag_seconds
    health = {
        "lag": dimension(
            "unknown"
            if lag is None
            else "critical"
            if lag > 900
            else "warning"
            if lag > 300
            else "healthy",
            "Lag measurement unavailable"
            if lag is None
            else f"Lag {lag:g} seconds; warning above 300, critical above 900 seconds",
        )
    }
    if record.last_success_at is None:
        health["freshness"] = dimension(
            "unknown", "Last successful synchronization time unavailable"
        )
    else:
        age = (as_of - record.last_success_at).total_seconds()
        if age < 0:
            raise ValueError("Last successful synchronization cannot be after the snapshot")
        health["freshness"] = dimension(
            "warning" if age > record.expected_sync_interval_seconds else "healthy",
            f"Last success {age:g} seconds ago; expected interval {record.expected_sync_interval_seconds} seconds",
        )
    service_status: dict[str, HealthStatus] = {
        "running": "healthy",
        "degraded": "warning",
        "failed": "critical",
        "unknown": "unknown",
    }
    health["service"] = dimension(
        service_status[record.service_health], f"Replication service is {record.service_health}"
    )
    if record.storage_used_gib is None or not record.storage_allocated_gib:
        health["storage"] = dimension(
            "unknown", "Storage usage or positive allocated capacity unavailable"
        )
    else:
        usage = 100 * record.storage_used_gib / record.storage_allocated_gib
        health["storage"] = dimension(
            "critical" if usage >= 90 else "warning" if usage >= 80 else "healthy",
            f"Storage utilization {usage:g}%; warning at 80%, critical at 90%",
        )
    return record.model_copy(
        update={
            "health": health,
            "status": max((value.status for value in health.values()), key=SEVERITY.__getitem__),
        }
    )


def context(snapshot: Snapshot) -> dict:
    return SnapshotContext.model_validate(
        snapshot.model_dump(include=set(SnapshotContext.model_fields))
    ).model_dump()


class InsightsService:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.clock = clock

    def snapshot(self, request: SnapshotRequest) -> Snapshot:
        now = self.clock().astimezone(UTC).replace(microsecond=0)
        reference = now
        if request.snapshot_id is not None:
            match = re.fullmatch(
                r"v1:(healthy|lagging|outage|capacity):([0-9]{1,11})", request.snapshot_id
            )
            if not match:
                raise ValueError("Invalid snapshot identifier")
            if match[1] != request.scenario_id:
                raise ValueError("Snapshot belongs to a different scenario")
            try:
                reference = datetime.fromtimestamp(int(match[2]), UTC)
            except (ValueError, OverflowError, OSError) as error:
                raise ValueError("Invalid snapshot reference time") from error
            if reference > now:
                raise ValueError("Snapshot reference time cannot be in the future")
        snapshot = make_snapshot(request.scenario_id, as_of=reference)
        snapshot.databases = [
            evaluate_health(record, as_of=reference) for record in snapshot.databases
        ]
        return snapshot

    def summary(self, request: SnapshotRequest) -> EstateSummary:
        snapshot = self.snapshot(request)
        return EstateSummary(
            **context(snapshot),
            total_databases=len(snapshot.databases),
            health_counts={
                status: sum(record.status == status for record in snapshot.databases)
                for status in SEVERITY
            },
            stale_databases=sum(
                record.health["freshness"].status == "warning" for record in snapshot.databases
            ),
            failed_runs_24h=sum(record.failed_runs_24h for record in snapshot.databases),
        )

    def databases(self, query: DatabaseQuery) -> DatabasePage:
        snapshot = self.snapshot(query)
        records = [
            record
            for record in snapshot.databases
            if (query.status is None or record.status == query.status)
            and (query.environment is None or record.environment == query.environment)
        ]
        return DatabasePage(
            **context(snapshot),
            items=records[query.offset : query.offset + query.limit],
            total=len(records),
            offset=query.offset,
            limit=query.limit,
        )

    def database(self, request: SnapshotRequest, database_id: str) -> DatabaseDetails:
        snapshot = self.snapshot(request)
        record = next((record for record in snapshot.databases if record.id == database_id), None)
        if record is None:
            raise ValueError(f"Unknown database identifier: {database_id}")
        return DatabaseDetails(
            **context(snapshot),
            database=record,
            incidents=[
                incident for incident in snapshot.incidents if incident.database_id == database_id
            ],
        )

    def incidents(self, request: SnapshotRequest, database_id: str | None = None) -> IncidentPage:
        snapshot = self.snapshot(request)
        if database_id is not None:
            self.database(request, database_id)
        return IncidentPage(
            **context(snapshot),
            items=[
                incident
                for incident in snapshot.incidents
                if database_id is None or incident.database_id == database_id
            ],
        )

    def history(self, query: HistoryQuery) -> MetricHistory:
        details = self.database(query, query.database_id)
        current: float | None = getattr(details.database, query.metric)
        points = [
            MetricPoint(
                at=details.as_of - timedelta(hours=query.hours * (24 - index) / 24),
                value=None
                if current is None
                else round(current * (1 - 0.75 * query.hours * (24 - index) / (24 * 24)), 3),
            )
            for index in range(25)
        ]
        units = {
            "lag_seconds": "seconds",
            "throughput_mib_per_second": "MiB/s",
            "storage_used_gib": "GiB",
        }
        return MetricHistory(
            **details.model_dump(include=set(SnapshotContext.model_fields)),
            database_id=query.database_id,
            metric=query.metric,
            hours=query.hours,
            unit=units[query.metric],
            points=points,
        )
