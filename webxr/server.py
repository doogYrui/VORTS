from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
import zmq
import zmq.asyncio
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


HTTPS_PORT = 1142
ZMQ_CONTROL_BIND_PORT = 6003
ZMQ_VIDEO_BIND_PORT = 6004

ROOT = Path(__file__).resolve().parent
CERT_FILE = ROOT / "localhost.pem"
KEY_FILE = ROOT / "localhost-key.pem"

QUEST_TO_ROS_BASIS = (
    (0.0, 0.0, -1.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
)

LEFT_POSITION_ZERO_OFFSET = None
RIGHT_POSITION_ZERO_OFFSET = None
RIGHT_INDEX4_WAS_PRESSED = False
APPLY_TO_ROBOT = False
ROTATION_ZERO_REFERENCE_EULER_DEG = {
    "roll": 0.0,
    "pitch": -35.0,
    "yaw": 0.0,
}


class StreamBroker:
    def __init__(self, name: str) -> None:
        self.name = name
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._latest: dict[str, object] = {}

    def subscribe(self, key: str, maxsize: int = 1) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[key].add(queue)
        if key in self._latest:
            self._enqueue(queue, self._latest[key])
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(key)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(key, None)

    def publish(self, key: str, payload: object) -> None:
        self._latest[key] = payload
        for queue in list(self._subscribers.get(key, set())):
            self._enqueue(queue, payload)

    def _enqueue(self, queue: asyncio.Queue, payload: object) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)


def round_number(value, digits: int = 4):
    return round(float(value), digits)


def make_empty_controller_state(handedness):
    return {
        "handedness": handedness,
        "available": False,
        "pose": {
            "position": None,
            "orientation": None,
        },
        "buttons": {
            "index0": {
                "pressed": False,
                "value": 0,
            },
            "index4": {
                "pressed": False,
                "value": 0,
            },
        },
        "axes": {
            "axis0": 0,
            "axis1": 0,
            "axis2": 0,
            "axis3": 0,
        },
    }


def sanitize_button_state(button_data):
    button_data = button_data or {}
    return {
        "pressed": bool(button_data.get("pressed", False)),
        "value": float(button_data.get("value", 0) or 0),
    }


def convert_axes(axes):
    axes = axes if isinstance(axes, dict) else {}
    raw_axis0 = float(axes.get("axis0", 0) or 0)
    raw_axis1 = float(axes.get("axis1", 0) or 0)
    raw_axis2 = float(axes.get("axis2", 0) or 0)
    raw_axis3 = float(axes.get("axis3", 0) or 0)
    return {
        "axis0": round_number(raw_axis0),
        "axis1": round_number(raw_axis1),
        "axis2": round_number(-raw_axis3),
        "axis3": round_number(-raw_axis2),
    }


def convert_position_to_ros(position):
    return {
        "x": round_number(-(position.get("z", 0) or 0)),
        "y": round_number(-(position.get("x", 0) or 0)),
        "z": round_number(position.get("y", 0) or 0),
    }


def quaternion_to_matrix(orientation):
    x = float(orientation.get("x", 0) or 0)
    y = float(orientation.get("y", 0) or 0)
    z = float(orientation.get("z", 0) or 0)
    w = float(orientation.get("w", 1) or 1)

    return (
        (
            1 - 2 * (y * y + z * z),
            2 * (x * y - z * w),
            2 * (x * z + y * w),
        ),
        (
            2 * (x * y + z * w),
            1 - 2 * (x * x + z * z),
            2 * (y * z - x * w),
        ),
        (
            2 * (x * z - y * w),
            2 * (y * z + x * w),
            1 - 2 * (x * x + y * y),
        ),
    )


def transpose_matrix(matrix):
    return tuple(tuple(matrix[j][i] for j in range(3)) for i in range(3))


def multiply_matrix(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def matrix_to_quaternion(matrix):
    m00, m01, m02 = matrix[0]
    m10, m11, m12 = matrix[1]
    m20, m21, m22 = matrix[2]
    trace = m00 + m11 + m22

    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s

    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}

    return {
        "x": round_number(x / norm),
        "y": round_number(y / norm),
        "z": round_number(z / norm),
        "w": round_number(w / norm),
    }


