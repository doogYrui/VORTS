# WebXR Demo

这个目录用于 Quest 3 WebXR 遥操作 Galaxy 机器人。

## 启动顺序

### 1. 在 Galaxy 机器人上启动基础环境

先运行：

```bash
bash webxr/robot/galaxy/sh/launch_webxr.sh
```

### 2. 在 Galaxy 机器人上让双臂复位

按下面顺序依次执行：

```bash
bash webxr/robot/galaxy/sh/left0.sh
bash webxr/robot/galaxy/sh/left1.sh
bash webxr/robot/galaxy/sh/right0.sh
bash webxr/robot/galaxy/sh/right1.sh
```

### 3. 在 Galaxy 机器人上启动视频和控制接收脚本

```bash
python3 webxr/robot/galaxy/rgb.py
python3 webxr/robot/galaxy/receiver.py
```

说明：

- `rgb.py`：读取机器人相机画面，编码后通过 ZMQ 发给 server
- `receiver.py`：接收 server 发来的 WebXR 控制数据，并发布到机器人 ROS 话题

### 4. 在 server 端启动 WebXR 服务

```bash
python3 webxr/server.py
```

启动后，Quest 3 或浏览器访问：

```text
https://114.214.211.251:1142/
```

## 当前目录说明

### 页面与服务

- [index.html](/home/rui/hw_task/mid_task/lite3_benchmark/VORTS/webxr/index.html)
  WebXR 页面入口，包含普通视频预览和 XR 入口。

- [app.js](/home/rui/hw_task/mid_task/lite3_benchmark/VORTS/webxr/app.js)
  前端主逻辑。
  负责：
  - Quest 3 手柄数据采集
  - WebSocket 接收机器人视频
  - XR 中悬浮视频面板渲染
  - 页面和 XR 中显示当前视频延迟

- [server.py](/home/rui/hw_task/mid_task/lite3_benchmark/VORTS/webxr/server.py)
  WebXR 服务端入口。
  负责：
  - HTTPS 静态页面服务，端口 `1142`
  - 接收 Quest 手柄数据
  - 通过 ZMQ 向机器人发送控制数据，端口 `6003`
  - 接收机器人 RGB 视频流，端口 `6004`
  - 通过 WebSocket 向前端推送视频和视频延迟信息

### 机器人侧

- [robot/galaxy/rgb.py](/home/rui/hw_task/mid_task/lite3_benchmark/VORTS/webxr/robot/galaxy/rgb.py)
  读取 RealSense 画面并通过 ZMQ 推送给 server。

- [robot/galaxy/receiver.py](/home/rui/hw_task/mid_task/lite3_benchmark/VORTS/webxr/robot/galaxy/receiver.py)
  接收手柄控制数据，并发布：
  - 左右臂目标位姿
  - 左右夹爪控制
  - 底盘速度控制

- `robot/galaxy/sh/`
  机器人启动和测试脚本目录，包括：
  - `launch_webxr.sh`
  - `left0.sh`
  - `left1.sh`
  - `right0.sh`
  - `right1.sh`

## 端口说明

- `1142`
  HTTPS 页面和 WebSocket 服务

- `6003`
  server -> robot 控制数据 ZMQ

- `6004`
  robot -> server 视频流 ZMQ

## 备注

- `webxr/localhost.pem` 和 `webxr/localhost-key.pem` 是本地开发证书，不应提交到仓库。
- 当前视频延迟显示的是“机器人采集到前端显示”的近似端到端延迟。
