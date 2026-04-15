from __future__ import annotations

import os
import time

from backend.config import get_settings
from backend.logging_config import configure_named_logger

from .mock_galaxy import create_mock_galaxy
from .mock_piper import create_mock_piper
from .mock_ysc import create_mock_ysc


def _endpoint_for_connect(bind_endpoint: str, env_name: str) -> str:
    override = os.getenv(env_name)
    if override:
        return override
    return (
        bind_endpoint.replace("0.0.0.0", "127.0.0.1")
        .replace("[::]", "127.0.0.1")
        .replace("*", "127.0.0.1")
    )


def main() -> None:
    settings = get_settings()
    logger = configure_named_logger("mock_robots", settings.mock_logs_dir / "mock_robots.log")

    sensor_endpoint = _endpoint_for_connect(settings.zmq_sensor_bind, "MOCK_SENSOR_ENDPOINT")
    command_endpoint = _endpoint_for_connect(settings.zmq_command_bind, "MOCK_COMMAND_ENDPOINT")

    robots = [
        create_mock_galaxy(sensor_endpoint, command_endpoint, logger),
        create_mock_ysc(sensor_endpoint, command_endpoint, logger),
        create_mock_piper(sensor_endpoint, command_endpoint, logger),
    ]

    logger.info(
        "Starting mock robots with sensor endpoint %s and command endpoint %s",
        sensor_endpoint,
        command_endpoint,
    )

    for robot in robots:
        robot.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Stopping mock robots")
    finally:
        for robot in robots:
            robot.stop()


if __name__ == "__main__":
    main()
