export function createSocketUrl(baseWsUrl, path) {
  return `${baseWsUrl}${path}`;
}


export class ManagedSocket {
  constructor({
    getUrl,
    onOpen = () => {},
    onMessage = () => {},
    onClose = () => {},
    onError = () => {},
    reconnectDelay = 1500,
    binaryType = null,
  }) {
    this.getUrl = getUrl;
    this.onOpen = onOpen;
    this.onMessage = onMessage;
    this.onClose = onClose;
    this.onError = onError;
    this.reconnectDelay = reconnectDelay;
    this.binaryType = binaryType;
    this.socket = null;
    this.reconnectTimer = null;
    this.manualClose = true;
  }

  restart() {
    this.manualClose = false;
    this.#connect();
  }

  close() {
    this.manualClose = true;
    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.close();
    }
  }

  isOpen() {
    return this.socket && this.socket.readyState === WebSocket.OPEN;
  }

  sendJson(payload) {
    if (!this.isOpen()) {
      return;
    }
    this.socket.send(JSON.stringify(payload));
  }

  #connect() {
    if (this.manualClose) {
      return;
    }

    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return;
    }

    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) {
      return;
    }

    const socket = new WebSocket(this.getUrl());
    if (this.binaryType) {
      socket.binaryType = this.binaryType;
    }

    socket.onopen = (event) => {
      this.socket = socket;
      this.onOpen(event);
    };

    socket.onmessage = (event) => {
      this.onMessage(event);
    };

    socket.onerror = (event) => {
      this.onError(event);
    };

    socket.onclose = (event) => {
      const shouldReconnect = !this.manualClose;
      if (this.socket === socket) {
        this.socket = null;
      }
      this.onClose(event, shouldReconnect);

      if (shouldReconnect) {
        this.reconnectTimer = window.setTimeout(() => this.#connect(), this.reconnectDelay);
      }
    };

    this.socket = socket;
  }
}


export class JpegStreamPlayer {
  constructor({ baseWsUrl, stageEl, imageEl, overlayEl }) {
    this.baseWsUrl = baseWsUrl;
    this.stageEl = stageEl;
    this.imageEl = imageEl;
    this.overlayEl = overlayEl;
    this.source = null;
    this.socket = null;
    this.active = false;
    this.lastFrameAt = 0;
    this.objectUrl = null;
    this.watchdogTimer = null;
  }

  setSource(source) {
    const sameSource =
      this.source &&
      source &&
      this.source.robot === source.robot &&
      this.source.source === source.source;

    this.source = source || null;
    if (sameSource) {
      return;
    }

    if (!this.source) {
      this.overlayEl.hidden = false;
      this.overlayEl.textContent = "等待视频流";
      this.#teardownSocket();
      return;
    }

    if (this.active) {
      this.#start();
    } else {
      this.overlayEl.hidden = false;
      this.overlayEl.textContent = "视频已暂停";
    }
  }

  resume() {
    this.active = true;
    this.#start();
  }

  suspend() {
    this.active = false;
    this.#teardownSocket();
    if (!this.source) {
      this.overlayEl.hidden = false;
      this.overlayEl.textContent = "等待视频流";
      return;
    }
    this.overlayEl.hidden = false;
    this.overlayEl.textContent = "视频已暂停";
  }

  destroy() {
    this.#teardownSocket();
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
  }

  #start() {
    this.#teardownSocket();

    if (!this.active || !this.source) {
      return;
    }

    this.overlayEl.hidden = false;
    this.overlayEl.textContent = `连接 ${this.source.label} 中...`;

    this.socket = new ManagedSocket({
      getUrl: () =>
        createSocketUrl(
          this.baseWsUrl,
          `/ws/video/${encodeURIComponent(this.source.robot)}/${encodeURIComponent(this.source.source)}`
        ),
      binaryType: "arraybuffer",
      onOpen: () => {
        this.overlayEl.hidden = false;
        this.overlayEl.textContent = `已连接 ${this.source.label}，等待视频帧`;
        this.#armWatchdog();
      },
      onMessage: (event) => {
        this.lastFrameAt = Date.now();
        const blob = new Blob([event.data], { type: "image/jpeg" });
        const nextUrl = URL.createObjectURL(blob);
        this.imageEl.src = nextUrl;
        this.imageEl.onload = () => {
          if (this.objectUrl) {
            URL.revokeObjectURL(this.objectUrl);
          }
          this.objectUrl = nextUrl;
        };
        this.overlayEl.hidden = true;
      },
      onClose: (_event, willReconnect) => {
        if (!this.active || !this.source) {
          return;
        }
        this.overlayEl.hidden = false;
        this.overlayEl.textContent = willReconnect ? "视频连接断开，正在重连..." : "视频连接已关闭";
      },
      onError: () => {
        if (!this.active || !this.source) {
          return;
        }
        this.overlayEl.hidden = false;
        this.overlayEl.textContent = "视频连接异常";
      },
    });

    this.socket.restart();
  }

  #teardownSocket() {
    window.clearTimeout(this.watchdogTimer);
    this.watchdogTimer = null;
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  #armWatchdog() {
    window.clearTimeout(this.watchdogTimer);
    this.watchdogTimer = window.setTimeout(() => {
      if (!this.active || !this.source) {
        return;
      }
      const age = Date.now() - this.lastFrameAt;
      if (age > 3500) {
        this.overlayEl.hidden = false;
        this.overlayEl.textContent = "暂未收到视频帧";
      }
      this.#armWatchdog();
    }, 3500);
  }
}
