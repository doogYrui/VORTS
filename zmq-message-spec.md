# VORTS ZMQ 消息文档

本文档描述当前系统中所有 ZMQ 消息，包括：

- 端口方向
- socket 角色
- topic 名称
- 消息体编码
- 各机器人在 `6001` 和 `6002` 上收发哪些消息

说明：

- 本文档按部署假设机器人 IP：
  - `galaxy`: `192.168.31.1`
  - `ysc`: `192.168.31.2`
  - `piper`: `192.168.31.3`
- 当前后端默认绑定：
  - `tcp://0.0.0.0:6001`
  - `tcp://0.0.0.0:6002`

## 1. 通信拓扑

### 1.1 端口 `6001`

用途：

- 机器人 -> 后端
- 发送传感器与状态数据

socket 角色：

- 机器人端：`PUB`
- 后端端：`SUB`

方向：

```text
robot PUB  --->  backend SUB
```

承载数据：

- RGB 视频
- 点云
- odom

---

### 1.2 端口 `6002`

用途：

- 后端 -> 机器人
- 发送控制与任务

socket 角色：

- 后端端：`PUB`
- 机器人端：`SUB`

方向：

```text
backend PUB  --->  robot SUB
```

承载数据：

- teleop 遥操命令
- 任务广播

## 2. ZMQ 消息封装格式

当前系统所有 ZMQ 消息统一采用 `multipart` 两帧格式：

```text
Frame 0: topic
Frame 1: payload
```

具体要求：

- `Frame 0`
  - 类型：UTF-8 字符串
  - 内容：topic 名
- `Frame 1`
  - 视频：二进制 JPEG 字节
  - 点云：UTF-8 编码的 JSON
  - odom：UTF-8 编码的 JSON
  - teleop：UTF-8 编码的 JSON
  - 任务：UTF-8 编码的 JSON

说明：

- 当前没有额外 header
- 没有 protobuf
- 没有 msgpack
- 没有压缩封装

## 3. 6001 端口消息清单

## 3.1 `galaxy` -> backend

机器人 IP：

- `192.168.31.1`

topic 列表：

- `video.galaxy.main`
- `video.galaxy.left_arm`
- `video.galaxy.right_arm`
- `pointcloud.galaxy`
- `odom.galaxy`

### 3.1.1 `video.galaxy.main`

- 方向：`192.168.31.1 -> backend:6001`
- payload 类型：二进制 JPEG

图像要求：

- 分辨率：`640x480`
- 帧率：约 `15fps`
- 编码：`JPEG`

multipart 示例：

```text
Frame 0: "video.galaxy.main"
Frame 1: <jpeg bytes>
```

### 3.1.2 `video.galaxy.left_arm`

- 方向：`192.168.31.1 -> backend:6001`
- payload 类型：二进制 JPEG

```text
Frame 0: "video.galaxy.left_arm"
Frame 1: <jpeg bytes>
```

### 3.1.3 `video.galaxy.right_arm`

- 方向：`192.168.31.1 -> backend:6001`
- payload 类型：二进制 JPEG

```text
Frame 0: "video.galaxy.right_arm"
Frame 1: <jpeg bytes>
```

### 3.1.4 `pointcloud.galaxy`

- 方向：`192.168.31.1 -> backend:6001`
- payload 类型：UTF-8 JSON
- 频率：约 `10Hz`

JSON 格式：

```json
{
  "robot": "galaxy",
  "timestamp": 1710000000.123,
  "points": [
    [1.0, 2.0, 0.5],
    [1.1, 2.1, 0.6]
  ]
}
```

字段说明：

- `robot`: 固定为 `galaxy`
- `timestamp`: 秒级浮点时间戳
- `points`: 二维数组，单点为 `[x, y, z]`

multipart 示例：

```text
Frame 0: "pointcloud.galaxy"
Frame 1: "{\"robot\":\"galaxy\",\"timestamp\":1710000000.123,\"points\":[[1.0,2.0,0.5]]}"
```

### 3.1.5 `odom.galaxy`

- 方向：`192.168.31.1 -> backend:6001`
- payload 类型：UTF-8 JSON
- 频率：约 `10Hz`

JSON 格式：

```json
{
  "robot": "galaxy",
  "timestamp": 1710000000.123,
  "pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
}
```

字段说明：

- `pose` 固定为：

```json
[x, y, z, qx, qy, qz, qw]
```

---

## 3.2 `ysc` -> backend

机器人 IP：

- `192.168.31.2`

topic 列表：

- `video.ysc.main`
- `pointcloud.ysc`
- `odom.ysc`

### 3.2.1 `video.ysc.main`

- 方向：`192.168.31.2 -> backend:6001`
- payload 类型：二进制 JPEG
- 分辨率：`640x480`
- 帧率：约 `15fps`

```text
Frame 0: "video.ysc.main"
Frame 1: <jpeg bytes>
```

### 3.2.2 `pointcloud.ysc`

- 方向：`192.168.31.2 -> backend:6001`
- payload 类型：UTF-8 JSON
- 频率：约 `10Hz`

JSON 格式：

```json
{
  "robot": "ysc",
  "timestamp": 1710000000.123,
  "points": [
    [1.0, 2.0, 0.5],
    [1.1, 2.1, 0.6]
  ]
}
```

### 3.2.3 `odom.ysc`

- 方向：`192.168.31.2 -> backend:6001`
- payload 类型：UTF-8 JSON
- 频率：约 `10Hz`

JSON 格式：

```json
{
  "robot": "ysc",
  "timestamp": 1710000000.123,
  "pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
}
```

---

## 3.3 `piper` -> backend

机器人 IP：

- `192.168.31.3`

topic 列表：

