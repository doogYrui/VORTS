import http.server
import json
import math
import ssl
from pathlib import Path


PORT = 1142
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


def round_number(value, digits=4):
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
    raw_axis2 = float(axes.get("axis2", 0) or 0)
    raw_axis3 = float(axes.get("axis3", 0) or 0)
    return {
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
        return payload

    buttons = right.get("buttons") or {}
    index4 = buttons.get("index4") or {}
    is_pressed = bool(index4.get("pressed"))
    left_position = ((left.get("pose") or {}).get("position"))
    position = ((right.get("pose") or {}).get("position"))

    if is_pressed and not RIGHT_INDEX4_WAS_PRESSED:
        APPLY_TO_ROBOT = not APPLY_TO_ROBOT

        if left.get("available") and left_position:
            LEFT_POSITION_ZERO_OFFSET = {
                "x": left_position.get("x", 0),
                "y": left_position.get("y", 0),
                "z": left_position.get("z", 0),
            }

        if position:
            RIGHT_POSITION_ZERO_OFFSET = {
                "x": position.get("x", 0),
                "y": position.get("y", 0),
                "z": position.get("z", 0),
            }

    RIGHT_INDEX4_WAS_PRESSED = is_pressed

    if left_position and LEFT_POSITION_ZERO_OFFSET:
        left["pose"]["position"] = offset_position(left_position, LEFT_POSITION_ZERO_OFFSET)

    if position and RIGHT_POSITION_ZERO_OFFSET:
        right["pose"]["position"] = offset_position(position, RIGHT_POSITION_ZERO_OFFSET)

    payload["apply_to_robot"] = APPLY_TO_ROBOT
    return payload


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


def debug_print_quest_data(payload):
    print("\n[quest-data] received")
    print(f"apply_to_robot: {payload.get('apply_to_robot')}")
    print(short_controller_state("left", payload.get("left")))
    print(short_controller_state("right", payload.get("right")))
    # print(json.dumps(payload, ensure_ascii=False, indent=2))


def send_to_robot(payload):
    # Placeholder for future ZMQ forwarding.
    return payload


def handle_quest_data(payload):
    cleaned_payload = sanitize_payload(payload)
    cleaned_payload = apply_right_position_zero(cleaned_payload)
    debug_print_quest_data(cleaned_payload)
    send_to_robot(cleaned_payload)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        if self.path == "/quest-data":
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path != "/quest-data":
            self.send_error(404, "Not Found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        handle_quest_data(payload)

        response = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))
httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

print(f"https server running at https://0.0.0.0:{PORT}")
print(f"quest data endpoint: https://0.0.0.0:{PORT}/quest-data")
httpd.serve_forever()
