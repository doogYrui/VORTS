const startBtn = document.getElementById("startBtn");
const logEl = document.getElementById("log");
const canvas = document.getElementById("xr-canvas");
const robotVideoEl = document.getElementById("robotVideo");
const videoStatusEl = document.getElementById("videoStatus");
const latencyStatusEl = document.getElementById("latencyStatus");

let xrSession = null;
let xrRefSpace = null;
let gl = null;
let lastPrintAt = 0;
let lastSendAt = 0;
let sendInFlight = false;
let videoSocket = null;
let reconnectTimer = null;
let currentFrameUrl = null;
let videoFrameDirty = false;
let latestVideoBitmap = null;
let pendingVideoBlob = null;
let bitmapDecodeInFlight = false;
let videoMetaSocket = null;
let currentLatencyMs = null;
let infoTextureDirty = true;

let videoPanelRenderer = null;
let panelPose = null;
let infoPanelRenderer = null;

const handlerUrl = "/quest-data";
const VIDEO_PANEL_DISTANCE = 1.2;
const VIDEO_PANEL_DROP = 0.15;
const VIDEO_PANEL_WIDTH = 1.2;
const VIDEO_PANEL_HEIGHT = 0.9;
const INFO_PANEL_WIDTH = 1.0;
const INFO_PANEL_HEIGHT = 0.16;

function formatNumber(value) {
  return Number(value.toFixed(4));
}

function makeEmptyControllerState(handedness) {
  return {
    handedness,
    available: false,
    pose: {
      position: null,
      orientation: null
    },
    buttons: {
      index0: {
        pressed: false,
        value: 0
      },
      index4: {
        pressed: false,
        value: 0
      }
    },
    axes: {
      axis0: 0,
      axis1: 0,
      axis2: 0,
      axis3: 0
    }
  };
}

function getButtonState(buttons, index) {
  const button = buttons[index];
  if (!button) {
    return {
      pressed: false,
      value: 0
    };
  }

  return {
    pressed: Boolean(button.pressed),
    value: formatNumber(button.value ?? 0)
  };
}

function log(message, data) {
  console.log(message, data ?? "");
  logEl.textContent = data ? `${message}\n\n${JSON.stringify(data, null, 2)}` : message;
}

function createShader(glContext, type, source) {
  const shader = glContext.createShader(type);
  glContext.shaderSource(shader, source);
  glContext.compileShader(shader);

  if (!glContext.getShaderParameter(shader, glContext.COMPILE_STATUS)) {
    const error = glContext.getShaderInfoLog(shader);
    glContext.deleteShader(shader);
    throw new Error(`Shader compile failed: ${error}`);
  }

  return shader;
}

function createProgram(glContext, vertexSource, fragmentSource) {
  const vertexShader = createShader(glContext, glContext.VERTEX_SHADER, vertexSource);
  const fragmentShader = createShader(glContext, glContext.FRAGMENT_SHADER, fragmentSource);
  const program = glContext.createProgram();

  glContext.attachShader(program, vertexShader);
  glContext.attachShader(program, fragmentShader);
  glContext.linkProgram(program);

  glContext.deleteShader(vertexShader);
  glContext.deleteShader(fragmentShader);

  if (!glContext.getProgramParameter(program, glContext.LINK_STATUS)) {
    const error = glContext.getProgramInfoLog(program);
    glContext.deleteProgram(program);
    throw new Error(`Program link failed: ${error}`);
  }

  return program;
}

function multiplyMatrices(a, b) {
  const out = new Float32Array(16);

  for (let col = 0; col < 4; col += 1) {
    for (let row = 0; row < 4; row += 1) {
      out[col * 4 + row] =
        a[0 * 4 + row] * b[col * 4 + 0] +
        a[1 * 4 + row] * b[col * 4 + 1] +
        a[2 * 4 + row] * b[col * 4 + 2] +
        a[3 * 4 + row] * b[col * 4 + 3];
    }
  }

  return out;
}

