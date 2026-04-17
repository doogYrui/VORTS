import json
import time
import rospy
from nav_msgs.msg import Odometry


ROBOT_NAME = "ysc"
TOPIC_NAME = "/local_odom"
OUTPUT_HZ = 10.0


class OdomToJsonNode:
    def __init__(self):
        self.sub = rospy.Subscriber(
            TOPIC_NAME,
            Odometry,
            self.callback,
            queue_size=1,
        )
        self.min_interval = 1.0 / OUTPUT_HZ
        self.last_output_time = 0.0

    def callback(self, msg: Odometry):
        now = time.time()
        if now - self.last_output_time < self.min_interval:
            return
        self.last_output_time = now

        p = msg.pose.pose.position
        q = msg.pose.pose.orientation

        payload = {
            "robot": ROBOT_NAME,
            "timestamp": msg.header.stamp.to_sec() if msg.header.stamp else time.time(),
            "pose": [
                float(p.x),
                float(p.y),
                float(p.z),
                float(q.x),
                float(q.y),
                float(q.z),
                float(q.w),
            ],
        }

        payload_json = json.dumps(payload, ensure_ascii=False)

        rospy.loginfo(
            "odom debug | timestamp=%.3f pose=[%.4f, %.4f, %.4f, %.4f, %.4f, %.4f, %.4f] json=%s",
            payload["timestamp"],
            payload["pose"][0],
            payload["pose"][1],
            payload["pose"][2],
            payload["pose"][3],
            payload["pose"][4],
            payload["pose"][5],
            payload["pose"][6],
            payload_json,
        )


def main():
    rospy.init_node("odom_to_json_debug", anonymous=True)
    rospy.loginfo("Subscribing to %s", TOPIC_NAME)
    OdomToJsonNode()
    rospy.spin()


if __name__ == "__main__":
    main()