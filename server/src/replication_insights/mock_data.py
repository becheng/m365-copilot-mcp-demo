from datetime import datetime, timedelta

from .models import (
    DatabaseRecord,
    Incident,
    ScenarioCatalogue,
    ScenarioDescriptor,
    ScenarioId,
    Snapshot,
)

SCENARIOS = ScenarioCatalogue(
    scenarios=[
        ScenarioDescriptor(
            id="healthy",
            name="Healthy baseline",
            description="Fresh synchronized databases with normal capacity.",
        ),
        ScenarioDescriptor(
            id="lagging",
            name="Increasing lag",
            description="Orders and inventory replication are falling behind.",
        ),
        ScenarioDescriptor(
            id="outage",
            name="Replication outage",
            description="Finance replication has failed with a simulated connectivity incident.",
        ),
        ScenarioDescriptor(
            id="capacity",
            name="Capacity pressure",
            description="Warehouse and analytics storage pressure, plus missing archive metrics.",
        ),
    ]
)


def make_snapshot(scenario_id: ScenarioId, *, as_of: datetime) -> Snapshot:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Snapshot reference time must be timezone-aware")
    if scenario_id not in {scenario.id for scenario in SCENARIOS.scenarios}:
        raise ValueError("Unknown scenario")
    as_of = as_of.replace(microsecond=0)
    records = []
    for index, name in enumerate(
        ["orders", "finance", "inventory", "warehouse", "archive", "analytics"]
    ):
        records.append(
            DatabaseRecord(
                id=name,
                name=f"Contoso {name.title()}",
                source=f"onprem-sql-{index + 1:02d}/{name}",
                target=f"azure-sql-demo-{index + 1:02d}/{name}",
                engine="SQL Server / Azure SQL (illustrative)",
                replication_method="Simulated replication telemetry",
                environment="staging" if name == "archive" else "production",
                expected_sync_interval_seconds=300,
                last_success_at=as_of - timedelta(seconds=60 + index * 20),
                lag_seconds=30 + index * 15,
                service_health="running",
                storage_used_gib=50 + index * 3,
                storage_allocated_gib=100,
                throughput_mib_per_second=8 + index * 2,
                failed_runs_24h=0,
            )
        )
    by_id = {record.id: record for record in records}
    incidents = []
    if scenario_id == "lagging":
        by_id["orders"].lag_seconds = 1320
        by_id["orders"].last_success_at = as_of - timedelta(minutes=30)
        by_id["orders"].service_health = "degraded"
        by_id["orders"].throughput_mib_per_second = 1.2
        by_id["inventory"].lag_seconds = 480
        by_id["inventory"].last_success_at = as_of - timedelta(minutes=11)
        incidents.append(
            Incident(
                id="lag-orders",
                database_id="orders",
                at=as_of - timedelta(minutes=25),
                severity="critical",
                title="Replication backlog growing",
                description="Simulated source change volume exceeds replication throughput.",
            )
        )
    elif scenario_id == "outage":
        by_id["finance"].service_health = "failed"
        by_id["finance"].lag_seconds = 7200
        by_id["finance"].last_success_at = as_of - timedelta(hours=2)
        by_id["finance"].throughput_mib_per_second = 0
        by_id["finance"].failed_runs_24h = 6
        incidents.append(
            Incident(
                id="outage-finance",
                database_id="finance",
                at=as_of - timedelta(hours=2),
                severity="critical",
                title="Replication connection unavailable",
                description="Simulated network interruption; six unsuccessful runs in the last 24 hours.",
            )
        )
    elif scenario_id == "capacity":
        by_id["warehouse"].storage_used_gib = 94
        by_id["analytics"].storage_used_gib = 85
        by_id["archive"].storage_used_gib = None
        by_id["archive"].storage_allocated_gib = None
        incidents.append(
            Incident(
                id="capacity-warehouse",
                database_id="warehouse",
                at=as_of - timedelta(hours=1),
                severity="critical",
                title="Warehouse capacity threshold exceeded",
                description="Simulated target storage is 94 GiB of 100 GiB allocated.",
            )
        )
    return Snapshot(
        scenario_id=scenario_id,
        snapshot_id=f"v1:{scenario_id}:{int(as_of.timestamp())}",
        as_of=as_of,
        databases=records,
        incidents=incidents,
    )
