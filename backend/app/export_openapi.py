"""Export the API's OpenAPI schema to a JSON file, for the frontend's type generation.

Usage (from backend/):
    uv run python -m app.export_openapi ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import app


def write_openapi_schema(path: Path) -> None:
    """Write the app's OpenAPI schema to path as indented JSON."""
    schema = app.openapi()
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Command-line entry point: write the schema to the path given as the first argument"""
    write_openapi_schema(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
