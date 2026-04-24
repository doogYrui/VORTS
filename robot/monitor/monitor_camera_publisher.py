from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import pyrealsense2 as rs
import zmq


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class MonitorCameraConfig:
    robot_name: str = _env("MONITOR_ROBOT_NAME", "monitor")
    camera_name: str = _env("MONITOR_CAMERA_NAME", "main")
    camera_serial: str = _env("MONITOR_CAMERA_SN", "247122070621")
    backend_host: str = _env("VORTS_BACKEND_HOST", _env("BACKEND_HOST", "192.168.31.46"))
    sensor_endpoint: str = _env("VORTS_SENSOR_ENDPOINT", "")
    sensor_port: int = _env_int("VORTS_SENSOR_PORT", 6001)
    video_width: int = _env_int("MONITOR_VIDEO_WIDTH", 640)
    video_height: int = _env_int("MONITOR_VIDEO_HEIGHT", 480)
    video_fps: int = _env_int("MONITOR_VIDEO_FPS", 15)
    jpeg_quality: int = _env_int("MONITOR_JPEG_QUALITY", 85)

    def resolve_sensor_endpoint(self) -> str:
        if self.sensor_endpoint:
            return self.sensor_endpoint
        return f"tcp://{self.backend_host}:{self.sensor_port}"


def _encode_jpeg(frame_bgr: np.ndarray, quality: int) -> bytes:
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    ok, buffer = cv2.imencode(".jpg", frame_bgr, encode_params)
    if not ok:
        raise RuntimeError("Failed to encode JPEG frame")
    return buffer.tobytes()


def _video_topic(robot_name: str, camera_name: str) -> bytes:
    return f"video.{robot_name}.{camera_name}".encode("utf-8")


class MonitorCameraPublisher:
    def __init__(self, config: Optional[MonitorCameraConfig] = None, logger: Optional[logging.Logger] = None) -> None:
        self.config = config or MonitorCameraConfig()
        self.logger = logger or self._build_logger()
        self._context = zmq.Context.instance()
        self._socket: Optional[zmq.Socket] = None
        self._pipeline: Optional[rs.pipeline] = None
        self._stop_event = threading.Event()

    @staticmethod
    def _build_logger() -> logging.Logger:
        logger = logging.getLogger("monitor_camera_publisher")
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(handler)
        return logger

    def start(self) -> None:
        if self._socket is not None or self._pipeline is not None:
            return

        socket = self._context.socket(zmq.PUB)
        socket.setsockopt(zmq.SNDHWM, 32)
        socket.connect(self.config.resolve_sensor_endpoint())

        pipeline = rs.pipeline()
        rs_config = rs.config()
        rs_config.enable_device(self.config.camera_serial)
        rs_config.enable_stream(
            rs.stream.color,
            self.config.video_width,
            self.config.video_height,
            rs.format.bgr8,
            self.config.video_fps,
        )
        pipeline.start(rs_config)

        self._socket = socket
        self._pipeline = pipeline
        time.sleep(0.3)
        self.logger.info(
            "Monitor camera publisher started: endpoint=%s topic=video.%s.%s serial=%s",
            self.config.resolve_sensor_endpoint(),
            self.config.robot_name,
            self.config.camera_name,
            self.config.camera_serial,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None

    def run_forever(self) -> None:
        self.start()
        assert self._socket is not None
        assert self._pipeline is not None

        topic = _video_topic(self.config.robot_name, self.config.camera_name)
        period = 1.0 / max(float(self.config.video_fps), 1.0)
        next_tick = time.monotonic()
        frame_count = 0
        last_log_at = time.time()

        while not self._stop_event.is_set():
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(next_tick - now, 0.01))
                continue

            try:
                frames = self._pipeline.wait_for_frames()
                color_frame = frames.get_color_frame()
                if not color_frame:
                    next_tick += period
                    continue

                frame_bgr = np.asanyarray(color_frame.get_data())
                payload = _encode_jpeg(frame_bgr, self.config.jpeg_quality)
                self._socket.send_multipart([topic, payload])
            except Exception as exc:
                self.logger.warning("Failed to publish monitor frame: %s", exc)
                time.sleep(0.2)
                next_tick = time.monotonic() + period
                continue

            frame_count += 1
            now_wall = time.time()
            if now_wall - last_log_at >= 5.0:
                self.logger.info("Published %s monitor frames", frame_count)
                last_log_at = now_wall

            next_tick += period


def main() -> None:
    publisher = MonitorCameraPublisher()

    def _shutdown_handler(_signum, _frame) -> None:
        publisher.stop()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    try:
        publisher.run_forever()
    finally:
        publisher.stop()


if __name__ == "__main__":
    main()
