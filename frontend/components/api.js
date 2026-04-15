export function createApi(baseUrl) {
  async function request(path, options = {}) {
    const response = await fetch(`${baseUrl}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();

    if (!response.ok) {
      const message = typeof payload === "string" ? payload : payload.detail || payload.message || "Request failed";
      throw new Error(message);
    }

    return payload;
  }

  return {
    getSystemStatus: () => request("/api/system/status"),
    getRobots: () => request("/api/robots"),
    getTeleopRobots: () => request("/api/robots/teleop"),
    getRobotCapabilities: () => request("/api/robots/capabilities"),
    getNetworkStats: () => request("/api/network/stats"),
    getNetworkHistory: () => request("/api/network/history"),
    getTaskStatus: () => request("/api/task/status"),
    sendTask: (payload) =>
      request("/api/task/send", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    clearTask: () =>
      request("/api/task/clear", {
        method: "POST",
        body: JSON.stringify({}),
      }),
    getVideoSources: () => request("/api/video/sources"),
    getPointcloudSources: () => request("/api/pointcloud/sources"),
    getOdomSources: () => request("/api/odom/sources"),
  };
}
