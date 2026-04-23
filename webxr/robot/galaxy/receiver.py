from __future__ import annotations

import json
import logging
import math
import os
import signal
from dataclasses import dataclass
from typing import Optional

import zmq
import rospy
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import TwistStamped
from std_msgs.msg import Float32


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
class ReceiverConfig:
    server_host: str = _env("WEBXR_SERVER_HOST", "192.168.31.46")
    control_port: int = _env_int("WEBXR_CONTROL_PORT", 6003)
    poll_timeout_ms: int = _env_int("WEBXR_POLL_TIMEOUT_MS", 200)
    left_topic: str = _env("GALAXY_LEFT_ARM_TOPIC", "/motion_target/target_pose_arm_left")
    right_topic: str = _env("GALAXY_RIGHT_ARM_TOPIC", "/motion_target/target_pose_arm_right")
    chassis_topic: str = _env("GALAXY_CHASSIS_TOPIC", "/motion_target/target_speed_chassis")
    left_gripper_topic: str = _env("GALAXY_LEFT_GRIPPER_TOPIC", "/motion_control/position_control_gripper_left")
    right_gripper_topic: str = _env("GALAXY_RIGHT_GRIPPER_TOPIC", "/motion_control/position_control_gripper_right")

    def resolve_control_endpoint(self) -> str:
        return f"tcp://{self.server_host}:{self.control_port}"


LEFT_ARM_BASE = {
    "position": {"x": 0.1, "y": 0.0, "z": 0.3},
    "orientation": {"x": 0.7, "y": 0.0, "z": 0.0, "w": -0.7},
}

RIGHT_ARM_BASE = {
    "position": {"x": 0.1, "y": 0.0, "z": 0.3},
    "orientation": {"x": 0.7, "y": 0.0, "z": 0.0, "w": 0.7},
}


def round_number(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def normalize_quaternion(quaternion: dict) -> dict:
    x = float(quaternion.get("x", 0.0) or 0.0)
    y = float(quaternion.get("y", 0.0) or 0.0)
    z = float(quaternion.get("z", 0.0) or 0.0)
    w = float(quaternion.get("w", 1.0) or 1.0)
    norm = math.sqrt(x * x + y * y + z * z + w * w)

    if norm == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}

    return {
        "x": round_number(x / norm),
        "y": round_number(y / norm),
        "z": round_number(z / norm),
        "w": round_number(w / norm),
    }


def quaternion_multiply(a: dict, b: dict) -> dict:
    ax = float(a.get("x", 0.0) or 0.0)
    ay = float(a.get("y", 0.0) or 0.0)
    az = float(a.get("z", 0.0) or 0.0)
    aw = float(a.get("w", 1.0) or 1.0)

    bx = float(b.get("x", 0.0) or 0.0)
    by = float(b.get("y", 0.0) or 0.0)
    bz = float(b.get("z", 0.0) or 0.0)
    bw = float(b.get("w", 1.0) or 1.0)

    return normalize_quaternion(
        {
            "x": aw * bx + ax * bw + ay * bz - az * by,
            "y": aw * by - ax * bz + ay * bw + az * bx,
            "z": aw * bz + ax * by - ay * bx + az * bw,
            "w": aw * bw - ax * bx - ay * by - az * bz,
        }
    )


def quaternion_to_euler_degrees(orientation: Optional[dict]) -> dict:
    if not orientation:
        return {"roll": None, "pitch": None, "yaw": None}

    q = normalize_quaternion(orientation)
    x = q["x"]
    y = q["y"]
    z = q["z"]
    w = q["w"]

    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return {
        "roll": round(math.degrees(roll), 2),
        "pitch": round(math.degrees(pitch), 2),
        "yaw": round(math.degrees(yaw), 2),
    }


