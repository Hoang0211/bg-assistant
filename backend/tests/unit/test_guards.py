import os
import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_env_forces_fake_provider() -> None:
    assert os.environ["LLM_PROVIDER"] == "fake"
    assert os.environ.get("OPENAI_API_KEY") == ""


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_external_network_is_blocked() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("1.1.1.1", 443))
