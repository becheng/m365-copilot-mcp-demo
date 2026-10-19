import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter
from replication_insights.models import (
    DashboardPayload,
    DatabaseDetails,
    DatabasePage,
    DatabaseQuery,
    EstateSummary,
    HistoryQuery,
    IncidentPage,
    MetricHistory,
    ScenarioCatalogue,
    SnapshotRequest,
)

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
schema = TypeAdapter(
    DashboardPayload
    | DatabaseDetails
    | DatabasePage
    | EstateSummary
    | MetricHistory
    | IncidentPage
    | ScenarioCatalogue
    | SnapshotRequest
    | DatabaseQuery
    | HistoryQuery
).json_schema()
schema["title"] = "PublicContracts"
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
content = json.dumps(schema, indent=2) + "\n"
target = (
    Path(__file__).resolve().parents[1] / "dashboard" / "schemas" / "responses.json"
)
if args.check:
    if not target.is_file() or target.read_text(encoding="utf-8") != content:
        raise SystemExit("Public schemas are stale; run scripts\\export-contracts.py")
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
