import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { JpegStreamPlayer, ManagedSocket, createSocketUrl } from "./ws.js";


function setPill(el, text, tone) {
  el.textContent = text;
  el.className = `pill pill-${tone}`;
}


function stringifyTaskStatus(status) {
  if (!status.busy || !status.current_task) {
    return "空闲";
  }
  return JSON.stringify(status.current_task, null, 2);
}


export class MonitorPage {
  constructor({ api, baseWsUrl, notify }) {
    this.api = api;
    this.baseWsUrl = baseWsUrl;
    this.notify = notify;
    this.active = false;
    this.taskTimer = null;
    this.pointcloudSocket = null;
    this.sceneGraphSocket = null;
    this.latestSceneGraph = null;

    this.taskBusyPillEl = document.getElementById("taskBusyPill");
    this.taskStatusTextEl = document.getElementById("taskStatusText");
    this.taskFormEl = document.getElementById("taskForm");
    this.taskTypeSelectEl = document.getElementById("taskTypeSelect");
    this.taskContentInputEl = document.getElementById("taskContentInput");
    this.clearTaskBtn = document.getElementById("clearTaskBtn");
    this.pointcloudSourceSelectEl = document.getElementById("pointcloudSourceSelect");
    this.pointcloudMetaEl = document.getElementById("pointcloudMeta");
    this.sceneGraphStatusEl = document.getElementById("sceneGraphStatus");
    this.sceneGraphCanvas = document.getElementById("sceneGraphCanvas");
    this.pointcloudViewport = document.getElementById("pointcloudViewport");
    this.primarySelectEl = document.getElementById("monitorRgbPrimarySelect");
    this.secondarySelectEl = document.getElementById("monitorRgbSecondarySelect");
    this.resetPointcloudBtn = document.getElementById("pointcloudResetBtn");

    this.videoSources = [];
    this.pointcloudSources = [];

    this.primaryPlayer = new JpegStreamPlayer({
      baseWsUrl,
      stageEl: document.getElementById("monitorRgbPrimaryStage"),
      imageEl: document.getElementById("monitorRgbPrimaryImage"),
      overlayEl: document.getElementById("monitorRgbPrimaryOverlay"),
    });
    this.secondaryPlayer = new JpegStreamPlayer({
      baseWsUrl,
      stageEl: document.getElementById("monitorRgbSecondaryStage"),
      imageEl: document.getElementById("monitorRgbSecondaryImage"),
      overlayEl: document.getElementById("monitorRgbSecondaryOverlay"),
    });
    this.globalPlayerA = new JpegStreamPlayer({
      baseWsUrl,
      stageEl: document.getElementById("globalMonitorStageA"),
      imageEl: document.getElementById("globalMonitorImageA"),
      overlayEl: document.getElementById("globalMonitorOverlayA"),
    });
    this.globalPlayerB = new JpegStreamPlayer({
      baseWsUrl,
      stageEl: document.getElementById("globalMonitorStageB"),
      imageEl: document.getElementById("globalMonitorImageB"),
      overlayEl: document.getElementById("globalMonitorOverlayB"),
    });
  }

