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
  cpuWatchTimer: null, cpuWatchBusy: false, cpuFastActive: false, cpuWatchFailures: 0,
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
  window.UbuntuIOS.notify(message, error);
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
  window.UbuntuCPU.stale();
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
  el("network-control-icon").src = "/assets/wifi-off.svg";
  put("performance-capability", "Unavailable");
  el("performance-capability").classList.remove("online");
  window.UbuntuIOS.setProfile("balanced", false);
  el("data-freshness").classList.remove("online");
  put("data-freshness", "No live data");
  const footer = document.querySelector(".overview-footer");
  footer.classList.remove("online");
}

function paintUbuntu(report) {
  const cpu = report.cpu || {};
  window.UbuntuCPU.update(report);
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
  el("network-control-icon").src = network.available && network.connected
    ? "/assets/wifi.svg" : "/assets/wifi-off.svg";
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
    if (!window.UbuntuIOS.profileDirty()) {
      window.UbuntuIOS.setProfile(manager.profile, false);
    } else if (el("profile-selector").value === manager.profile) {
      window.UbuntuIOS.markProfileSynced();
    }
  }
}

/**
 * A single power action is shown for each device. "Reachable" never means
 * the LG screen is on, and a missing Ubuntu heartbeat never proves power off.
 */
function setPowerCard(device, model) {
  const name = device === "desktop" ? "Ubuntu Desktop" : "LG Display";
  const state = model.state === "on" ? "on" : model.state === "off" ? "off" : "unknown";
  const card = el(device + "-power-card");
  const badge = el(device + "-power-badge");
  const symbol = el(device + "-power-symbol");
  const button = el(device + "-power-button");
  const label = model.label;
  card.dataset.powerState = state;
  symbol.classList.toggle("is-unknown", state === "unknown");
  symbol.classList.toggle("is-off", state === "off");
  symbol.classList.toggle("is-on", state === "on");
  const filename = device === "desktop" ? "ubuntu" : "monitor";
  el(device + "-power-icon").src = "/assets/" + filename + "-" + (state === "on" ? "on" : "off") + ".svg";
  badge.textContent = model.badge;
  badge.className = "power-state-chip is-" + state;
  put(device === "desktop" ? "ubuntu-power-status" : "tv-power-status", model.detail);
  put(device + "-power-label", label);
  put(device + "-power-note", model.note);
  button.dataset.action = model.action || "";
  button.disabled = !model.action;
  button.className = "btn power-toggle " + (model.action ? (model.action === "tv-power-off" ? "is-standby" : "is-wake") : "is-locked");
  button.title = model.note;
  button.setAttribute("aria-label", name + ": " + label + ". " + model.badge);
}

function renderPowerUnavailable() {
  setPowerCard("desktop", {
    state: "unknown", badge: "Unknown", detail: "Hub connection unavailable",
    label: "Power unavailable", action: null,
    note: "Connect to the private Raspberry Pi Hub to refresh Ubuntu power status.",
  });
  setPowerCard("tv", {
    state: "unknown", badge: "Unknown", detail: "Hub connection unavailable",
    label: "Power unavailable", action: null,
    note: "Connect to the private Raspberry Pi Hub to refresh LG power status.",
  });
}