def normalize_quaternion(quaternion):
    x = float(quaternion.get("x", 0) or 0)
    y = float(quaternion.get("y", 0) or 0)
    z = float(quaternion.get("z", 0) or 0)
    w = float(quaternion.get("w", 1) or 1)
    norm = math.sqrt(x * x + y * y + z * z + w * w)

    if norm == 0:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}

    return {
        "x": round_number(x / norm),
        "y": round_number(y / norm),
        "z": round_number(z / norm),
        "w": round_number(w / norm),
    }


def quaternion_multiply(a, b):
    ax = float(a.get("x", 0) or 0)
    ay = float(a.get("y", 0) or 0)
    az = float(a.get("z", 0) or 0)
    aw = float(a.get("w", 1) or 1)

    bx = float(b.get("x", 0) or 0)
    by = float(b.get("y", 0) or 0)
    bz = float(b.get("z", 0) or 0)
    bw = float(b.get("w", 1) or 1)

    return normalize_quaternion(
        {
            "x": aw * bx + ax * bw + ay * bz - az * by,
            "y": aw * by - ax * bz + ay * bw + az * bx,
            "z": aw * bz + ax * by - ay * bx + az * bw,
            "w": aw * bw - ax * bx - ay * by - az * bz,
        }
    )


def quaternion_conjugate(quaternion):
    return {
        "x": round_number(-(quaternion.get("x", 0) or 0)),
        "y": round_number(-(quaternion.get("y", 0) or 0)),
        "z": round_number(-(quaternion.get("z", 0) or 0)),
        "w": round_number(quaternion.get("w", 1) or 1),
    }


def euler_degrees_to_quaternion(roll, pitch, yaw):
    roll_rad = math.radians(roll)
    pitch_rad = math.radians(pitch)
    yaw_rad = math.radians(yaw)

    cr = math.cos(roll_rad / 2)
    sr = math.sin(roll_rad / 2)
    cp = math.cos(pitch_rad / 2)
    sp = math.sin(pitch_rad / 2)
    cy = math.cos(yaw_rad / 2)
    sy = math.sin(yaw_rad / 2)

    return normalize_quaternion(
        {
            "x": sr * cp * cy - cr * sp * sy,
            "y": cr * sp * cy + sr * cp * sy,
            "z": cr * cp * sy - sr * sp * cy,
            "w": cr * cp * cy + sr * sp * sy,
        }
    )


def convert_orientation_to_ros(orientation):
    quest_rotation = quaternion_to_matrix(orientation)
    ros_basis_t = transpose_matrix(QUEST_TO_ROS_BASIS)
    ros_rotation = multiply_matrix(
        multiply_matrix(QUEST_TO_ROS_BASIS, quest_rotation),
        ros_basis_t,
    )
    return matrix_to_quaternion(ros_rotation)


def apply_rotation_zero_reference(orientation):
    reference = euler_degrees_to_quaternion(
        ROTATION_ZERO_REFERENCE_EULER_DEG["roll"],
        ROTATION_ZERO_REFERENCE_EULER_DEG["pitch"],
        ROTATION_ZERO_REFERENCE_EULER_DEG["yaw"],
    )
    reference_inverse = quaternion_conjugate(reference)
    return quaternion_multiply(reference_inverse, orientation)


def sanitize_controller_state(handedness, data):
    cleaned = make_empty_controller_state(handedness)
    if not isinstance(data, dict):
        return cleaned

    cleaned["available"] = bool(data.get("available", False))

    pose = data.get("pose") if isinstance(data.get("pose"), dict) else {}
    position = pose.get("position") if isinstance(pose.get("position"), dict) else None
    orientation = pose.get("orientation") if isinstance(pose.get("orientation"), dict) else None

    if position:
        cleaned["pose"]["position"] = convert_position_to_ros(position)

    if orientation:
        ros_orientation = convert_orientation_to_ros(orientation)
        cleaned["pose"]["orientation"] = apply_rotation_zero_reference(ros_orientation)

    buttons = data.get("buttons") if isinstance(data.get("buttons"), dict) else {}
    cleaned["buttons"]["index0"] = sanitize_button_state(buttons.get("index0"))
    cleaned["buttons"]["index4"] = sanitize_button_state(buttons.get("index4"))
    cleaned["axes"] = convert_axes(data.get("axes"))
    return cleaned


def sanitize_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    return {
        "ts": payload.get("ts"),
        "apply_to_robot": APPLY_TO_ROBOT,
        "left": sanitize_controller_state("left", payload.get("left")),
        "right": sanitize_controller_state("right", payload.get("right")),
    }


