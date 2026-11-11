"""Run the Docling parse in a child process, so a crash in native code can't stop the backend.

The child runs this module: python -m app.ingestion.parse_process <pdf> <output.json>
"""

import json
import logging
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from app.ingestion.elements import Element, ElementKind

logger = logging.getLogger(__name__)

# The folder that holds the `app` package, so the child can import it.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class ParseFailedError(Exception):
    """Raised when every parse attempt failed."""


def parse_in_process(path: Path, attempts: int) -> list[Element]:
    """Parse a PDF in a child process, trying again if the child fails or crashes."""
    with TemporaryDirectory() as folder:
        output = Path(folder) / "elements.json"
        command = [
            sys.executable,
            "-m",
            "app.ingestion.parse_process",
            str(path.resolve()),
            str(output),
        ]
        for attempt in range(1, attempts + 1):
            code = subprocess.run(command, cwd=_BACKEND_DIR).returncode
            if code == 0:
                items = json.loads(output.read_text(encoding="utf-8"))
                return [
                    Element(
                        ElementKind(item["kind"]), item["text"], item["page"], item["last_page"]
                    )
                    for item in items
                ]
            logger.warning("parse attempt %d of %d exited with code %d", attempt, attempts, code)

    raise ParseFailedError(f"parsing failed {attempts} times; the backend log has the details")


def _main(pdf: str, output: str) -> None:
    # Imported here so the backend process never loads Docling; only the child needs it.
    from app.ingestion.layout_parser import parse_pdf

    elements = parse_pdf(Path(pdf))
    Path(output).write_text(json.dumps([asdict(element) for element in elements]), encoding="utf-8")


if __name__ == "__main__":
    _main(*sys.argv[1:])