  async init() {
    const [videoSources, pointcloudSources] = await Promise.all([
      this.api.getVideoSources(),
      this.api.getPointcloudSources(),
    ]);

    this.videoSources = videoSources;
    this.pointcloudSources = pointcloudSources;

    this.#populateVideoSelect(this.primarySelectEl, 0);
    this.#populateVideoSelect(this.secondarySelectEl, 1);
    this.#populatePointcloudSelect();

    this.primarySelectEl.addEventListener("change", () => this.#updateRgbPlayers());
    this.secondarySelectEl.addEventListener("change", () => this.#updateRgbPlayers());
    this.taskFormEl.addEventListener("submit", (event) => this.#handleTaskSubmit(event));
    this.clearTaskBtn.addEventListener("click", () => this.#handleTaskClear());
    this.pointcloudSourceSelectEl.addEventListener("change", () => this.#restartPointcloudSocket());
    this.resetPointcloudBtn.addEventListener("click", () => this.#resetPointcloudCamera());

    this.#setupPointcloudScene();
    this.#setupSceneGraphCanvas();
    this.#updateRgbPlayers();

    const piperArm = this.videoSources.find((item) => item.robot === "piper" && item.source === "arm_full");
    const piperSide = this.videoSources.find((item) => item.robot === "piper" && item.source === "side");
    this.globalPlayerA.setSource(piperArm || null);
    this.globalPlayerB.setSource(piperSide || null);
  }

  setActive(active) {
    if (this.active === active) {
      return;
    }
    this.active = active;

    if (active) {
      this.primaryPlayer.resume();
      this.secondaryPlayer.resume();
      this.globalPlayerA.resume();
      this.globalPlayerB.resume();
      this.#restartPointcloudSocket();
      this.#startSceneGraphSocket();
      this.#refreshTaskStatus();
      this.taskTimer = window.setInterval(() => this.#refreshTaskStatus(), 1200);
      return;
    }

    window.clearInterval(this.taskTimer);
    this.taskTimer = null;
    this.primaryPlayer.suspend();
    this.secondaryPlayer.suspend();
    this.globalPlayerA.suspend();
    this.globalPlayerB.suspend();
    this.#stopPointcloudSocket();
    this.#stopSceneGraphSocket();
  }

  #populateVideoSelect(selectEl, defaultIndex) {
    selectEl.innerHTML = "";
    this.videoSources.forEach((source, index) => {
      const option = document.createElement("option");
      option.value = `${source.robot}/${source.source}`;
      option.textContent = source.label;
      if (index === defaultIndex) {
        option.selected = true;
      }
      selectEl.appendChild(option);
    });
  }

  #populatePointcloudSelect() {
    this.pointcloudSourceSelectEl.innerHTML = "";
    this.pointcloudSources.forEach((source) => {
      const option = document.createElement("option");
      option.value = source.robot;
      option.textContent = source.label;
      this.pointcloudSourceSelectEl.appendChild(option);
    });
  }

  #findVideoSource(value) {
    return this.videoSources.find((item) => `${item.robot}/${item.source}` === value) || null;
  }

  #updateRgbPlayers() {
    this.primaryPlayer.setSource(this.#findVideoSource(this.primarySelectEl.value));
    this.secondaryPlayer.setSource(this.#findVideoSource(this.secondarySelectEl.value));
  }

  async #handleTaskSubmit(event) {
    event.preventDefault();
    const taskContent = this.taskContentInputEl.value.trim();
    if (!taskContent) {
      this.notify("请先填写任务内容", "warning");
      return;
    }

    try {
      const response = await this.api.sendTask({
        task_type: this.taskTypeSelectEl.value,
        task_content: taskContent,
      });
      this.#applyTaskStatus(response);
      this.notify(response.ok ? "任务发送成功" : response.message || "任务发送失败", response.ok ? "success" : "warning");
    } catch (error) {
      console.error("Failed to send task", error);
      this.notify(`任务发送失败: ${error.message}`, "danger");
    }
  }

  async #handleTaskClear() {
    try {
      const status = await this.api.clearTask();
      this.#applyTaskStatus(status);
      this.notify("任务已清空", "success");
    } catch (error) {
      console.error("Failed to clear task", error);
      this.notify(`清空任务失败: ${error.message}`, "danger");
    }
  }

  async #refreshTaskStatus() {
    try {
      const status = await this.api.getTaskStatus();
      this.#applyTaskStatus(status);
    } catch (error) {
      console.error("Failed to refresh task status", error);
    }
  }

  #applyTaskStatus(status) {
    const busy = Boolean(status.busy);
    setPill(this.taskBusyPillEl, busy ? "Busy" : "Idle", busy ? "warning" : "success");
    this.taskStatusTextEl.textContent = stringifyTaskStatus(status);
  }

  #setupPointcloudScene() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.pointcloudViewport.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = null;

    this.camera = new THREE.PerspectiveCamera(58, 1, 0.1, 100);
    this.camera.position.set(0, -4.5, 2.8);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0, 0.3);

    const grid = new THREE.GridHelper(8, 16, 0x8ea3b0, 0xc8d6df);
    grid.rotation.x = Math.PI / 2;
    this.scene.add(grid);

    const axes = new THREE.AxesHelper(1.2);
    this.scene.add(axes);

    this.pointGeometry = new THREE.BufferGeometry();
    this.pointMaterial = new THREE.PointsMaterial({
      color: 0x4f738b,
      size: 0.035,
      sizeAttenuation: true,
    });
    this.pointMesh = new THREE.Points(this.pointGeometry, this.pointMaterial);
    this.scene.add(this.pointMesh);

    this.#resizePointcloud();
    this.#animatePointcloud();

    const resizeObserver = new ResizeObserver(() => this.#resizePointcloud());
    resizeObserver.observe(this.pointcloudViewport);
  }

  #animatePointcloud() {
    window.requestAnimationFrame(() => this.#animatePointcloud());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  #resizePointcloud() {
    const width = this.pointcloudViewport.clientWidth || 640;
    const height = this.pointcloudViewport.clientHeight || 280;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  #resetPointcloudCamera() {
    this.camera.position.set(0, -4.5, 2.8);
    this.controls.target.set(0, 0, 0.3);
    this.controls.update();
  }

  #restartPointcloudSocket() {
    this.#stopPointcloudSocket();

    if (!this.active) {
      return;
    }

    const robot = this.pointcloudSourceSelectEl.value;
    if (!robot) {
      this.pointcloudMetaEl.textContent = "未选择点云来源";
      return;
    }

    this.pointcloudSocket = new ManagedSocket({
      getUrl: () => createSocketUrl(this.baseWsUrl, `/ws/pointcloud/${encodeURIComponent(robot)}`),
      onOpen: () => {
        this.pointcloudMetaEl.textContent = `${robot} 点云已连接`;
      },
      onMessage: (event) => {
        const packet = JSON.parse(event.data);
        this.#updatePointcloud(packet);
      },
      onClose: (_event, willReconnect) => {
        this.pointcloudMetaEl.textContent = willReconnect ? `${robot} 点云重连中` : `${robot} 点云已断开`;
      },
      onError: () => {
        this.pointcloudMetaEl.textContent = `${robot} 点云连接异常`;
      },
    });

