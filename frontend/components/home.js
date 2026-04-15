import { ManagedSocket, createSocketUrl } from "./ws.js";


function formatTime(timestampSeconds) {
  const date = new Date(timestampSeconds * 1000);
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}


function setPill(el, text, tone) {
  el.textContent = text;
  el.className = `pill pill-${tone}`;
}


export class HomePage {
  constructor({ api, baseWsUrl, notify, setBackendBadge }) {
    this.api = api;
    this.baseWsUrl = baseWsUrl;
    this.notify = notify;
    this.setBackendBadge = setBackendBadge;
    this.active = false;
    this.refreshTimer = null;
    this.pingTimer = null;
    this.rttSocket = null;
    this.refreshInFlight = false;

    this.interfaceEl = document.getElementById("homeInterface");
    this.taskTextEl = document.getElementById("homeTaskText");
    this.updatedAtEl = document.getElementById("homeUpdatedAt");
    this.uploadValueEl = document.getElementById("uploadValue");
    this.downloadValueEl = document.getElementById("downloadValue");
    this.rttValueEl = document.getElementById("rttValue");
    this.rttStatusEl = document.getElementById("rttStatus");
  }

  async init() {
    this.gaugeChart = window.echarts.init(document.getElementById("networkGaugeChart"));
    this.historyChart = window.echarts.init(document.getElementById("networkHistoryChart"));
    window.addEventListener("resize", () => {
      this.gaugeChart.resize();
      this.historyChart.resize();
    });
  }

  setActive(active) {
    if (this.active === active) {
      return;
    }
    this.active = active;

    if (active) {
      this.refresh();
      this.refreshTimer = window.setInterval(() => this.refresh(), 1000);
      this.#startRtt();
      return;
    }

    window.clearInterval(this.refreshTimer);
    this.refreshTimer = null;
    this.#stopRtt();
  }

  async refresh() {
    if (this.refreshInFlight) {
      return;
    }
    this.refreshInFlight = true;

    try {
      const [systemStatus, history] = await Promise.all([
        this.api.getSystemStatus(),
        this.api.getNetworkHistory(),
      ]);

      this.interfaceEl.textContent = systemStatus.interface || "-";
      this.taskTextEl.textContent = systemStatus.task.busy ? "执行中" : "空闲";
      this.updatedAtEl.textContent = formatTime(systemStatus.server_time);
      this.uploadValueEl.textContent = systemStatus.network.upload_kbps.toFixed(2);
      this.downloadValueEl.textContent = systemStatus.network.download_kbps.toFixed(2);
      this.#renderGauge(systemStatus.network);
      this.#renderHistory(history.samples || []);
      this.setBackendBadge("后端已连接", "success");
    } catch (error) {
      console.error("Failed to refresh home page", error);
      this.setBackendBadge("后端不可达", "danger");
      this.notify(`首页数据刷新失败: ${error.message}`, "danger");
    } finally {
      this.refreshInFlight = false;
    }
  }

  #renderGauge(network) {
    const maxValue = Math.max(120, Math.ceil(Math.max(network.upload_kbps, network.download_kbps) * 1.6));

