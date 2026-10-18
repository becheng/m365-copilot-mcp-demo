from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

AS_OF = datetime(2026, 10, 18, 21, 0, tzinfo=UTC)


def service():
    from replication_insights.insights import InsightsService

    return InsightsService(clock=lambda: AS_OF)


@pytest.mark.parametrize(
    "metric",
    [
        "lag_seconds",
        "throughput_mib_per_second",
        "storage_used_gib",
    ],
)
def test_history_windows_agree_at_overlapping_snapshot_timestamps(metric):
    from replication_insights.models import HistoryQuery

    histories = [
        service().history(
            HistoryQuery(
                scenario_id="lagging",
                snapshot_id="v1:lagging:1792357200",
                database_id="orders",
                metric=metric,
                hours=hours,
            )
        )
        for hours in (1, 6, 24)
    ]
    canonical = {point.at: point.value for point in histories[-1].points}
    for history in histories[:-1]:
        overlap = [point for point in history.points if point.at in canonical]
        assert len(overlap) >= 2
        assert all(point.value == canonical[point.at] for point in overlap)


def test_repeatable_snapshots_and_scenario_isolation():
    from replication_insights.models import SnapshotRequest

    insights = service()
    first = insights.snapshot(SnapshotRequest(scenario_id="healthy"))
    insights.snapshot(SnapshotRequest(scenario_id="outage"))
    second = insights.snapshot(SnapshotRequest(scenario_id="healthy"))
    assert first == second
    assert len(first.databases) == 6
    assert first.simulated is True
    assert first.databases[0].status == "healthy"


def test_snapshot_cannot_be_reinterpreted_as_another_scenario():
    from replication_insights.models import SnapshotRequest

    snapshot = service().snapshot(SnapshotRequest(scenario_id="healthy"))
    with pytest.raises(ValueError, match="scenario"):
        service().snapshot(SnapshotRequest(scenario_id="outage", snapshot_id=snapshot.snapshot_id))


@pytest.mark.parametrize(
    "seconds,want",
    [(300, "healthy"), (301, "warning"), (900, "warning"), (901, "critical"), (None, "unknown")],
)
def test_lag_thresholds(seconds, want):
    from replication_insights.insights import evaluate_health
    from replication_insights.models import SnapshotRequest

    record = service().snapshot(SnapshotRequest(scenario_id="healthy")).databases[0]
    record = record.model_copy(update={"lag_seconds": seconds})
    result = evaluate_health(record, as_of=AS_OF)
    assert result.health["lag"].status == want


@pytest.mark.parametrize(
    "used,allocated,want",
    [
        (79.99, 100, "healthy"),
        (80, 100, "warning"),
        (90, 100, "critical"),
        (0, 0, "unknown"),
        (None, 100, "unknown"),
        (10, None, "unknown"),
    ],
)
def test_storage_thresholds_and_unknown_capacity(used, allocated, want):
    from replication_insights.insights import evaluate_health
    from replication_insights.models import SnapshotRequest

    record = service().snapshot(SnapshotRequest(scenario_id="healthy")).databases[0]
    record = record.model_copy(
        update={"storage_used_gib": used, "storage_allocated_gib": allocated}
    )
    result = evaluate_health(record, as_of=AS_OF)
    assert result.health["storage"].status == want
    assert result.health["storage"].reason


def test_freshness_is_distinct_from_lag_and_has_exact_interval_boundary():
    from replication_insights.insights import evaluate_health
    from replication_insights.models import SnapshotRequest

    record = service().snapshot(SnapshotRequest(scenario_id="healthy")).databases[0]
    record = record.model_copy(
        update={
            "last_success_at": AS_OF - timedelta(seconds=record.expected_sync_interval_seconds),
            "lag_seconds": 30,
        }
    )
    assert evaluate_health(record, as_of=AS_OF).health["freshness"].status == "healthy"
    record = record.model_copy(
        update={"last_success_at": record.last_success_at - timedelta(seconds=1)}
    )
    result = evaluate_health(record, as_of=AS_OF)
    assert result.health["freshness"].status == "warning"
    assert result.health["lag"].status == "healthy"


def test_failed_service_is_critical_even_when_other_metrics_are_missing():
    from replication_insights.insights import evaluate_health
    from replication_insights.models import SnapshotRequest

    record = service().snapshot(SnapshotRequest(scenario_id="healthy")).databases[0]
    result = evaluate_health(
        record.model_copy(
            update={
                "service_health": "failed",
                "lag_seconds": None,
            }
        ),
        as_of=AS_OF,
    )
    assert result.status == "critical"
    assert result.health["service"].status == "critical"
    assert result.health["lag"].status == "unknown"


def test_summary_details_history_and_pagination_share_a_snapshot():
    from replication_insights.models import DatabaseQuery, HistoryQuery, SnapshotRequest

    insights = service()
    request = SnapshotRequest(scenario_id="lagging")
    summary = insights.summary(request)
    request = request.model_copy(update={"snapshot_id": summary.snapshot_id})
    page = insights.databases(DatabaseQuery(**request.model_dump(), limit=2))
    detail = insights.database(request, "orders")
    history = insights.history(
        HistoryQuery(**request.model_dump(), database_id="orders", metric="lag_seconds", hours=24)
    )
    assert summary.total_databases == 6
    assert sum(summary.health_counts.values()) == 6
    assert page.total == 6
    assert len(page.items) == 2
    assert detail.database.lag_seconds == 1320
    assert history.points[-1].value == 1320
    assert history.points[-1].at == AS_OF
    assert history.snapshot_id == detail.snapshot_id == page.snapshot_id == summary.snapshot_id
    assert len(history.points) == 25
    assert len(insights.incidents(request, "orders").items) == 1


def test_invalid_identifiers_and_input_bounds_fail_explicitly():
    from replication_insights.models import DatabaseQuery, HistoryQuery, SnapshotRequest

    with pytest.raises(ValidationError):
        SnapshotRequest(scenario_id="made-up")
    with pytest.raises(ValidationError):
        DatabaseQuery(scenario_id="healthy", limit=101)
    with pytest.raises(ValidationError):
        DatabaseQuery(scenario_id="healthy", offset=-1)
    with pytest.raises(ValidationError):
        HistoryQuery(scenario_id="healthy", database_id="orders", metric="lag_seconds", hours=1000)
    with pytest.raises(ValueError, match="database"):
        service().database(SnapshotRequest(scenario_id="healthy"), "missing")
    with pytest.raises(ValueError, match="snapshot"):
        service().snapshot(SnapshotRequest(scenario_id="healthy", snapshot_id="invalid"))
    with pytest.raises(ValueError, match="future"):
        service().snapshot(
            SnapshotRequest(
                scenario_id="healthy", snapshot_id=f"v1:healthy:{int(AS_OF.timestamp()) + 60}"
            )
        )


def test_unknown_history_stays_missing_and_filters_can_be_empty():
    from replication_insights.models import DatabaseQuery, HistoryQuery

    page = service().databases(DatabaseQuery(scenario_id="healthy", status="critical"))
    assert page.total == 0
    assert page.items == []
    history = service().history(
        HistoryQuery(
            scenario_id="capacity", database_id="archive", metric="storage_used_gib", hours=1
        )
    )
    assert all(point.value is None for point in history.points)
