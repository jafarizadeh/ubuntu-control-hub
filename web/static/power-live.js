"use strict";
/* One real-power card and one authoritative signed snapshot. No browser power
 * execution, no simulated timer, no local override of Atlas or root checks. */
(() => {
  const $=id=>document.getElementById(id);
  const put=(id,text)=>{const node=$(id);if(node)node.textContent=String(text);};
  const STATES=new Set(["absent","armed","dispatching","sent","completed_unverified","canceled","expired","blocked"]);
  let mode="shutdown",minutes=0;
  let schedule={state:"absent",remaining_seconds:0,can_cancel:false};
  let readiness=null,inspection=null,ready=false,available=false;
  let loading=false,mutating=false,confirming=false,possibleArm=false;
  let epoch=0,validUntil=0,checkedAt=null,lastTick=performance.now(),lastRemaining=0;

  const delayLabel=n=>n===0?"after a 30-second safety countdown":
    "in "+window.UbuntuIOS.displayDuration(n);
  const authorized=()=>Boolean(typeof app!=="undefined"&&app.canControl);
  const isReady=()=>authorized()&&available&&ready&&performance.now()<validUntil;
  const busyState=()=>possibleArm||["armed","dispatching","sent"].includes(schedule.state);
  const canTryCancel=()=>authorized()&&!mutating&&(possibleArm||schedule.state==="armed");

  async function request(path,options={}){
    const abort=new AbortController();
    const timer=setTimeout(()=>abort.abort(),8000);
    try{return await api(path,{...options,signal:abort.signal});}
    finally{clearTimeout(timer);}
  }

  function invalidate(reason="Cannot verify the private Hub"){
    epoch++;
    ready=false;available=false;readiness=null;inspection=null;validUntil=0;checkedAt=null;
    $("live-power-loss-accepted").checked=false;
    // Do not erase a known armed timer: it may still run on the Pi. Preserve
    // cancellation as an attempted server operation; never claim local cancel.
    put("live-power-status",busyState()
      ?reason+". An earlier power timer may still execute. Reconnect or try Cancel timer."
      :reason+". New power requests are locked.");
    render();
  }

  function adopt(data,started){
    if(!data||!data.schedule||!STATES.has(data.schedule.state)||
       typeof data.ready_to_arm!=="boolean"||
       !Number.isInteger(data.schedule.remaining_seconds)||data.schedule.remaining_seconds<0||
       typeof data.safety_valid_for_seconds!=="number"||
       !Number.isFinite(data.safety_valid_for_seconds)||
       data.safety_valid_for_seconds<0||data.safety_valid_for_seconds>15){
      throw Error("Power snapshot could not be verified");
    }
    schedule=data.schedule;
    if(["armed","dispatching","sent"].includes(schedule.state)){
      if(!["shutdown","restart"].includes(schedule.action)||
         typeof schedule.schedule_id!=="string"||!/^[a-f0-9]{32}$/.test(schedule.schedule_id))
        throw Error("Active timer identity is invalid");
      mode=schedule.action;
      const span=schedule.deadline-schedule.created_at;
      if(span===30)minutes=0;
      else if(Number.isInteger(span)&&span>=60&&span<=14400&&span%60===0)minutes=span/60;
    }
    possibleArm=false;
    readiness=data.real_power||null;inspection=data.inspection||null;
    available=true;ready=data.ready_to_arm===true&&readiness?.eligible===true;
    // Use the server's freshness budget and monotonic time, not phone clock.
    validUntil=started+data.safety_valid_for_seconds*1000;
    checkedAt=data.safety_checked_at||null;
    lastRemaining=schedule.remaining_seconds;lastTick=performance.now();
    if(!isReady())$("live-power-loss-accepted").checked=false;
  }

  function list(id,items){
    const node=$(id);node.replaceChildren();
    for(const text of items){const item=document.createElement("li");item.textContent=String(text);node.append(item);}
  }

  function renderInspection(){
    const fresh=available&&performance.now()<validUntil;
    const info=fresh?inspection:null;
    const gate=fresh?readiness:null;
    const atlas=info?.atlas_control||{};
    put("live-details-status",!authorized()?"Owner access required":!fresh?"Unverified":isReady()?"Ready with warnings":"Blocked");
    put("live-inspection-age",!fresh
      ?"No current verified snapshot. The controls and these details are locked together."
      :"Same signed Ubuntu report as the power controls · checked "+
        (checkedAt?new Date(checkedAt).toLocaleTimeString("en-GB"):"recently"));
    put("guard-atlas",info?.atlas_state==="active"?"Service online":info?.atlas_state==="inactive"?"Service inactive":"Unknown");
    const labels={running:"RUN · executing",armed_idle:"RUN · can dispatch",
      owner_stop_draining:"Owner STOP · draining",owner_stop_no_active_attempts:"Owner STOP · no active attempts",
      unverified_stop:"STOP · origin unknown",unavailable:"Unknown"};
    put("guard-atlas-dispatch",labels[atlas.status]||"Unknown");
    put("guard-owner-switches",Number.isInteger(gate?.codex_owner_paused_count)
      ?gate.codex_owner_paused_count+" / 3 explicitly OFF":"Unknown");
    put("guard-atlas-attempts",Number.isInteger(gate?.active_jobs)?gate.active_jobs+" active":"Unknown");
    put("guard-cpuwm",gate?.cpuwm_verified===true?"Verified · no managed jobs":fresh?"Not verified":"Unknown");
    put("guard-processes",gate?.processes_verified===true?"Scan available · see blockers":fresh?"Not verified":"Unknown");
    put("guard-desktop","Unverified · saving is optional; loss consent is required");
    const proof=atlas.codex_stop||{};
    const supported=fresh&&typeof proof.status==="string"&&proof.status!=="unsupported";
    $("live-proof-details").hidden=!supported;
    const proofLabels={not_requested:"Not requested",draining:"Waiting for workers",stale:"Expired · recheck",
      resumed:"Codex resumed",invalid:"Invalid proof",unavailable:"Unavailable",verified:"Verified owner stop"};
    put("guard-codex-stop",proofLabels[proof.status]||"Not available");
    put("guard-stop-acks",Number.isInteger(proof.expected_workers)
      ?(proof.acknowledged_workers||0)+" / "+proof.expected_workers+" workers":"—");
    put("guard-stop-barrier",proof.dispatch_frozen===true?"Reported active":"Not verified");
    const blockers=Array.isArray(gate?.blockers)?gate.blockers:[];
    const warnings=Array.isArray(gate?.warnings)?gate.warnings:
      ["Unsaved files may be permanently lost. Saving is optional; explicit acceptance is required."];
    const shownBlockers=!fresh?["Current signed Ubuntu safety evidence is unavailable."]:blockers;
    $("live-hard-blockers").hidden=shownBlockers.length===0;
    list("live-blocking-details",shownBlockers);list("live-power-details",warnings);
    put("live-power-count",warnings.length);
  }

  function render(){
    const control=authorized(),allowed=isReady(),locked=busyState();
    $("live-power-readiness").classList.toggle("is-ready",allowed);
    $("live-power-readiness").classList.toggle("is-blocked",!allowed);
    put("live-power-headline",!control?"Owner access required":!available||performance.now()>=validUntil
      ?"Waiting for a fresh safety check":allowed?"Atlas & active jobs verified for power":"Shutdown blocked by workstation safeguards");
    put("live-power-description",allowed
      ?"Unsaved files are allowed only after explicit data-loss acceptance and final confirmation."
      :"Idle is not owner STOP. Current Atlas, Codex and job checks must pass.");
    put("live-power-capability",!control?"Locked":!available||performance.now()>=validUntil?"Unverified":allowed?"Ready with warnings":"Blocked");
    const fresh=available&&performance.now()<validUntil;
    put("live-atlas-fact","Atlas · "+(fresh&&readiness?.atlas_owner_paused===true?"owner STOP":"not verified"));
    put("live-codex-fact","Codex · "+(fresh&&Number.isInteger(readiness?.codex_owner_paused_count)?readiness.codex_owner_paused_count+"/3 owner OFF":"unknown"));
    put("live-job-fact","Active jobs · "+(fresh&&Number.isInteger(readiness?.active_jobs)?readiness.active_jobs:"unknown"));
    document.querySelectorAll("[data-live-mode]").forEach(b=>{
      const selected=b.dataset.liveMode===mode;b.classList.toggle("selected",selected);
      b.setAttribute("aria-pressed",String(selected));b.disabled=locked||mutating||confirming;
    });
    document.querySelectorAll("[data-live-delay]").forEach(b=>{
      const selected=Number(b.dataset.liveDelay)===minutes;b.classList.toggle("selected",selected);
      b.setAttribute("aria-pressed",String(selected));b.disabled=locked||mutating||confirming;
    });
    const custom=!Array.from(document.querySelectorAll("[data-live-delay]")).some(b=>Number(b.dataset.liveDelay)===minutes);
    put("live-custom-picker",custom?window.UbuntuIOS.displayDuration(minutes):"Custom…");
    $("live-custom-picker").classList.toggle("selected",custom);
    $("live-custom-picker").disabled=locked||mutating||confirming;
    const ack=$("live-power-loss-accepted");ack.disabled=locked||mutating||confirming;
    put("live-power-arm","Schedule real "+(mode==="shutdown"?"shutdown":"restart")+" · "+(minutes===0?"30s":window.UbuntuIOS.displayDuration(minutes)));
    $("live-power-arm").disabled=!allowed||!ack.checked||locked||mutating||confirming||loading;
    $("live-power-cancel").disabled=!canTryCancel();
    $("live-clock-panel").classList.toggle("is-armed",schedule.state==="armed");
    $("live-clock-panel").classList.toggle("is-blocked",schedule.state==="blocked"||!available&&locked);
    const states={absent:"No scheduled action",armed:(schedule.action==="restart"?"Restart":"Shutdown")+" is armed",
      dispatching:"Dispatch reserved · cancellation unavailable",sent:"Power command sent · outcome unverified",
      completed_unverified:"Power command outcome unverified",canceled:"Timer canceled",expired:"Timer expired without dispatch",
      blocked:"Safety check blocked dispatch"};
    put("live-timer-state",!available&&locked?"Timer status unverified · may still run":
      !available&&schedule.state==="absent"?"Timer status unavailable":
      possibleArm?"Request outcome unknown · check or cancel":states[schedule.state]||"Timer status unavailable");
    put("live-timer-detail",schedule.state==="armed"
      ?(Number(schedule.remaining_seconds)===0
        ? "Final signed safety verification · cancel remains available (max 30s)"
        : "Cancel before dispatch · the Pi and Ubuntu recheck safety")
      :schedule.detail||"No power is scheduled or pending");
    const remaining=Math.max(0,Math.ceil(lastRemaining-(performance.now()-lastTick)/1000));
    const two=n=>String(n).padStart(2,"0"),h=Math.floor(remaining/3600),m=Math.floor(remaining%3600/60),sec=remaining%60;
    put("live-timer-countdown",schedule.state==="armed"&&available
      ?remaining?(h?h+":"+two(m)+":"+two(sec):two(m)+":"+two(sec)):"Checking…":"—");
    renderInspection();
  }

  async function refresh(){
    if(loading||mutating)return;
    if(!authorized()){invalidate("Verified owner access is required");return;}
    loading=true;const ticket=epoch,started=performance.now();render();
    try{
      const data=await request("/api/power/live");
      if(ticket!==epoch||!authorized())return;
      adopt(data,started);
      put("live-power-status",schedule.state==="armed"
        ?"Real power timer is armed on the Pi. Closing this app does not cancel it."
        :schedule.state==="sent"||schedule.state==="completed_unverified"
        ?"A power command was sent; shutdown or restart has not been confirmed. Verify Ubuntu separately."
        :schedule.state==="blocked"?"Fresh safety checks blocked this timer; no power command was dispatched."
        :"One real timer only. Opening Safety details never runs a command. Unsaved-file loss requires your explicit acceptance.");
    }catch{if(ticket===epoch)invalidate("Private Hub connection or signed readiness unavailable");}
    finally{loading=false;render();}
  }

  async function write(path,body){
    if(!app.session)app.session=await api("/api/session");
    return request(path,{method:"POST",headers:{"Content-Type":"application/json","X-UC-CSRF":app.session.csrf,"X-UC-Power-Protocol":"2"},body:JSON.stringify(body)});
  }

  async function arm(){
    if(mutating||confirming||loading||busyState()||!isReady()||!$("live-power-loss-accepted").checked)return;
    const operation=mode,delay=minutes;confirming=true;render();
    const approved=await window.UbuntuIOS.confirm({
      tone:"danger",symbol:operation==="shutdown"?"⏻":"↻",eyebrow:"REAL UBUNTU POWER · FINAL OWNER CONFIRMATION",
      title:operation==="shutdown"?"Shut down Ubuntu?":"Restart Ubuntu?",
      message:"This is a REAL power action scheduled "+delayLabel(delay)+".",
      note:"DATA LOSS WARNING: Unsaved documents, browser forms and terminal work may be irreversibly lost. You may proceed WITHOUT saving or closing them. Atlas and active job checks stay mandatory. You may cancel only before dispatch.",
      confirmText:"Confirm "+(operation==="shutdown"?"shutdown":"restart")+" · accept data loss",
    });
    confirming=false;
    if(!approved||!authorized()||!$("live-power-loss-accepted").checked){render();return;}
    mutating=true;epoch++;render();let submitted=false;
    try{
      const started=performance.now();const data=await request("/api/power/live");
      adopt(data,started);
      if(!isReady()||busyState()||!$("live-power-loss-accepted").checked)throw Error("Readiness or timer state changed. Confirm again after refreshing.");
      $("live-power-loss-accepted").checked=false;
      submitted=true;possibleArm=true;
      const sentAt=performance.now();
      const result=await write("/api/power/live/arm",{action:operation,delay_minutes:delay,ack_unsaved_loss:true,confirm:true});
      if(result.ok!==true||result.schedule?.state!=="armed")throw Error("The Pi did not confirm an armed timer");
      adopt(result,sentAt);
      window.UbuntuIOS.notify("Real power timer armed. Cancel before dispatch if needed.");
    }catch(error){
      if(submitted){possibleArm=true;invalidate("Power request outcome is uncertain");}
      else put("live-power-status","No power request submitted: "+error.message);
      window.UbuntuIOS.notify(submitted?"Power request may have reached the Pi. Refresh or try Cancel timer.":error.message,true);
    }finally{mutating=false;render();void refresh();}
  }

  async function cancel(){
    if(!canTryCancel())return;
    mutating=true;epoch++;render();
    try{
      // Bind cancellation to the timer the owner saw. A stale tab must not
      // cancel a replacement timer created from another device.
      if(possibleArm||!schedule.schedule_id){
        const started=performance.now();
        adopt(await request("/api/power/live"),started);
      }
      const result=await write("/api/power/live/cancel",schedule.schedule_id
        ?{schedule_id:schedule.schedule_id}:{});
      if(result.ok!==true||!result.schedule||!["canceled","absent","blocked","expired","completed_unverified"].includes(result.schedule.state))
        throw Error("Cancellation was not confirmed");
      schedule=result.schedule;possibleArm=false;lastRemaining=0;
      put("live-power-status",schedule.state==="canceled"?"Timer cancellation confirmed by the Pi. No command was dispatched for this timer.":"No armed timer is reported. An earlier dispatched command cannot be recalled.");
      window.UbuntuIOS.notify(schedule.state==="canceled"?"Power timer canceled.":"No armed timer remains; verify any earlier command separately.");
    }catch(error){put("live-power-status","Cancellation could not be confirmed. A pending timer may still execute. "+error.message);window.UbuntuIOS.notify("Cancellation unconfirmed. Check the Pi connection and timer state.",true);}
    finally{mutating=false;render();void refresh();}
  }

  function init(){
    document.querySelectorAll("[data-live-mode]").forEach(b=>b.addEventListener("click",()=>{if(!busyState()&&!mutating&&!confirming){mode=b.dataset.liveMode;render();}}));
    document.querySelectorAll("[data-live-delay]").forEach(b=>b.addEventListener("click",()=>{if(!busyState()&&!mutating&&!confirming){minutes=Number(b.dataset.liveDelay);render();}}));
    $("live-custom-picker").addEventListener("click",()=>{
      if(busyState()||mutating||confirming)return;
      window.UbuntuIOS.openLiveDuration(minutes||15,value=>{if(Number.isInteger(value)&&value>=1&&value<=240){minutes=value;render();}});
    });
    $("live-power-loss-accepted").addEventListener("change",render);
    $("live-power-arm").addEventListener("click",()=>void arm());
    $("live-power-cancel").addEventListener("click",()=>void cancel());
    setInterval(()=>{if(!document.hidden){if(!isReady())$("live-power-loss-accepted").checked=false;render();}},1000);
    setInterval(()=>{if(!document.hidden&&(app.tab==="control"||busyState()))void refresh();},3000);
    document.addEventListener("visibilitychange",()=>{if(!document.hidden){ready=false;validUntil=0;$("live-power-loss-accepted").checked=false;render();void refresh();}});
    render();
  }
  window.UbuntuRealPower={init,refresh,invalidate,open:()=>{switchTab("control");$("real-power-card").scrollIntoView({behavior:"smooth",block:"start"});void refresh();}};
})();