    this.gaugeChart.setOption({
      animationDuration: 300,
      tooltip: { formatter: "{a}<br/>{b}: {c} KB/s" },
      series: [
        {
          type: "gauge",
          center: ["30%", "56%"],
          radius: "74%",
          min: 0,
          max: maxValue,
          axisLine: { lineStyle: { width: 14, color: [[1, "#cfdce5"]] } },
          progress: { show: true, width: 14, itemStyle: { color: "#587b92" } },
          pointer: { length: "55%", width: 5, itemStyle: { color: "#4b6579" } },
          splitLine: { distance: -16, length: 10, lineStyle: { color: "#9fb4c4" } },
          axisTick: { show: false },
          axisLabel: { color: "#718592" },
          detail: {
            formatter: "{value} KB/s",
            color: "#233340",
            fontSize: 16,
            offsetCenter: [0, "62%"],
          },
          title: { offsetCenter: [0, "82%"], color: "#607583" },
          data: [{ value: Number(network.upload_kbps.toFixed(2)), name: "上行" }],
        },
        {
          type: "gauge",
          center: ["72%", "56%"],
          radius: "74%",
          min: 0,
          max: maxValue,
          axisLine: { lineStyle: { width: 14, color: [[1, "#dbe5eb"]] } },
          progress: { show: true, width: 14, itemStyle: { color: "#7ea1b6" } },
          pointer: { length: "55%", width: 5, itemStyle: { color: "#607f94" } },
          splitLine: { distance: -16, length: 10, lineStyle: { color: "#adc0cd" } },
          axisTick: { show: false },
          axisLabel: { color: "#718592" },
          detail: {
            formatter: "{value} KB/s",
            color: "#233340",
            fontSize: 16,
            offsetCenter: [0, "62%"],
          },
          title: { offsetCenter: [0, "82%"], color: "#607583" },
          data: [{ value: Number(network.download_kbps.toFixed(2)), name: "下行" }],
        },
      ],
    });
  }

  #renderHistory(samples) {
    const xAxis = samples.map((sample) => formatTime(sample.timestamp));
    const upload = samples.map((sample) => sample.upload_kbps);
    const download = samples.map((sample) => sample.download_kbps);

    this.historyChart.setOption({
      animationDuration: 300,
      tooltip: { trigger: "axis" },
      legend: { top: 4, textStyle: { color: "#607583" } },
      grid: { top: 44, left: 46, right: 20, bottom: 30 },
      xAxis: {
        type: "category",
        data: xAxis,
        boundaryGap: false,
        axisLabel: { color: "#718592", interval: Math.max(0, Math.floor(samples.length / 6)) },
        axisLine: { lineStyle: { color: "#cad7df" } },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: "#718592" },
        splitLine: { lineStyle: { color: "rgba(119, 145, 162, 0.14)" } },
      },
      series: [
        {
          name: "上行",
          type: "line",
          smooth: true,
          data: upload,
          symbol: "none",
          lineStyle: { width: 3, color: "#55788f" },
          areaStyle: { color: "rgba(85, 120, 143, 0.12)" },
        },
        {
          name: "下行",
          type: "line",
          smooth: true,
          data: download,
          symbol: "none",
          lineStyle: { width: 3, color: "#86a7bb" },
          areaStyle: { color: "rgba(134, 167, 187, 0.12)" },
        },
      ],
    });
  }

  #startRtt() {
    this.#stopRtt();

    this.rttSocket = new ManagedSocket({
      getUrl: () => createSocketUrl(this.baseWsUrl, "/ws/rtt"),
      onOpen: () => {
        setPill(this.rttStatusEl, "WS 已连接", "success");
        this.pingTimer = window.setInterval(() => this.#sendPing(), 1000);
        this.#sendPing();
      },
      onMessage: (event) => {
        const payload = JSON.parse(event.data);
        const rtt = Date.now() - Number(payload.client_ts || Date.now());
        this.rttValueEl.textContent = String(Math.max(rtt, 0));
      },
      onClose: (_event, willReconnect) => {
        setPill(this.rttStatusEl, willReconnect ? "RTT 重连中" : "WS 已断开", willReconnect ? "warning" : "danger");
      },
      onError: () => {
        setPill(this.rttStatusEl, "WS 异常", "danger");
      },
    });

    this.rttSocket.restart();
  }

  #stopRtt() {
    window.clearInterval(this.pingTimer);
    this.pingTimer = null;
    if (this.rttSocket) {
      this.rttSocket.close();
      this.rttSocket = null;
    }
    setPill(this.rttStatusEl, "WS 未连接", "info");
  }

  #sendPing() {
    if (!this.rttSocket || !this.rttSocket.isOpen()) {
      return;
    }
    this.rttSocket.sendJson({
      type: "ping",
      client_ts: Date.now(),
    });
  }
}