def offset_position(position, offset):
    if not position or not offset:
        return position

    return {
        "x": round_number(position.get("x", 0) - offset.get("x", 0)),
        "y": round_number(position.get("y", 0) - offset.get("y", 0)),
        "z": round_number(position.get("z", 0) - offset.get("z", 0)),
    }


def apply_right_position_zero(payload):
    global LEFT_POSITION_ZERO_OFFSET
    global RIGHT_POSITION_ZERO_OFFSET
    global RIGHT_INDEX4_WAS_PRESSED
    global APPLY_TO_ROBOT

    left = payload.get("left") or {}
    right = payload.get("right") or {}
    if not right.get("available"):
        RIGHT_INDEX4_WAS_PRESSED = False
        payload["apply_to_robot"] = APPLY_TO_ROBOT
        return payload

    buttons = right.get("buttons") or {}
    index4 = buttons.get("index4") or {}
    is_pressed = bool(index4.get("pressed"))
    left_position = ((left.get("pose") or {}).get("position"))
    right_position = ((right.get("pose") or {}).get("position"))

    if is_pressed and not RIGHT_INDEX4_WAS_PRESSED:
        APPLY_TO_ROBOT = not APPLY_TO_ROBOT

        if left.get("available") and left_position:
            LEFT_POSITION_ZERO_OFFSET = {
                "x": left_position.get("x", 0),
                "y": left_position.get("y", 0),
                "z": left_position.get("z", 0),
            }

        if right_position:
            RIGHT_POSITION_ZERO_OFFSET = {
                "x": right_position.get("x", 0),
                "y": right_position.get("y", 0),
                "z": right_position.get("z", 0),
            }

    RIGHT_INDEX4_WAS_PRESSED = is_pressed

    if left_position and LEFT_POSITION_ZERO_OFFSET:
        left["pose"]["position"] = offset_position(left_position, LEFT_POSITION_ZERO_OFFSET)

    if right_position and RIGHT_POSITION_ZERO_OFFSET:
        right["pose"]["position"] = offset_position(right_position, RIGHT_POSITION_ZERO_OFFSET)

    payload["apply_to_robot"] = APPLY_TO_ROBOT
    return payload


def build_robot_controller_payload(controller):
    pose = controller.get("pose") or {}
    buttons = controller.get("buttons") or {}
    return {
        "pos": pose.get("position"),
        "rot": pose.get("orientation"),
        "index0_value": (buttons.get("index0") or {}).get("value", 0.0),
        "axes": controller.get("axes"),
    }


def build_robot_payload(payload):
    return {
        "apply_to_robot": bool(payload.get("apply_to_robot", False)),
        "left": build_robot_controller_payload(payload.get("left") or {}),
        "right": build_robot_controller_payload(payload.get("right") or {}),
    }


def quaternion_to_euler_degrees(orientation):
    if not orientation:
        return {
            "roll": None,
            "pitch": None,
            "yaw": None,
        }

    x = float(orientation.get("x", 0) or 0)
    y = float(orientation.get("y", 0) or 0)
    z = float(orientation.get("z", 0) or 0)
    w = float(orientation.get("w", 1) or 1)

    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return {
        "roll": round(math.degrees(roll), 2),
        "pitch": round(math.degrees(pitch), 2),
        "yaw": round(math.degrees(yaw), 2),
    }


def short_controller_state(name, data):
    if not data.get("available"):
        return f"{name}: unavailable"

    pose = data.get("pose") or {}
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    euler = quaternion_to_euler_degrees(orientation)
    buttons = data.get("buttons") or {}
    axes = data.get("axes") or {}
    return (
        f"{name}: "
        f"pos=({position.get('x')}, {position.get('y')}, {position.get('z')}) "
        f"rot_deg=({euler.get('roll')}, {euler.get('pitch')}, {euler.get('yaw')}) "
        f"index0={buttons.get('index0')} "
        f"index4={buttons.get('index4')} "
        f"axes=({axes.get('axis2')}, {axes.get('axis3')})"
    )


def debug_print_quest_data(payload, robot_payload):
    print("\n[quest-data] received")
    print(f"apply_to_robot: {payload.get('apply_to_robot')}")
    print(short_controller_state("left", payload.get("left")))
    print(short_controller_state("right", payload.get("right")))
    print("[robot-payload]")
    print(json.dumps(robot_payload, ensure_ascii=False, indent=2))


