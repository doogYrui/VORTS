# VORTS 后端接口文档

本文档基于当前仓库实现整理，覆盖：

- HTTP `GET` 接口
- HTTP `POST` 接口
- WebSocket 接口
- 机器人清单、视频源、点云源、odom 源

说明：

- 后端默认监听：`http://0.0.0.0:1141`
- 前端默认监听：`http://0.0.0.0:1140`
- 文档中的机器人 IP 按需求假设为：
  - `galaxy`: `192.168.31.1`
  - `ysc`: `192.168.31.2`
  - `piper`: `192.168.31.3`
- 当前代码里的 `scene graph` 由后端本地生成，不经过 ZMQ。

## 1. 机器人与能力概览

### 1.1 机器人列表

| 机器人 | 类型 | IP | 可遥操 | 摄像头 | 激光雷达 | odom |
|---|---|---|---|---|---|---|
| `galaxy` | `mobile_dual_arm` | `192.168.31.1` | 是 | `main`, `left_arm`, `right_arm` | 是 | 是 |
| `ysc` | `quadruped` | `192.168.31.2` | 是 | `main` | 是 | 是 |
| `piper` | `fixed_arm` | `192.168.31.3` | 否 | `arm_full`, `side` | 否 | 否 |

### 1.2 遥操按键

仅以下两个机器人支持遥操：

- `galaxy`
- `ysc`

固定按键集合：

```json
["w", "s", "a", "d", "q", "e"]
```

## 2. HTTP 接口

