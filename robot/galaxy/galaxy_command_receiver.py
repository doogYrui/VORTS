from __future__ import annotations

import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from typing import Optional

import zmq
import rospy
from geometry_msgs.msg import TwistStamped


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
class CommandReceiverConfig:
    robot_name: str = _env("GALAXY_ROBOT_NAME", "galaxy")
    backend_host: str = _env("VORTS_BACKEND_HOST", _env("BACKEND_HOST", "192.168.31.32"))
    command_endpoint: str = _env("VORTS_COMMAND_ENDPOINT", "")
    command_port: int = _env_int("VORTS_COMMAND_PORT", 6002)
    chassis_topic: str = _env("GALAXY_CHASSIS_TOPIC", "/motion_target/target_speed_chassis")
    linear_speed: float = float(_env("GALAXY_LINEAR_SPEED", "0.2"))
    angular_speed: float = float(_env("GALAXY_ANGULAR_SPEED", "0.5"))
    poll_timeout_ms: int = _env_int("GALAXY_POLL_TIMEOUT_MS", 200)

    def resolve_command_endpoint(self) -> str:
        if self.command_endpoint:
            return self.command_endpoint
        return f"tcp://{self.backend_host}:{self.command_port}"


class GalaxyCommandReceiver:
    def __init__(self, config: Optional[CommandReceiverConfig] = None, logger: Optional[logging.Logger] = None) -> None:
        self.config = config or CommandReceiverConfig()
        self.logger = logger or self._build_logger()
        self._context = zmq.Context.instance()
        self._socket: Optional[zmq.Socket] = None
        self._publisher = None
        self._stop_event = threading.Event()

    @staticmethod
    def _build_logger() -> logging.Logger:
        logger = logging.getLogger("galaxy_command_receiver")
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(handler)
        return logger

    def start(self) -> None:
        if self._socket is not None or self._publisher is not None:
            return

        socket = self._context.socket(zmq.SUB)
        socket.setsockopt_string(zmq.SUBSCRIBE, f"teleop.{self.config.robot_name}")
        socket.setsockopt_string(zmq.SUBSCRIBE, "task.broadcast")
        socket.setsockopt(zmq.RCVHWM, 32)
        socket.connect(self.config.resolve_command_endpoint())

        self._socket = socket
        self._publisher = rospy.Publisher(self.config.chassis_topic, TwistStamped, queue_size=10)
        self.logger.info("Command receiver connected to %s", self.config.resolve_command_endpoint())
        self.logger.info("ROS publisher ready on %s", self.config.chassis_topic)

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None
        self._publisher = None

    def run_forever(self) -> None:
        self.start()
        assert self._socket is not None

        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)

        while not self._stop_event.is_set() and not rospy.is_shutdown():
            events = dict(poller.poll(timeout=self.config.poll_timeout_ms))
            if self._socket not in events:
                continue

            try:
                topic_raw, payload = self._socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue

            topic = topic_raw.decode("utf-8", errors="ignore")
            self._handle_message(topic, payload)

    def _handle_message(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.logger.warning("Failed to decode message topic=%s payload_len=%d", topic, len(payload))
            return

        if topic == f"teleop.{self.config.robot_name}":
            keys = self._normalize_keys(data.get("keys", []))
            ts = data.get("ts")
            twist_msg = self._build_twist_message(keys, ts)
            self._publish_twist(twist_msg)
            self.logger.info(
                "teleop received | robot=%s keys=%s twist=(%.3f, %.3f, %.3f) ts=%s",
                self.config.robot_name,
                keys,
                twist_msg.twist.linear.x,
                twist_msg.twist.linear.y,
                twist_msg.twist.angular.z,
                ts,
            )
            return

        if topic == "task.broadcast":
            task_type = data.get("task_type")
            task_content = data.get("task_content")
            self.logger.info("task received | type=%s content=%s", task_type, task_content)
            return

        self.logger.info("unknown topic=%s data=%s", topic, data)

    @staticmethod
    def _normalize_keys(keys) -> list:
        if not isinstance(keys, (list, tuple)):
            return []
        normalized = []
        for key in keys:
            if isinstance(key, str):
                normalized.append(key.lower())
        return normalized

    def _build_twist_message(self, keys, ts) -> TwistStamped:
        msg = TwistStamped()
        msg.header.stamp = self._to_ros_time(ts)
        msg.header.frame_id = "base_link"

        linear_x = 0.0
        linear_y = 0.0
        angular_z = 0.0

        if "w" in keys:
            linear_x += self.config.linear_speed
        if "s" in keys:
            linear_x -= self.config.linear_speed
        if "a" in keys:
            linear_y += self.config.linear_speed
        if "d" in keys:
            linear_y -= self.config.linear_speed
        if "q" in keys:
            angular_z += self.config.angular_speed
        if "e" in keys:
            angular_z -= self.config.angular_speed

        msg.twist.linear.x = linear_x
        msg.twist.linear.y = linear_y
        msg.twist.linear.z = 0.0
        msg.twist.angular.x = 0.0
        msg.twist.angular.y = 0.0
        msg.twist.angular.z = angular_z
        return msg

    @staticmethod
    def _to_ros_time(ts) -> rospy.Time:
        try:
            if ts is not None:
                return rospy.Time.from_sec(float(ts))
        except Exception:
            pass
        return rospy.Time.now()

    def _publish_twist(self, twist_msg: TwistStamped) -> None:
        if self._publisher is None:
            return
        self._publisher.publish(twist_msg)


def main() -> None:
    rospy.init_node("galaxy_command_receiver", anonymous=False)
    receiver = GalaxyCommandReceiver()

    def _shutdown_handler(_signum, _frame) -> None:
        receiver.stop()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    try:
        receiver.run_forever()
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()
