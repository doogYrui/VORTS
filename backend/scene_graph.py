from __future__ import annotations

import math
import time

from .models import SceneEdge, SceneGraphMessage, SceneNode
from .robot_registry import canonical_robot_name


DEFAULT_POSES: dict[str, list[float]] = {
    "galaxea": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    "ysc": [2.4, 0.4, 0.0, 0.0, 0.0, 0.0, 1.0],
}

GALAXEA_TO_LITE3_ODOM = (
    (-0.99846, 0.05540, -5.04959),
    (-0.05540, -0.99846, 4.00999),
)

STATIC_OBJECTS = [
    {"id": "obj_1", "type": "object", "label": "main_table", "pose": [-8.2268, 3.586076, 0.0, 0.0, 0.0, 0.0, 1.0]},
    {"id": "obj_2", "type": "object", "label": "roboticarm_table", "pose": [-3.3891540336608887, 9.093396530151367, 0.0, 0.0, 0.0, 0.0, 1.0]},
    {"id": "obj_3", "type": "object", "label": "dropoff_zone", "pose": [-4.0116, 5.18515, 0.0, 0.0, 0.0, 0.111691, 0.993742887]},
]


def _distance_xy(source_pose: list[float], target_pose: list[float]) -> float:
    return math.dist(source_pose[:2], target_pose[:2])


def _yaw_from_quaternion(qx: float, qy: float, qz: float, qw: float) -> float:
    return math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))


def _quaternion_from_yaw(yaw: float) -> tuple[float, float, float, float]:
    half_yaw = yaw / 2.0
    return (0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw))


def _transform_galaxea_pose_to_lite3_odom(pose: list[float]) -> list[float]:
    x, y, z, qx, qy, qz, qw = pose
    row1, row2 = GALAXEA_TO_LITE3_ODOM
    transformed_x = row1[0] * x + row1[1] * y + row1[2]
    transformed_y = row2[0] * x + row2[1] * y + row2[2]
    yaw = _yaw_from_quaternion(qx, qy, qz, qw)
    delta_yaw = math.atan2(row2[0], row1[0])
    transformed_qx, transformed_qy, transformed_qz, transformed_qw = _quaternion_from_yaw(yaw + delta_yaw)
    return [transformed_x, transformed_y, z, transformed_qx, transformed_qy, transformed_qz, transformed_qw]


class SceneGraphGenerator:
    def build(self, runtime_robot_poses: dict[str, list[float]]) -> SceneGraphMessage:
        nodes: list[SceneNode] = []
        normalized_runtime_poses = {
            canonical_robot_name(robot_name): pose for robot_name, pose in runtime_robot_poses.items()
        }
        galaxea_pose = normalized_runtime_poses.get("galaxea")
        if galaxea_pose is not None:
            normalized_runtime_poses["galaxea"] = _transform_galaxea_pose_to_lite3_odom(galaxea_pose)

        robot_nodes = []
        for robot_name, default_pose in DEFAULT_POSES.items():
            pose = normalized_runtime_poses.get(robot_name, default_pose)
            node = SceneNode(id=robot_name, type="robot", label=robot_name, pose=pose)
            nodes.append(node)
            robot_nodes.append(node)

        object_nodes = [
            SceneNode(
                id=item["id"],
                type="object",
                label=item["label"],
                pose=item["pose"],
            )
            for item in STATIC_OBJECTS
        ]
        nodes.extend(object_nodes)

        edges: list[SceneEdge] = []

        for index, source in enumerate(robot_nodes):
            for target in robot_nodes[index + 1 :]:
                edge_type = self._classify_robot_edge(source.pose, target.pose)
                if edge_type:
                    edges.append(SceneEdge(source=source.id, target=target.id, type=edge_type))

            for target in object_nodes:
                edge_type = self._classify_robot_edge(source.pose, target.pose)
                if edge_type:
                    edges.append(SceneEdge(source=source.id, target=target.id, type=edge_type))

        for index, source in enumerate(object_nodes):
            for target in object_nodes[index + 1 :]:
                if _distance_xy(source.pose, target.pose) < 2.0:
                    edges.append(SceneEdge(source=source.id, target=target.id, type="near"))

        return SceneGraphMessage(timestamp=time.time(), nodes=nodes, edges=edges)

    @staticmethod
    def _classify_robot_edge(source_pose: list[float], target_pose: list[float]) -> str | None:
        distance = _distance_xy(source_pose, target_pose)
        if distance < 0.8:
            return "reach"
        if distance < 1.5:
            return "near"
        return None
