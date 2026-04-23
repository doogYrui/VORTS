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


def convert_orientation_to_ros(orientation):
    quest_rotation = quaternion_to_matrix(orientation)
    ros_basis_t = transpose_matrix(QUEST_TO_ROS_BASIS)
    ros_rotation = multiply_matrix(
        multiply_matrix(QUEST_TO_ROS_BASIS, quest_rotation),
        ros_basis_t,
    )
    return matrix_to_quaternion(ros_rotation)


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
        cleaned["pose"]["orientation"] = convert_orientation_to_ros(orientation)

    buttons = data.get("buttons") if isinstance(data.get("buttons"), dict) else {}
    cleaned["buttons"]["index0"] = sanitize_button_state(buttons.get("index0"))
    cleaned["buttons"]["index4"] = sanitize_button_state(buttons.get("index4"))

    axes = data.get("axes") if isinstance(data.get("axes"), dict) else {}
    cleaned["axes"] = {
        "axis2": float(axes.get("axis2", 0) or 0),
        "axis3": float(axes.get("axis3", 0) or 0),
    }

    return cleaned


def sanitize_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    return {
        "ts": payload.get("ts"),
        "left": sanitize_controller_state("left", payload.get("left")),
        "right": sanitize_controller_state("right", payload.get("right")),
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


def debug_print_quest_data(payload):
    print("\n[quest-data] received")
    print(short_controller_state("left", payload.get("left")))
    print(short_controller_state("right", payload.get("right")))
    # print(json.dumps(payload, ensure_ascii=False, indent=2))


def send_to_robot(payload):
    # Placeholder for future ZMQ forwarding.
    return payload


def handle_quest_data(payload):
    cleaned_payload = sanitize_payload(payload)
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
