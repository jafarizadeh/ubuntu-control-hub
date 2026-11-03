"use strict";

const METRICS = [
  ["cpu_temp", "CPU temperature"],
  ["gpu_temp", "GPU temperature"],
  ["memory", "Available memory"],
  ["disk", "Free storage"],
  ["fans", "Cooling fans"],
  ["uptime", "Uptime"],
  ["gpu_memory", "GPU memory"],
  ["network", "Network"],
  ["audio", "System audio"],
  ["performance", "CPUWM profile"],
];
const DEFAULT_METRICS = ["cpu_temp", "gpu_temp", "memory", "disk", "fans", "uptime"];
const STORAGE_KEY = "ubuntu-control.dashboard.metrics.v1";

const app = {
  session: null, busy: false, timer: null, toastTimer: null,
  tab: "dashboard", lastStatus: null, visibleMetrics: loadMetrics(),
  canControl: false, commandBusy: false,
};

const el = (id) => document.getElementById(id);
const put = (id, value) => { const node = el(id); if (node) node.textContent = String(value); };
const fmt = (value, maximumFractionDigits = 1) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—" : Number(value).toLocaleString("en-US", {maximumFractionDigits});
const numeric = (value, suffix = "", decimals = 1) =>
  value === null || value === undefined || !Number.isFinite(Number(value))
    ? "—" : fmt(value, decimals) + suffix;

function duration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "—";
  const value = Math.max(0, Number(seconds));
  if (value >= 86400) return fmt(Math.floor(value / 86400), 0) + "d " + fmt(Math.floor(value % 86400 / 3600), 0) + "h";
  if (value >= 3600) return fmt(Math.floor(value / 3600), 0) + "h " + fmt(Math.floor(value % 3600 / 60), 0) + "m";
  return fmt(Math.floor(value / 60), 0) + " min";
}

function loadMetrics() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(stored)) {
      const known = new Set(METRICS.map(([key]) => key));
      const safe = stored.filter((x) => typeof x === "string" && known.has(x));
      if (safe.length) return new Set(safe);
    }
  } catch {}
  return new Set(DEFAULT_METRICS);
}

function saveMetrics() {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...app.visibleMetrics])); }
  catch { toast("These preferences cannot be saved by this browser.", true); }
}

function applyMetricVisibility() {
  document.querySelectorAll("[data-metric]").forEach((card) => {
    card.hidden = !app.visibleMetrics.has(card.dataset.metric);
  });
  document.querySelectorAll("#metric-options input").forEach((input) => {
    input.checked = app.visibleMetrics.has(input.value);
  });
}

function initCustomization() {
  const choices = el("metric-options");
  for (const [key, label] of METRICS) {
    const wrapper = document.createElement("label");
    wrapper.className = "metric-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = key;
    input.checked = app.visibleMetrics.has(key);
    input.addEventListener("change", () => {
      if (input.checked) app.visibleMetrics.add(key);
      else app.visibleMetrics.delete(key);
      if (!app.visibleMetrics.size) {
        app.visibleMetrics.add(key);
        input.checked = true;
        toast("Keep at least one metric visible.", true);
      }
      saveMetrics();
      applyMetricVisibility();
    });
    wrapper.append(input, document.createTextNode(label));
    choices.append(wrapper);
  }
  const toggle = el("customize-btn");
  toggle.addEventListener("click", () => {
    const panel = el("customize-panel");
    panel.hidden = !panel.hidden;
    toggle.setAttribute("aria-expanded", String(!panel.hidden));
    toggle.textContent = panel.hidden ? "Customize" : "Done";
  });
  el("reset-metrics").addEventListener("click", () => {
    app.visibleMetrics = new Set(DEFAULT_METRICS);
    saveMetrics();
    applyMetricVisibility();
    toast("Default metrics restored.");
  });
  applyMetricVisibility();
}