function createPanelModelMatrix(position, yaw) {
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);

  return new Float32Array([
    cosYaw, 0, -sinYaw, 0,
    0, 1, 0, 0,
    sinYaw, 0, cosYaw, 0,
    position.x, position.y, position.z, 1
  ]);
}

function rotateVectorByQuaternion(vector, quaternion) {
  const qx = quaternion.x;
  const qy = quaternion.y;
  const qz = quaternion.z;
  const qw = quaternion.w;

  const uvx = qy * vector[2] - qz * vector[1];
  const uvy = qz * vector[0] - qx * vector[2];
  const uvz = qx * vector[1] - qy * vector[0];

  const uuvx = qy * uvz - qz * uvy;
  const uuvy = qz * uvx - qx * uvz;
  const uuvz = qx * uvy - qy * uvx;

  return [
    vector[0] + 2 * (qw * uvx + uuvx),
    vector[1] + 2 * (qw * uvy + uuvy),
    vector[2] + 2 * (qw * uvz + uuvz)
  ];
}

function initializePanelPose(viewerTransform) {
  if (panelPose) return;

  const position = viewerTransform.position;
  const orientation = viewerTransform.orientation;
  const forward = rotateVectorByQuaternion([0, 0, -1], orientation);
  const horizontalForward = [forward[0], 0, forward[2]];
  const horizontalLength = Math.hypot(horizontalForward[0], horizontalForward[2]) || 1;
  const normalizedForward = [
    horizontalForward[0] / horizontalLength,
    0,
    horizontalForward[2] / horizontalLength
  ];

  const panelPosition = {
    x: position.x + normalizedForward[0] * VIDEO_PANEL_DISTANCE,
    y: Math.max(1.0, position.y - VIDEO_PANEL_DROP),
    z: position.z + normalizedForward[2] * VIDEO_PANEL_DISTANCE
  };

  const panelNormal = [-normalizedForward[0], 0, -normalizedForward[2]];
  const yaw = Math.atan2(panelNormal[0], panelNormal[2]);

  panelPose = {
    modelMatrix: createPanelModelMatrix(panelPosition, yaw),
    infoModelMatrix: createPanelModelMatrix(
      {
        x: panelPosition.x,
        y: panelPosition.y + VIDEO_PANEL_HEIGHT / 2 + 0.14,
        z: panelPosition.z
      },
      yaw
    )
  };
}

function initVideoPanelRenderer(glContext) {
  const vertexSource = `
    attribute vec3 aPosition;
    attribute vec2 aTexCoord;
    uniform mat4 uMvp;
    varying vec2 vTexCoord;

    void main() {
      gl_Position = uMvp * vec4(aPosition, 1.0);
      vTexCoord = aTexCoord;
    }
  `;

  const fragmentSource = `
    precision mediump float;
    varying vec2 vTexCoord;
    uniform sampler2D uTexture;

    void main() {
      gl_FragColor = texture2D(uTexture, vTexCoord);
    }
  `;

  const program = createProgram(glContext, vertexSource, fragmentSource);
  const positionLocation = glContext.getAttribLocation(program, "aPosition");
  const texCoordLocation = glContext.getAttribLocation(program, "aTexCoord");
  const mvpLocation = glContext.getUniformLocation(program, "uMvp");
  const textureLocation = glContext.getUniformLocation(program, "uTexture");

  const vertexBuffer = glContext.createBuffer();
  glContext.bindBuffer(glContext.ARRAY_BUFFER, vertexBuffer);
  glContext.bufferData(
    glContext.ARRAY_BUFFER,
    new Float32Array([
      -VIDEO_PANEL_WIDTH / 2, -VIDEO_PANEL_HEIGHT / 2, 0, 0, 1,
       VIDEO_PANEL_WIDTH / 2, -VIDEO_PANEL_HEIGHT / 2, 0, 1, 1,
      -VIDEO_PANEL_WIDTH / 2,  VIDEO_PANEL_HEIGHT / 2, 0, 0, 0,
      -VIDEO_PANEL_WIDTH / 2,  VIDEO_PANEL_HEIGHT / 2, 0, 0, 0,
       VIDEO_PANEL_WIDTH / 2, -VIDEO_PANEL_HEIGHT / 2, 0, 1, 1,
       VIDEO_PANEL_WIDTH / 2,  VIDEO_PANEL_HEIGHT / 2, 0, 1, 0
    ]),
    glContext.STATIC_DRAW
  );

  const texture = glContext.createTexture();
  glContext.bindTexture(glContext.TEXTURE_2D, texture);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_S, glContext.CLAMP_TO_EDGE);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_T, glContext.CLAMP_TO_EDGE);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MIN_FILTER, glContext.LINEAR);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MAG_FILTER, glContext.LINEAR);
  glContext.texImage2D(
    glContext.TEXTURE_2D,
    0,
    glContext.RGBA,
    1,
    1,
    0,
    glContext.RGBA,
    glContext.UNSIGNED_BYTE,
    new Uint8Array([0, 0, 0, 255])
  );

  videoPanelRenderer = {
    program,
    positionLocation,
    texCoordLocation,
    mvpLocation,
    textureLocation,
    vertexBuffer,
    texture
  };
}

