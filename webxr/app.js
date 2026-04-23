const startBtn = document.getElementById("startBtn");
const logEl = document.getElementById("log");
const canvas = document.getElementById("xr-canvas");

let xrSession = null;
let xrRefSpace = null;
let gl = null;
let lastPrintAt = 0;
let lastSendAt = 0;
let sendInFlight = false;

const handlerUrl = "/quest-data";

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

  const baseLayer = session.renderState.baseLayer;
  gl.bindFramebuffer(gl.FRAMEBUFFER, baseLayer.framebuffer);
  gl.clearColor(0.0, 0.0, 0.0, 0.0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

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

  xrSession.updateRenderState({
    baseLayer: new XRWebGLLayer(xrSession, gl, { alpha: true })
  });

  xrRefSpace = await xrSession.requestReferenceSpace("local-floor");
  log(`XR started, blend mode = ${xrSession.environmentBlendMode}`);
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
