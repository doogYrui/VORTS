import json
import time
import rospy
from sensor_msgs.msg import PointCloud2
import sensor_msgs.point_cloud2 as pc2


ROBOT_NAME = "ysc"
TOPIC_NAME = "/livox/lidar"
MAX_POINTS = 20000


def downsample_points(points, max_points):
    n = len(points)
    if n <= max_points:
        return points

    step = n / float(max_points)
    sampled = []
    idx = 0.0
    for _ in range(max_points):
        sampled.append(points[int(idx)])
        idx += step
    return sampled


class PointCloudToJsonNode:
    def __init__(self):
        self.sub = rospy.Subscriber(
            TOPIC_NAME,
            PointCloud2,
            self.callback,
            queue_size=1,
            buff_size=2**24,
        )
        self.last_print_time = 0.0

    def callback(self, msg: PointCloud2):
        points_iter = pc2.read_points(
            msg,
            field_names=("x", "y", "z"),
            skip_nans=True,
        )

        points = [[float(x), float(y), float(z)] for x, y, z in points_iter]
        raw_count = len(points)

        sampled_points = downsample_points(points, MAX_POINTS)
        sampled_count = len(sampled_points)

        payload = {
            "robot": ROBOT_NAME,
            "timestamp": msg.header.stamp.to_sec() if msg.header.stamp else time.time(),
            "points": sampled_points,
        }

        # 这里只做本地处理，不发网络
        # 你如果后面要接 websocket / udp / tcp，直接发 payload 即可
        payload_json = json.dumps(payload, ensure_ascii=False)

        now = time.time()
        if now - self.last_print_time > 0.08:  # 控制打印频率，避免刷屏太猛
            rospy.loginfo(
                "pointcloud debug | raw=%d sampled=%d timestamp=%.3f json_size=%.2f MB",
                raw_count,
                sampled_count,
                payload["timestamp"],
                len(payload_json.encode("utf-8")) / (1024 * 1024),
            )
            self.last_print_time = now


def main():
    rospy.init_node("livox_to_json_debug", anonymous=True)
    rospy.loginfo("Subscribing to %s", TOPIC_NAME)
    PointCloudToJsonNode()
    rospy.spin()


if __name__ == "__main__":
    main()