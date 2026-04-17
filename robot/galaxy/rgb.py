import sys
import cv2
import numpy as np
import pyrealsense2 as rs


RIGHT_SN = "346522071650"
LEFT_SN = "333422301212"

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
    right_pipeline = None
    left_pipeline = None

    try:
        print(f"Starting right camera: {RIGHT_SN}")
        right_pipeline = create_pipeline(RIGHT_SN)

        print(f"Starting left camera: {LEFT_SN}")
        left_pipeline = create_pipeline(LEFT_SN)

        print("Cameras started. Press 'q' to quit.")

        while True:
            right_frames = right_pipeline.wait_for_frames()
            left_frames = left_pipeline.wait_for_frames()

            right_color_frame = right_frames.get_color_frame()
            left_color_frame = left_frames.get_color_frame()

            if not right_color_frame or not left_color_frame:
                print("Warning: failed to get one of the color frames.")
                continue

            right_img = np.asanyarray(right_color_frame.get_data())
            left_img = np.asanyarray(left_color_frame.get_data())

            combined = np.hstack((left_img, right_img))

            cv2.putText(
                combined,
                f"LEFT  {LEFT_SN}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                combined,
                f"RIGHT {RIGHT_SN}",
                (WIDTH + 20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow("Dual RealSense Color", combined)

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
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()