function toast(message, error = false) {
  const node = el("toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.add("visible");
  if (app.toastTimer) clearTimeout(app.toastTimer);
  app.toastTimer = setTimeout(() => node.classList.remove("visible"), 4700);
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", credentials: "same-origin", ...options});
  let result = null;
  try { result = await response.json(); }
  catch { result = {error: "The server response could not be read."}; }
  if (!response.ok) throw new Error(result.error || "Request failed.");
  return result;
}

function setTag(id, value, online) {
  const tag = el(id);
  tag.textContent = value;
  tag.classList.toggle("online", Boolean(online));
  tag.classList.toggle("offline", !online);
}

function setConnectionState(kind) {
  const pill = el("hub-state");
  pill.classList.toggle("live", kind === "online");
  pill.classList.toggle("offline", kind !== "online");
  put("hub-label", kind === "online" ? "Ubuntu Online" :
    kind === "agent-offline" ? "Ubuntu Offline" : "Hub Offline");
}

function paintWithoutUbuntu() {
  const empty = ["hero-cpu", "hero-memory", "hero-gpu", "metric-cpu-temp", "metric-gpu-temp",
    "metric-memory", "metric-disk", "metric-fans", "metric-uptime", "metric-gpu-memory",
    "metric-network", "metric-audio", "metric-performance", "control-volume", "control-profile"];
  empty.forEach((id) => put(id, "—"));
  put("hero-cpu-model", "No fresh Ubuntu readings");
  put("hero-memory-detail", "—");
  put("hero-gpu-detail", "—");
  put("metric-memory-detail", "RAM available");
  put("metric-disk-detail", "System disk");
  put("metric-fans-detail", "Fan speeds");
  put("metric-network-detail", "Connection status");
  put("metric-audio-detail", "Default output volume");
  put("desktop-hostname", "Ubuntu Desktop");
  put("desktop-subtitle", "Ubuntu telemetry is unavailable");
  put("connection-summary", "Signed Ubuntu agent disconnected");
  put("uptime-summary", "Uptime —");
  put("network-count", "—");
  el("network-items").replaceChildren();
  const hint = document.createElement("span");
  hint.textContent = "No network details";
  el("network-items").append(hint);
  put("audio-capability", "Unavailable");
  put("network-capability", "Unavailable");
  put("performance-capability", "Unavailable");
  el("performance-capability").classList.remove("online");
  el("profile-selector").value = "balanced";
  el("data-freshness").classList.remove("online");
  put("data-freshness", "No live data");
  const footer = document.querySelector(".overview-footer");
  footer.classList.remove("online");
}

function paintUbuntu(report) {
  const cpu = report.cpu || {};
  const mem = report.memory || {};
  const disk = report.storage || {};
  const gpus = Array.isArray(report.gpus) ? report.gpus : [];
  const gpu = gpus[0] || {};
  const fans = Array.isArray(report.fans) ? report.fans : [];
  const network = report.network || {};
  const audio = report.audio || {};
  const manager = report.workload_manager || {};
  const memUsed = Number.isFinite(Number(mem.total_mib)) && Number.isFinite(Number(mem.available_mib))
    ? Math.max(0, Number(mem.total_mib) - Number(mem.available_mib)) : null;

  put("desktop-subtitle", [report.os, cpu.logical_cores ? cpu.logical_cores + " logical CPUs" : null]
    .filter(Boolean).join(" · ") || "Ubuntu workstation");
  put("desktop-hostname", report.hostname || "Ubuntu Desktop");
  put("hero-cpu", numeric(cpu.usage_percent, "%"));
  put("hero-cpu-model", cpu.model || "Live CPU utilization");
  put("hero-memory", numeric(mem.used_percent, "%"));
  put("hero-memory-detail", memUsed === null ? "RAM usage" :
    fmt(memUsed / 1024) + " / " + fmt(mem.total_mib / 1024) + " GiB used (estimated)");
  put("hero-gpu", numeric(gpu.usage_percent, "%"));
  put("hero-gpu-detail", gpu.name || "Graphics processor");
  put("metric-cpu-temp", numeric(cpu.temperature_c, "°C"));
  put("metric-gpu-temp", numeric(gpu.temperature_c, "°C"));
  put("metric-memory", numeric(mem.available_mib == null ? null : mem.available_mib / 1024, " GiB"));
  put("metric-memory-detail", mem.total_mib == null ? "RAM available" : fmt(mem.total_mib / 1024) + " GiB total");
  put("metric-disk", numeric(disk.free_gib, " GiB"));
  put("metric-disk-detail", disk.total_gib == null ? "System disk" : fmt(disk.total_gib) + " GiB total");
  put("metric-fans", fans.length ? fmt(fans.length, 0) + (fans.length === 1 ? " fan" : " fans") : "—");
  put("metric-fans-detail", fans.length
    ? fans.slice(0, 2).map((fan) => numeric(fan.rpm, " RPM", 0)).join(" · ") : "No sensor reported");
  put("metric-uptime", duration(report.uptime_s));
  put("metric-gpu-memory", gpu.memory_used_mib == null ? "—" :
    numeric(gpu.memory_used_mib / 1024, " GiB"));
  const connections = Array.isArray(network.connections) ? network.connections : [];
  put("metric-network", network.available ? network.connected ? "Connected" : "Offline" : "—");
  put("metric-network-detail", connections.length
    ? connections.map((c) => c.type === "wifi" ? "Wi-Fi" : "Ethernet").join(" + ") : "No active physical interface");
  put("metric-audio", audio.available ? audio.muted ? "Muted" : numeric(audio.volume_percent, "%", 0) : "—");
  put("metric-audio-detail", audio.available ? "Default audio output" : "No audio sink reported");
  put("metric-performance", manager.available && manager.profile ?
    manager.profile.charAt(0).toUpperCase() + manager.profile.slice(1) : "—");
  put("uptime-summary", "Uptime " + duration(report.uptime_s));
  put("connection-summary", "Signed Ubuntu telemetry · live");
  put("data-freshness", "Live data");
  el("data-freshness").classList.add("online");
  document.querySelector(".overview-footer").classList.add("online");

  put("control-volume", audio.available
    ? audio.muted ? numeric(audio.volume_percent, "%", 0) + " · muted" : numeric(audio.volume_percent, "%", 0)
    : "Unavailable");
  el("volume-slider").value = audio.available ? String(audio.volume_percent || 0) : "0";
  put("audio-capability", audio.available ? "Monitoring" : "Unavailable");
  put("network-count", network.available ? fmt(connections.length, 0) + " active" : "Unavailable");
  put("network-capability", network.available ? "Monitoring" : "Unavailable");
  const networkList = el("network-items");
  networkList.replaceChildren();
  if (connections.length) {
    for (const connection of connections) {
      const chip = document.createElement("span");
      chip.textContent = (connection.type === "wifi" ? "Wi-Fi" : "Ethernet")
        + (connection.connection ? " · " + connection.connection : "");
      networkList.append(chip);
    }
  } else {
    const chip = document.createElement("span");
    chip.textContent = "No active physical interface";
    networkList.append(chip);
  }
  put("control-profile", manager.available
    ? manager.profile.charAt(0).toUpperCase() + manager.profile.slice(1) : "Unavailable");
  put("performance-capability", manager.available ? "Connected" : "Unavailable");
  el("performance-capability").classList.toggle("online", Boolean(manager.available));
  if (["quiet", "balanced", "performance"].includes(manager.profile)) {
    el("profile-selector").value = manager.profile;
  }
}

function renderStatus(data) {
  app.lastStatus = data;
  const desktop = data.desktop || {};
  const tv = data.tv || {};
  const age = Date.now() / 1000 - Number(desktop.last_agent_report_unix || 0);
  const fresh = desktop.control_agent === "online" && desktop.metrics && age >= -15 && age < 45;
  if (fresh) {
    paintUbuntu(desktop.metrics);
    setConnectionState("online");
    setTag("desktop-state", "Online", true);
    put("desktop-agent-state", "Ubuntu agent connected");
    put("updated-at", "Updated " + new Date(
      (desktop.metrics.checked_at_unix || desktop.last_agent_report_unix) * 1000
    ).toLocaleTimeString("en-GB", {hour: "2-digit", minute: "2-digit"}));
  } else {
    paintWithoutUbuntu();
    setConnectionState("agent-offline");
    setTag("desktop-state", desktop.ping_reachable ? "Agent offline" : "Offline", false);
    put("desktop-agent-state", desktop.ping_reachable ?
      "Network reachable · no fresh Ubuntu data" : "Ubuntu is not responding");
    put("updated-at", "No recent telemetry");
  }
  const tvReachable = Boolean(tv.ping_reachable && tv.webos_api_reachable);
  put("ubuntu-power-status", fresh ? "Online · signed telemetry" :
    desktop.ping_reachable ? "Network reachable · agent offline" : "Offline / not responding");
  el("desktop-on").disabled = Boolean(fresh);
  put("desktop-power-note", fresh
    ? "Shutdown is not yet connected; protected actions will be added separately."
    : "Wake-on-LAN can send a packet. Shutdown is not yet connected.");
  put("tv-power-status", tvReachable ? "Network reachable · screen state unknown" : "Not reachable");
  el("tv-on").disabled = false;
  el("tv-off").disabled = !(tvReachable && tv.paired);
  put("tv-power-note", tv.paired
    ? "Standby uses paired LG webOS. Confirm device state after sending."
    : "Standby control requires LG webOS pairing.");
  put("tv-control-capability", tv.paired ? "Paired" : "Pairing needed");
  el("tv-control-capability").classList.toggle("online", Boolean(tv.paired));
  el("pair-tv-btn").hidden = Boolean(tv.paired);
  el("pair-tv-btn").disabled = !tvReachable;
  el("tv-remote-controls").hidden = !tv.paired;
  document.querySelectorAll("#tv-remote-controls [data-action]").forEach((button) => { button.disabled = !tvReachable || !tv.paired; });
  syncControls();
  put("tv-controls-message", tv.paired
    ? "LG webOS is paired. Volume and standby controls are available."
    : "Turn on the LG display and approve the pairing request on its screen.");
}

async function refreshStatus(manual = false) {
  if (app.busy) return;
  app.busy = true;
  el("refresh-btn").disabled = true;
  try {
    renderStatus(await api("/api/status"));
    if (app.tab === "control") await refreshPowerPreview();
    syncControls();
    if (manual) toast("Ubuntu status refreshed.");
  } catch {
    app.lastStatus = null;
    clearPowerPreview();
    paintWithoutUbuntu();
    setConnectionState("hub-offline");
    setTag("desktop-state", "Not connected", false);
    put("desktop-agent-state", "Cannot reach the private Raspberry Pi Hub");
    put("updated-at", "Connection unavailable");
    put("ubuntu-power-status", "Connection unavailable");
    put("tv-power-status", "Connection unavailable");
    el("desktop-on").disabled = true;
    el("tv-on").disabled = true;
    el("tv-off").disabled = true;
    el("pair-tv-btn").disabled = true;
    document.querySelectorAll("#tv-remote-controls [data-action]").forEach((button) => { button.disabled = true; });
    syncControls();
    if (manual) toast("Cannot reach the private Hub. Check Tailscale.", true);
  } finally {
    app.busy = false;
    el("refresh-btn").disabled = false;
  }
}

function switchTab(tab) {
  if (!["dashboard", "control", "history"].includes(tab)) return;
  app.tab = tab;
  for (const key of ["dashboard", "control", "history"]) el("view-" + key).hidden = key !== tab;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const selected = button.dataset.tab === tab;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-current", selected ? "page" : "false");
  });
  window.scrollTo({top: 0, behavior: "instant"});
  if (tab === "history") loadHistory();
  if (tab === "control") void refreshControlAccess();
}

