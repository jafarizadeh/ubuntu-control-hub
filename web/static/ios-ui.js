"use strict";
/* iPhone control surfaces. Presentation only: no power or CPU action is executed here. */
(() => {
  const $ = (id) => document.getElementById(id);
  const DURATION_MAX = 240;
  const WHEEL_ROW = 44;
  const validProfiles = new Set(["quiet", "balanced", "performance"]);
  let activeSheet = null;
  let lastFocus = null;
  let hour = 0;
  let minute = 15;
  let selectedProfile = "balanced";
  let liveDurationSetter = null;
  let liveDurationInitial = null;
  let profileDirty = false;
  let scrollFrames = {hours: null, minutes: null};
  let toastTimeout = null;
  let confirmResolver = null;

  function displayDuration(value) {
    const h = Math.floor(value / 60), m = value % 60;
    if (!h) return value + " min";
    return h + (h === 1 ? " hour" : " hours") + (m ? " " + m + " min" : "");
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
      const selected = liveDurationInitial===null ? 15 : liveDurationInitial;
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
        } else return;
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

  function init() {
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
    setProfile("balanced");
  }
  function openLiveDuration(currentMinutes,onSelect) {
    if (typeof onSelect !== "function" || $("ios-picker-sheet").open) return;
    const value=Number(currentMinutes);
    liveDurationInitial=Number.isInteger(value) && value>=1 && value<=240 ? value : 15;
    liveDurationSetter=onSelect;
    openSheet("duration");
  }

  window.UbuntuIOS = {
    init,confirm:confirmAction,notify:toast,
    openLiveDuration,
    profileDirty:()=>profileDirty,markProfileSynced:()=>{profileDirty=false;},
    setProfile,
    syncProfileLabel:()=>displayProfile($("profile-selector").value),
    displayDuration,
  };
})();
