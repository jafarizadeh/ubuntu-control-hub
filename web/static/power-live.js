"use strict";
/* Real Ubuntu power: authenticated Pi schedule, explicit owner consent, cancellable grace.
 * Never execute a power action in the browser or assume wake success from ping.
 */
(() => {
  const $=id=>document.getElementById(id);
  let mode="shutdown",minutes=0;
  let schedule={state:"absent",remaining_seconds:0,can_cancel:false};
  let ready=false,readiness=null,loading=false,mutating=false;
  let lastTick=performance.now(),lastRemaining=0;

  const delayLabel=n=>n===0?"after a 30-second safety countdown":
    n===1?"in 1 minute":n>=60?
      "in "+(n/60===Math.floor(n/60)?(n/60)+" hour"+(n===60?"":"s"):
        Math.floor(n/60)+"h "+n%60+"m"): "in "+n+" minutes";
  function displayTimer(){
    const remaining=Math.max(0,Math.ceil(lastRemaining-(performance.now()-lastTick)/1000));
    const hh=Math.floor(remaining/3600),mm=Math.floor(remaining%3600/60),ss=remaining%60;
    const two=n=>String(n).padStart(2,"0");
    $("live-timer-countdown").textContent=schedule.state==="armed"
      ? hh?hh+":"+two(mm)+":"+two(ss):two(mm)+":"+two(ss) : "—";
  }

  function render(){
    const control=Boolean(typeof app!=="undefined"&&app.canControl);
    const armed=schedule.state==="armed";
    const pending=schedule.state==="dispatching";
    const sent=schedule.state==="sent";
    const locked=armed||pending||sent;
    $("live-power-readiness").classList.toggle("is-ready",ready);
    $("live-power-readiness").classList.toggle("is-blocked",!ready);
    $("live-power-headline").textContent=!control?"Owner access required":
      ready?"Atlas & active jobs verified for power":"Shutdown blocked by workstation safeguards";
    $("live-power-description").textContent=ready
      ?"Owner confirmation and acceptance of possible unsaved-data loss are required."
      :"Stop Atlas and each Codex explicitly; ensure jobs are drained. Automatic idle does not qualify.";
    $("live-power-capability").textContent=ready?"Ready with warnings":"Blocked";
    $("live-atlas-fact").textContent="Atlas · "+(readiness?.atlas_owner_paused===true?"owner STOP":"not verified");
    $("live-codex-fact").textContent="Codex · "+(Number.isInteger(readiness?.codex_owner_paused_count)
      ?readiness.codex_owner_paused_count+"/3 owner OFF":"unknown");
    $("live-job-fact").textContent="Active jobs · "+(Number.isInteger(readiness?.active_jobs)
      ?readiness.active_jobs:"unknown");
    document.querySelectorAll("[data-live-mode]").forEach(b=>{
      const selected=b.dataset.liveMode===mode;
      b.classList.toggle("selected",selected);
      b.setAttribute("aria-pressed",String(selected));
      b.disabled=locked||mutating;
    });
    document.querySelectorAll("[data-live-delay]").forEach(b=>{
      const selected=Number(b.dataset.liveDelay)===minutes;
      b.classList.toggle("selected",selected);
      b.setAttribute("aria-pressed",String(selected));
      b.disabled=locked||mutating;
    });
    $("live-custom-picker").disabled=locked||mutating;
    const ack=$("live-power-loss-accepted");
    ack.disabled=locked||mutating;
    $("live-power-arm").textContent="Schedule real "+(mode==="shutdown"?"shutdown":"restart")
      +" · "+(minutes===0?"30s":window.UbuntuIOS.displayDuration(minutes));
    $("live-power-arm").disabled=!control||!ready||!ack.checked||locked||mutating||loading;
    $("live-power-cancel").disabled=!control||!armed||mutating;
    $("live-clock-panel").classList.toggle("is-armed",armed);
    $("live-clock-panel").classList.toggle("is-blocked",schedule.state==="blocked");
    const states={
      absent:"No scheduled action",
      armed:(schedule.action==="restart"?"Restart":"Shutdown")+" is armed",
      dispatching:"Sending to Ubuntu…",
      sent:"Power request sent to Ubuntu",
      completed_unverified:"Power command outcome unverified",
      canceled:"Timer canceled",
      expired:"Timer expired without execution",
      blocked:"Safety check blocked execution",
    };
    $("live-timer-state").textContent=states[schedule.state]||"Power state unavailable";
    $("live-timer-detail").textContent=armed
      ?"Cancel before countdown ends · rechecks Atlas at deadline":
      schedule.detail||"No power is scheduled or pending";
    displayTimer();
    const reasons=[...(readiness?.blockers||[]),...(readiness?.warnings||[])];
    const list=$("live-power-details");
    list.replaceChildren();
    for(const reason of reasons){
      const item=document.createElement("li");
      item.textContent=reason;
      list.append(item);
    }
    $("live-power-count").textContent=String(reasons.length);
  }

  async function refresh(){
    if(loading || mutating)return;
    if(typeof app==="undefined"||!app.canControl){
      ready=false;readiness=null;render();return;
    }
    loading=true;
    try{
      const data=await api("/api/power/live");
      if(!data||!data.schedule||typeof data.ready_to_arm!=="boolean")
        throw Error("Power state response unavailable");
      const previous=schedule.state;
      schedule=data.schedule;
      readiness=data.real_power;
      ready=data.ready_to_arm===true && readiness?.eligible===true;
      lastRemaining=Number.isInteger(schedule.remaining_seconds)?schedule.remaining_seconds:0;
      lastTick=performance.now();
      if(previous==="armed"&&schedule.state==="sent"){
        $("live-power-status").textContent="Power command sent to Ubuntu. The desktop may disconnect after a successful request; reboot or wake status must be confirmed separately.";
      }else if(previous==="armed"&&schedule.state==="blocked"){
        $("live-power-status").textContent="Power action was prevented by a fresh safety check. No shutdown was executed.";
      }else if(!ready&&schedule.state!=="armed"){
        $("live-power-status").textContent="Real power is locked until Atlas and active jobs are verified. The timer can never override this check.";
      }else if(ready&&schedule.state!=="armed"){
        $("live-power-status").textContent="Atlas and workload checks passed. Unsaved files are NOT a blocker after you accept the permanent data-loss risk and confirm.";
      }
    }catch{
      ready=false;
      readiness=null;
      if(schedule.state==="armed") schedule={...schedule,state:"unavailable",can_cancel:false};
      $("live-power-status").textContent="Private hub connection or power readiness unavailable. No new power request can be armed.";
    }finally{
      loading=false;render();
    }
  }

  function apiWrite(path,payload){
    return api(path,{
      method:"POST",
      headers:{"Content-Type":"application/json","X-UC-CSRF":app.session.csrf},
      body:JSON.stringify(payload),
    });
  }

  async function arm(){
    if(mutating||loading||!ready||!app.canControl||!$("live-power-loss-accepted").checked)return;
    const operation=mode,delay=minutes;
    const approved=await window.UbuntuIOS.confirm({
      tone:"danger",symbol:operation==="shutdown"?"⏻":"↻",
      eyebrow:"REAL UBUNTU POWER · FINAL OWNER CONFIRMATION",
      title:operation==="shutdown"?"Shut down Ubuntu?":"Restart Ubuntu?",
      message:"This is a REAL power action scheduled "+delayLabel(delay)+".",
      note:"DATA LOSS WARNING: Unsaved documents, browser forms and terminal work may be irreversibly lost. You may proceed WITHOUT saving or closing them. Ubuntu will request normal systemd shutdown with GNOME's session shutdown inhibitor bypassed, not forced process killing. Atlas and active job checks stay mandatory. Cancel before dispatch.",
      confirmText:"Confirm "+(operation==="shutdown"?"shutdown":"restart")+" · accept data loss",
    });
    if(!approved||!$("live-power-loss-accepted").checked)return;
    mutating=true;render();
    try{
      if(!app.session)app.session=await api("/api/session");
      const fresh=await api("/api/power/live");
      if(fresh.ready_to_arm!==true||fresh.real_power?.eligible!==true){
        throw Error("Workstation readiness changed. The timer was not armed.");
      }
      const result=await apiWrite("/api/power/live/arm",{
        action:operation,delay_minutes:delay,ack_unsaved_loss:true,confirm:true,
      });
      if(!result.ok||result.schedule?.state!=="armed")throw Error("Timer did not confirm");
      schedule=result.schedule;
      readiness=result.real_power;
      ready=result.ready_to_arm===true;
      lastRemaining=schedule.remaining_seconds;
      lastTick=performance.now();
      $("live-power-loss-accepted").checked=false;
      $("live-power-status").textContent="Real "+operation+" armed. Cancel before the deadline; the Pi will recheck safety before dispatching.";
      window.UbuntuIOS.notify("Real power timer armed. Cancel before dispatch if needed.");
    }catch(error){
      $("live-power-status").textContent="Power request not armed: "+error.message;
      window.UbuntuIOS.notify("Power request was rejected: "+error.message,true);
    }finally{
      mutating=false;render();
      void refresh();
    }
  }

  async function cancel(){
    if(mutating||schedule.state!=="armed"||!app.canControl)return;
    mutating=true;render();
    try{
      if(!app.session)app.session=await api("/api/session");
      const result=await apiWrite("/api/power/live/cancel",{});
      if(!result.ok||result.schedule?.state!=="canceled")throw Error("Cancellation was not confirmed");
      schedule=result.schedule;
      $("live-power-status").textContent="Real power timer canceled by owner. No shutdown command was dispatched.";
      window.UbuntuIOS.notify("Power timer canceled.");
    }catch(err){
      $("live-power-status").textContent="Cancellation could not be confirmed: "+err.message;
      window.UbuntuIOS.notify("Check timer state immediately: "+err.message,true);
    }finally{mutating=false;render();void refresh()}
  }

  function init(){
    document.querySelectorAll("[data-live-mode]").forEach(button=>{
      button.addEventListener("click",()=>{
        if(schedule.state==="armed"||mutating)return;
        mode=button.dataset.liveMode;
        render();
      });
    });
    document.querySelectorAll("[data-live-delay]").forEach(button=>{
      button.addEventListener("click",()=>{
        if(schedule.state==="armed"||mutating)return;
        minutes=Number(button.dataset.liveDelay);
        render();
      });
    });
    $("live-custom-picker").addEventListener("click",()=>{
      if(schedule.state==="armed"||mutating)return;
      window.UbuntuIOS.openLiveDuration(minutes===0?15:minutes,(value)=>{
        if(Number.isInteger(value)&&value>=1&&value<=240){
          minutes=value;render();
        }
      });
    });
    $("live-power-loss-accepted").addEventListener("change",render);
    $("live-power-arm").addEventListener("click",()=>void arm());
    $("live-power-cancel").addEventListener("click",()=>void cancel());
    setInterval(()=>{if(!document.hidden)displayTimer();},1000);
    setInterval(()=>{
      if(!document.hidden && (app.tab==="control"||schedule.state==="armed"))
        void refresh();
    },3000);
    document.addEventListener("visibilitychange",()=>{
      if(!document.hidden)void refresh();
    });
    render();
  }

  window.UbuntuRealPower={init,refresh,open:()=>{
    if(typeof switchTab==="function")switchTab("control");
    $("real-power-card").scrollIntoView({behavior:"smooth",block:"start"});
    void refresh();
  }};
})();