function initInfoPanelRenderer(glContext) {
  const texture = glContext.createTexture();
  glContext.bindTexture(glContext.TEXTURE_2D, texture);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_S, glContext.CLAMP_TO_EDGE);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_T, glContext.CLAMP_TO_EDGE);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MIN_FILTER, glContext.LINEAR);
  glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MAG_FILTER, glContext.LINEAR);
  glContext.texImage2D(
    glContext.TEXTURE_2D,
    0,
    glContext.RGBA,
    1,
    1,
    0,
    glContext.RGBA,
    glContext.UNSIGNED_BYTE,
    new Uint8Array([20, 20, 20, 220])
  );

  const canvasEl = document.createElement("canvas");
  canvasEl.width = 512;
  canvasEl.height = 96;
  const context2d = canvasEl.getContext("2d");

  infoPanelRenderer = {
    texture,
    canvasEl,
    context2d
  };
}

function updateInfoStatusText(latencyMs) {
  currentLatencyMs = latencyMs;
  latencyStatusEl.textContent =
    latencyMs == null ? "当前视频延迟: -- ms" : `当前视频延迟: ${latencyMs} ms`;
  infoTextureDirty = true;
}

function updateInfoTexture(glContext) {
  if (!infoPanelRenderer || !videoPanelRenderer || !infoTextureDirty) return;

  const { canvasEl, context2d, texture } = infoPanelRenderer;
  context2d.clearRect(0, 0, canvasEl.width, canvasEl.height);
  context2d.fillStyle = "rgba(16, 16, 16, 0.86)";
  context2d.fillRect(0, 0, canvasEl.width, canvasEl.height);
  context2d.strokeStyle = "rgba(255, 255, 255, 0.18)";
  context2d.lineWidth = 2;
  context2d.strokeRect(1, 1, canvasEl.width - 2, canvasEl.height - 2);
  context2d.fillStyle = "#9ecbff";
  context2d.font = "bold 30px sans-serif";
  context2d.textAlign = "center";
  context2d.textBaseline = "middle";
  const text =
    currentLatencyMs == null ? "Video latency: -- ms" : `Video latency: ${currentLatencyMs} ms`;
  context2d.fillText(text, canvasEl.width / 2, canvasEl.height / 2);

  glContext.bindTexture(glContext.TEXTURE_2D, texture);
  glContext.texImage2D(
    glContext.TEXTURE_2D,
    0,
    glContext.RGBA,
    glContext.RGBA,
    glContext.UNSIGNED_BYTE,
    canvasEl
  );

  infoTextureDirty = false;
}