- `video.piper.arm_full`
- `video.piper.side`

### 3.3.1 `video.piper.arm_full`

- 方向：`192.168.31.3 -> backend:6001`
- payload 类型：二进制 JPEG

```text
Frame 0: "video.piper.arm_full"
Frame 1: <jpeg bytes>
```

### 3.3.2 `video.piper.side`

- 方向：`192.168.31.3 -> backend:6001`
- payload 类型：二进制 JPEG

```text
Frame 0: "video.piper.side"
Frame 1: <jpeg bytes>
```

说明：

- `piper` 当前不发送点云
- `piper` 当前不发送 odom

## 4. 6002 端口消息清单

## 4.1 backend -> `galaxy`

目标机器人 IP：

- `192.168.31.1`

订阅 topic：

- `teleop.galaxy`
- `task.broadcast`

### 4.1.1 `teleop.galaxy`

- 方向：`backend:6002 -> 192.168.31.1`
- payload 类型：UTF-8 JSON
- 用途：遥操控制

JSON 格式：

```json
{
  "robot": "galaxy",
  "keys": ["w", "a"],
  "ts": 1710000000.123
}
```

停止示例：

```json
{
  "robot": "galaxy",
  "keys": [],
  "ts": 1710000000.456
}
```

字段说明：

- `robot`: 固定为 `galaxy`
- `keys`: 当前按键列表
- `ts`: 前端产生的时间戳，秒，浮点数

允许按键：

```json
["w", "s", "a", "d", "q", "e"]
```

### 4.1.2 `task.broadcast`

- 方向：`backend:6002 -> 192.168.31.1`
- payload 类型：UTF-8 JSON
- 用途：任务广播

JSON 格式：

```json
{
  "task_type": "benchmark2",
  "task_content": "让 galaxy 和 ysc 去 A 点"
}
```

字段说明：

- `task_type`: `benchmark2` / `benchmark3` / `corobot`
- `task_content`: 任务描述文本

---

## 4.2 backend -> `ysc`

目标机器人 IP：

- `192.168.31.2`

订阅 topic：

- `teleop.ysc`
- `task.broadcast`

### 4.2.1 `teleop.ysc`

- 方向：`backend:6002 -> 192.168.31.2`
- payload 类型：UTF-8 JSON

JSON 格式：

```json
{
  "robot": "ysc",
  "keys": ["w", "d"],
  "ts": 1710000000.123
}
```

### 4.2.2 `task.broadcast`

- 方向：`backend:6002 -> 192.168.31.2`
- payload 类型：UTF-8 JSON

JSON 格式：

```json
{
  "task_type": "corobot",
  "task_content": "让 ysc 与 galaxy 协同作业"
}
```

---

## 4.3 backend -> `piper`

目标机器人 IP：

- `192.168.31.3`

订阅 topic：

- `task.broadcast`

### 4.3.1 `task.broadcast`

- 方向：`backend:6002 -> 192.168.31.3`
- payload 类型：UTF-8 JSON

JSON 格式：

```json
{
  "task_type": "benchmark3",
  "task_content": "让 piper 配合执行固定工位动作"
}
```

说明：

- `piper` 当前不支持 teleop
- 因此不会订阅 `teleop.piper`

## 5. 按端口汇总 topic 名称

### 5.1 走 `6001` 的 topic

| topic | 来源机器人 | IP | payload |
|---|---|---|---|
| `video.galaxy.main` | `galaxy` | `192.168.31.1` | JPEG 二进制 |
| `video.galaxy.left_arm` | `galaxy` | `192.168.31.1` | JPEG 二进制 |
| `video.galaxy.right_arm` | `galaxy` | `192.168.31.1` | JPEG 二进制 |
| `pointcloud.galaxy` | `galaxy` | `192.168.31.1` | JSON |
| `odom.galaxy` | `galaxy` | `192.168.31.1` | JSON |
| `video.ysc.main` | `ysc` | `192.168.31.2` | JPEG 二进制 |
| `pointcloud.ysc` | `ysc` | `192.168.31.2` | JSON |
| `odom.ysc` | `ysc` | `192.168.31.2` | JSON |
| `video.piper.arm_full` | `piper` | `192.168.31.3` | JPEG 二进制 |
| `video.piper.side` | `piper` | `192.168.31.3` | JPEG 二进制 |

### 5.2 走 `6002` 的 topic

| topic | 目标机器人 | IP | payload |
|---|---|---|---|
| `teleop.galaxy` | `galaxy` | `192.168.31.1` | JSON |
| `teleop.ysc` | `ysc` | `192.168.31.2` | JSON |
| `task.broadcast` | `galaxy` / `ysc` / `piper` | `192.168.31.1/2/3` | JSON |

## 6. 推荐的部署理解方式

若后端部署在 server 上，机器人部署在各自内网 IP，上述端口的理解建议为：

- 机器人向 `server_ip:6001` 发送自身数据
- 机器人订阅 `server_ip:6002` 接收控制与任务

可以理解为：

```text
192.168.31.1 (galaxy) --PUB--> server:6001
192.168.31.2 (ysc)    --PUB--> server:6001
192.168.31.3 (piper)  --PUB--> server:6001

server:6002 --PUB--> 192.168.31.1 (galaxy SUB)
server:6002 --PUB--> 192.168.31.2 (ysc SUB)
server:6002 --PUB--> 192.168.31.3 (piper SUB)
```

## 7. 当前实现边界

- `scene graph` 不走 ZMQ，由后端本地根据 odom 生成
- `RTT` 不走 ZMQ，只走 WebSocket `/ws/rtt`
- 任务当前为全局单例状态，不区分单机器人执行状态
- 视频、点云、odom 当前未做额外压缩或协议封装