async function executeAction(name, button) {
  const actions = {
    "wake-desktop": {path: "/api/wake", payload: {target: "desktop"}, label: "Ubuntu wake request"},
    "wake-tv": {path: "/api/wake", payload: {target: "tv"}, label: "LG wake request"},
    "tv-power-off": {path: "/api/tv/control", payload: {action: "power_off"}, label: "LG standby request"},
    "pair-tv": {path: "/api/tv/pair", payload: {}, label: "LG pairing"},
    "tv-volume-up": {path: "/api/tv/control", payload: {action: "volume_up"}, label: "TV volume up"},
    "tv-volume-down": {path: "/api/tv/control", payload: {action: "volume_down"}, label: "TV volume down"},
    "tv-mute": {path: "/api/tv/control", payload: {action: "mute"}, label: "TV mute"},
    "tv-unmute": {path: "/api/tv/control", payload: {action: "unmute"}, label: "TV unmute"},
  };
  const action = actions[name];
  if (!action || button.disabled) return;
  if (name === "tv-power-off" && !window.confirm("Put the LG display into standby?")) return;
  if (name === "wake-desktop" && !window.confirm("Send a Wake-on-LAN packet to Ubuntu Desktop?")) return;
  if (name === "pair-tv" && !window.confirm(
    "Turn on the LG display. Approve the connection prompt on the TV after continuing."
  )) return;

  button.disabled = true;
  try {
    if (!app.session) app.session = await api("/api/session");
    await api(action.path, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-UC-CSRF": app.session.csrf},
      body: JSON.stringify(action.payload),
    });
    toast(action.label + " sent. Confirm the actual device result.");
    setTimeout(() => refreshStatus(), 2500);
  } catch (err) {
    toast("Request failed: " + err.message, true);
  } finally {
    button.disabled = false;
    if (app.lastStatus) renderStatus(app.lastStatus);
  }
}

