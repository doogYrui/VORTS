from __future__ import annotations

import io
import json
import math
import threading
import time
from dataclasses import dataclass

import zmq
from PIL import Image, ImageDraw, ImageFont


@dataclass(slots=True)
class MockRobotConfig:
    name: str
    robot_type: str
    cameras: list[str]
    teleop_enabled: bool
    has_lidar: bool
    has_odom: bool
    base_pose: list[float]
    sensor_endpoint: str
    command_endpoint: str


class MockRobot:
    def __init__(self, config: MockRobotConfig, logger) -> None:
        self.config = config
        self.logger = logger
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_logged_keys: tuple[str, ...] = ()
        self._last_teleop_log = 0.0
        self._font = ImageFont.load_default()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"mock-{self.config.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        context = zmq.Context.instance()
        publisher = context.socket(zmq.PUB)
        publisher.setsockopt(zmq.SNDHWM, 32)
        publisher.connect(self.config.sensor_endpoint)

        subscriber = context.socket(zmq.SUB)
        subscriber.connect(self.config.command_endpoint)
        subscriber.setsockopt_string(zmq.SUBSCRIBE, "task.broadcast")
        if self.config.teleop_enabled:
            subscriber.setsockopt_string(zmq.SUBSCRIBE, f"teleop.{self.config.name}")

        poller = zmq.Poller()
        poller.register(subscriber, zmq.POLLIN)

        next_video = time.monotonic()
        next_pointcloud = time.monotonic()
        next_odom = time.monotonic()

        time.sleep(0.5)
        self.logger.info("[%s] Mock robot started", self.config.name)

        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                timestamp = time.time()

                if now >= next_video:
                    for camera_name in self.config.cameras:
                        frame = self._build_frame(camera_name, timestamp)
                        publisher.send_multipart(
                            [f"video.{self.config.name}.{camera_name}".encode("utf-8"), frame]
                        )
                    next_video = now + (1.0 / 15.0)

                if self.config.has_lidar and now >= next_pointcloud:
                    pointcloud = self._build_pointcloud(timestamp)
                    publisher.send_multipart(
                        [
                            f"pointcloud.{self.config.name}".encode("utf-8"),
                            json.dumps(pointcloud, ensure_ascii=False).encode("utf-8"),
                        ]
                    )
                    next_pointcloud = now + 0.1

                if self.config.has_odom and now >= next_odom:
                    odom = self._build_odom(timestamp)
                    publisher.send_multipart(
                        [
                            f"odom.{self.config.name}".encode("utf-8"),
                            json.dumps(odom, ensure_ascii=False).encode("utf-8"),
                        ]
                    )
                    next_odom = now + 0.1

                events = dict(poller.poll(timeout=10))
                if subscriber in events:
                    while True:
                        try:
                            topic_raw, payload = subscriber.recv_multipart(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        self._handle_command(topic_raw.decode("utf-8"), payload)
        finally:
            publisher.close(0)
            subscriber.close(0)
            self.logger.info("[%s] Mock robot stopped", self.config.name)

    def _build_frame(self, camera_name: str, timestamp: float) -> bytes:
        width, height = 640, 480
        palette = {
            "galaxy": (188, 210, 224),
            "ysc": (210, 220, 204),
            "piper": (225, 214, 205),
        }
        base_color = palette.get(self.config.name, (210, 214, 222))
        image = Image.new("RGB", (width, height), base_color)
        draw = ImageDraw.Draw(image)

        accent = (
            min(base_color[0] + 20, 255),
            min(base_color[1] + 18, 255),
            min(base_color[2] + 24, 255),
        )
        draw.rectangle([24, 24, width - 24, height - 24], outline=(68, 87, 101), width=3)
        draw.rounded_rectangle([40, 40, width - 40, 190], radius=22, fill=accent)

        phase = (timestamp * 60) % width
        draw.ellipse([phase - 18, 230, phase + 18, 266], fill=(63, 94, 114))
        draw.rectangle([60, 320, width - 60, 340], fill=(228, 235, 240))
        draw.rectangle([60, 320, min(width - 60, 60 + phase), 340], fill=(94, 132, 156))

        lines = [
            f"Robot: {self.config.name}",
            f"Camera: {camera_name}",
            f"Time: {time.strftime('%H:%M:%S', time.localtime(timestamp))}",
            f"Frame ts: {timestamp:.3f}",
        ]

        y = 70
        for line in lines:
            draw.text((70, y), line, font=self._font, fill=(34, 48, 60))
            y += 28

        draw.text((70, 360), "Mock RGB JPEG stream", font=self._font, fill=(58, 84, 102))
        draw.text((70, 392), self.config.robot_type, font=self._font, fill=(58, 84, 102))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        return buffer.getvalue()

    def _build_pointcloud(self, timestamp: float) -> dict:
        point_count = 10000 if self.config.name == "galaxy" else 8000
        points: list[list[float]] = []
        phase = timestamp * 0.7

        for index in range(point_count):
            ratio = index / point_count
            angle = ratio * math.tau * 2
            radius = 1.8 + 0.55 * math.sin(angle * 5 + phase) + 0.2 * math.cos(angle * 2 - phase)
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            z = 0.25 * math.sin(angle * 3 + phase) + 0.02 * math.cos(index * 0.15)
            points.append([round(x, 3), round(y, 3), round(z, 3)])

        return {
            "robot": self.config.name,
            "timestamp": timestamp,
            "points": points,
        }

    def _build_odom(self, timestamp: float) -> dict:
        if self.config.name == "galaxy":
            x = 1.3 * math.cos(timestamp * 0.22)
            y = 0.9 * math.sin(timestamp * 0.18)
            yaw = timestamp * 0.18
        else:
            x = 2.2 + 0.75 * math.cos(timestamp * 0.31)
            y = -0.4 + 0.55 * math.sin(timestamp * 0.27)
            yaw = timestamp * 0.24

        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)

        return {
            "robot": self.config.name,
            "timestamp": timestamp,
            "pose": [round(x, 3), round(y, 3), 0.0, 0.0, 0.0, round(qz, 4), round(qw, 4)],
        }

    def _handle_command(self, topic: str, payload: bytes) -> None:
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.logger.warning("[%s] Failed to decode command topic=%s", self.config.name, topic)
            return

        if topic.startswith("teleop."):
            keys = tuple(message.get("keys", []))
            now = time.time()
            if keys != self._last_logged_keys or now - self._last_teleop_log > 1.0:
                self.logger.info("[%s] Teleop keys=%s", self.config.name, list(keys))
                self._last_logged_keys = keys
                self._last_teleop_log = now
            return

        if topic == "task.broadcast":
            self.logger.info("[%s] Received task: %s", self.config.name, message)