function renderDevicePower(desktop, tv, ubuntuFresh) {
  if (ubuntuFresh) {
    const realReady=desktop.metrics?.power_safety?.real_power?.eligible === true;
    setPowerCard("desktop", {
      state: "on", badge: "On", detail: "Online · verified Ubuntu telemetry",
      label: realReady ? "Shutdown / restart options" : "View power safety",
      action: "open-power-controls",
      note: realReady
        ? "Open owner-confirmed real shutdown or restart. Work must be saved before arming."
        : "Power is blocked until Atlas and other work are safe. View the reasons.",
    });
  } else if (desktop.ping_reachable) {
    setPowerCard("desktop", {
      state: "unknown", badge: "Unverified", detail: "Network reachable · agent offline",
      label: "Verify Ubuntu status", action: null,
      note: "A ping does not prove the operating system is ready. No power action is offered.",
    });
  } else {
    const canWake = desktop.mac_configured === true;
    setPowerCard("desktop", {
      state: "unknown", badge: "Not reachable", detail: "No verified Ubuntu heartbeat",
      label: canWake ? "Send wake signal" : "Power unavailable",
      action: canWake ? "wake-desktop" : null,
      note: canWake
        ? "Wake-on-LAN sends a packet; it does not confirm the computer was off or has turned on."
        : "Wake-on-LAN is not configured. A missing heartbeat is not proof of power off.",
    });
  }

  const reachable = Boolean(tv.ping_reachable && tv.webos_api_reachable);
  const paired = tv.paired === true;
  const known = paired && reachable ? tv.power_state : "unknown";
  if (known === "on") {
    setPowerCard("tv", {
      state: "on", badge: "On", detail: "Screen active · verified by LG webOS",
      label: "Standby display", action: "tv-power-off",
      note: "Send LG standby after confirmation. The next webOS report verifies the result.",
    });
  } else if (known === "screen_off") {
    setPowerCard("tv", {
      state: "off", badge: "Screen off", detail: "Display dark · verified by LG webOS",
      label: "Turn screen on", action: "tv-screen-on",
      note: "Use the paired webOS screen-on command; this is not Wake-on-LAN.",
    });
  } else if (known === "off") {
    const canWake = tv.mac_configured === true;
    setPowerCard("tv", {
      state: "off", badge: "Standby", detail: "Power state reported by LG webOS",
      label: canWake ? "Turn on display" : "Wake unavailable",
      action: canWake ? "wake-tv" : null,
      note: "Wake-on-LAN sends a signal. Screen power-on is only confirmed after a new webOS report.",
    });
  } else if (!reachable) {
    const canWake = tv.mac_configured === true;
    setPowerCard("tv", {
      state: "unknown", badge: "Not reachable", detail: "LG screen state unverified",
      label: canWake ? "Send wake signal" : "Power unavailable",
      action: canWake ? "wake-tv" : null,
      note: "LG did not answer. Wake-on-LAN is available, but the display may not actually be off.",
    });
  } else {
    setPowerCard("tv", {
      state: "unknown", badge: "Unverified",
      detail: paired ? "Connected · webOS state unavailable" : "Connected · pairing required",
      label: paired ? "Refresh to verify" : "Pair LG in Control",
      action: null,
      note: paired
        ? "Network reachability is not enough. The screen must report its power state."
        : "Complete LG webOS pairing in Control before standby can be used.",
    });
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
  renderDevicePower(desktop, tv, Boolean(fresh));
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
    if (app.tab === "control") {
      await refreshPowerPreview();
      await window.UbuntuRealPower.refresh();
    }
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
    renderPowerUnavailable();
    el("pair-tv-btn").disabled = true;
    document.querySelectorAll("#tv-remote-controls [data-action]").forEach((button) => { button.disabled = true; });
    syncControls();
    if (manual) toast("Cannot reach the private Hub. Check Tailscale.", true);
  } finally {
    app.busy = false;
    el("refresh-btn").disabled = false;
  }
}

function stopCpuWatch() {
  if (app.cpuWatchTimer !== null) {
    clearInterval(app.cpuWatchTimer);
    app.cpuWatchTimer = null;
  }
  app.cpuFastActive = false;
  if (window.UbuntuCPU.setSyncMode) window.UbuntuCPU.setSyncMode(false);
}

