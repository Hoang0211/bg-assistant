import json
from pathlib import Path

from app.export_openapi import write_openapi_schema


def test_write_openapi_schema_includes_health_endpoint(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"
    write_openapi_schema(output)

    schema = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/health" in schema["paths"]
