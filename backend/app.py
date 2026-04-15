from __future__ import annotations

import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .logging_config import configure_named_logger
from .models import (
    SourceItem,
    SystemStatus,
    TaskPayload,
    TaskSendResponse,
    TaskStatus,
    TeleopMessage,
)
from .network_stats import NetworkStatsMonitor
from .robot_registry import (
    get_odom_sources,
    get_pointcloud_sources,
    get_robot_capabilities,
    get_robot_list,
    get_teleop_robots,
    get_video_sources,
)
from .scene_graph import SceneGraphGenerator
from .task_state import TaskState
from .ws_manager import StreamBroker
from .zmq_bridge import ZMQBridge


settings = get_settings()
logger = configure_named_logger("backend", settings.logs_dir / "backend.log")


@asynccontextmanager
async def lifespan(app: FastAPI):
    network_monitor = NetworkStatsMonitor(
        interface=settings.public_interface,
        history_seconds=settings.history_seconds,
        logger=logger,
    )
    task_state = TaskState()
    video_broker = StreamBroker("video")
    pointcloud_broker = StreamBroker("pointcloud")
    odom_broker = StreamBroker("odom")
    scene_graph_broker = StreamBroker("scene_graph")
    scene_graph_generator = SceneGraphGenerator()
    zmq_bridge = ZMQBridge(
        settings=settings,
        logger=logger,
        video_broker=video_broker,
        pointcloud_broker=pointcloud_broker,
        odom_broker=odom_broker,
    )

    await network_monitor.start()
    await zmq_bridge.start()

    app.state.network_monitor = network_monitor
    app.state.task_state = task_state
    app.state.video_broker = video_broker
    app.state.pointcloud_broker = pointcloud_broker
    app.state.odom_broker = odom_broker
    app.state.scene_graph_broker = scene_graph_broker
    app.state.scene_graph_generator = scene_graph_generator
    app.state.zmq_bridge = zmq_bridge
    app.state.teleop_log_cache = {}

    scene_graph_task = asyncio.create_task(scene_graph_loop(app), name="scene-graph-loop")
    logger.info("Backend startup completed")

    try:
        yield
    finally:
        scene_graph_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scene_graph_task
        await zmq_bridge.stop()
        await network_monitor.stop()
        logger.info("Backend shutdown completed")


app = FastAPI(title="VORTS Robot Demo Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "HTTP %s %s -> %s (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


async def scene_graph_loop(app: FastAPI) -> None:
    interval = 1.0 / max(settings.scene_graph_hz, 0.5)

    while True:
        graph = app.state.scene_graph_generator.build(app.state.zmq_bridge.get_robot_poses())
        app.state.scene_graph_broker.publish("global", graph.model_dump())
        await asyncio.sleep(interval)


@app.get("/api/system/status", response_model=SystemStatus)
async def get_system_status():
    task_status: TaskStatus = await app.state.task_state.get_status()
    network = app.state.network_monitor.get_current()
    return SystemStatus(
        server_time=time.time(),
        interface=app.state.network_monitor.interface,
        network=network,
        task=task_status,
        robot_count=len(get_robot_list()),
    )


@app.get("/api/robots")
async def get_robots():
    return get_robot_list()


@app.get("/api/robots/teleop")
async def get_teleop_robot_list():
    return get_teleop_robots()


@app.get("/api/robots/capabilities")
async def get_robot_capabilities_api():
    return get_robot_capabilities()


@app.get("/api/network/stats")
async def get_network_stats():
    return app.state.network_monitor.get_current()


@app.get("/api/network/history")
async def get_network_history():
    return app.state.network_monitor.get_history()


@app.get("/api/task/status", response_model=TaskStatus)
async def get_task_status():
    return await app.state.task_state.get_status()


@app.post("/api/task/send", response_model=TaskSendResponse)
async def send_task(payload: TaskPayload):
    response: TaskSendResponse = await app.state.task_state.send_task(payload)
    if response.ok:
        logger.info("Accepted task type=%s content=%s", payload.task_type, payload.task_content)
        await app.state.zmq_bridge.publish_task(payload)
    else:
        logger.warning("Rejected task because busy: type=%s content=%s", payload.task_type, payload.task_content)
    return response


@app.post("/api/task/clear", response_model=TaskStatus)
async def clear_task():
    logger.info("Cleared current task manually")
    return await app.state.task_state.clear()


@app.get("/api/video/sources", response_model=list[SourceItem])
async def get_video_sources_api():
    return get_video_sources()


@app.get("/api/pointcloud/sources", response_model=list[SourceItem])
async def get_pointcloud_sources_api():
    return get_pointcloud_sources()


@app.get("/api/odom/sources", response_model=list[SourceItem])
async def get_odom_sources_api():
    return get_odom_sources()


@app.websocket("/ws/rtt")
async def websocket_rtt(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected: /ws/rtt")

    try:
        while True:
            message = await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "pong",
                    "client_ts": message.get("client_ts"),
                    "server_ts": time.time(),
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: /ws/rtt")


@app.websocket("/ws/teleop")
async def websocket_teleop(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connected: /ws/teleop")

    try:
        while True:
            payload = TeleopMessage.model_validate(await websocket.receive_json())
            cache = app.state.teleop_log_cache
            now = time.time()
            previous = cache.get(payload.robot, {"keys": None, "ts": 0.0})
            if previous["keys"] != payload.keys or now - previous["ts"] > 1.0:
                logger.info("Teleop robot=%s keys=%s", payload.robot, payload.keys)
                cache[payload.robot] = {"keys": payload.keys, "ts": now}
            await app.state.zmq_bridge.send_teleop(payload)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: /ws/teleop")


@app.websocket("/ws/video/{robot_name}/{camera_name}")
async def websocket_video(websocket: WebSocket, robot_name: str, camera_name: str):
    await stream_binary_endpoint(websocket, app.state.video_broker, f"{robot_name}/{camera_name}")


@app.websocket("/ws/pointcloud/{robot_name}")
async def websocket_pointcloud(websocket: WebSocket, robot_name: str):
    await stream_json_endpoint(websocket, app.state.pointcloud_broker, robot_name)


@app.websocket("/ws/odom/{robot_name}")
async def websocket_odom(websocket: WebSocket, robot_name: str):
    await stream_json_endpoint(websocket, app.state.odom_broker, robot_name)


@app.websocket("/ws/scene_graph")
async def websocket_scene_graph(websocket: WebSocket):
    await stream_json_endpoint(websocket, app.state.scene_graph_broker, "global")


async def stream_binary_endpoint(websocket: WebSocket, broker: StreamBroker, key: str) -> None:
    await websocket.accept()
    queue = broker.subscribe(key)
    logger.info("WebSocket connected: %s", websocket.url.path)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_bytes(payload)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", websocket.url.path)
    finally:
        broker.unsubscribe(key, queue)


async def stream_json_endpoint(websocket: WebSocket, broker: StreamBroker, key: str) -> None:
    await websocket.accept()
    queue = broker.subscribe(key)
    logger.info("WebSocket connected: %s", websocket.url.path)

    try:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", websocket.url.path)
    finally:
        broker.unsubscribe(key, queue)


if __name__ == "__main__":
    uvicorn.run("backend.app:app", host=settings.host, port=settings.port, reload=False)
