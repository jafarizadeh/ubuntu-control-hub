"use strict";

const app = {
  session: null,
  timer: null,
  busy: false,
  tab: "dashboard",
  toastTimeout: null,
  lastStatus: null,
};

const el = (id) => document.getElementById(id);
const text = (id, content) => { const node = el(id); if (node) node.textContent = content; };
const fmt = (value) => (value !== null && value !== undefined && Number.isFinite(Number(value))) ? Number(value).toLocaleString("en-US") : "—";
const shortTime = (seconds) => {
  const h = Math.floor(Number(seconds || 0) / 3600);
  const d = Math.floor(h / 24);
  return d ? fmt(d) + (d === 1 ? " day" : " days") : h ? fmt(h) + (h === 1 ? " hour" : " hours") : fmt(Math.floor(Number(seconds || 0) / 60)) + " minutes";
};

function toast(message, error = false) {
  const node = el("toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("visible");
  if (app.toastTimeout) clearTimeout(app.toastTimeout);
  app.toastTimeout = setTimeout(() => node.classList.remove("visible"), 4800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
  });
  let result = null;
  try { result = await response.json(); }
  catch { result = {error: "Could not read the server response."}; }
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

function setDeviceStatus(id, available) {
  const node = el(id);
  node.textContent = available ? "Reachable" : "No response";
  node.classList.toggle("online", Boolean(available));
  node.classList.toggle("offline", !available);
}

function setHubStatus(ok) {
  el("hub-state").classList.toggle("live", Boolean(ok));
  el("hub-state").classList.toggle("offline", !ok);
  text("hub-label", ok ? "Hub Online" : "Hub Offline");
  text("pi-state", ok ? "Online" : "Offline");
  el("pi-state").classList.toggle("offline", !ok);
  el("pi-state").classList.toggle("online", Boolean(ok));
}

async function refreshStatus(manual = false) {
  if (app.busy) return;
  app.busy = true;
  const button = el("refresh-btn");
  button.disabled = true;
  try {
    const data = await api("/api/status");
    app.lastStatus = data;
    setHubStatus(true);
    const controller = data.controller || {};
    const desktop = data.desktop || {};
    const tv = data.tv || {};
    text("pi-ethernet-ip", controller.ethernet_ip || "—");
    text("desktop-ip", desktop.ip || "—");
    text("tv-ip", tv.ip || "—");
    text("tv-model", (tv.model || "webOS") + " · Wi-Fi");
    text("pi-temperature", controller.temperature_c == null ? "—" : fmt(controller.temperature_c));
    text("pi-memory", fmt(controller.memory?.available_mib));
    text("pi-disk", fmt(controller.storage?.free_gib));
    text("pi-uptime", shortTime(controller.uptime_s));
    text("pi-sub", "Raspberry Pi OS Lite · " + String(controller.hostname || "RPI"));
    const ts = String(controller.tailscale_state || "Unknown");
    text("ts-state", ts === "Running" ? "Connected" : ts === "NeedsLogin" ? "Sign-in required" : ts);
    setDeviceStatus("desktop-state", desktop.ping_reachable);
    const agentReady = desktop.control_agent === "online" && desktop.metrics;
    const report = agentReady ? desktop.metrics : {};
    text("desktop-agent-state", agentReady ? "Read-only agent connected"
      : desktop.control_agent === "unavailable" ? "Desktop agent unavailable" : "Desktop agent not configured");
    el("desktop-telemetry").hidden = !agentReady;
    if (agentReady) {
      text("desktop-cpu", report.cpu?.usage_percent == null ? "—" : fmt(report.cpu.usage_percent) + "%");
      text("desktop-temperature", report.cpu?.temperature_c == null ? "—" : fmt(report.cpu.temperature_c) + "°C");
      text("desktop-memory", report.memory?.available_mib == null ? "—" : fmt(report.memory.available_mib) + " MiB");
      text("desktop-disk", report.storage?.free_gib == null ? "—" : fmt(report.storage.free_gib) + " GiB");
      const gpu = Array.isArray(report.gpus) ? report.gpus[0] : null;
      text("desktop-gpu", gpu && gpu.usage_percent != null
        ? fmt(gpu.usage_percent) + "%" + (gpu.temperature_c == null ? "" : " · " + fmt(gpu.temperature_c) + "°C")
        : "Not available");
      const fans = Array.isArray(report.fans) ? report.fans : [];
      text("desktop-fans", fans.length
        ? fans.slice(0, 2).map(item => fmt(item.rpm) + " RPM").join(" · ")
        : "Not available");
    }
    setDeviceStatus("tv-state", tv.ping_reachable && tv.webos_api_reachable);
    text("tv-pairing", tv.paired ? "webOS paired" : "Pairing required");
    text("tv-controls-message", tv.paired
      ? "Connected via a paired webOS session"
      : "Volume and standby controls become available after approving the pairing request on the TV.");
    el("tv-remote-controls").hidden = !tv.paired;
    el("pair-tv-btn").hidden = Boolean(tv.paired);
    const checked = data.checked_at_unix ? new Date(data.checked_at_unix * 1000) : new Date();
    text("updated-at", "Updated " + checked.toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit"}));
    if (manual) toast("Device status updated.");
  } catch (error) {
    setHubStatus(false);
    if (manual) toast("Cannot reach Raspberry Pi.", true);
  } finally {
    app.busy = false;
    button.disabled = false;
  }
}

async function loadHistory() {
  const list = el("events-list");
  try {
    const result = await api("/api/history");
    list.replaceChildren();
    if (!Array.isArray(result.events) || !result.events.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No commands have been sent from the app yet.";
      list.append(empty);
      return;
    }
    for (const event of result.events) {
      const wrapper = document.createElement("div");
      wrapper.className = "event";
      const icon = document.createElement("span");
      icon.className = "event-icon";
      icon.textContent = event.action === "wake" ? "⏻" : "◉";
      const block = document.createElement("div");
      block.className = "event-text";
      const title = document.createElement("div");
      title.className = "event-title";
      const names = {
        wake: "Wake command sent",
        volume_up: "Increase volume",
        volume_down: "Decrease volume",
        mute: "Mute",
        unmute: "Unmute",
        power_off: "Put TV in standby"
      };
      const target = event.target === "tv" ? "LG" : "Ubuntu";
      title.textContent = (names[event.action] || "Action") + " · " + target;
      const date = document.createElement("div");
      date.className = "event-meta";
      date.textContent = new Date(Number(event.at) * 1000).toLocaleString("en-GB");
      const status = document.createElement("span");
      status.className = "event-status";
      status.textContent = event.result === "failed" ? "Failed" : event.result === "packet_sent" ? "Sent" : "Completed";
      block.append(title, date);
      wrapper.append(icon, block, status);
      list.append(wrapper);
    }
  } catch (error) {
    list.textContent = "History is temporarily unavailable.";
  }
}

function switchTab(next) {
  if (!["dashboard", "control", "history"].includes(next)) return;
  app.tab = next;
  for (const name of ["dashboard", "control", "history"]) {
    el("view-" + name).hidden = next !== name;
  }
  for (const button of document.querySelectorAll("[data-tab]")) {
    const active = button.dataset.tab === next;
    button.classList.toggle("selected", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  }
  window.scrollTo({top: 0, behavior: "instant"});
  if (next === "history") loadHistory();
}

async function executeAction(name, button) {
  const actions = {
    "wake-desktop": {path: "/api/wake", payload: {target: "desktop"}, label: "Wake Ubuntu Desktop"},
    "wake-tv": {path: "/api/wake", payload: {target: "tv"}, label: "Wake LG TV"},
    "pair-tv": {path: "/api/tv/pair", payload: {}, label: "Pair LG TV"},
    "tv-volume-up": {path: "/api/tv/control", payload: {action: "volume_up"}, label: "Increase volume"},
    "tv-volume-down": {path: "/api/tv/control", payload: {action: "volume_down"}, label: "Decrease volume"},
    "tv-mute": {path: "/api/tv/control", payload: {action: "mute"}, label: "Mute"},
    "tv-unmute": {path: "/api/tv/control", payload: {action: "unmute"}, label: "Unmute"},
    "tv-power-off": {path: "/api/tv/control", payload: {action: "power_off"}, label: "Put LG TV in standby"}
  };
  const action = actions[name];
  if (!action) return;
  if (name === "tv-power-off" && !window.confirm("Put the LG TV in standby?")) return;
  if (name === "pair-tv" && !window.confirm("Turn on the LG TV. After continuing, approve the pairing request on the TV screen.")) return;
  button.disabled = true;
  if (name === "pair-tv") toast("Pairing LG TV… Approve the connection request on the TV.");
  try {
    if (!app.session) app.session = await api("/api/session");
    await api(action.path, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-UC-CSRF": app.session.csrf},
      body: JSON.stringify(action.payload),
    });
    toast(action.label + ": request submitted. Check the device status for confirmation.");
    setTimeout(() => refreshStatus(), 3000);
  } catch (error) {
    toast("Error: " + error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function init() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action, button));
  });
  el("refresh-btn").addEventListener("click", () => refreshStatus(true));
  el("reload-history").addEventListener("click", loadHistory);
  window.addEventListener("online", () => refreshStatus());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshStatus();
  });
  try { app.session = await api("/api/session"); }
  catch { app.session = null; }
  await refreshStatus();
  app.timer = setInterval(() => {
    if (!document.hidden) refreshStatus();
  }, 15000);
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}
document.addEventListener("DOMContentLoaded", init);