def add_base_transform(base: dict, pose: dict) -> dict:
    base_position = base["position"]
    pose_position = pose.get("pos") or {}

    target_position = {
        "x": round_number(base_position["x"] + float(pose_position.get("x", 0.0) or 0.0)),
        "y": round_number(base_position["y"] + float(pose_position.get("y", 0.0) or 0.0)),
        "z": round_number(base_position["z"] + float(pose_position.get("z", 0.0) or 0.0)),
    }

    target_orientation = quaternion_multiply(
        pose.get("rot") or {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        base["orientation"],
    )

    return {
        "position": target_position,
        "orientation": target_orientation,
    }


def base_pose_only(base: dict) -> dict:
    return {
        "position": {
            "x": base["position"]["x"],
            "y": base["position"]["y"],
            "z": base["position"]["z"],
        },
        "orientation": normalize_quaternion(base["orientation"]),
    }


def gripper_value_from_index0(index0_value) -> float:
    raw_value = float(index0_value or 0.0)
    return round_number((1.0 - raw_value) * 100.0, 2)


def build_chassis_command(left: dict, right: dict, apply_to_robot: bool) -> TwistStamped:
    left_axes = left.get("axes") or {}
    right_axes = right.get("axes") or {}

    linear_x = float(left_axes.get("axis2", 0.0) or 0.0) * 0.2
    linear_y = float(left_axes.get("axis3", 0.0) or 0.0) * 0.2
    angular_z = float(right_axes.get("axis3", 0.0) or 0.0) * 0.5

    msg = TwistStamped()
    msg.header.stamp = rospy.Time.now()
    msg.header.frame_id = "base_link"
    msg.twist.linear.x = round_number(linear_x)
    msg.twist.linear.y = round_number(linear_y)
    msg.twist.linear.z = 0.0
    msg.twist.angular.x = 0.0
    msg.twist.angular.y = 0.0
    msg.twist.angular.z = round_number(angular_z)
    return msg


class GalaxyArmReceiver:
    def __init__(self, config: Optional[ReceiverConfig] = None, logger: Optional[logging.Logger] = None) -> None:
        self.config = config or ReceiverConfig()
        self.logger = logger or self._build_logger()
        self._context = zmq.Context.instance()
        self._socket: Optional[zmq.Socket] = None
        self._running = False
        self._left_publisher = rospy.Publisher(self.config.left_topic, PoseStamped, queue_size=10)
        self._right_publisher = rospy.Publisher(self.config.right_topic, PoseStamped, queue_size=10)
        self._chassis_publisher = rospy.Publisher(self.config.chassis_topic, TwistStamped, queue_size=10)
        self._left_gripper_publisher = rospy.Publisher(self.config.left_gripper_topic, Float32, queue_size=10)
        self._right_gripper_publisher = rospy.Publisher(self.config.right_gripper_topic, Float32, queue_size=10)

    @staticmethod
    def _build_logger() -> logging.Logger:
        logger = logging.getLogger("webxr_galaxy_receiver")
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(handler)
        return logger

    def start(self) -> None:
        if self._socket is not None:
            return

        socket = self._context.socket(zmq.SUB)
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
        socket.setsockopt(zmq.RCVHWM, 32)
        socket.connect(self.config.resolve_control_endpoint())

        self._socket = socket
        self._running = True
        self.logger.info("Receiver connected to %s", self.config.resolve_control_endpoint())
        self.logger.info("ROS left topic: %s", self.config.left_topic)
        self.logger.info("ROS right topic: %s", self.config.right_topic)
        self.logger.info("ROS chassis topic: %s", self.config.chassis_topic)
        self.logger.info("ROS left gripper topic: %s", self.config.left_gripper_topic)
        self.logger.info("ROS right gripper topic: %s", self.config.right_gripper_topic)

    def stop(self) -> None:
        self._running = False
        if self._socket is not None:
            self._socket.close(0)
            self._socket = None

    def run_forever(self) -> None:
        self.start()
        assert self._socket is not None

        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)

        while self._running:
            events = dict(poller.poll(timeout=self.config.poll_timeout_ms))
            if self._socket not in events:
                continue

            try:
                payload = self._socket.recv_json(flags=zmq.NOBLOCK)
            except zmq.Again:
                continue
            except Exception as exc:
                self.logger.warning("Failed to receive control payload: %s", exc)
                continue

            self._handle_payload(payload)

    def _handle_payload(self, payload: dict) -> None:
        apply_to_robot = bool(payload.get("apply_to_robot", False))
        left = payload.get("left") or {}
        right = payload.get("right") or {}

        self._debug_print_arm("left", left)
        self._debug_print_arm("right", right)
        self.logger.info("apply_to_robot=%s", apply_to_robot)

        left_gripper_msg = Float32(data=gripper_value_from_index0(left.get("index0_value", 0.0)))
        right_gripper_msg = Float32(data=gripper_value_from_index0(right.get("index0_value", 0.0)))
        self._left_gripper_publisher.publish(left_gripper_msg)
        self._right_gripper_publisher.publish(right_gripper_msg)

        chassis_msg = build_chassis_command(left, right, apply_to_robot)
        self._chassis_publisher.publish(chassis_msg)

        if apply_to_robot:
            left_target = add_base_transform(LEFT_ARM_BASE, left)
            right_target = add_base_transform(RIGHT_ARM_BASE, right)
        else:
            left_target = base_pose_only(LEFT_ARM_BASE)
            right_target = base_pose_only(RIGHT_ARM_BASE)

        left_msg = self._build_pose_stamped(left_target)
        right_msg = self._build_pose_stamped(right_target)
        self._left_publisher.publish(left_msg)
        self._right_publisher.publish(right_msg)

        left_target_euler = quaternion_to_euler_degrees(left_target["orientation"])
        right_target_euler = quaternion_to_euler_degrees(right_target["orientation"])
        self.logger.info(
            "ros_target_mode=%s left_target_pos=(%s, %s, %s) left_target_euler=(%s, %s, %s) right_target_pos=(%s, %s, %s) right_target_euler=(%s, %s, %s)",
            "teleop" if apply_to_robot else "base",
            left_target["position"]["x"],
            left_target["position"]["y"],
            left_target["position"]["z"],
            left_target_euler["roll"],
            left_target_euler["pitch"],
            left_target_euler["yaw"],
            right_target["position"]["x"],
            right_target["position"]["y"],
            right_target["position"]["z"],
            right_target_euler["roll"],
            right_target_euler["pitch"],
            right_target_euler["yaw"],
        )
        self.logger.info(
            "gripper_target left=%s right=%s",
            left_gripper_msg.data,
            right_gripper_msg.data,
        )
        self.logger.info(
            "chassis_target linear=(%s, %s, %s) angular=(%s, %s, %s)",
            chassis_msg.twist.linear.x,
            chassis_msg.twist.linear.y,
            chassis_msg.twist.linear.z,
            chassis_msg.twist.angular.x,
            chassis_msg.twist.angular.y,
            chassis_msg.twist.angular.z,
        )

    def _debug_print_arm(self, name: str, arm_data: dict) -> None:
        pos = arm_data.get("pos") or {}
        rot = arm_data.get("rot") or {}
        euler = quaternion_to_euler_degrees(rot)
        index0_value = arm_data.get("index0_value", 0.0)
        axes = arm_data.get("axes") or {}

        self.logger.info(
            "%s raw pos=(%s, %s, %s) euler_deg=(%s, %s, %s) index0_value=%s axes=(%s, %s)",
            name,
            pos.get("x"),
            pos.get("y"),
            pos.get("z"),
            euler.get("roll"),
            euler.get("pitch"),
            euler.get("yaw"),
            index0_value,
            axes.get("axis2"),
            axes.get("axis3"),
        )

    def _build_pose_stamped(self, pose: dict):
        msg = PoseStamped()
        msg.header.stamp = rospy.Time.now()
        msg.pose.position.x = pose["position"]["x"]
        msg.pose.position.y = pose["position"]["y"]
        msg.pose.position.z = pose["position"]["z"]
        msg.pose.orientation.x = pose["orientation"]["x"]
        msg.pose.orientation.y = pose["orientation"]["y"]
        msg.pose.orientation.z = pose["orientation"]["z"]
        msg.pose.orientation.w = pose["orientation"]["w"]
        return msg


def main() -> None:
    rospy.init_node("webxr_galaxy_receiver", anonymous=False)
    receiver = GalaxyArmReceiver()

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
