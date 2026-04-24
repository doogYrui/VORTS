from __future__ import annotations

from .models import RobotCapability, RobotInfo, SourceItem


TELEOP_KEYS = ["w", "s", "a", "d", "q", "e"]
ROBOT_ALIASES: dict[str, str] = {}


def canonical_robot_name(name: str) -> str:
    return ROBOT_ALIASES.get(name, name)


_CAPABILITIES = [
    RobotCapability(
        name="galaxea",
        type="mobile_dual_arm",
        ip="127.0.0.1",
        teleop=True,
        teleop_keys=TELEOP_KEYS,
        cameras=["main", "left_arm", "right_arm"],
        lidar=True,
        odom=True,
    ),
    RobotCapability(
        name="ysc",
        type="quadruped",
        ip="127.0.0.1",
        teleop=True,
        teleop_keys=TELEOP_KEYS,
        cameras=["main"],
        lidar=True,
        odom=True,
    ),
    RobotCapability(
        name="piper",
        type="fixed_arm",
        ip="127.0.0.1",
        teleop=False,
        teleop_keys=[],
        cameras=["arm_full", "side"],
        lidar=False,
        odom=False,
    ),
    RobotCapability(
        name="monitor",
        type="fixed_camera",
        ip="192.168.31.220",
        teleop=False,
        teleop_keys=[],
        cameras=["main"],
        lidar=False,
        odom=False,
    ),
]


def get_robot_capabilities() -> list[RobotCapability]:
    return [item.model_copy(deep=True) for item in _CAPABILITIES]


def get_robot_list() -> list[RobotInfo]:
    robots: list[RobotInfo] = []
    for item in _CAPABILITIES:
        robots.append(
            RobotInfo(
                name=item.name,
                type=item.type,
                ip=item.ip,
                teleop_enabled=item.teleop,
                camera_count=len(item.cameras),
                camera_names=item.cameras,
                has_lidar=item.lidar,
                has_odom=item.odom,
            )
        )
    return robots


def get_teleop_robots() -> list[RobotInfo]:
    return [robot for robot in get_robot_list() if robot.teleop_enabled]


def get_video_sources() -> list[SourceItem]:
    sources: list[SourceItem] = []
    for robot in _CAPABILITIES:
        for camera in robot.cameras:
            sources.append(
                SourceItem(
                    robot=robot.name,
                    source=camera,
                    label=f"{robot.name} / {camera}",
                )
            )
    return sources


def get_pointcloud_sources() -> list[SourceItem]:
    return [
        SourceItem(robot=item.name, source=item.name, label=f"{item.name} / lidar")
        for item in _CAPABILITIES
        if item.lidar
    ]


def get_odom_sources() -> list[SourceItem]:
    return [
        SourceItem(robot=item.name, source=item.name, label=f"{item.name} / odom")
        for item in _CAPABILITIES
        if item.odom
    ]
