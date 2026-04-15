from __future__ import annotations

from .mock_robot_base import MockRobot, MockRobotConfig


def create_mock_ysc(sensor_endpoint: str, command_endpoint: str, logger) -> MockRobot:
    return MockRobot(
        MockRobotConfig(
            name="ysc",
            robot_type="quadruped",
            cameras=["main"],
            teleop_enabled=True,
            has_lidar=True,
            has_odom=True,
            base_pose=[2.4, 0.4, 0.0, 0.0, 0.0, 0.0, 1.0],
            sensor_endpoint=sensor_endpoint,
            command_endpoint=command_endpoint,
        ),
        logger=logger,
    )