function updateVideoTexture(glContext) {
  if (!videoPanelRenderer) return;
  if (!videoFrameDirty) return;

  const textureSource =
    latestVideoBitmap ||
    (robotVideoEl.complete && robotVideoEl.naturalWidth ? robotVideoEl : null);

  if (!textureSource) return;

  glContext.bindTexture(glContext.TEXTURE_2D, videoPanelRenderer.texture);
  glContext.texImage2D(
    glContext.TEXTURE_2D,
    0,
    glContext.RGBA,
    glContext.RGBA,
    glContext.UNSIGNED_BYTE,
    textureSource
  );
  videoFrameDirty = false;
}

function renderVideoPanel(glContext, view) {
  if (!videoPanelRenderer || !panelPose) return;
  if (!robotVideoEl.complete || !robotVideoEl.naturalWidth) return;

  const mvp = multiplyMatrices(
    view.projectionMatrix,
    multiplyMatrices(view.transform.inverse.matrix, panelPose.modelMatrix)
  );

  glContext.useProgram(videoPanelRenderer.program);
  glContext.bindBuffer(glContext.ARRAY_BUFFER, videoPanelRenderer.vertexBuffer);
  glContext.enableVertexAttribArray(videoPanelRenderer.positionLocation);
  glContext.vertexAttribPointer(videoPanelRenderer.positionLocation, 3, glContext.FLOAT, false, 20, 0);
  glContext.enableVertexAttribArray(videoPanelRenderer.texCoordLocation);
  glContext.vertexAttribPointer(videoPanelRenderer.texCoordLocation, 2, glContext.FLOAT, false, 20, 12);
  glContext.uniformMatrix4fv(videoPanelRenderer.mvpLocation, false, mvp);
  glContext.activeTexture(glContext.TEXTURE0);
  glContext.bindTexture(glContext.TEXTURE_2D, videoPanelRenderer.texture);
  glContext.uniform1i(videoPanelRenderer.textureLocation, 0);
  glContext.drawArrays(glContext.TRIANGLES, 0, 6);
}

function renderInfoPanel(glContext, view) {
  if (!videoPanelRenderer || !infoPanelRenderer || !panelPose) return;

  const scaleMatrix = new Float32Array([
    INFO_PANEL_WIDTH / VIDEO_PANEL_WIDTH, 0, 0, 0,
    0, INFO_PANEL_HEIGHT / VIDEO_PANEL_HEIGHT, 0, 0,
    0, 0, 1, 0,
    0, 0, 0, 1
  ]);

  const modelMatrix = multiplyMatrices(panelPose.infoModelMatrix, scaleMatrix);
  const mvp = multiplyMatrices(
    view.projectionMatrix,
    multiplyMatrices(view.transform.inverse.matrix, modelMatrix)
  );

  glContext.useProgram(videoPanelRenderer.program);
  glContext.bindBuffer(glContext.ARRAY_BUFFER, videoPanelRenderer.vertexBuffer);
  glContext.enableVertexAttribArray(videoPanelRenderer.positionLocation);
  glContext.vertexAttribPointer(videoPanelRenderer.positionLocation, 3, glContext.FLOAT, false, 20, 0);
  glContext.enableVertexAttribArray(videoPanelRenderer.texCoordLocation);
  glContext.vertexAttribPointer(videoPanelRenderer.texCoordLocation, 2, glContext.FLOAT, false, 20, 12);
  glContext.uniformMatrix4fv(videoPanelRenderer.mvpLocation, false, mvp);
  glContext.activeTexture(glContext.TEXTURE0);
  glContext.bindTexture(glContext.TEXTURE_2D, infoPanelRenderer.texture);
  glContext.uniform1i(videoPanelRenderer.textureLocation, 0);
  glContext.drawArrays(glContext.TRIANGLES, 0, 6);
}