### 2.1 总表

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/system/status` | 获取系统总状态 |
| `GET` | `/api/robots` | 获取机器人基础信息列表 |
| `GET` | `/api/robots/teleop` | 获取可遥操机器人列表 |
| `GET` | `/api/robots/capabilities` | 获取机器人能力清单 |
| `GET` | `/api/network/stats` | 获取当前网卡流量 |
| `GET` | `/api/network/history` | 获取最近一段时间的网卡流量历史 |
| `GET` | `/api/task/status` | 获取当前全局任务状态 |
| `POST` | `/api/task/send` | 发送任务 |
| `POST` | `/api/task/clear` | 清空当前任务 |
| `GET` | `/api/video/sources` | 获取可用视频源 |
| `GET` | `/api/pointcloud/sources` | 获取可用点云源 |
| `GET` | `/api/odom/sources` | 获取可用 odom 源 |

---

### 2.2 `GET /api/system/status`

用途：

- 获取系统整体状态
- 包括服务时间、网卡状态、任务状态、机器人数量

返回字段：

```json
{
  "server_time": 1776351166.026065,
  "interface": "enp131s0",
  "network": {
    "interface": "enp131s0",
    "timestamp": 1776351165.5914364,
    "upload_kbps": 0.72,
    "download_kbps": 25.62
  },
  "task": {
    "busy": false,
    "current_task": null
  },
  "robot_count": 3
}
```

字段说明：

- `server_time`: 后端当前时间戳，秒，浮点数
- `interface`: 当前监控的公网网卡名
- `network.upload_kbps`: 当前上行速率，单位 `KB/s`
- `network.download_kbps`: 当前下行速率，单位 `KB/s`
- `task.busy`: 当前是否存在全局任务
- `task.current_task`: 当前任务对象或 `null`
- `robot_count`: 当前机器人数量

---

### 2.3 `GET /api/robots`

用途：

- 获取机器人基础信息

返回示例：

```json
[
  {
    "name": "galaxy",
    "type": "mobile_dual_arm",
    "ip": "192.168.31.1",
    "teleop_enabled": true,
    "camera_count": 3,
    "camera_names": ["main", "left_arm", "right_arm"],
    "has_lidar": true,
    "has_odom": true
  }
]
```

字段说明：

- `teleop_enabled`: 是否允许遥操
- `camera_count`: 摄像头数量
- `camera_names`: 摄像头名字列表
- `has_lidar`: 是否具备点云来源
- `has_odom`: 是否具备 odom 来源

---

### 2.4 `GET /api/robots/teleop`

用途：

- 获取所有可遥操机器人

当前返回内容：

- `galaxy`
- `ysc`

返回结构与 `/api/robots` 相同，只是过滤了不可遥操机器人。

---

### 2.5 `GET /api/robots/capabilities`

用途：

- 获取机器人能力清单

返回示例：

```json
[
  {
    "name": "galaxy",
    "type": "mobile_dual_arm",
    "ip": "192.168.31.1",
    "teleop": true,
    "teleop_keys": ["w", "s", "a", "d", "q", "e"],
    "cameras": ["main", "left_arm", "right_arm"],
    "lidar": true,
    "odom": true
  },
  {
    "name": "ysc",
    "type": "quadruped",
    "ip": "192.168.31.2",
    "teleop": true,
    "teleop_keys": ["w", "s", "a", "d", "q", "e"],
    "cameras": ["main"],
    "lidar": true,
    "odom": true
  },
  {
    "name": "piper",
    "type": "fixed_arm",
    "ip": "192.168.31.3",
    "teleop": false,
    "teleop_keys": [],
    "cameras": ["arm_full", "side"],
    "lidar": false,
    "odom": false
  }
]
```

---

### 2.6 `GET /api/network/stats`

用途：

- 获取当前网卡瞬时上下行流量

返回示例：

```json
{
  "interface": "eth0",
  "timestamp": 1710000000.123,
  "upload_kbps": 12.34,
  "download_kbps": 56.78
}
```

---

### 2.7 `GET /api/network/history`

用途：

- 获取最近一段时间的流量历史
- 当前默认历史长度约 `60` 秒

返回示例：

```json
{
  "interface": "eth0",
  "samples": [
    {
      "timestamp": 1710000000.123,
      "upload_kbps": 12.34,
      "download_kbps": 56.78
    },
    {
      "timestamp": 1710000001.123,
      "upload_kbps": 10.12,
      "download_kbps": 52.11
    }
  ]
}
```

---

### 2.8 `GET /api/task/status`

用途：

- 获取当前全局任务状态

返回示例 1：空闲

```json
{
  "busy": false,
  "current_task": null
}
```

返回示例 2：执行中

```json
{
  "busy": true,
  "current_task": {
    "task_type": "benchmark2",
    "task_content": "让 galaxy 和 ysc 去 A 点"
  }
}
```

规则：

- `busy = false` 表示无任务
- `busy = true` 表示已有全局任务执行中
- `current_task != null` 与 `busy = true` 对应

---

### 2.9 `POST /api/task/send`

用途：

- 提交一个全局任务

请求体：

```json
{
  "task_type": "benchmark2",
  "task_content": "让 galaxy 和 ysc 去 A 点"
}
```

字段说明：

- `task_type`: 仅支持：
  - `benchmark2`
  - `benchmark3`
  - `corobot`
- `task_content`: 任务描述文本

成功返回：

```json
{
  "ok": true,
  "busy": true,
  "current_task": {
    "task_type": "benchmark2",
    "task_content": "让 galaxy 和 ysc 去 A 点"
  },
  "message": null
}
```

冲突返回：

```json
{
  "ok": false,
  "busy": true,
  "current_task": {
    "task_type": "benchmark2",
    "task_content": "已有任务"
  },
  "message": "已有任务执行中"
}
```

规则：

- 后端维护单一全局任务
- 若当前 `busy = true`，则拒绝新任务

---

### 2.10 `POST /api/task/clear`

用途：

- 清空当前全局任务
- 主要用于 demo 测试

请求体：

- 当前实现不依赖请求体内容，可发送空 JSON `{}` 或空 body

返回示例：

```json
{
  "busy": false,
  "current_task": null
}
```

---

### 2.11 `GET /api/video/sources`

用途：

- 获取所有可选 RGB 视频源

返回示例：

```json
[
  { "robot": "galaxy", "source": "main", "label": "galaxy / main" },
  { "robot": "galaxy", "source": "left_arm", "label": "galaxy / left_arm" },
  { "robot": "galaxy", "source": "right_arm", "label": "galaxy / right_arm" },
  { "robot": "ysc", "source": "main", "label": "ysc / main" },
  { "robot": "piper", "source": "arm_full", "label": "piper / arm_full" },
  { "robot": "piper", "source": "side", "label": "piper / side" }
]
```

---

### 2.12 `GET /api/pointcloud/sources`

用途：

- 获取所有可选点云源

返回示例：

```json
[
  { "robot": "galaxy", "source": "galaxy", "label": "galaxy / lidar" },
  { "robot": "ysc", "source": "ysc", "label": "ysc / lidar" }
]
```

---

### 2.13 `GET /api/odom/sources`

用途：

- 获取所有可选 odom 源

返回示例：

```json
[
  { "robot": "galaxy", "source": "galaxy", "label": "galaxy / odom" },
  { "robot": "ysc", "source": "ysc", "label": "ysc / odom" }
]
```

## 3. WebSocket 接口

### 3.1 总表

| 路径 | 方向 | 数据类型 | 说明 |
|---|---|---|---|
| `/ws/rtt` | 双向 | JSON | RTT 心跳 |
| `/ws/teleop` | 前端 -> 后端 | JSON | 遥操指令 |
| `/ws/video/{robot_name}/{camera_name}` | 后端 -> 前端 | 二进制 JPEG | 视频流 |
| `/ws/pointcloud/{robot_name}` | 后端 -> 前端 | JSON 文本 | 点云流 |
| `/ws/odom/{robot_name}` | 后端 -> 前端 | JSON 文本 | odom 流 |
| `/ws/scene_graph` | 后端 -> 前端 | JSON 文本 | scene graph 实时推送 |

说明：

- 视频流是 `binary frame`
- 点云、odom、scene graph 是 `text frame`，内容为 JSON 字符串
- 当前 `/ws/teleop` 只接收消息，不回 ACK

---

### 3.2 `/ws/rtt`

用途：

- 浏览器与后端之间做 RTT 心跳测量

前端发送：

```json
{
  "type": "ping",
  "client_ts": 1710000000123
}
```

后端返回：

```json
{
  "type": "pong",
  "client_ts": 1710000000123,
  "server_ts": 1710000000.456
}
```

字段说明：

- `client_ts`: 前端本地时间，当前实现通常用毫秒整数
- `server_ts`: 后端当前秒级浮点时间戳

---

### 3.3 `/ws/teleop`

用途：

- 前端持续发送当前按键状态
- 后端收到后转发到 ZMQ `6002`

消息格式：

```json
{
  "robot": "galaxy",
  "keys": ["w", "a"],
  "ts": 1710000000.123
}
```

松开全部按键：

```json
{
  "robot": "galaxy",
  "keys": [],
  "ts": 1710000000.456
}
```

字段说明：

- `robot`: 目标机器人，只允许 `galaxy` 或 `ysc`
- `keys`: 当前按下的按键列表，允许组合键
- `ts`: 前端发送时间戳，秒，浮点数

---

### 3.4 `/ws/video/{robot_name}/{camera_name}`

用途：

- 订阅某一路 RGB 视频

路径参数：

- `robot_name`: `galaxy` / `ysc` / `piper`
- `camera_name`:
  - `galaxy`: `main`, `left_arm`, `right_arm`
  - `ysc`: `main`
  - `piper`: `arm_full`, `side`

消息格式：

- 二进制 WebSocket frame
- 内容为单帧 JPEG 原始字节

图像约束：

- 编码：`JPEG`
- 分辨率：`640x480`
- 帧率：约 `15fps`

---

### 3.5 `/ws/pointcloud/{robot_name}`

用途：

- 订阅某个机器人的点云流

路径参数：

- `robot_name`: `galaxy` / `ysc`

消息格式：

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

- `points` 为二维数组
- 单点格式为 `[x, y, z]`
- 当前 demo 点数通常：
  - `galaxy`: 约 `10000`
  - `ysc`: 约 `8000`
- 频率：约 `10Hz`

---

### 3.6 `/ws/odom/{robot_name}`

用途：

- 订阅某个机器人的 odom

路径参数：

- `robot_name`: `galaxy` / `ysc`

消息格式：

```json
{
  "robot": "galaxy",
  "timestamp": 1710000000.123,
  "pose": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
}
```

字段说明：

- `pose` 格式固定为：
  - `[x, y, z, qx, qy, qz, qw]`
- 当前频率：约 `10Hz`

---

### 3.7 `/ws/scene_graph`

用途：

- 订阅全局 scene graph

消息格式：

```json
{
  "timestamp": 1710000000.123,
  "nodes": [
    {
      "id": "galaxy",
      "type": "robot",
      "label": "galaxy",
      "pose": [0, 0, 0, 0, 0, 0, 1]
    },
    {
      "id": "obj_1",
      "type": "object",
      "label": "chair",
      "pose": [1.2, 0.5, 0, 0, 0, 0, 1]
    }
  ],
  "edges": [
    {
      "source": "galaxy",
      "target": "obj_1",
      "type": "near"
    }
  ]
}
```

字段说明：

- `timestamp`: scene graph 生成时间
- `nodes`: 节点数组
- `edges`: 边数组

节点字段：

- `id`: 节点唯一 ID
- `type`: `robot` 或 `object`
- `label`: 显示名称
- `pose`: `[x, y, z, qx, qy, qz, qw]`

边字段：

- `source`: 源节点 ID
- `target`: 目标节点 ID
- `type`: `near` 或 `reach`

生成规则：

- `robot-robot`、`robot-object`：
  - `xy` 距离 `< 1m` -> `reach`
  - `xy` 距离 `< 2m` -> `near`
- `object-object`：
  - 仅可能生成 `near`

当前静态物体：

- `obj_1`: `chair`
- `obj_2`: `workbench`
- `obj_3`: `cart`

当前更新频率：

- 默认约 `2Hz`

## 4. 数据格式规范汇总

### 4.1 JPEG 图像

- 传输方式：
  - ZMQ：二进制 payload
  - WebSocket：二进制 frame
- 编码：`JPEG`
- 分辨率：`640x480`
- 帧率：约 `15fps`

### 4.2 点云

- 编码：`UTF-8 JSON`
- 传输方式：
  - ZMQ：multipart 第二帧为 JSON 字节串
  - WebSocket：text frame，内容为 JSON 字符串
- 单点格式：`[x, y, z]`

### 4.3 odom

- 编码：`UTF-8 JSON`
- `pose` 格式固定：

```json
[x, y, z, qx, qy, qz, qw]
```

### 4.4 遥操

- 编码：`UTF-8 JSON`
- `keys` 为字符串数组
- 支持空数组表示停止

### 4.5 任务

- 编码：`UTF-8 JSON`
- `task_type` 仅支持：
  - `benchmark2`
  - `benchmark3`
  - `corobot`

## 5. 说明

- 文档基于当前代码行为整理
- 当前实现中：
  - 前端通过 HTTP + WebSocket 连接后端
  - 后端通过 ZMQ `6001/6002` 与机器人通信
  - `scene graph` 不走 ZMQ，由后端根据 odom 与静态物体生成
- 若后续你修改了 topic 名、端口或 JSON 字段，需要同步更新本文档
