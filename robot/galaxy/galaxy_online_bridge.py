from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np
import pyrealsense2 as rs
import rospy
import sensor_msgs.point_cloud2 as pc2
import zmq
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2


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
class GalaxyBridgeConfig:
    robot_name: str = "galaxea"
    backend_host: str = _env("VORTS_BACKEND_HOST", _env("BACKEND_HOST", "192.168.31.46"))
    sensor_endpoint: str = _env("VORTS_SENSOR_ENDPOINT", "")
    command_endpoint: str = _env("VORTS_COMMAND_ENDPOINT", "")
    webxr_video_endpoint: str = _env("VORTS_WEBXR_VIDEO_ENDPOINT", "")
    sensor_port: int = _env_int("VORTS_SENSOR_PORT", 6001)
    command_port: int = _env_int("VORTS_COMMAND_PORT", 6002)
    webxr_video_port: int = _env_int("VORTS_WEBXR_VIDEO_PORT", 6004)
    left_serial: str = _env("GALAXY_LEFT_SN", "333422301212")
    right_serial: str = _env("GALAXY_RIGHT_SN", "346522071650")
    main_serial: str = _env("GALAXY_MAIN_SN", "347622072588")
    webxr_video_robot_name: str = _env("GALAXY_WEBXR_VIDEO_ROBOT_NAME", "galaxy")
    webxr_video_camera_name: str = _env("GALAXY_WEBXR_VIDEO_CAMERA_NAME", "rgb")
    pointcloud_topic: str = _env("GALAXY_POINTCLOUD_TOPIC", "/livox/lidar")
    odom_topic: str = _env("GALAXY_ODOM_TOPIC", "/local_odom")
    video_width: int = _env_int("GALAXY_VIDEO_WIDTH", 640)
    video_height: int = _env_int("GALAXY_VIDEO_HEIGHT", 480)
    video_fps: int = _env_int("GALAXY_VIDEO_FPS", 15)
    video_wait_timeout_ms: int = _env_int("GALAXY_VIDEO_WAIT_TIMEOUT_MS", 120)
    pointcloud_hz: float = float(_env("GALAXY_POINTCLOUD_HZ", "10.0"))
    odom_hz: float = float(_env("GALAXY_ODOM_HZ", "10.0"))
    max_points: int = _env_int("GALAXY_MAX_POINTS", 50000)
    jpeg_quality: int = _env_int("GALAXY_JPEG_QUALITY", 85)

    def resolve_sensor_endpoint(self) -> str:
        if self.sensor_endpoint:
            return self.sensor_endpoint
        return f"tcp://{self.backend_host}:{self.sensor_port}"

    def resolve_command_endpoint(self) -> str:
        if self.command_endpoint:
            return self.command_endpoint
        return f"tcp://{self.backend_host}:{self.command_port}"

    def resolve_webxr_video_endpoint(self) -> str:
        if self.webxr_video_endpoint:
            return self.webxr_video_endpoint
        return f"tcp://{self.backend_host}:{self.webxr_video_port}"


def _sample_points(points: list[list[float]], max_points: int) -> list[list[float]]:
    if len(points) <= max_points:
        return points

    step = len(points) / float(max_points)
    sampled: list[list[float]] = []
    index = 0.0
    for _ in range(max_points):
        sampled.append(points[int(index)])
        index += step
    return sampled


def _encode_jpeg(frame_bgr: np.ndarray, quality: int = 85) -> bytes:
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    ok, buffer = cv2.imencode(".jpg", frame_bgr, encode_params)
    if not ok:
        raise RuntimeError("Failed to encode JPEG frame")
    return buffer.tobytes()


def _frame_to_topic(robot_name: str, camera_name: str) -> str:
    return f"video.{robot_name}.{camera_name}"


def _timestamp(msg_stamp=None) -> float:
    if msg_stamp:
        try:
            return msg_stamp.to_sec()
        except Exception:
            pass
    return time.time()


