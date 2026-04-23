import sys
import cv2
import numpy as np
import pyrealsense2 as rs


CAMERA_SN = "347622072588"

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


def main():
    pipeline = None

    try:
        print(f"Starting camera: {CAMERA_SN}")
        pipeline = create_pipeline(CAMERA_SN)

        print("Camera started. Press 'q' to quit.")

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
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