async function loadHistory() {
  const list = el("events-list");
  try {
    const result = await api("/api/history");
    list.replaceChildren();
    if (!Array.isArray(result.events) || !result.events.length) {
      const message = document.createElement("p");
      message.className = "empty";
      message.textContent = "No commands have been sent yet.";
      list.append(message);
      return;
    }
    for (const event of result.events) {
      const row = document.createElement("div");
      row.className = "event";
      const icon = document.createElement("span");
      icon.className = "event-icon";
      icon.textContent = event.action === "wake" ? "⏻" : "◉";
      const description = document.createElement("div");
      description.className = "event-text";
      const label = document.createElement("div");
      label.className = "event-title";
      const names = {
        wake: "Wake-on-LAN", pair: "Device pairing",
        volume_up: "Volume up", volume_down: "Volume down",
        mute: "Mute", unmute: "Unmute", power_off: "Standby",
      };
      label.textContent = (names[event.action] || "Action") +
        " · " + (event.target === "tv" ? "LG Display" : "Ubuntu Desktop");
      const date = document.createElement("div");
      date.className = "event-meta";
      date.textContent = new Date(Number(event.at) * 1000).toLocaleString("en-GB");
      const outcome = document.createElement("span");
      outcome.className = "event-status";
      outcome.textContent = event.result === "packet_sent" ? "Packet sent" :
        event.result === "failed" ? "Failed" : "Submitted";
      description.append(label, date);
      row.append(icon, description, outcome);
      list.append(row);
    }
  } catch {
    list.textContent = "History is temporarily unavailable.";
  }
}