class GalaxyZMQBridge:
    def __init__(self, config: GalaxyBridgeConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or self._build_logger()
        self._context = zmq.Context.instance()
        self._publish_socket: Optional[zmq.Socket] = None
        self._webxr_video_socket: Optional[zmq.Socket] = None
        self._command_socket: Optional[zmq.Socket] = None
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._command_thread: Optional[threading.Thread] = None
        self.latest_teleop: Optional[dict] = None
        self.latest_task: Optional[dict] = None

    @staticmethod
    def _build_logger() -> logging.Logger:
        logger = logging.getLogger("galaxy_online_bridge")
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(handler)
        return logger

    def start(self) -> None:
        self._publish_socket = self._context.socket(zmq.PUB)
        self._publish_socket.setsockopt(zmq.SNDHWM, 32)
        self._publish_socket.connect(self.config.resolve_sensor_endpoint())

        self._webxr_video_socket = self._context.socket(zmq.PUB)
        self._webxr_video_socket.setsockopt(zmq.SNDHWM, 32)
        self._webxr_video_socket.connect(self.config.resolve_webxr_video_endpoint())

        self._command_socket = self._context.socket(zmq.SUB)
        self._command_socket.setsockopt_string(zmq.SUBSCRIBE, f"teleop.{self.config.robot_name}")
        self._command_socket.setsockopt_string(zmq.SUBSCRIBE, "task.broadcast")
        self._command_socket.setsockopt(zmq.RCVHWM, 32)
        self._command_socket.connect(self.config.resolve_command_endpoint())

        self._command_thread = threading.Thread(target=self._command_loop, name="galaxy-zmq-command", daemon=True)
        self._command_thread.start()

        self.logger.info(
            "ZMQ bridge started: sensor=%s command=%s webxr_video=%s",
            self.config.resolve_sensor_endpoint(),
            self.config.resolve_command_endpoint(),
            self.config.resolve_webxr_video_endpoint(),
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._command_thread is not None:
            self._command_thread.join(timeout=2.0)

        if self._command_socket is not None:
            self._command_socket.close(0)
            self._command_socket = None

        if self._publish_socket is not None:
            self._publish_socket.close(0)
            self._publish_socket = None

        if self._webxr_video_socket is not None:
            self._webxr_video_socket.close(0)
            self._webxr_video_socket = None

    def publish_video(self, camera_name: str, frame_bgr: np.ndarray) -> None:
        if self._publish_socket is None:
            return

        payload = _encode_jpeg(frame_bgr, self.config.jpeg_quality)
        topic = _frame_to_topic(self.config.robot_name, camera_name)
        with self._send_lock:
            self._publish_socket.send_multipart([topic.encode("utf-8"), payload])

    def publish_webxr_rgb(self, frame_bgr: np.ndarray, capture_ts: Optional[float] = None) -> None:
        if self._webxr_video_socket is None:
            return

        timestamp = float(capture_ts if capture_ts is not None else time.time())
        payload = _encode_jpeg(frame_bgr, self.config.jpeg_quality)
        topic = _frame_to_topic(self.config.webxr_video_robot_name, self.config.webxr_video_camera_name)
        metadata = json.dumps(
            {
                "capture_ts": timestamp,
                "camera": self.config.webxr_video_camera_name,
                "robot": self.config.webxr_video_robot_name,
                "width": self.config.video_width,
                "height": self.config.video_height,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        with self._send_lock:
            self._webxr_video_socket.send_multipart([topic.encode("utf-8"), metadata, payload])

    def publish_pointcloud(self, points: Iterable[Iterable[float]], timestamp: Optional[float] = None) -> None:
        if self._publish_socket is None:
            return

        point_list = [[float(x), float(y), float(z)] for x, y, z in points]
        point_list = _sample_points(point_list, self.config.max_points)
        payload = {
            "robot": self.config.robot_name,
            "timestamp": float(timestamp if timestamp is not None else time.time()),
            "points": point_list,
        }
        message = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with self._send_lock:
            self._publish_socket.send_multipart([f"pointcloud.{self.config.robot_name}".encode("utf-8"), message])

    def publish_odom(self, pose: list[float], timestamp: Optional[float] = None) -> None:
        if self._publish_socket is None:
            return

        if len(pose) != 7:
            raise ValueError("odom pose must be [x, y, z, qx, qy, qz, qw]")

        payload = {
            "robot": self.config.robot_name,
            "timestamp": float(timestamp if timestamp is not None else time.time()),
            "pose": [float(v) for v in pose],
        }
        message = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        with self._send_lock:
            self._publish_socket.send_multipart([f"odom.{self.config.robot_name}".encode("utf-8"), message])

    def _command_loop(self) -> None:
        assert self._command_socket is not None

        poller = zmq.Poller()
        poller.register(self._command_socket, zmq.POLLIN)

        while not self._stop_event.is_set():
            events = dict(poller.poll(timeout=200))
            if self._command_socket not in events:
                continue

            try:
                topic_raw, payload = self._command_socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue

            topic = topic_raw.decode("utf-8", errors="ignore")
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.logger.warning("Failed to decode command payload for topic=%s", topic)
                continue

            if topic == f"teleop.{self.config.robot_name}":
                self.latest_teleop = data
                self.logger.info("Teleop received: keys=%s ts=%s", data.get("keys"), data.get("ts"))
            elif topic == "task.broadcast":
                self.latest_task = data
                self.logger.info("Task broadcast received: type=%s", data.get("task_type"))


class RealSenseDualCameraPublisher:
    def __init__(self, config: GalaxyBridgeConfig, bridge: GalaxyZMQBridge, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.bridge = bridge
        self.logger = logger or bridge.logger
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._left_pipeline: Optional[rs.pipeline] = None
        self._right_pipeline: Optional[rs.pipeline] = None
        self._main_pipeline: Optional[rs.pipeline] = None
        self._placeholders = {
            "left_arm": self._build_placeholder_frame("left_arm", self.config.left_serial),
            "right_arm": self._build_placeholder_frame("right_arm", self.config.right_serial),
            "main": self._build_placeholder_frame("main", self.config.main_serial),
        }

    def start(self) -> None:
        self._left_pipeline = self._create_pipeline(self.config.left_serial)
        self._right_pipeline = self._create_pipeline(self.config.right_serial)
        self._main_pipeline = self._create_pipeline(self.config.main_serial)
        self._thread = threading.Thread(target=self._run, name="galaxy-rgb", daemon=True)
        self._thread.start()
        self.logger.info("RGB publisher started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._stop_pipeline(self._left_pipeline)
        self._stop_pipeline(self._right_pipeline)
        self._stop_pipeline(self._main_pipeline)
        self._left_pipeline = None
        self._right_pipeline = None
        self._main_pipeline = None

    def _create_pipeline(self, serial_number: str) -> Optional[rs.pipeline]:
        if not serial_number:
            self.logger.warning("Camera serial number is empty, camera will be skipped")
            return None

        if not self._camera_online(serial_number):
            self.logger.warning("RealSense camera offline, using placeholder: serial=%s", serial_number)
            return None

        try:
            pipeline = rs.pipeline()
            config = rs.config()
            config.enable_device(serial_number)
            config.enable_stream(
                rs.stream.color,
                self.config.video_width,
                self.config.video_height,
                rs.format.bgr8,
                self.config.video_fps,
            )
            pipeline.start(config)
            self.logger.info("RealSense camera started: serial=%s", serial_number)
            return pipeline
        except Exception as exc:
            self.logger.warning("Failed to start RealSense camera serial=%s: %s", serial_number, exc)
            return None

    @staticmethod
    def _camera_online(serial_number: str) -> bool:
        try:
            context = rs.context()
            for device in context.query_devices():
                if device.get_info(rs.camera_info.serial_number) == serial_number:
                    return True
        except Exception:
            return False
        return False

    def _build_placeholder_frame(self, camera_name: str, serial_number: str) -> np.ndarray:
        frame = np.zeros((self.config.video_height, self.config.video_width, 3), dtype=np.uint8)
        frame[:, :] = (38, 44, 50)
        cv2.rectangle(frame, (24, 24), (self.config.video_width - 24, self.config.video_height - 24), (90, 110, 124), 2)
        cv2.putText(
            frame,
            f"galaxy / {camera_name}",
            (48, 96),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (220, 230, 235),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "camera offline",
            (48, 148),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (170, 188, 198),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"serial: {serial_number or 'unset'}",
            (48, 198),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (145, 165, 176),
            2,
            cv2.LINE_AA,
        )
        return frame

    @staticmethod
    def _stop_pipeline(pipeline: Optional[rs.pipeline]) -> None:
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:
                pass

    def _frame_from_pipeline(self, pipeline: Optional[rs.pipeline]) -> Optional[np.ndarray]:
        if pipeline is None:
            return None

        try:
            frames = pipeline.wait_for_frames(self.config.video_wait_timeout_ms)
            color_frame = frames.get_color_frame()
        except Exception:
            return None
        if not color_frame:
            return None
        return np.asanyarray(color_frame.get_data())

    @staticmethod
    def _label_webxr_frame(frame_bgr: np.ndarray, serial_number: str) -> np.ndarray:
        frame = frame_bgr.copy()
        cv2.putText(
            frame,
            f"CAMERA {serial_number}",
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        return frame

    def _run(self) -> None:
        period = 1.0 / max(float(self.config.video_fps), 1.0)
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(next_tick - now, 0.01))
                continue

            left_img = None
            right_img = None
            main_img = None

            left_img = self._frame_from_pipeline(self._left_pipeline)
            right_img = self._frame_from_pipeline(self._right_pipeline)
            main_img = self._frame_from_pipeline(self._main_pipeline)

            if left_img is not None:
                self.bridge.publish_video("left_arm", left_img)
            else:
                self.bridge.publish_video("left_arm", self._placeholders["left_arm"])
            if right_img is not None:
                self.bridge.publish_video("right_arm", right_img)
            else:
                self.bridge.publish_video("right_arm", self._placeholders["right_arm"])

            if main_img is not None:
                self.bridge.publish_video("main", main_img)
                self.bridge.publish_webxr_rgb(self._label_webxr_frame(main_img, self.config.main_serial))
            else:
                self.bridge.publish_video("main", self._placeholders["main"])
                self.bridge.publish_webxr_rgb(
                    self._label_webxr_frame(self._placeholders["main"], self.config.main_serial)
                )

            next_tick += period


class GalaxyPointCloudPublisher:
    def __init__(self, config: GalaxyBridgeConfig, bridge: GalaxyZMQBridge, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.bridge = bridge
        self.logger = logger or bridge.logger
        self._last_output_time = 0.0
        self._last_warning_time = 0.0
        self._min_interval = 1.0 / max(float(self.config.pointcloud_hz), 0.1)
        self._subscriber: Optional[rospy.Subscriber] = None

        if not self.config.pointcloud_topic:
            self.logger.warning("Pointcloud topic is empty, pointcloud publisher disabled")
            return

        try:
            self._subscriber = rospy.Subscriber(
                self.config.pointcloud_topic,
                PointCloud2,
                self._callback,
                queue_size=1,
                buff_size=2 ** 24,
            )
            self.logger.info("Pointcloud subscriber ready on %s", self.config.pointcloud_topic)
        except Exception as exc:
            self.logger.warning("Failed to subscribe pointcloud topic=%s: %s", self.config.pointcloud_topic, exc)

    def stop(self) -> None:
        if self._subscriber is not None:
            try:
                self._subscriber.unregister()
            except Exception:
                pass
            self._subscriber = None

    def _callback(self, msg: PointCloud2) -> None:
        now = time.time()
        if now - self._last_output_time < self._min_interval:
            return
        self._last_output_time = now

        try:
            points_iter = pc2.read_points(
                msg,
                field_names=("x", "y", "z"),
                skip_nans=True,
            )
            points = [[float(x), float(y), float(z)] for x, y, z in points_iter]
        except Exception as exc:
            self._sampled_warning("Failed to read pointcloud: %s", exc)
            return

        if not points:
            self._sampled_warning("Pointcloud is empty, skipping publish")
            return

        timestamp = _timestamp(msg.header.stamp if hasattr(msg, "header") else None)
        self.bridge.publish_pointcloud(points, timestamp=timestamp)

    def _sampled_warning(self, message: str, *args) -> None:
        now = time.time()
        if now - self._last_warning_time < 5.0:
            return
        self._last_warning_time = now
        self.logger.warning(message, *args)


class GalaxyOdomPublisher:
    def __init__(self, config: GalaxyBridgeConfig, bridge: GalaxyZMQBridge, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.bridge = bridge
        self.logger = logger or bridge.logger
        self._last_output_time = 0.0
        self._last_warning_time = 0.0
        self._min_interval = 1.0 / max(float(self.config.odom_hz), 0.1)
        self._subscriber: Optional[rospy.Subscriber] = None

        if not self.config.odom_topic:
            self.logger.warning("Odom topic is empty, odom publisher disabled")
            return

        try:
            self._subscriber = rospy.Subscriber(
                self.config.odom_topic,
                Odometry,
                self._callback,
                queue_size=1,
            )
            self.logger.info("Odom subscriber ready on %s", self.config.odom_topic)
        except Exception as exc:
            self.logger.warning("Failed to subscribe odom topic=%s: %s", self.config.odom_topic, exc)

    def stop(self) -> None:
        if self._subscriber is not None:
            try:
                self._subscriber.unregister()
            except Exception:
                pass
            self._subscriber = None

    def _callback(self, msg: Odometry) -> None:
        now = time.time()
        if now - self._last_output_time < self._min_interval:
            return
        self._last_output_time = now

        try:
            p = msg.pose.pose.position
            q = msg.pose.pose.orientation
            pose = [
                float(p.x),
                float(p.y),
                float(p.z),
                float(q.x),
                float(q.y),
                float(q.z),
                float(q.w),
            ]
            timestamp = _timestamp(msg.header.stamp if hasattr(msg, "header") else None)
        except Exception as exc:
            self._sampled_warning("Failed to read odom: %s", exc)
            return

        self.bridge.publish_odom(pose, timestamp=timestamp)

    def _sampled_warning(self, message: str, *args) -> None:
        now = time.time()
        if now - self._last_warning_time < 5.0:
            return
        self._last_warning_time = now
        self.logger.warning(message, *args)


class GalaxyOnlineRuntime:
    def __init__(self, config: Optional[GalaxyBridgeConfig] = None, logger: Optional[logging.Logger] = None) -> None:
        self.config = config or GalaxyBridgeConfig()
        self.logger = logger or GalaxyZMQBridge._build_logger()
        self.bridge = GalaxyZMQBridge(self.config, self.logger)
        self.rgb = RealSenseDualCameraPublisher(self.config, self.bridge, self.logger)
        self.pointcloud = GalaxyPointCloudPublisher(self.config, self.bridge, self.logger)
        self.odom = GalaxyOdomPublisher(self.config, self.bridge, self.logger)

    def start(self) -> None:
        self.bridge.start()
        self.rgb.start()
        self.logger.info("Galaxy online runtime started")

    def stop(self) -> None:
        self.pointcloud.stop()
        self.odom.stop()
        self.rgb.stop()
        self.bridge.stop()
        self.logger.info("Galaxy online runtime stopped")


def main() -> None:
    rospy.init_node("galaxy_online_zmq_bridge", anonymous=False)
    runtime = GalaxyOnlineRuntime()
    runtime.start()
    rospy.on_shutdown(runtime.stop)
    rospy.loginfo("Galaxy online ZMQ bridge is running")
    rospy.spin()


if __name__ == "__main__":
    main()
