from __future__ import annotations

from .mock_robot_base import MockRobot, MockRobotConfig


def create_mock_piper(sensor_endpoint: str, command_endpoint: str, logger) -> MockRobot:
    return MockRobot(
        MockRobotConfig(
            name="piper",
            robot_type="fixed_arm",
            cameras=["arm_full", "side"],
            teleop_enabled=False,
            has_lidar=False,
            has_odom=False,
            base_pose=[-1.7, -0.6, 0.0, 0.0, 0.0, 0.0, 1.0],
            sensor_endpoint=sensor_endpoint,
            command_endpoint=command_endpoint,
        ),
        logger=logger,
    )