async function init() {
  initCustomization();
  initCommandControls();
  initPowerPreview();
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => executeAction(button.dataset.action, button));
  });
  el("refresh-btn").addEventListener("click", () => refreshStatus(true));
  el("reload-history").addEventListener("click", loadHistory);
  window.addEventListener("online", () => refreshStatus());
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshStatus(); });
  try { app.session = await api("/api/session"); }
  catch { app.session = null; }
  await refreshStatus();
  await refreshControlAccess();
  app.timer = setInterval(() => { if (!document.hidden) refreshStatus(); }, 15000);
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

const CONTROL_STATUS = new Set(["queued", "delivered", "succeeded", "failed", "expired"]);

function commandAuthorizedAndReady() {
  if (!app.canControl || app.commandBusy || !app.lastStatus) return false;
  const desktop = app.lastStatus.desktop || {};
  const age = Date.now() / 1000 - Number(desktop.last_agent_report_unix || 0);
  return desktop.control_agent === "online" && desktop.metrics && age >= -15 && age < 45;
}

function syncControls() {
  const ready = Boolean(commandAuthorizedAndReady());
  const report = app.lastStatus?.desktop?.metrics || {};
  const audioReady = ready && report.audio?.available === true;
  const profileReady = ready && report.workload_manager?.available === true;

  el("volume-slider").disabled = !audioReady;
  el("apply-volume").disabled = !audioReady;
  el("mute-toggle").disabled = !audioReady;
  el("profile-selector").disabled = !profileReady;
  el("apply-profile").disabled = !profileReady;
  put("mute-toggle", report.audio?.muted ? "Unmute" : "Mute");
  put("audio-capability", audioReady ? "Control enabled" : report.audio?.available ? "Monitoring" : "Unavailable");
  put("performance-capability", profileReady ? "Control enabled" : report.workload_manager?.available ? "Monitoring" : "Unavailable");
  el("performance-capability").classList.toggle("online", Boolean(profileReady));
  put("control-access", app.commandBusy ? "Waiting for Ubuntu confirmation…" :
    !app.canControl ? "Changes locked · owner access required" :
    !ready ? "Ubuntu agent offline or unavailable" :
    "Owner verified · secure commands ready");
}

