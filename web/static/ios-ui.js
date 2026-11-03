"use strict";
/* iPhone control surfaces. Presentation only: no power or CPU action is executed here. */
(() => {
  const $ = (id) => document.getElementById(id);
  const DURATION_MAX = 240;
  const WHEEL_ROW = 44;
  const RING_CIRCUMFERENCE = 2 * Math.PI * 43;
  const validProfiles = new Set(["quiet", "balanced", "performance"]);
  let activeSheet = null;
  let lastFocus = null;
  let hour = 0;
  let minute = 15;
  let selectedProfile = "balanced";
  let liveDurationSetter = null;
  let liveDurationInitial = null;
  let profileDirty = false;
  let snapshot = null;
  let scrollFrames = {hours: null, minutes: null};
  let toastTimeout = null;
  let confirmResolver = null;

  function displayDuration(value) {
    const h = Math.floor(value / 60), m = value % 60;
    if (!h) return value + " min";
    return h + (h === 1 ? " hour" : " hours") + (m ? " " + m + " min" : "");
  }

  function duration(value) {
    const n = Number(value);
    if (!Number.isInteger(n) || n < 1 || n > DURATION_MAX) return false;
    $("power-preview-delay").value = String(n);
    $("duration-display").textContent = displayDuration(n);
    document.querySelectorAll("[data-duration]").forEach((b) => {
      const active = Number(b.dataset.duration) === n;
      b.classList.toggle("selected", active);
      b.setAttribute("aria-pressed", String(active));
    });
    return true;
  }

  function mode(value) {
    if (!["shutdown", "restart"].includes(value)) return;
    $("power-preview-action").value = value;
    document.querySelectorAll("[data-preview-mode]").forEach((b) => {
      const active = b.dataset.previewMode === value;
      b.classList.toggle("selected", active);
      b.setAttribute("aria-pressed", String(active));
    });
  }

  function displayProfile(value) {
    if (!validProfiles.has(value)) return;
    $("profile-selected-label").textContent = value.charAt(0).toUpperCase() + value.slice(1);
    const trigger = $("profile-picker-open");
    trigger.setAttribute("aria-label", "Target performance profile: " + value);
  }

  function setProfile(value, dirty = false) {
    if (!validProfiles.has(value)) return;
    $("profile-selector").value = value;
    profileDirty = dirty;
    displayProfile(value);
  }

  function drawSheetProfile() {
    document.querySelectorAll("[data-profile-option]").forEach((node) => {
      const selected = node.dataset.profileOption === selectedProfile;
      node.classList.toggle("is-selected", selected);
      node.setAttribute("aria-pressed", String(selected));
    });
  }

  function buildWheel(id, max, unit) {
    const container = $(id);
    for (let number = 0; number <= max; number++) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ios-wheel-option";
      button.textContent = String(number).padStart(2, "0");
      button.dataset.value = String(number);
      button.setAttribute("aria-label", number + " " + unit);
      button.addEventListener("click", () => {
        if (unit === "hours") hour = number; else minute = number;
        drawWheel();
        container.scrollTo({top: number * WHEEL_ROW, behavior: "smooth"});
      });
      container.append(button);
    }
    container.addEventListener("scroll", () => {
      if (activeSheet !== "duration") return;
      if (scrollFrames[unit] !== null) cancelAnimationFrame(scrollFrames[unit]);
      scrollFrames[unit] = requestAnimationFrame(() => {
        scrollFrames[unit] = null;
        const choice = Math.max(0, Math.min(max, Math.round(container.scrollTop / WHEEL_ROW)));
        if (unit === "hours") hour = choice; else minute = choice;
        drawWheel();
      });
    }, {passive:true});
    container.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "PageUp", "PageDown"].includes(event.key)) return;
      event.preventDefault();
      const step = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1
        : event.key === "PageUp" ? -5 : 5;
      const next = Math.max(0, Math.min(max, (unit === "hours" ? hour : minute) + step));
      if (unit === "hours") hour = next; else minute = next;
      drawWheel();
      container.scrollTo({top: next * WHEEL_ROW, behavior: "instant"});
    });
  }

  function drawWheel() {
    [["ios-hours-wheel", hour], ["ios-minutes-wheel", minute]].forEach(([id,value]) => {
      $(id).querySelectorAll(".ios-wheel-option").forEach((el) => {
        const selected = Number(el.dataset.value) === value;
        el.classList.toggle("is-selected", selected);
        el.setAttribute("aria-pressed", String(selected));
      });
    });
    const value = hour * 60 + minute;
    const allowed = value >= 1 && value <= DURATION_MAX;
    $("ios-sheet-done").disabled = !allowed;
    $("ios-sheet-duration-summary").textContent = allowed
      ? displayDuration(value) + " selected"
      : (value === 0 ? "Select at least 1 minute" : "Maximum duration is 4 hours");
  }

  function openSheet(type) {
    const sheet = $("ios-picker-sheet");
    if (sheet.open) return;
    activeSheet = type;
    lastFocus = document.activeElement;
    $("ios-sheet-duration").hidden = type !== "duration";
    $("ios-sheet-profiles").hidden = type !== "profile";
    $("ios-picker-title").textContent = type === "duration" ? "Set duration" : "Workload profile";
    $("ios-sheet-done").disabled = false;
    if (type === "duration") {
      const selected = liveDurationInitial===null
        ? Number($("power-preview-delay").value) : liveDurationInitial;
      hour = Math.floor(selected / 60);
      minute = selected % 60;
    } else {
      selectedProfile = $("profile-selector").value;
    }
    sheet.showModal();
    if (type === "duration") {
      drawWheel();
      requestAnimationFrame(() => {
        $("ios-hours-wheel").scrollTo({top:hour * WHEEL_ROW,behavior:"instant"});
        $("ios-minutes-wheel").scrollTo({top:minute * WHEEL_ROW,behavior:"instant"});
      });
    } else {
      drawSheetProfile();
    }
  }

  function closeSheet(apply) {
    const sheet = $("ios-picker-sheet");
    if (!sheet.open) return;
    if (apply) {
      if (activeSheet === "duration") {
        const total = hour * 60 + minute;
        if (liveDurationSetter) {
          if (!Number.isInteger(total) || total < 1 || total > 240) return;
          liveDurationSetter(total);
        } else if (!duration(total)) return;
      }
      if (activeSheet === "profile") setProfile(selectedProfile, true);
    }
    sheet.close();
    liveDurationSetter = null;
    liveDurationInitial = null;
  }

  function confirmAction(options) {
    const dialog = $("ios-confirm-dialog");
    if (dialog.open) return Promise.resolve(false);
    $("ios-confirm-eyebrow").textContent = options.eyebrow || "CONFIRM ACTION";
    $("ios-confirm-title").textContent = options.title || "Confirm action?";
    $("ios-confirm-message").textContent = options.message || "";
    $("ios-confirm-note").textContent = options.note || "";
    $("ios-confirm-submit").textContent = options.confirmText || "Confirm";
    $("ios-confirm-symbol").textContent = options.symbol || "⏻";
    dialog.classList.toggle("is-danger", options.tone === "danger");
    dialog.classList.toggle("is-warning", options.tone === "warning");
    lastFocus = document.activeElement;
    dialog.showModal();
    return new Promise((resolve) => {confirmResolver = resolve;});
  }

  function finishConfirm(approved) {
    const dialog = $("ios-confirm-dialog");
    if (!dialog.open) return;
    const resolve = confirmResolver;
    confirmResolver = null;
    dialog.close();
    if (resolve) resolve(Boolean(approved));
  }

  function toast(text, error = false) {
    const node = $("toast");
    node.replaceChildren();
    const mark = document.createElement("span");
    mark.className = "ios-toast-symbol";
    mark.textContent = error ? "!" : "✓";
    const content = document.createElement("span");
    content.className = "ios-toast-copy";
    const heading = document.createElement("strong");
    heading.textContent = error ? "Action needs attention" : "Ubuntu Control";
    const message = document.createElement("span");
    message.textContent = String(text);
    content.append(heading,message);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "ios-toast-close";
    close.textContent = "×";
    close.setAttribute("aria-label","Dismiss notification");
    close.addEventListener("click", () => node.classList.remove("visible"));
    node.append(mark,content,close);
    node.classList.toggle("error",error);
    node.classList.add("visible");
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => node.classList.remove("visible"), 4600);
  }

  function preview(data) {
    if (!data || data.preview_only !== true || data.will_execute !== false) return;
    const state = data.state || "absent";
    if (state === "draft") {
      const remaining = Math.max(0, Number(data.remaining_seconds)||0);
      const duration = Math.max(1, Number(data.expires_at) - Number(data.created_at)||remaining);
      snapshot = {remaining,duration,receivedAt:performance.now(),serverTime:Number(data.server_time)||0};
    } else snapshot = null;
    $("ios-timer-state").textContent = ({
      draft: "Preview in progress",
      elapsed: "Preview finished · no action",
      canceled: "Preview canceled",
      absent: "No active preview"
    })[state] || "Preview unavailable";
    updateClock();
  }

  function clearPreview() {
    snapshot = null;
    $("ios-timer-readout").textContent = "—";
    $("ios-timer-state").textContent = "Preview unavailable";
    $("ios-timer-sync").textContent = "Cannot verify server timer";
    $("ios-ring-progress").style.strokeDashoffset = String(RING_CIRCUMFERENCE);
  }

  function updateClock() {
    if (!snapshot) {
      $("ios-timer-readout").textContent = "—";
      $("ios-ring-progress").style.strokeDashoffset = String(RING_CIRCUMFERENCE);
      $("ios-timer-sync").textContent = "No running simulation · never executes";
      return;
    }
    // Monotonic interpolation is visual only. Raspberry Pi remains authoritative.
    const estimated = Math.max(0, Math.ceil(snapshot.remaining - (performance.now() - snapshot.receivedAt) / 1000));
    const hours = Math.floor(estimated / 3600);
    const mins = Math.floor(estimated % 3600 / 60);
    const secs = estimated % 60;
    const pad = (value) => String(value).padStart(2,"0");
    $("ios-timer-readout").textContent = hours ? hours+":"+pad(mins)+":"+pad(secs) : pad(mins)+":"+pad(secs);
    const fraction = Math.min(1, estimated / snapshot.duration);
    $("ios-ring-progress").style.strokeDashoffset = String(RING_CIRCUMFERENCE * (1 - fraction));
    $("ios-timer-sync").textContent = estimated
      ? "Estimated remaining · synced with Raspberry Pi"
      : "Awaiting server status · no action will execute";
  }

  function init() {
    // Timer choice: immediate, local-only selection; requires the usual server-side authorization to send a draft.
    document.querySelectorAll("[data-preview-mode]").forEach((b) => {
      b.addEventListener("click", () => mode(b.dataset.previewMode));
    });
    document.querySelectorAll("[data-duration]").forEach((b) => {
      b.setAttribute("aria-pressed", String(Number(b.dataset.duration) === 15));
      b.addEventListener("click", () => duration(Number(b.dataset.duration)));
    });
    $("duration-picker-open").addEventListener("click", () => openSheet("duration"));
    $("profile-picker-open").addEventListener("click", () => {
      if (!$("profile-picker-open").disabled) openSheet("profile");
    });
    buildWheel("ios-hours-wheel",4,"hours");
    buildWheel("ios-minutes-wheel",59,"minutes");
    document.querySelectorAll("[data-profile-option]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedProfile=button.dataset.profileOption;
        drawSheetProfile();
      });
    });
    $("ios-sheet-cancel").addEventListener("click", () => closeSheet(false));
    $("ios-sheet-done").addEventListener("click", () => closeSheet(true));
    $("ios-picker-sheet").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) closeSheet(false);
    });
    $("ios-picker-sheet").addEventListener("close", () => {
      activeSheet = null;
      liveDurationSetter = null;
      liveDurationInitial = null;
      if (lastFocus?.isConnected) lastFocus.focus({preventScroll:true});
    });
    $("ios-confirm-cancel").addEventListener("click", () => finishConfirm(false));
    $("ios-confirm-submit").addEventListener("click", () => finishConfirm(true));
    $("ios-confirm-dialog").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) finishConfirm(false);
    });
    $("ios-confirm-dialog").addEventListener("close", () => {
      if (confirmResolver) {const resolve=confirmResolver; confirmResolver=null; resolve(false);}
      if (lastFocus?.isConnected) lastFocus.focus({preventScroll:true});
    });
    duration(15);
    mode("shutdown");
    setProfile("balanced");
    clearPreview();
    setInterval(() => {if (!document.hidden) updateClock();},1000);
    document.addEventListener("visibilitychange", () => {if (!document.hidden) updateClock();});
  }
  function openLiveDuration(currentMinutes,onSelect) {
    if (typeof onSelect !== "function") return;
    const value=Number(currentMinutes);
    liveDurationInitial=Number.isInteger(value) && value>=1 && value<=240 ? value : 15;
    liveDurationSetter=onSelect;
    openSheet("duration");
  }

  window.UbuntuIOS = {
    init,confirm:confirmAction,notify:toast,renderPreview:preview,clearPreview,
    openLiveDuration,
    profileDirty:()=>profileDirty,markProfileSynced:()=>{profileDirty=false;},
    setProfile,
    syncProfileLabel:()=>displayProfile($("profile-selector").value),
    duration,mode,displayDuration,
  };
})();
