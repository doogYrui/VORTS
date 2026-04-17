# VORTS Robot Demo

一个可直接运行的机器人前后端 demo，覆盖以下链路：

- FastAPI 后端，端口 `1141`
- 原生 HTML/CSS/JS 前端，端口 `1140`
- mock 机器人通过 ZMQ 向后端推送视频、点云、odom
- 前端通过 HTTP + WebSocket 与后端交互
- 首页、遥操页、监控与协作任务页全部打通

## 目录结构

```text
VORTS/
  backend/
    app.py
    config.py
    logging_config.py
    models.py
    network_stats.py
    robot_registry.py
    scene_graph.py
    task_state.py
    ws_manager.py
    zmq_bridge.py
    logs/
      backend.log
  mock_robots/
    mock_robot_base.py
    mock_galaxy.py
    mock_ysc.py
    mock_piper.py
    run_mock_robots.py
    logs/
      mock_robots.log
  frontend/
    index.html
    styles.css
    app.js
    server.py
    components/
      api.js
      home.js
      monitor.js
      teleop.js
      ws.js
  requirements.txt
  README.md
```

## 运行环境

- Ubuntu 24
- Python 3.11+
- 浏览器支持 ES Module

## 安装依赖

```bash
cd /path/to/VORTS
conda create -n VORTS python=3.11
conda activate VORTS
pip install -r requirements.txt
```

## 启动方式

建议分三个终端启动。

### 1. 启动后端

```bash
conda activate VORTS
python -m backend.app
```

默认绑定 `0.0.0.0:1141`。

如果自动识别的公网 IPv6 网卡不对，可以手动指定：

```bash
conda activate VORTS
PUBLIC_INTERFACE=eth0 python -m backend.app
```

### 2. 启动 mock 机器人

```bash
conda activate VORTS
python -m mock_robots.run_mock_robots
```

mock 机器人默认连接：

- `tcp://127.0.0.1:6001` 发送视频 / 点云 / odom
- `tcp://127.0.0.1:6002` 接收 teleop / 任务广播

如果你修改了后端 ZMQ 绑定地址，可以同时设置：

```bash
source .venv/bin/activate
MOCK_SENSOR_ENDPOINT=tcp://127.0.0.1:6001 \
MOCK_COMMAND_ENDPOINT=tcp://127.0.0.1:6002 \
python -m mock_robots.run_mock_robots
```

### 3. 启动前端

```bash
python frontend/server.py
```

默认绑定 `0.0.0.0:1140`。

## 访问地址

- 前端首页：`http://127.0.0.1:1140`
- 后端接口：`http://127.0.0.1:1141`
- 后端 Swagger：`http://127.0.0.1:1141/docs`

如果通过公网 IPv6 访问，请使用：

- 前端：`http://[你的公网IPv6]:1140`
- 后端：`http://[你的公网IPv6]:1141`

前端会自动根据浏览器当前访问的 host，拼接到 `1141` 端口访问后端。

## 已实现功能

- 首页：
  - 指定网卡上下行速率展示
  - 最近 60 秒流量历史曲线
  - RTT WebSocket 心跳测量
- 机器人遥操页：
  - 仅 `galaxy` 和 `ysc` 可选
  - `w/s/a/d/q/e` 按键状态持续 30Hz 发送
  - 组合键支持
  - 根据当前机器人自动切换视频源
  - 视频全屏、占位提示、断开提示
- 监控与协作任务页：
  - `benchmark2 / benchmark3 / corobot` 任务派发
  - 全局 `busy` 冲突检查
  - 清空任务接口与按钮
  - RGB 双监控位
  - Three.js 点云查看，支持旋转 / 缩放 / 平移 / 重置
  - 两路固定全局监控画面
  - scene graph 二维渲染
- 后端：
  - 完整 HTTP API
  - 分功能 WebSocket 端点
  - CORS 已开启
  - Python logging 控制台 + 文件日志
- mock 机器人：
  - `galaxy` / `ysc` / `piper`
  - JPEG 视频 15fps
  - 点云 10Hz
  - odom 10Hz
  - teleop / 任务广播接收日志

## 已简化功能

- 不接真实机器人，全部使用 mock 数据
- 不做登录、权限、数据库持久化
- 不做机器人在线离线检测
- 任务状态为后端全局单例，仅做 busy 拒绝
- 任务默认不会自动完成，使用 `POST /api/task/clear` 或页面按钮清空
- 视频采用 WebSocket 二进制 JPEG 帧，不做复杂流媒体方案
- 点云直接传原始数组，不做额外滤波、建图和压缩
- scene graph 由后端根据 mock odom 和静态物体直接生成

## 主要接口

### HTTP

- `GET /api/system/status`
- `GET /api/robots`
- `GET /api/robots/teleop`
- `GET /api/robots/capabilities`
- `GET /api/network/stats`
- `GET /api/network/history`
- `GET /api/task/status`
- `POST /api/task/send`
- `POST /api/task/clear`
- `GET /api/video/sources`
- `GET /api/pointcloud/sources`
- `GET /api/odom/sources`

### WebSocket

- `/ws/rtt`
- `/ws/teleop`
- `/ws/video/{robot_name}/{camera_name}`
- `/ws/pointcloud/{robot_name}`
- `/ws/odom/{robot_name}`
- `/ws/scene_graph`

## 日志位置

- 后端日志：`backend/logs/backend.log`
- mock 机器人日志：`mock_robots/logs/mock_robots.log`

## 联调建议

1. 先启动后端
2. 再启动 mock 机器人
3. 最后启动前端并打开首页
4. 进入遥操页验证 `galaxy` / `ysc` 视频和按键发送
5. 进入监控页验证点云、scene graph 和任务 busy 冲突