    this.pointcloudSocket.restart();
  }

  #stopPointcloudSocket() {
    if (this.pointcloudSocket) {
      this.pointcloudSocket.close();
      this.pointcloudSocket = null;
    }
  }

  #updatePointcloud(packet) {
    const points = packet.points || [];
    const positions = new Float32Array(points.length * 3);
    for (let index = 0; index < points.length; index += 1) {
      positions[index * 3] = points[index][0];
      positions[index * 3 + 1] = points[index][1];
      positions[index * 3 + 2] = points[index][2];
    }

    this.pointGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.pointGeometry.computeBoundingSphere();
    this.pointcloudMetaEl.textContent = `${packet.robot} 点云 ${points.length} 点 @ ${new Date(
      packet.timestamp * 1000
    ).toLocaleTimeString("zh-CN", { hour12: false })}`;
  }

  #setupSceneGraphCanvas() {
    this.sceneGraphCtx = this.sceneGraphCanvas.getContext("2d");
    const resize = () => {
      const devicePixelRatio = window.devicePixelRatio || 1;
      const rect = this.sceneGraphCanvas.getBoundingClientRect();
      this.sceneGraphCanvas.width = Math.max(1, Math.floor(rect.width * devicePixelRatio));
      this.sceneGraphCanvas.height = Math.max(1, Math.floor(rect.height * devicePixelRatio));
      this.sceneGraphCtx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      this.#drawSceneGraph(this.latestSceneGraph);
    };
    resize();
    window.addEventListener("resize", resize);
  }

  #startSceneGraphSocket() {
    this.#stopSceneGraphSocket();

    if (!this.active) {
      return;
    }

    this.sceneGraphSocket = new ManagedSocket({
      getUrl: () => createSocketUrl(this.baseWsUrl, "/ws/scene_graph"),
      onOpen: () => {
        setPill(this.sceneGraphStatusEl, "WS 已连接", "success");
      },
      onMessage: (event) => {
        this.latestSceneGraph = JSON.parse(event.data);
        this.#drawSceneGraph(this.latestSceneGraph);
      },
      onClose: (_event, willReconnect) => {
        setPill(this.sceneGraphStatusEl, willReconnect ? "重连中" : "WS 已断开", willReconnect ? "warning" : "danger");
      },
      onError: () => {
        setPill(this.sceneGraphStatusEl, "WS 异常", "danger");
      },
    });

    this.sceneGraphSocket.restart();
  }

  #stopSceneGraphSocket() {
    if (this.sceneGraphSocket) {
      this.sceneGraphSocket.close();
      this.sceneGraphSocket = null;
    }
    setPill(this.sceneGraphStatusEl, "WS 未连接", "info");
  }

  #drawSceneGraph(graph) {
    const ctx = this.sceneGraphCtx;
    if (!ctx) {
      return;
    }

    const width = this.sceneGraphCanvas.clientWidth;
    const height = this.sceneGraphCanvas.clientHeight;
    ctx.clearRect(0, 0, width, height);

    if (!graph) {
      ctx.fillStyle = "#607583";
      ctx.font = "14px Segoe UI";
      ctx.fillText("等待 scene graph 数据", 20, 28);
      return;
    }

    const padding = 40;
    const xs = graph.nodes.map((node) => node.pose[0]);
    const ys = graph.nodes.map((node) => node.pose[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const span = Math.max(maxX - minX, maxY - minY, 1.5);
    const scale = Math.min((width - padding * 2) / span, (height - padding * 2) / span);

    const positions = new Map();
    graph.nodes.forEach((node) => {
      const canvasX = width / 2 + (node.pose[0] - centerX) * scale;
      const canvasY = height / 2 - (node.pose[1] - centerY) * scale;
      positions.set(node.id, { x: canvasX, y: canvasY, node });
    });

    ctx.lineWidth = 2;
    graph.edges.forEach((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) {
        return;
      }
      ctx.beginPath();
      ctx.strokeStyle = edge.type === "reach" ? "#cb8a49" : "#7c99ad";
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.stroke();
    });

    graph.nodes.forEach((node) => {
      const { x, y } = positions.get(node.id);
      const radius = node.type === "robot" ? 12 : 9;
      ctx.beginPath();
      ctx.fillStyle = node.type === "robot" ? "#55788f" : "#9eb5c4";
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#233340";
      ctx.font = "13px Segoe UI";
      ctx.fillText(node.label, x + radius + 6, y + 4);
    });

    ctx.fillStyle = "#607583";
    ctx.font = "12px Segoe UI";
    ctx.fillText(`更新时间 ${new Date(graph.timestamp * 1000).toLocaleTimeString("zh-CN", { hour12: false })}`, 16, 24);
    ctx.fillText("near: 蓝灰线  reach: 橙色线", 16, height - 16);
  }
}