async function refreshControlAccess() {
  try {
    const capability = await api("/api/control/capabilities");
    app.canControl = capability?.can_control === true;
  } catch {
    app.canControl = false;
  }
  syncControls();
  await refreshPowerPreview();
}

function feedback(message, level = "") {
  const pane = el("command-feedback");
  pane.hidden = false;
  pane.classList.toggle("error", level === "error");
  pane.classList.toggle("success", level === "success");
  pane.textContent = message;
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForReceipt(id, label) {
  const createdAt = Date.now();
  while (Date.now() - createdAt < 56000) {
    await delay(1800);
    let result;
    try { result = await api("/api/commands/" + encodeURIComponent(id)); }
    catch (err) { feedback(label + ": receipt unavailable (" + err.message + ").", "error"); return; }
    const state = result?.status;
    if (!CONTROL_STATUS.has(state)) {
      feedback(label + ": unexpected receipt status.", "error");
      return;
    }
    if (state === "succeeded") {
      feedback(label + ": confirmed by Ubuntu.", "success");
      await refreshStatus();
      return;
    }
    if (state === "failed" || state === "expired") {
      feedback(label + ": " + (state === "failed" ? "execution failed." : "request expired without confirmation."), "error");
      return;
    }
    feedback(label + ": " + (state === "queued" ? "waiting for Ubuntu…" : "delivered, awaiting execution result…"));
  }
  feedback(label + ": no confirmed result. Check Ubuntu before trying again.", "error");
}

async function submitCommand(action, value, label, confirmed = false) {
  if (!commandAuthorizedAndReady()) {
    feedback("Remote controls are locked or Ubuntu is unavailable.", "error");
    return;
  }
  app.commandBusy = true;
  syncControls();
  feedback(label + ": requesting authorization…");
  try {
    if (!app.session) app.session = await api("/api/session");
    const payload = {action, value};
    if (action === "cpuwm.set_profile") payload.confirm = confirmed;
    const response = await api("/api/commands", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-UC-CSRF": app.session.csrf},
      body: JSON.stringify(payload),
    });
    if (typeof response?.id !== "string" || response.status !== "queued") {
      throw new Error("The Hub did not return a queued receipt.");
    }
    feedback(label + ": queued on Raspberry Pi; not executed yet.");
    await waitForReceipt(response.id, label);
  } catch (err) {
    feedback(label + ": " + (err?.message || "request failed."), "error");
  } finally {
    app.commandBusy = false;
    syncControls();
  }
}