function setVideoStatus(message) {
  videoStatusEl.textContent = message;
}

function connectRobotVideo() {
  const wsProtocol = location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${wsProtocol}://${location.host}/ws/video/galaxy/rgb`;

  if (videoSocket) {
    videoSocket.close();
  }

  setVideoStatus("机器人视频连接中...");
  videoSocket = new WebSocket(wsUrl);
  videoSocket.binaryType = "blob";

  videoSocket.addEventListener("open", () => {
    setVideoStatus("机器人视频已连接");
  });

  videoSocket.addEventListener("message", (event) => {
    const nextUrl = URL.createObjectURL(event.data);
    robotVideoEl.src = nextUrl;

    if (currentFrameUrl) {
      URL.revokeObjectURL(currentFrameUrl);
    }

    currentFrameUrl = nextUrl;
    setVideoStatus(`机器人视频已连接，最近更新时间 ${new Date().toLocaleTimeString()}`);

    if ("createImageBitmap" in window) {
      pendingVideoBlob = event.data;
      scheduleBitmapDecode();
    } else {
      videoFrameDirty = true;
    }
  });

  videoSocket.addEventListener("close", () => {
    setVideoStatus("机器人视频已断开，准备重连...");
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    reconnectTimer = setTimeout(connectRobotVideo, 1000);
  });

  videoSocket.addEventListener("error", () => {
    setVideoStatus("机器人视频连接失败");
  });
}

function connectRobotVideoMeta() {
  const wsProtocol = location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${wsProtocol}://${location.host}/ws/video_meta/galaxy/rgb`;

  if (videoMetaSocket) {
    videoMetaSocket.close();
  }

  videoMetaSocket = new WebSocket(wsUrl);

  videoMetaSocket.addEventListener("message", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (typeof payload.capture_ts === "number") {
        const latencyMs = Math.max(0, Math.round((Date.now() / 1000 - payload.capture_ts) * 1000));
        updateInfoStatusText(latencyMs);
      }
    } catch (error) {
      console.warn("视频延迟信息解析失败", error);
    }
  });

  videoMetaSocket.addEventListener("close", () => {
    updateInfoStatusText(null);
    setTimeout(connectRobotVideoMeta, 1000);
  });
}

robotVideoEl.addEventListener("load", () => {
  videoFrameDirty = true;
});

function scheduleBitmapDecode() {
  if (!("createImageBitmap" in window)) return;
  if (bitmapDecodeInFlight || !pendingVideoBlob) return;

  const blob = pendingVideoBlob;
  pendingVideoBlob = null;
  bitmapDecodeInFlight = true;

  createImageBitmap(blob)
    .then((bitmap) => {
      if (latestVideoBitmap) {
        latestVideoBitmap.close();
      }
      latestVideoBitmap = bitmap;
      videoFrameDirty = true;
    })
    .catch((error) => {
      console.warn("视频帧解码失败", error);
    })
    .finally(() => {
      bitmapDecodeInFlight = false;
      if (pendingVideoBlob) {
        scheduleBitmapDecode();
      }
    });
}

async function sendToHandler(data) {
  if (sendInFlight) return;
  sendInFlight = true;

  try {
    const response = await fetch(handlerUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      console.warn("quest_data_handler 返回失败状态", response.status);
    }
  } catch (error) {
    console.warn("发送 Quest 数据到 handler 失败", error);
  } finally {
    sendInFlight = false;
  }
}

