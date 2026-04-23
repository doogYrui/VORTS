from __future__ import annotations

import asyncio
import json
import struct
import time

import numpy as np
import zmq
import zmq.asyncio

from .models import TaskPayload, TeleopMessage
from .robot_registry import canonical_robot_name
from .ws_manager import StreamBroker


class ZMQBridge:
    def __init__(
        self,
        settings,
        logger,
        video_broker: StreamBroker,
        pointcloud_broker: StreamBroker,
        odom_broker: StreamBroker,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.video_broker = video_broker
        self.pointcloud_broker = pointcloud_broker
        self.odom_broker = odom_broker
        self.robot_poses: dict[str, list[float]] = {}
        self._context = zmq.asyncio.Context.instance()
        self._sensor_socket: zmq.asyncio.Socket | None = None
        self._command_socket: zmq.asyncio.Socket | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._last_data_log: dict[str, float] = {}

    async def start(self) -> None:
        self._sensor_socket = self._context.socket(zmq.SUB)
        self._sensor_socket.setsockopt_string(zmq.SUBSCRIBE, "")
        self._sensor_socket.setsockopt(zmq.RCVHWM, 32)
        self._sensor_socket.bind(self.settings.zmq_sensor_bind)

        self._command_socket = self._context.socket(zmq.PUB)
        self._command_socket.setsockopt(zmq.SNDHWM, 32)
        self._command_socket.bind(self.settings.zmq_command_bind)

        self.logger.info(
            "ZMQ bridge ready: sensor=%s command=%s",
            self.settings.zmq_sensor_bind,
            self.settings.zmq_command_bind,
        )

        await asyncio.sleep(0.3)
        self._receiver_task = asyncio.create_task(self._receiver_loop(), name="zmq-receiver")

    async def stop(self) -> None:
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass

        if self._sensor_socket is not None:
            self._sensor_socket.close(0)
        if self._command_socket is not None:
            self._command_socket.close(0)

    async def send_teleop(self, payload: TeleopMessage) -> None:
        if self._command_socket is None:
            return
        topic = f"teleop.{payload.robot}"
        message = payload.model_dump()
        await self._command_socket.send_multipart(
            [topic.encode("utf-8"), json.dumps(message, ensure_ascii=False).encode("utf-8")]
        )

    async def publish_task(self, payload: TaskPayload) -> None:
        if self._command_socket is None:
            return
        topic = "task.broadcast"
        message = payload.model_dump()
        await self._command_socket.send_multipart(
            [topic.encode("utf-8"), json.dumps(message, ensure_ascii=False).encode("utf-8")]
        )

    def get_robot_poses(self) -> dict[str, list[float]]:
        return {name: pose[:] for name, pose in self.robot_poses.items()}

    async def _receiver_loop(self) -> None:
        assert self._sensor_socket is not None

        while True:
            frames = await self._sensor_socket.recv_multipart()
            if not frames:
                continue

            topic = frames[0].decode("utf-8", errors="ignore")
            if not topic:
                continue

            if topic == "points_xyz":
                self._handle_lite3_pointcloud(topic, frames)
                continue

            parts = topic.split(".")
            if len(parts) < 2:
                continue

            channel = parts[0]

            if channel == "video" and len(parts) >= 3 and len(frames) == 2:
                robot_name = canonical_robot_name(parts[1])
                camera_name = parts[2]
                payload = frames[1]
                self.video_broker.publish(f"{robot_name}/{camera_name}", payload)
                self._sampled_log(
                    f"video:{robot_name}/{camera_name}",
                    "Received video frame for %s/%s",
                    robot_name,
                    camera_name,
                )
                continue

            if len(frames) != 2:
                self.logger.warning("Unexpected ZMQ frame count=%s for topic %s", len(frames), topic)
                continue

            payload = frames[1]
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.logger.warning("Failed to decode ZMQ payload for topic %s", topic)
                continue

            if channel == "pointcloud":
                robot_name = canonical_robot_name(parts[1])
                if isinstance(message, dict):
                    message["robot"] = robot_name
                self.pointcloud_broker.publish(robot_name, message)
                self._sampled_log(
                    f"pointcloud:{robot_name}",
                    "Received pointcloud for %s with %s points",
                    robot_name,
                    len(message.get("points", [])) if isinstance(message, dict) else 0,
                )
            elif channel == "odom":
                robot_name = canonical_robot_name(parts[1])
                if isinstance(message, dict):
                    message["robot"] = robot_name
                pose = message.get("pose") if isinstance(message, dict) else None
                if isinstance(pose, list):
                    self.robot_poses[robot_name] = pose
                self.odom_broker.publish(robot_name, message)
                self._sampled_log(
                    f"odom:{robot_name}",
                    "Received odom for %s pose=%s",
                    robot_name,
                    pose,
                )

    def _handle_lite3_pointcloud(self, topic: str, frames: list[bytes]) -> None:
        if len(frames) != 3:
            self.logger.warning("Unexpected Lite3 pointcloud frame count=%s for topic %s", len(frames), topic)
            return

        header = frames[1]
        payload = frames[2]
        if len(header) != struct.calcsize("<Id"):
            self.logger.warning("Invalid Lite3 pointcloud header size=%s for topic %s", len(header), topic)
            return

        point_count, timestamp = struct.unpack("<Id", header)
        expected_bytes = int(point_count) * 3 * 4
        if len(payload) < expected_bytes:
            self.logger.warning(
                "Lite3 pointcloud payload too short for topic %s: expected=%s actual=%s",
                topic,
                expected_bytes,
                len(payload),
            )
            return

        try:
            points = np.frombuffer(payload[:expected_bytes], dtype=np.float32).reshape(-1, 3)
        except ValueError:
            self.logger.warning("Failed to reshape Lite3 pointcloud payload for topic %s", topic)
            return

        robot_name = canonical_robot_name(self.settings.lite3_pointcloud_robot)
        message = {
            "robot": robot_name,
            "timestamp": float(timestamp),
            "points": points.tolist(),
        }
        self.pointcloud_broker.publish(robot_name, message)
        self._sampled_log(
            f"pointcloud:{robot_name}",
            "Received pointcloud for %s with %s points",
            robot_name,
            int(points.shape[0]),
        )

    def _sampled_log(self, key: str, message: str, *args) -> None:
        now = time.time()
        previous = self._last_data_log.get(key, 0.0)
        if now - previous < 5.0:
            return
        self._last_data_log[key] = now
        self.logger.info(message, *args)
