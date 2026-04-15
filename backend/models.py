from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TaskType = Literal["benchmark2", "benchmark3", "corobot"]
NodeType = Literal["robot", "object"]
EdgeType = Literal["near", "reach"]


class RobotInfo(BaseModel):
    name: str
    type: str
    ip: str
    teleop_enabled: bool
    camera_count: int
    camera_names: list[str]
    has_lidar: bool
    has_odom: bool


class RobotCapability(BaseModel):
    name: str
    type: str
    ip: str
    teleop: bool
    teleop_keys: list[str] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)
    lidar: bool
    odom: bool


class SourceItem(BaseModel):
    robot: str
    source: str
    label: str


class NetworkSample(BaseModel):
    timestamp: float
    upload_kbps: float
    download_kbps: float


class NetworkStatsResponse(BaseModel):
    interface: str
    timestamp: float
    upload_kbps: float
    download_kbps: float


class NetworkHistoryResponse(BaseModel):
    interface: str
    samples: list[NetworkSample] = Field(default_factory=list)


class TaskInfo(BaseModel):
    task_type: TaskType
    task_content: str


class TaskPayload(BaseModel):
    task_type: TaskType
    task_content: str


class TaskStatus(BaseModel):
    busy: bool
    current_task: TaskInfo | None = None


class TaskSendResponse(BaseModel):
    ok: bool
    busy: bool
    current_task: TaskInfo | None = None
    message: str | None = None


class TeleopMessage(BaseModel):
    robot: str
    keys: list[str] = Field(default_factory=list)
    ts: float


class PointCloudMessage(BaseModel):
    robot: str
    timestamp: float
    points: list[list[float]] = Field(default_factory=list)


class OdomMessage(BaseModel):
    robot: str
    timestamp: float
    pose: list[float]


class SceneNode(BaseModel):
    id: str
    type: NodeType
    label: str
    pose: list[float]


class SceneEdge(BaseModel):
    source: str
    target: str
    type: EdgeType


class SceneGraphMessage(BaseModel):
    timestamp: float
    nodes: list[SceneNode]
    edges: list[SceneEdge]


class SystemStatus(BaseModel):
    server_time: float
    interface: str
    network: NetworkStatsResponse
    task: TaskStatus
    robot_count: int
