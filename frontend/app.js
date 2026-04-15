import { createApi } from "./components/api.js";


function wrapHost(hostname) {
  if (hostname.includes(":") && !hostname.startsWith("[")) {
    return `[${hostname}]`;
  }
  return hostname;
}


function createNotifier(container) {
  return (message, tone = "info") => {
    console.log(`[${tone}] ${message}`);
    const toast = document.createElement("div");
    toast.className = `toast toast-${tone}`;
    toast.textContent = message;
    container.prepend(toast);
    window.setTimeout(() => {
      toast.remove();
    }, 4200);
  };
}


function setBadge(el, text, tone) {
  el.textContent = text;
  el.className = `pill pill-${tone}`;
}


async function main() {
  const host = wrapHost(window.location.hostname || "localhost");
  const httpProtocol = window.location.protocol === "https:" ? "https:" : "http:";
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const apiBaseUrl = `${httpProtocol}//${host}:1141`;
  const wsBaseUrl = `${wsProtocol}//${host}:1141`;
  const api = createApi(apiBaseUrl);

  const statusBar = document.getElementById("statusBar");
  const backendBadge = document.getElementById("backendBadge");
  const notify = createNotifier(statusBar);
  const setBackendBadge = (text, tone = "info") => setBadge(backendBadge, text, tone);

  const pages = {
    home: createFallbackPage(),
    teleop: createFallbackPage(),
    monitor: createFallbackPage(),
  };

  function switchPage(name) {
    document.querySelectorAll(".page").forEach((page) => {
      page.classList.toggle("is-active", page.dataset.page === name);
    });
    document.querySelectorAll(".nav-tab").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.page === name);
    });

    Object.entries(pages).forEach(([pageName, page]) => {
      page.setActive(pageName === name);
    });
  }

  document.querySelectorAll(".nav-tab").forEach((button) => {
    button.addEventListener("click", () => switchPage(button.dataset.page));
  });

  switchPage("home");

  const [homeModule, teleopModule, monitorModule] = await Promise.allSettled([
    import("./components/home.js"),
    import("./components/teleop.js"),
    import("./components/monitor.js"),
  ]);

  if (homeModule.status === "fulfilled") {
    const homePage = new homeModule.value.HomePage({ api, baseWsUrl: wsBaseUrl, notify, setBackendBadge });
    pages.home = homePage;
    try {
      await homePage.init();
    } catch (error) {
      console.error("Home page init failed", error);
      notify(`首页初始化失败: ${error.message}`, "danger");
    }
  } else {
    console.error("Failed to load home module", homeModule.reason);
    notify(`首页脚本加载失败: ${homeModule.reason?.message || homeModule.reason}`, "danger");
  }

  if (teleopModule.status === "fulfilled") {
    const teleopPage = new teleopModule.value.TeleopPage({ api, baseWsUrl: wsBaseUrl, notify });
    pages.teleop = teleopPage;
    try {
      await teleopPage.init();
    } catch (error) {
      console.error("Teleop page init failed", error);
      notify(`遥操页初始化失败: ${error.message}`, "danger");
    }
  } else {
    console.error("Failed to load teleop module", teleopModule.reason);
    notify(`遥操脚本加载失败: ${teleopModule.reason?.message || teleopModule.reason}`, "danger");
  }

  if (monitorModule.status === "fulfilled") {
    const monitorPage = new monitorModule.value.MonitorPage({ api, baseWsUrl: wsBaseUrl, notify });
    pages.monitor = monitorPage;
    try {
      await monitorPage.init();
    } catch (error) {
      console.error("Monitor page init failed", error);
      notify(`监控页初始化失败: ${error.message}`, "danger");
    }
  } else {
    console.error("Failed to load monitor module", monitorModule.reason);
    notify(`监控脚本加载失败: ${monitorModule.reason?.message || monitorModule.reason}`, "danger");
  }

  switchPage("home");

  async function heartbeat() {
    try {
      await api.getSystemStatus();
      setBackendBadge("后端已连接", "success");
    } catch (error) {
      console.error("Backend heartbeat failed", error);
      setBackendBadge("后端不可达", "danger");
    }
  }

  heartbeat();
  window.setInterval(heartbeat, 5000);
}


function createFallbackPage() {
  return {
    async init() {},
    setActive() {},
  };
}


main().catch((error) => {
  console.error("Frontend bootstrap failed", error);
  const statusBar = document.getElementById("statusBar");
  const toast = document.createElement("div");
  toast.className = "toast toast-danger";
  toast.textContent = `前端初始化失败: ${error.message}`;
  statusBar.prepend(toast);
});
