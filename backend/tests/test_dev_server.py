"""Порт dev-сервера backend задаётся окружением, а не константой (#220).

Стенд E2E поднимает backend на своём порту и обязан уживаться с работающим
devstack: с жёстко зашитым 8012 Playwright ждал бы чужой (или свой, но тот же)
порт, и параллельный прогон был бы невозможен.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_SERVER_PATH = BACKEND_DIR / "scripts" / "dev_server.py"


def _load_dev_server() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_server_under_test", DEV_SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_port_falls_back_to_dev_stack_port() -> None:
    """Без переменных окружения поведение прежнее — порт devstack 8012."""
    assert _load_dev_server().resolve_port({}) == 8012


def test_port_comes_from_environment() -> None:
    assert _load_dev_server().resolve_port({"BACKEND_PORT": "8013"}) == 8013


def test_non_numeric_port_fails_loudly() -> None:
    """Молча упасть на 8012 нельзя: это порт чужого devstack."""
    with pytest.raises(ValueError, match="BACKEND_PORT"):
        _load_dev_server().resolve_port({"BACKEND_PORT": "busy"})


def test_out_of_range_port_fails_loudly() -> None:
    with pytest.raises(ValueError, match="BACKEND_PORT"):
        _load_dev_server().resolve_port({"BACKEND_PORT": "70000"})
