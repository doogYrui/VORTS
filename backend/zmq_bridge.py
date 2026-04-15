from __future__ import annotations

import asyncio
import json
import time

import zmq
import zmq.asyncio

from .models import TaskPayload, TeleopMessage
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
            topic_raw, payload = await self._sensor_socket.recv_multipart()
            topic = topic_raw.decode("utf-8")
            parts = topic.split(".")

            if len(parts) < 2:
                continue

            channel = parts[0]

            if channel == "video" and len(parts) >= 3:
                robot_name = parts[1]
                camera_name = parts[2]
                self.video_broker.publish(f"{robot_name}/{camera_name}", payload)
                self._sampled_log(
                    f"video:{robot_name}/{camera_name}",
                    "Received video frame for %s/%s",
                    robot_name,
                    camera_name,
                )
                continue

            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.logger.warning("Failed to decode ZMQ payload for topic %s", topic)
                continue

            if channel == "pointcloud":
                robot_name = parts[1]
                self.pointcloud_broker.publish(robot_name, message)
                self._sampled_log(
                    f"pointcloud:{robot_name}",
                    "Received pointcloud for %s with %s points",
                    robot_name,
                    len(message.get("points", [])),
                )
            elif channel == "odom":
                robot_name = parts[1]
                pose = message.get("pose")
                if isinstance(pose, list):
                    self.robot_poses[robot_name] = pose
                self.odom_broker.publish(robot_name, message)
                self._sampled_log(
                    f"odom:{robot_name}",
                    "Received odom for %s pose=%s",
                    robot_name,
                    pose,
                )

    def _sampled_log(self, key: str, message: str, *args) -> None:
        now = time.time()
        previous = self._last_data_log.get(key, 0.0)
        if now - previous < 5.0:
            return
        self._last_data_log[key] = now
        self.logger.info(message, *args)
