import sys
import cv2
import numpy as np
import pyrealsense2 as rs


RIGHT_SN = "346522071650"
LEFT_SN = "333422301212"
MAIN_SN = "347622072588"

WIDTH = 640
HEIGHT = 480
FPS = 15
WAIT_TIMEOUT_MS = 120


def camera_online(serial_number: str) -> bool:
    try:
        context = rs.context()
        for device in context.query_devices():
            if device.get_info(rs.camera_info.serial_number) == serial_number:
                return True
    except Exception:
        return False
    return False


def create_pipeline(serial_number: str):
    if not camera_online(serial_number):
        print(f"Camera offline, using placeholder: {serial_number}")
        return None

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(serial_number)
    config.enable_stream(rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS)
    pipeline.start(config)
    return pipeline


def build_placeholder(label: str, serial_number: str):
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    frame[:, :] = (38, 44, 50)
    cv2.rectangle(frame, (24, 24), (WIDTH - 24, HEIGHT - 24), (90, 110, 124), 2)
    cv2.putText(frame, label, (48, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (220, 230, 235), 2, cv2.LINE_AA)
    cv2.putText(frame, "camera offline", (48, 148), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (170, 188, 198), 2, cv2.LINE_AA)
    cv2.putText(frame, f"serial: {serial_number}", (48, 198), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (145, 165, 176), 2, cv2.LINE_AA)
    return frame


def read_frame(pipeline, placeholder):
    if pipeline is None:
        return placeholder

    try:
        frames = pipeline.wait_for_frames(WAIT_TIMEOUT_MS)
        color_frame = frames.get_color_frame()
    except Exception:
        return placeholder

    if not color_frame:
        return placeholder
    return np.asanyarray(color_frame.get_data())


def label_frame(frame, label: str, serial_number: str):
    cv2.putText(
        frame,
        f"{label} {serial_number}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return frame


def main():
    right_pipeline = None
    left_pipeline = None
    main_pipeline = None

    placeholders = {
        "LEFT": build_placeholder("LEFT", LEFT_SN),
        "MAIN": build_placeholder("MAIN", MAIN_SN),
        "RIGHT": build_placeholder("RIGHT", RIGHT_SN),
    }

    try:
        print(f"Starting right camera: {RIGHT_SN}")
        right_pipeline = create_pipeline(RIGHT_SN)

        print(f"Starting left camera: {LEFT_SN}")
        left_pipeline = create_pipeline(LEFT_SN)

        print(f"Starting main camera: {MAIN_SN}")
        main_pipeline = create_pipeline(MAIN_SN)

        print("Cameras started. Press 'q' to quit.")

        while True:
            left_img = read_frame(left_pipeline, placeholders["LEFT"].copy())
            main_img = read_frame(main_pipeline, placeholders["MAIN"].copy())
            right_img = read_frame(right_pipeline, placeholders["RIGHT"].copy())

            combined = np.hstack(
                (
                    label_frame(left_img, "LEFT", LEFT_SN),
                    label_frame(main_img, "MAIN", MAIN_SN),
                    label_frame(right_img, "RIGHT", RIGHT_SN),
                )
            )

            cv2.imshow("Triple RealSense Color", combined)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

    except KeyboardInterrupt:
        print("Interrupted by user.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        if right_pipeline is not None:
            right_pipeline.stop()
        if left_pipeline is not None:
            left_pipeline.stop()
        if main_pipeline is not None:
            main_pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
