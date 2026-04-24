# 启动说明

本文档按启动对象分为三类：

- 主前后端
- 星海图机器人
- WebXR

机器分工：

- 主前后端 / WebXR server：`192.168.31.46`
- 星海图机器人：`192.168.31.45`
- 监控上位机：`192.168.31.220`

每段命令前都会标明目标机器；命令块中的 `cd` 路径就是该脚本的执行目录。

## 1. 主前后端

在 `192.168.31.46` 上启动主后端：

```bash
cd ~/doogYrui/VORTS
python -m backend.app
```

在 `192.168.31.46` 上启动主前端：

```bash
cd ~/doogYrui/VORTS
python frontend/server.py
```

主网页访问地址：

```text
http://114.214.211.251:1140/
```

## 2. 星海图机器人

先在星海图机器人 `192.168.31.45` 上启动基础环境：

```bash
ssh nvidia@192.168.31.45
cd ~/ZHXY/sh
bash launch_all.sh
```

然后将左右机械臂复位，继续在星海图机器人 `192.168.31.45` 的项目根目录下依次执行：

```bash
cd ~/doogYrui/VORTS
bash webxr/robot/galaxy/sh/left0.sh
bash webxr/robot/galaxy/sh/left1.sh
bash webxr/robot/galaxy/sh/right0.sh
bash webxr/robot/galaxy/sh/right1.sh
```

然后继续在星海图机器人 `192.168.31.45` 的项目根目录分别启动下面两个脚本。

启动机器人在线桥接脚本：

```bash
cd ~/doogYrui/VORTS
python3 -m robot.galaxy.run_galaxy_online
```

启动机器人命令接收脚本：

```bash
cd ~/doogYrui/VORTS
python3 robot/galaxy/galaxy_command_receiver.py
```

说明：

- `robot/galaxy/galaxy_online_bridge.py` 负责机器人在线数据桥接，包括 RGB、点云、odom 等数据转发。
- `robot/galaxy/galaxy_command_receiver.py` 负责接收后端下发的控制命令。

## 3. WebXR

启动 WebXR 前，先在监控上位机 `192.168.31.220` 上启动监控相机发布器：

```bash
ssh sonic@192.168.31.220
cd ~/doogYrui/VORTS
export VORTS_BACKEND_HOST=192.168.31.46
python3 -m robot.monitor.monitor_camera_publisher
```

然后在 server `192.168.31.46` 上进入 `webxr/` 目录启动 WebXR 服务：

```bash
cd webxr
python3 server.py
```

再在星海图机器人 `192.168.31.45` 上启动 WebXR 控制接收脚本：

```bash
ssh nvidia@192.168.31.45
cd ~/doogYrui/VORTS
python3 webxr/robot/galaxy/receiver.py
```

Quest 3 访问地址：

```text
https://114.214.211.251:1142/
```

说明：

- WebXR 的 RGB 视频已经合并到 `robot/galaxy/galaxy_online_bridge.py`，不需要再启动 `webxr/robot/galaxy/rgb.py`。
- `webxr/robot/galaxy/receiver.py` 只负责接收 WebXR 控制数据并发布到机器人 ROS 话题。