async def send_to_robot(payload, socket):
    robot_payload = build_robot_payload(payload)
    await socket.send_json(robot_payload)
    return robot_payload


async def handle_quest_data(payload, socket):
    cleaned_payload = sanitize_payload(payload)
    cleaned_payload = apply_right_position_zero(cleaned_payload)
    robot_payload = await send_to_robot(cleaned_payload, socket)
    # debug_print_quest_data(cleaned_payload, robot_payload)
    return cleaned_payload


def topic_to_video_key(topic: str) -> str | None:
    if not topic.startswith("video."):
        return None

    parts = topic.split(".")
    if len(parts) < 3:
        return None

    robot_name = parts[1]
    camera_name = ".".join(parts[2:])
    return f"{robot_name}/{camera_name}"


async def video_zmq_loop(app: FastAPI) -> None:
    socket = app.state.video_sub_socket
    broker = app.state.video_broker
    meta_broker = app.state.video_meta_broker

    while True:
        message = await socket.recv_multipart()
        if len(message) == 2:
            topic_raw, payload = message
            metadata = None
        elif len(message) >= 3:
            topic_raw, metadata_raw, payload = message[:3]
            try:
                metadata = json.loads(metadata_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                metadata = None
        else:
            continue

        topic = topic_raw.decode("utf-8", errors="ignore")
        key = topic_to_video_key(topic)
        if key:
            broker.publish(key, payload)
            if metadata is not None:
                meta_broker.publish(key, metadata)


@asynccontextmanager
async def lifespan(app: FastAPI):
    context = zmq.asyncio.Context.instance()

    control_pub_socket = context.socket(zmq.PUB)
    control_pub_socket.setsockopt(zmq.SNDHWM, 32)
    control_pub_socket.bind(f"tcp://0.0.0.0:{ZMQ_CONTROL_BIND_PORT}")

    video_sub_socket = context.socket(zmq.SUB)
    video_sub_socket.setsockopt(zmq.RCVHWM, 32)
    video_sub_socket.setsockopt_string(zmq.SUBSCRIBE, "video.")
    video_sub_socket.bind(f"tcp://0.0.0.0:{ZMQ_VIDEO_BIND_PORT}")

    app.state.control_pub_socket = control_pub_socket
    app.state.video_sub_socket = video_sub_socket
    app.state.video_broker = StreamBroker("video")
    app.state.video_meta_broker = StreamBroker("video_meta")

    video_task = asyncio.create_task(video_zmq_loop(app), name="webxr-video-zmq")

    print(f"https server running at https://0.0.0.0:{HTTPS_PORT}")
    print(f"quest data endpoint: https://0.0.0.0:{HTTPS_PORT}/quest-data")
    print(f"robot control publisher: tcp://0.0.0.0:{ZMQ_CONTROL_BIND_PORT}")
    print(f"robot video subscriber: tcp://0.0.0.0:{ZMQ_VIDEO_BIND_PORT}")

    try:
        yield
    finally:
        video_task.cancel()
        with suppress(asyncio.CancelledError):
            await video_task

        video_sub_socket.close(0)
        control_pub_socket.close(0)


app = FastAPI(title="WebXR Quest Bridge", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/quest-data")
async def post_quest_data(request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    processed = await handle_quest_data(payload, app.state.control_pub_socket)
    return {"ok": True, "apply_to_robot": processed.get("apply_to_robot")}


@app.websocket("/ws/video/{robot_name}/{camera_name}")
async def websocket_video(websocket: WebSocket, robot_name: str, camera_name: str):
    await websocket.accept()
    key = f"{robot_name}/{camera_name}"
    queue = app.state.video_broker.subscribe(key)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_bytes(payload)
    except WebSocketDisconnect:
        pass
    finally:
        app.state.video_broker.unsubscribe(key, queue)


@app.websocket("/ws/video_meta/{robot_name}/{camera_name}")
async def websocket_video_meta(websocket: WebSocket, robot_name: str, camera_name: str):
    await websocket.accept()
    key = f"{robot_name}/{camera_name}"
    queue = app.state.video_meta_broker.subscribe(key)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        app.state.video_meta_broker.unsubscribe(key, queue)


app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=HTTPS_PORT,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
        reload=False,
    )
