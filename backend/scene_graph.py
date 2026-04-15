from __future__ import annotations

import math
import time

from .models import SceneEdge, SceneGraphMessage, SceneNode


DEFAULT_POSES: dict[str, list[float]] = {
    "galaxy": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    "ysc": [2.4, 0.4, 0.0, 0.0, 0.0, 0.0, 1.0],
    "piper": [-1.7, -0.6, 0.0, 0.0, 0.0, 0.0, 1.0],
}

STATIC_OBJECTS = [
    {"id": "obj_1", "type": "object", "label": "chair", "pose": [1.2, 0.5, 0.0, 0.0, 0.0, 0.0, 1.0]},
    {"id": "obj_2", "type": "object", "label": "workbench", "pose": [-0.8, 1.6, 0.0, 0.0, 0.0, 0.0, 1.0]},
    {"id": "obj_3", "type": "object", "label": "cart", "pose": [2.7, -0.4, 0.0, 0.0, 0.0, 0.0, 1.0]},
]


def _distance_xy(source_pose: list[float], target_pose: list[float]) -> float:
    return math.dist(source_pose[:2], target_pose[:2])


class SceneGraphGenerator:
    def build(self, runtime_robot_poses: dict[str, list[float]]) -> SceneGraphMessage:
        nodes: list[SceneNode] = []

        robot_nodes = []
        for robot_name, default_pose in DEFAULT_POSES.items():
            pose = runtime_robot_poses.get(robot_name, default_pose)
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
        if distance < 1.0:
            return "reach"
        if distance < 2.0:
            return "near"
        return None