async function refreshCpuWatch() {
  if (app.tab !== "cpu" || document.hidden || app.cpuWatchBusy) return;
  if (!app.canControl) {
    stopCpuWatch();
    return;
  }
  app.cpuWatchBusy = true;
  try {
    if (!app.session) app.session = await api("/api/session");
    const response = await api("/api/cpu/watch", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-UC-CSRF": app.session.csrf},
      body: "{}",
    });
    if (app.tab !== "cpu" || document.hidden) return;
    app.cpuWatchFailures = 0;
    app.cpuFastActive = response.watch_active === true;
    if (window.UbuntuCPU.setSyncMode) window.UbuntuCPU.setSyncMode(app.cpuFastActive);
    const age = Date.now() / 1000 - Number(response.last_agent_report_unix || 0);
    if (response.control_agent === "online" && response.metrics?.cpu &&
        age >= -15 && age <= 45) {
      window.UbuntuCPU.update(response.metrics);
    } else {
      window.UbuntuCPU.stale();
    }
  } catch {
    app.cpuWatchFailures++;
    if (app.cpuWatchFailures >= 3) {
      // Failed authentication or network: fall back to ordinary 15s Dashboard
      // reporting. Never continue requesting an unavailable fast endpoint.
      stopCpuWatch();
      if (window.UbuntuCPU.setSyncMode) window.UbuntuCPU.setSyncMode(false);
    }
  } finally {
    app.cpuWatchBusy = false;
  }
}

function startCpuWatch() {
  if (app.tab !== "cpu" || document.hidden || app.cpuWatchTimer !== null) return;
  if (!app.canControl) {
    if (window.UbuntuCPU.setSyncMode) window.UbuntuCPU.setSyncMode(false);
    return;
  }
  app.cpuWatchFailures = 0;
  void refreshCpuWatch();
  app.cpuWatchTimer = setInterval(() => { void refreshCpuWatch(); }, 2000);
}

function switchTab(tab) {
  if (!["dashboard", "control", "history", "cpu"].includes(tab)) return;
  if (app.tab === "cpu" && tab !== "cpu") stopCpuWatch();
  app.tab = tab;
  for (const key of ["dashboard", "control", "history", "cpu"]) el("view-" + key).hidden = key !== tab;
  document.body.classList.toggle("cpu-details-open", tab === "cpu");
  document.querySelectorAll("[data-tab]").forEach((button) => {
    const selected = button.dataset.tab === (tab === "cpu" ? "dashboard" : tab);
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-current", selected ? "page" : "false");
  });
  window.scrollTo({top: 0, behavior: "instant"});
  if (tab === "history") loadHistory();
  if (tab === "control") void refreshControlAccess();
  if (tab === "cpu") {
    window.UbuntuCPU.onOpen();
    void refreshStatus();
    // Recheck owner capability if navigation occurs before initial login.
    void refreshControlAccess().then(() => {
      if (app.tab === "cpu") startCpuWatch();
    });
  }
}