function initCommandControls() {
  el("volume-slider").addEventListener("input", () => {
    put("control-volume", el("volume-slider").value + "% · not applied");
  });
  el("apply-volume").addEventListener("click", () => {
    const value = Number(el("volume-slider").value);
    if (!Number.isInteger(value) || value < 0 || value > 100) return;
    void submitCommand("audio.set_volume", value, "Ubuntu volume " + value + "%");
  });
  el("mute-toggle").addEventListener("click", () => {
    const audio = app.lastStatus?.desktop?.metrics?.audio;
    if (!audio || !audio.available) return;
    const mute = !Boolean(audio.muted);
    void submitCommand("audio.set_mute", mute, mute ? "Mute Ubuntu audio" : "Unmute Ubuntu audio");
  });
  el("apply-profile").addEventListener("click", () => {
    const profile = el("profile-selector").value;
    if (!["quiet", "balanced", "performance"].includes(profile)) return;
    if (!window.confirm("Change CPU & GPU Workload Manager to " + profile +
      "? This may affect running workloads and the thermal/resource budget.")) return;
    void submitCommand("cpuwm.set_profile", profile, "CPUWM " + profile, true);
  });
}


document.addEventListener("DOMContentLoaded", init);


let previewBusy = false;
let previewState = null;

function syncPreviewControls() {
  el("power-preview-create").disabled = !app.canControl || previewBusy || previewState === "draft";
  el("power-preview-cancel").disabled = !app.canControl || previewBusy || previewState !== "draft";
}

function clearPowerPreview() {
  previewState = null;
  put("power-safety-status", "Safety data unavailable — power actions blocked");
  el("power-safety-details").replaceChildren();
  put("power-preview-status", "Preview unavailable — refresh to check server state");
  syncPreviewControls();
}

function paintPowerPreview(data) {
  if (data.preview_only !== true || data.will_execute !== false) throw new Error("Invalid preview response");
  previewState = data.state;
  const safety = data.safety || {};
  put("power-safety-status", "Blocked: no power action will be performed. Safety: " + (safety.status || "unknown"));
  const list = el("power-safety-details");
  list.replaceChildren();
  for (const text of [...(safety.blocked_reasons || []), ...(safety.warnings || [])]) {
    const item = document.createElement("li");
    item.textContent = text;
    list.append(item);
  }
  put("power-preview-status", "Simulation: " + data.state + (data.action ? " · " + data.action : "")
    + " · " + data.remaining_seconds + " seconds remaining (server reading at "
    + new Date(data.server_time * 1000).toLocaleTimeString("en-GB") + ")");
  syncPreviewControls();
}

async function refreshPowerPreview() {
  if (previewBusy) return;
  if (!app.canControl) { clearPowerPreview(); return; }
  try { paintPowerPreview(await api("/api/power/preview")); }
  catch { clearPowerPreview(); }
}

async function changePowerPreview(cancel) {
  if (previewBusy || !app.canControl) return;
  const value = el("power-preview-delay").value;
  if (!cancel && (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 240)) {
    toast("Choose an integer delay from 1 to 240 minutes.", true);
    return;
  }
  previewBusy = true;
  syncPreviewControls();
  try {
    if (!app.session) app.session = await api("/api/session");
    paintPowerPreview(await api(cancel ? "/api/power/cancel" : "/api/power/preview", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-UC-CSRF": app.session.csrf},
      body: JSON.stringify(cancel ? {} : {action: el("power-preview-action").value, delay_minutes: Number(value)}),
    }));
  } catch (error) {
    clearPowerPreview();
    toast(error.message, true);
  } finally {
    previewBusy = false;
    await refreshPowerPreview();
  }
}

function initPowerPreview() {
  el("power-preview-create").addEventListener("click", () => changePowerPreview(false));
  el("power-preview-cancel").addEventListener("click", () => changePowerPreview(true));
}
