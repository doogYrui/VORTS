# Monitor Camera Publisher

Runs on the monitor camera host and publishes RealSense color frames to the VORTS backend.

Default flow:

```text
RealSense 247122070621 -> JPEG -> ZMQ topic video.monitor.main -> tcp://192.168.31.46:6001
```

Start on the monitor host:

```bash
export VORTS_BACKEND_HOST=192.168.31.46
export MONITOR_CAMERA_SN=247122070621
python -m robot.monitor.monitor_camera_publisher
```

Optional settings:

```bash
export MONITOR_ROBOT_NAME=monitor
export MONITOR_CAMERA_NAME=main
export VORTS_SENSOR_PORT=6001
export MONITOR_VIDEO_WIDTH=640
export MONITOR_VIDEO_HEIGHT=480
export MONITOR_VIDEO_FPS=15
export MONITOR_JPEG_QUALITY=85
```