async function executeAction(name, button) {
  if (name === "open-power-controls") {
    window.UbuntuRealPower.open();
    return;
  }
  const actions = {
    "wake-desktop": {path: "/api/wake", payload: {target: "desktop"}, label: "Ubuntu wake request"},
    "wake-tv": {path: "/api/wake", payload: {target: "tv"}, label: "LG wake request"},
    "tv-power-off": {path: "/api/tv/control", payload: {action: "power_off"}, label: "LG standby request"},
    "tv-screen-on": {path: "/api/tv/control", payload: {action: "screen_on"}, label: "LG screen-on request"},
    "pair-tv": {path: "/api/tv/pair", payload: {}, label: "LG pairing"},
    "tv-volume-up": {path: "/api/tv/control", payload: {action: "volume_up"}, label: "TV volume up"},
    "tv-volume-down": {path: "/api/tv/control", payload: {action: "volume_down"}, label: "TV volume down"},
    "tv-mute": {path: "/api/tv/control", payload: {action: "mute"}, label: "TV mute"},
    "tv-unmute": {path: "/api/tv/control", payload: {action: "unmute"}, label: "TV unmute"},
  };
  const action = actions[name];
  if (!action || button.disabled) return;
  const confirmations = {
    "tv-power-off": {
      tone: "danger", symbol: "⏻", eyebrow: "LG DISPLAY · POWER",
      title: "Put display in standby?",
      message: "The LG screen will be asked to enter standby.",
      note: "Your Raspberry Pi sends a paired webOS command. The app will check the reported power state afterward.",
      confirmText: "Enter standby",
    },
    "wake-desktop": {
      symbol: "↗", eyebrow: "UBUNTU · WAKE SIGNAL",
      title: "Wake Ubuntu Desktop?",
      message: "Send a Wake-on-LAN signal to the workstation.",
      note: "A wake packet is not proof that Ubuntu has started. Its status will be checked separately.",
      confirmText: "Send wake",
    },
    "wake-tv": {
      symbol: "↗", eyebrow: "LG DISPLAY · WAKE SIGNAL",
      title: "Wake LG Display?",
      message: "Send a wake signal through Raspberry Pi.",
      note: "The screen may still be off even if it responds to the network.",
      confirmText: "Send wake",
    },
    "pair-tv": {
      symbol: "▣", eyebrow: "LG WEBOS · CONNECTION",
      title: "Connect LG Display?",
      message: "Turn on the LG display before continuing.",
      note: "An approval prompt may appear on the TV. Choose Allow using the television remote.",
      confirmText: "Start pairing",
    },
  };
  if (confirmations[name] && !(await window.UbuntuIOS.confirm(confirmations[name]))) return;

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
  window.UbuntuIOS.init();
  window.UbuntuCPU.init();
  window.UbuntuRealPower.init();
  el("open-cpu-details").addEventListener("click", () => switchTab("cpu"));
  el("cpu-back-button").addEventListener("click", () => switchTab("dashboard"));
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
  window.addEventListener("online", () => {
    void refreshStatus();
    if (app.tab === "cpu") startCpuWatch();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopCpuWatch();
    } else {
      void refreshStatus();
      if (app.tab === "cpu") startCpuWatch();
    }
  });
  try { app.session = await api("/api/session"); }
  catch { app.session = null; }
  await refreshStatus();
  await refreshControlAccess();
  // Keep the Dashboard on 15s. CPU Details uses a separate 2s owner-only
  // lightweight watch; ordinary polling remains the safe fallback.
  app.timer = setInterval(() => {
    if (!document.hidden && (app.tab !== "cpu" || !app.cpuFastActive)) refreshStatus();
  }, 15000);
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
  el("profile-picker-open").disabled = !profileReady;
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
  await window.UbuntuRealPower.refresh();
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
  el("apply-profile").addEventListener("click", async () => {
    const profile = el("profile-selector").value;
    if (!["quiet", "balanced", "performance"].includes(profile)) return;
    if (!commandAuthorizedAndReady()) {
      feedback("Changes are locked until the authorized Ubuntu agent is available.", "error");
      return;
    }
    const approved = await window.UbuntuIOS.confirm({
      tone: "warning", symbol: "◉", eyebrow: "CPU & GPU · PERFORMANCE",
      title: "Apply " + profile + " profile?",
      message: "Update the active CPU & GPU Workload Manager profile.",
      note: "This can change the resource budget of running workloads. The change will only be considered complete after Ubuntu confirms execution.",
      confirmText: "Apply profile",
    });
    if (!approved) return;
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
  put("guard-atlas", "Unknown");
  put("guard-atlas-dispatch", "Unknown");
  put("guard-atlas-attempts", "Unknown");
  put("guard-codex-stop", "Not verified");
  put("guard-stop-acks", "—");
  put("guard-stop-barrier", "Not verified");
  put("guard-cpuwm", "Unknown");
  put("guard-desktop", "Unverified");
  el("power-safety-details").replaceChildren();
  put("power-safety-count", "0");
  el("power-safety-more").open = false;
  put("power-preview-status", "Preview unavailable — refresh to check server state");
  window.UbuntuIOS.clearPreview();
  syncPreviewControls();
}

function paintPowerPreview(data) {
  if (data.preview_only !== true || data.will_execute !== false) throw new Error("Invalid preview response");
  previewState = data.state;
  const safety = data.safety || {};
  const cpuwm = safety.cpuwm || {};
  const desktopWork = safety.desktop_work || {};
  const atlasControl = safety.atlas_control || {};
  const stop = atlasControl.codex_stop || {};
  put("guard-atlas", safety.atlas_state === "active" ? "Active" :
    safety.atlas_state === "inactive" ? "Inactive" : "Unknown");
  const atlasLabels = {
    running: "RUN · executing",
    armed_idle: "RUN · can dispatch",
    unverified_stop: "STOP · origin unknown",
    owner_stop_draining: "Owner STOP · draining",
    owner_stop_no_active_attempts: "Owner STOP · no active attempts",
    unavailable: "Unknown",
  };
  const verifiedStop = atlasControl.codex_user_stop_verified === true
    && atlasControl.atlas_power_gate_clear === true && stop.status === "verified";
  put("guard-atlas-dispatch", verifiedStop && atlasControl.scheduler_mode === "RUN"
    ? "RUN · Codex dispatch frozen"
    : (atlasLabels[atlasControl.status] || "Unknown"));
  put("guard-atlas-attempts", Number.isInteger(atlasControl.inflight_attempts)
    ? fmt(atlasControl.inflight_attempts, 0) + " active" : "Unknown");
  const stopLabels = {
    unsupported: "Awaiting Atlas support",
    not_requested: "Not requested",
    draining: "Waiting for workers",
    stale: "Expired · recheck",
    resumed: "Codex resumed",
    invalid: "Invalid proof",
    unavailable: "Unavailable",
    verified: "Verified owner stop",
  };
  put("guard-codex-stop", verifiedStop
    ? "Verified owner stop" : (stopLabels[stop.status] || "Not verified"));
  put("guard-stop-acks", Number.isInteger(stop.expected_workers)
    ? (Number.isInteger(stop.acknowledged_workers) ? stop.acknowledged_workers : 0)
      + " / " + stop.expected_workers + " workers"
    : "—");
  put("guard-stop-barrier", stop.dispatch_frozen === true
    ? "Owner stop barrier active" : "Not verified");
  put("guard-cpuwm", cpuwm.status === "fresh" && Number.isInteger(cpuwm.managed_scopes)
    ? fmt(cpuwm.managed_scopes, 0) + " extra" : "Unknown");
  put("guard-desktop", desktopWork.status === "unverifiable" ?
    (desktopWork.app_categories?.length
      ? "Unverified · " + desktopWork.app_categories.join(", ") : "Unverified") : "Unknown");
  const realPower=safety.real_power || {};
  const canProceedWithWarning=realPower.eligible === true;
  el("power-safety-status").classList.toggle("is-ready",canProceedWithWarning);
  put("power-safety-status", canProceedWithWarning
    ? "Real power safeguards satisfied · unsaved work can be lost only after explicit user acceptance. This preview never executes."
    : "Real power blocked by the Atlas/workload safeguards · this preview never executes.");
  const list = el("power-safety-details");
  list.replaceChildren();
  // The old conservative read-only list treated *unverifiable saved files*
  // as a blocker. Real power has its own stricter Atlas/job gate, so avoid
  // showing a contradictory unsaved-file hard block after consent is allowed.
  const details = canProceedWithWarning
    ? [...(realPower.warnings || [])]
    : [...(realPower.blockers || []),...(realPower.warnings || []),
       ...(safety.blocked_reasons || []).filter(item=>
         !String(item).includes("Unsaved desktop work"))];
  put("power-safety-count", String(details.length));
  for (const text of details) {
    const item = document.createElement("li");
    item.textContent = text;
    list.append(item);
  }
  put("power-preview-status", "Simulation: " + data.state + (data.action ? " · " + data.action : "")
    + " · " + data.remaining_seconds + " seconds remaining (server reading at "
    + new Date(data.server_time * 1000).toLocaleTimeString("en-GB") + ")");
  window.UbuntuIOS.renderPreview(data);
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
