import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_socket import SocketConnectBlockedError

from app.config import get_settings


def test_env_forces_fake_provider() -> None:
    assert os.environ["LLM_PROVIDER"] == "fake"
    assert os.environ.get("OPENAI_API_KEY") == ""


def test_settings_turn_off_the_ingestion_worker() -> None:
    assert get_settings().run_ingestion_worker is False


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_external_network_is_blocked() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("1.1.1.1", 443))


def test_app_startup_imports_no_heavy_library() -> None:
    # A new process, because in a full test run other test files have already loaded these.
    code = (
        "import sys, app.main; "
        "heavy = ('docling', 'sentence_transformers', 'torch'); "
        "print([name for name in heavy if name in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]"
