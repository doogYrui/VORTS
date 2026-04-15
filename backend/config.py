from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    host: str = os.getenv("BACKEND_HOST", "0.0.0.0")
    port: int = _env_int("BACKEND_PORT", 1141)
    frontend_port: int = _env_int("FRONTEND_PORT", 1140)
    public_interface: str | None = os.getenv("PUBLIC_INTERFACE")
    zmq_sensor_bind: str = os.getenv("ZMQ_SENSOR_BIND", "tcp://0.0.0.0:6001")
    zmq_command_bind: str = os.getenv("ZMQ_COMMAND_BIND", "tcp://0.0.0.0:6002")
    history_seconds: int = _env_int("NETWORK_HISTORY_SECONDS", 60)
    scene_graph_hz: float = _env_float("SCENE_GRAPH_HZ", 2.0)
    logs_dir: Path = ROOT_DIR / "backend" / "logs"
    mock_logs_dir: Path = ROOT_DIR / "mock_robots" / "logs"


_SETTINGS = Settings()


def get_settings() -> Settings:
    return _SETTINGS
