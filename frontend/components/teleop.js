import { JpegStreamPlayer, ManagedSocket, createSocketUrl } from "./ws.js";


const TELEOP_KEY_ORDER = ["w", "s", "a", "d", "q", "e"];


function setPill(el, text, tone) {
  el.textContent = text;
  el.className = `pill pill-${tone}`;
}


export class TeleopPage {
  constructor({ api, baseWsUrl, notify }) {
    this.api = api;
    this.baseWsUrl = baseWsUrl;
    this.notify = notify;
    this.active = false;
    this.teleopSocket = null;
    this.sendTimer = null;
    this.pressedKeys = new Set();
    this.teleopRobots = [];
    this.videoSources = [];

    this.robotSelectEl = document.getElementById("teleopRobotSelect");
    this.cameraSelectEl = document.getElementById("teleopCameraSelect");
    this.pressedKeysEl = document.getElementById("teleopPressedKeys");
    this.videoLabelEl = document.getElementById("teleopVideoLabel");
    this.socketStatusEl = document.getElementById("teleopSocketStatus");
    this.fullscreenBtn = document.getElementById("teleopFullscreenBtn");
    this.keyEls = Array.from(document.querySelectorAll("#teleopKeyGrid .key-chip"));
    this.stageEl = document.getElementById("teleopStage");

    this.videoPlayer = new JpegStreamPlayer({
      baseWsUrl,
      stageEl: this.stageEl,
      imageEl: document.getElementById("teleopVideoImage"),
    });

    this.onKeyDown = this.#handleKeyDown.bind(this);
    this.onKeyUp = this.#handleKeyUp.bind(this);
  }

  async init() {
    const [teleopRobots, videoSources] = await Promise.all([
      this.api.getTeleopRobots(),
      this.api.getVideoSources(),
    ]);

    this.teleopRobots = teleopRobots;
    this.videoSources = videoSources;

    this.#populateRobotSelect();
    this.#populateCameraSelect();
    this.#updatePressedKeys();

    this.robotSelectEl.addEventListener("change", () => {
      this.#populateCameraSelect();
      this.#updateVideoSource();
    });
    this.cameraSelectEl.addEventListener("change", () => this.#updateVideoSource());
    this.fullscreenBtn.addEventListener("click", () => {
      this.stageEl.requestFullscreen?.();
    });

    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("keyup", this.onKeyUp);
  }

  setActive(active) {
    if (this.active === active) {
      return;
    }

    if (active) {
      this.active = true;
      this.#startTeleopSocket();
      this.videoPlayer.resume();
      this.#updateVideoSource();
      this.sendTimer = window.setInterval(() => this.#sendCurrentState(), 1000 / 30);
      return;
    }

    this.#sendStop();
    this.active = false;
    this.pressedKeys.clear();
    this.#refreshKeyState();
    window.clearInterval(this.sendTimer);
    this.sendTimer = null;
    if (this.teleopSocket) {
      this.teleopSocket.close();
      this.teleopSocket = null;
    }
    this.videoPlayer.suspend();
    setPill(this.socketStatusEl, "WS 未连接", "info");
  }

  #startTeleopSocket() {
    if (this.teleopSocket) {
      this.teleopSocket.close();
      this.teleopSocket = null;
    }

    this.teleopSocket = new ManagedSocket({
      getUrl: () => createSocketUrl(this.baseWsUrl, "/ws/teleop"),
      onOpen: () => {
        console.log("Teleop websocket connected");
        setPill(this.socketStatusEl, "WS 已连接", "success");
      },
      onClose: (_event, willReconnect) => {
        setPill(this.socketStatusEl, willReconnect ? "重连中" : "WS 已断开", willReconnect ? "warning" : "danger");
      },
      onError: () => {
        setPill(this.socketStatusEl, "WS 异常", "danger");
      },
    });

    this.teleopSocket.restart();
  }

  #populateRobotSelect() {
    this.robotSelectEl.innerHTML = "";
    this.teleopRobots.forEach((robot) => {
      const option = document.createElement("option");
      option.value = robot.name;
      option.textContent = `${robot.name} (${robot.type})`;
      this.robotSelectEl.appendChild(option);
    });
  }

  #populateCameraSelect() {
    const robotName = this.robotSelectEl.value;
    const sources = this.videoSources.filter((source) => source.robot === robotName);
    this.cameraSelectEl.innerHTML = "";
    sources.forEach((source) => {
      const option = document.createElement("option");
      option.value = `${source.robot}/${source.source}`;
      option.textContent = source.label;
      this.cameraSelectEl.appendChild(option);
    });
  }

  #updateVideoSource() {
    const source = this.#currentVideoSource();
    if (!source) {
      this.videoLabelEl.textContent = "等待选择视频源";
      this.videoPlayer.setSource(null);
      return;
    }
    this.videoLabelEl.textContent = source.label;
    this.videoPlayer.setSource(source);
  }

  #currentVideoSource() {
    const value = this.cameraSelectEl.value;
    return this.videoSources.find((item) => `${item.robot}/${item.source}` === value) || null;
  }

  #handleKeyDown(event) {
    if (!this.active) {
      return;
    }
    const key = event.key.toLowerCase();
    if (!TELEOP_KEY_ORDER.includes(key)) {
      return;
    }
    event.preventDefault();
    this.pressedKeys.add(key);
    this.#refreshKeyState();
  }

  #handleKeyUp(event) {
    const key = event.key.toLowerCase();
    if (!TELEOP_KEY_ORDER.includes(key)) {
      return;
    }
    event.preventDefault();
    this.pressedKeys.delete(key);
    this.#refreshKeyState();
  }

  #refreshKeyState() {
    this.keyEls.forEach((button) => {
      button.classList.toggle("is-active", this.pressedKeys.has(button.dataset.key));
    });
    this.#updatePressedKeys();
  }

  #updatePressedKeys() {
    this.pressedKeysEl.textContent = JSON.stringify(this.#orderedKeys());
  }

  #orderedKeys() {
    return TELEOP_KEY_ORDER.filter((key) => this.pressedKeys.has(key));
  }

  #sendCurrentState() {
    if (!this.active || !this.teleopSocket || !this.teleopSocket.isOpen()) {
      return;
    }

    const robot = this.robotSelectEl.value;
    if (!robot) {
      return;
    }

    this.teleopSocket.sendJson({
      robot,
      keys: this.#orderedKeys(),
      ts: Date.now() / 1000,
    });
  }

  #sendStop() {
    if (!this.teleopSocket || !this.teleopSocket.isOpen()) {
      return;
    }

    const robot = this.robotSelectEl.value;
    if (!robot) {
      return;
    }

    this.teleopSocket.sendJson({
      robot,
      keys: [],
      ts: Date.now() / 1000,
    });
  }
}
