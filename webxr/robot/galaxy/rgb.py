import sys
import time
import cv2
import numpy as np
import pyrealsense2 as rs
import zmq


CAMERA_SN = "347622072588"
ROBOT_NAME = "galaxy"
CAMERA_NAME = "rgb"
SERVER_HOST = "192.168.31.46"
ZMQ_VIDEO_PORT = 6004
JPEG_QUALITY = 85

WIDTH = 640
HEIGHT = 480
FPS = 15


def create_pipeline(serial_number: str):
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial_number)
    config.enable_stream(rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS)
    pipeline.start(config)
    return pipeline


def encode_jpeg(frame_bgr: np.ndarray):
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(JPEG_QUALITY)]
    ok, buffer = cv2.imencode(".jpg", frame_bgr, encode_params)
    if not ok:
        raise RuntimeError("Failed to encode JPEG frame")
    return buffer.tobytes()


def main():
    pipeline = None
    socket = None
    context = zmq.Context.instance()

    try:
        print(f"Starting camera: {CAMERA_SN}")
        pipeline = create_pipeline(CAMERA_SN)

        endpoint = f"tcp://{SERVER_HOST}:{ZMQ_VIDEO_PORT}"
        socket = context.socket(zmq.PUB)
        socket.setsockopt(zmq.SNDHWM, 32)
        socket.connect(endpoint)

        # Give PUB/SUB a brief moment to establish.
        time.sleep(0.3)

        print(f"Camera started. Publishing video to {endpoint}. Press 'q' to quit.")

        while True:
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()

            if not color_frame:
                print("Warning: failed to get color frame.")
                continue

            image = np.asanyarray(color_frame.get_data())

            cv2.putText(
                image,
                f"CAMERA {CAMERA_SN}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            jpeg_bytes = encode_jpeg(image)
            socket.send_multipart([f"video.{ROBOT_NAME}.{CAMERA_NAME}".encode("utf-8"), jpeg_bytes])

            cv2.imshow("Single RealSense Color", image)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

    except KeyboardInterrupt:
        print("Interrupted by user.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        if pipeline is not None:
            pipeline.stop()
        if socket is not None:
            socket.close(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