function buildControllerState(frame, session, refSpace) {
  const result = {
    ts: Date.now(),
    left: makeEmptyControllerState("left"),
    right: makeEmptyControllerState("right")
  };

  for (const source of session.inputSources) {
    const handedness = source.handedness;
    if (handedness !== "left" && handedness !== "right") continue;

    const controllerData = makeEmptyControllerState(handedness);
    const gamepad = source.gamepad;

    if (!gamepad) {
      result[handedness] = controllerData;
      continue;
    }

    controllerData.available = true;
    if (source.gripSpace) {
      const gripPose = frame.getPose(source.gripSpace, refSpace);
      if (gripPose) {
        const p = gripPose.transform.position;
        const q = gripPose.transform.orientation;
        controllerData.pose = {
          position: {
            x: formatNumber(p.x),
            y: formatNumber(p.y),
            z: formatNumber(p.z)
          },
          orientation: {
            x: formatNumber(q.x),
            y: formatNumber(q.y),
            z: formatNumber(q.z),
            w: formatNumber(q.w)
          }
        };
      }
    }

    controllerData.buttons = {
      index0: getButtonState(gamepad.buttons, 0),
      index4: getButtonState(gamepad.buttons, 4)
    };

    controllerData.axes = {
      axis0: formatNumber(gamepad.axes[0] ?? 0),
      axis1: formatNumber(gamepad.axes[1] ?? 0),
      axis2: formatNumber(gamepad.axes[2] ?? 0),
      axis3: formatNumber(gamepad.axes[3] ?? 0)
    };

    result[handedness] = controllerData;
  }

  return result;
}

function onXRFrame(_, frame) {
  const session = frame.session;
  session.requestAnimationFrame(onXRFrame);

  const viewerPose = frame.getViewerPose(xrRefSpace);
  if (!viewerPose) return;
  initializePanelPose(viewerPose.transform);

  const baseLayer = session.renderState.baseLayer;
  gl.bindFramebuffer(gl.FRAMEBUFFER, baseLayer.framebuffer);
  gl.clearColor(0.0, 0.0, 0.0, 0.0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.enable(gl.DEPTH_TEST);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

  updateVideoTexture(gl);
  updateInfoTexture(gl);

  for (const view of viewerPose.views) {
    const viewport = baseLayer.getViewport(view);
    gl.viewport(viewport.x, viewport.y, viewport.width, viewport.height);
    renderVideoPanel(gl, view);
    renderInfoPanel(gl, view);
  }

  const now = performance.now();
  if (now - lastPrintAt < 120) return;

  lastPrintAt = now;
  const controllerState = buildControllerState(frame, session, xrRefSpace);
  log("Quest3 手柄数据", controllerState);

  if (now - lastSendAt >= 120) {
    lastSendAt = now;
    void sendToHandler(controllerState);
  }
}

async function startXR() {
  if (!navigator.xr) {
    throw new Error("当前浏览器不支持 WebXR");
  }

  const supported = await navigator.xr.isSessionSupported("immersive-ar");
  if (!supported) {
    throw new Error("当前设备/浏览器不支持 immersive-ar");
  }

  xrSession = await navigator.xr.requestSession("immersive-ar", {
    optionalFeatures: ["local-floor", "bounded-floor", "hand-tracking"]
  });

  gl = canvas.getContext("webgl", {
    xrCompatible: true,
    alpha: true,
    antialias: true
  });

  if (!gl) {
    throw new Error("无法创建 WebGL context");
  }

  if (gl.makeXRCompatible) {
    await gl.makeXRCompatible();
  }

  initVideoPanelRenderer(gl);
  initInfoPanelRenderer(gl);
  panelPose = null;

  xrSession.updateRenderState({
    baseLayer: new XRWebGLLayer(xrSession, gl, { alpha: true })
  });

  xrRefSpace = await xrSession.requestReferenceSpace("local-floor");
  log(`XR started, blend mode = ${xrSession.environmentBlendMode}. 视频面板会出现在你前方。`);
  xrSession.requestAnimationFrame(onXRFrame);
}

startBtn.addEventListener("click", async () => {
  try {
    await startXR();
  } catch (error) {
    console.error(error);
    log(`启动失败: ${error.message}`);
  }
});

connectRobotVideo();
connectRobotVideoMeta();
