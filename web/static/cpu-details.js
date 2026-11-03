"use strict";
/* CPU Details. All readings come from the signed Ubuntu Agent, never the Pi. */
(() => {
  const $ = id => document.getElementById(id);
  const MAX_CORES = 256;
  const HISTORY_LIMIT = 90;
  const HOT_THRESHOLD = 90;
  let samples = [];
  let latestHistorySize = 0;

  const isPercentage = v => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 100;
  const number = (v, places = 1) =>
    typeof v === "number" && Number.isFinite(v)
      ? v.toLocaleString("en-US", {maximumFractionDigits: places})
      : "—";
  const percentage = (v, places = 1) => isPercentage(v) ? number(v, places) + "%" : "—";
  const degrees = v => typeof v === "number" && Number.isFinite(v) && v >= -20 && v <= 150
    ? number(v) + "°C" : "—";

  function validCoreList(input) {
    if (!Array.isArray(input)) return [];
    const result = [], seen = new Set();
    for (const core of input.slice(0, MAX_CORES)) {
      if (!core || typeof core !== "object" || !Number.isInteger(core.index) ||
          core.index < 0 || core.index >= MAX_CORES || seen.has(core.index)) continue;
      seen.add(core.index);
      result.push({index: core.index, usage: isPercentage(core.usage_percent) ? core.usage_percent : null});
    }
    return result.sort((a, b) => a.index - b.index);
  }

  function validatedHistory(raw) {
    if (!Array.isArray(raw)) return [];
    const now = Math.floor(Date.now() / 1000);
    const byTimestamp = new Map();
    for (const sample of raw.slice(-HISTORY_LIMIT)) {
      if (!sample || !Number.isInteger(sample.time_unix) ||
          sample.time_unix < now - 180 || sample.time_unix > now + 15 ||
          !isPercentage(sample.usage_percent)) continue;
      byTimestamp.set(sample.time_unix, sample.usage_percent);
    }
    return [...byTimestamp.entries()].sort((a,b)=>a[0]-b[0])
      .slice(-HISTORY_LIMIT).map(([t,value])=>({t,value}));
  }

  function cores(list, expected) {
    const node = $("cpu-core-grid");
    node.replaceChildren();
    if (!list.length) {
      const unavailable = document.createElement("div");
      unavailable.className = "cpu-core-empty";
      unavailable.textContent = "Waiting for actual per-core CPU readings…";
      node.append(unavailable);
      return;
    }
    for (const core of list) {
      const entry = document.createElement("div");
      entry.className = "cpu-core-item";
      if (core.usage !== null && core.usage >= HOT_THRESHOLD) entry.classList.add("is-hot");
      else if (core.usage !== null && core.usage >= 75) entry.classList.add("is-busy");
      const label = document.createElement("span");
      label.className = "cpu-core-number";
      label.textContent = core.index + ":";
      const value = document.createElement("span");
      value.className = "cpu-core-value";
      value.textContent = percentage(core.usage, 0);
      entry.setAttribute("aria-label","Logical core "+core.index+": "+percentage(core.usage,0));
      entry.append(label,value);
      node.append(entry);
    }
    node.setAttribute("aria-label", list.length+" of "+(expected || list.length)+" logical CPU readings");
  }

  function paintHistory() {
    const canvas = $("cpu-history-canvas");
    if (!canvas || $("view-cpu").hidden) return;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const scale = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.round(bounds.width * scale));
    const height = Math.max(1, Math.round(bounds.height * scale));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0,0,width,height);
    ctx.fillStyle = "#0a0c11";
    ctx.fillRect(0,0,width,height);

    const insetX = 4 * scale, insetY = 7 * scale;
    const graphW = width - insetX * 2, graphH = height - insetY * 2;
    // Subtle, clean grid; the one-pixel red waveform stays the focus.
    ctx.strokeStyle = "rgba(145,155,168,.08)";
    ctx.lineWidth = scale * .55;
    for (const fraction of [.25,.5,.75]) {
      const y = height - insetY - graphH * fraction;
      ctx.beginPath(); ctx.moveTo(insetX,y); ctx.lineTo(width-insetX,y); ctx.stroke();
    }

    if (!samples.length) return;
    const latest = samples[samples.length - 1].t;
    const earliest = latest - (HISTORY_LIMIT - 1);
    const coords = samples.map(point=>({
      x: insetX + (Math.max(0,Math.min(HISTORY_LIMIT-1,point.t-earliest)) / (HISTORY_LIMIT-1)) * graphW,
      y: height-insetY - point.value/100 * graphH,
    }));
    if (coords.length===1) {
      ctx.fillStyle = "#ff4a61";
      ctx.fillRect(coords[0].x-1.3*scale,coords[0].y-1.3*scale,2.6*scale,2.6*scale);
      return;
    }
    ctx.beginPath();
    ctx.moveTo(coords[0].x,coords[0].y);
    for (let i=1;i<coords.length;i++) ctx.lineTo(coords[i].x,coords[i].y);
    ctx.lineWidth=1.9*scale;
    ctx.lineJoin="round";
    ctx.lineCap="round";
    ctx.strokeStyle="#ff4960";
    ctx.shadowColor="rgba(255,73,96,.32)";
    ctx.shadowBlur=3.5*scale;
    ctx.stroke();
    ctx.shadowBlur=0;
  }

  function update(report) {
    if (!report || typeof report !== "object") return stale();
    const cpu = report.cpu || {}, gpu = Array.isArray(report.gpus) ? report.gpus[0] || {} : {};
    const allCores = validCoreList(cpu.per_core);
    $("cpu-detail-temp").textContent = degrees(cpu.temperature_c);
    $("cpu-detail-usage").textContent = percentage(cpu.usage_percent);
    $("cpu-detail-gpu-temp").textContent = degrees(gpu.temperature_c);
    $("cpu-detail-gpu-load").textContent = percentage(gpu.usage_percent,0);
    cores(allCores,cpu.logical_cores);

    samples = validatedHistory(cpu.history);
    latestHistorySize = samples.length;
    $("cpu-history-count").textContent =
      latestHistorySize ? latestHistorySize+" real samples · ~1s interval" : "Collecting real CPU samples…";

    const now = Math.floor(Date.now()/1000);
    const sampledAt = Number.isInteger(cpu.sampled_at_unix) ? cpu.sampled_at_unix : report.checked_at_unix;
    const age = typeof sampledAt==="number" ? Math.max(0,now-sampledAt) : null;
    $("cpu-detail-time").textContent = age === null ? "Reading Ubuntu…" : "Sampled "+age+"s ago";
    $("cpu-freshness").textContent = age !== null && age <= 45 ? "Ubuntu Live" : "Waiting for fresh sample";
    $("cpu-freshness").classList.toggle("stale",age===null || age>45);

    const clock = cpu.clock || {}, loads = cpu.load_average || {};
    const fields = {
      "cpu-info-model": cpu.model || "Unknown CPU",
      "cpu-info-logical": Number.isInteger(cpu.logical_cores) ? String(cpu.logical_cores) : "—",
      "cpu-info-physical": Number.isInteger(cpu.physical_cores) ? String(cpu.physical_cores) : "—",
      "cpu-info-clock": typeof clock.current_ghz==="number" ? number(clock.current_ghz,2)+" GHz" : "—",
      "cpu-info-max-clock": typeof clock.maximum_ghz==="number" ? number(clock.maximum_ghz,2)+" GHz" : "—",
      "cpu-info-governor": clock.governor || "—",
      "cpu-info-arch": cpu.architecture || "—",
      "cpu-info-load1": number(loads["1m"],2),
      "cpu-info-load5": number(loads["5m"],2),
      "cpu-info-load15": number(loads["15m"],2),
      "cpu-info-peak": allCores.length
        ? (()=>{const peak=allCores.filter(x=>x.usage!==null).sort((a,b)=>b.usage-a.usage)[0];
            return peak ? "Core "+peak.index+" · "+percentage(peak.usage,0) : "—";})()
        : "—",
    };
    for (const [key,value] of Object.entries(fields)) $(key).textContent=String(value);
    const label = latestHistorySize
      ? "Red CPU utilization history with "+latestHistorySize+" verified Ubuntu readings; latest "+percentage(samples.at(-1).value)
      : "No recent CPU utilization history is available";
    $("cpu-history-canvas").setAttribute("aria-label",label);
    paintHistory();
  }

  function stale() {
    $("cpu-freshness").textContent="Ubuntu data unavailable";
    $("cpu-freshness").classList.add("stale");
    $("cpu-detail-time").textContent="No verified report";
    $("cpu-detail-temp").textContent="—";
    $("cpu-detail-usage").textContent="—";
    $("cpu-detail-gpu-temp").textContent="—";
    $("cpu-detail-gpu-load").textContent="—";
    cores([],null);
    samples=[];
    latestHistorySize=0;
    $("cpu-history-count").textContent="No recent CPU samples";
    for(const id of ["cpu-info-model","cpu-info-logical","cpu-info-physical","cpu-info-clock",
      "cpu-info-max-clock","cpu-info-governor","cpu-info-arch","cpu-info-load1",
      "cpu-info-load5","cpu-info-load15","cpu-info-peak"])$(id).textContent="—";
    $("cpu-history-canvas").setAttribute("aria-label","No verified CPU history");
    paintHistory();
  }

  function setSyncMode(fast) {
    $("cpu-details-source").textContent = fast
      ? "2s live sync · 1s core sampling" : "Standard 15s sync · 1s core sampling";
  }

  function init() {
    window.addEventListener("resize", () => {if(!$("view-cpu").hidden) paintHistory()});
    setSyncMode(false);
  }

  window.UbuntuCPU={init, update, stale, onOpen:paintHistory, setSyncMode};
})();
