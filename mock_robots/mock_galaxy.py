from __future__ import annotations

from .mock_robot_base import MockRobot, MockRobotConfig


def create_mock_galaxy(sensor_endpoint: str, command_endpoint: str, logger) -> MockRobot:
    return MockRobot(
        MockRobotConfig(
            name="galaxy",
            robot_type="mobile_dual_arm",
            cameras=["main", "left_arm", "right_arm"],
            teleop_enabled=True,
            has_lidar=True,
            has_odom=True,
            base_pose=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            sensor_endpoint=sensor_endpoint,
            command_endpoint=command_endpoint,
        ),
        logger=logger,
    )
