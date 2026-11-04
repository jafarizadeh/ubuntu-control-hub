"use strict";
/* Files & Folders: owner-confirmed fixed GNOME actions; no web terminal
 * shell, arbitrary path, remote command argument, deletion or silent save.
 */
(() => {
  const $=id=>document.getElementById(id);
  const CLOSE=new Set(["desktop.close_documents","desktop.close_terminals"]);
  const ACTIONS={
    "desktop.close_documents":{
      id:"desktop-close-documents",name:"Close open documents & web pages",
      confirmation:{
        tone:"danger",symbol:"▣",
        eyebrow:"FILES & FOLDERS · PERMANENT DATA LOSS WARNING",
        title:"Close all documents and web pages?",
        message:"Request the closure of all supported open document/file windows and browser windows.",
        note:"UNSAVED WORK MAY BE PERMANENTLY LOST. Chrome browser windows and their open tabs may close without further save prompts. Files on disk are not deleted. Atlas and active workloads must remain stopped.",
        confirmText:"Close files & web pages",
      },
    },
    "desktop.close_terminals":{
      id:"desktop-close-terminals",name:"Close terminal windows",
      confirmation:{
        tone:"danger",symbol:"⌘",
        eyebrow:"TERMINALS · RUNNING SHELLS",
        title:"Close every terminal window?",
        message:"Request closure of all GNOME terminal windows, including Ptyxis.",
        note:"RUNNING SHELL COMMANDS MAY STOP and terminal history or unsaved work may be lost. Atlas must be stopped, no model jobs may be active. If GPT Remote was started inside a terminal, closing that terminal may disconnect it.",
        confirmText:"Close all terminals",
      },
    },
    "desktop.start_gpt_remote":{
      id:"desktop-start-gpt",name:"Open GPT Remote terminal",
      confirmation:{
        tone:"standard",symbol:"⌘",
        eyebrow:"PRIVATE GPT REMOTE · LOCAL TERMINAL",
        title:"Open GPT Remote terminal?",
        message:"Open a new Ubuntu terminal for Desktop Commander Remote.",
        note:"The existing GPT Remote connection will be preserved if it is already running. Otherwise the installed Desktop Commander CLI starts in the new terminal. No arbitrary shell command is accepted from this app.",
        confirmText:"Open GPT Remote",
      },
    },
    "desktop.open_terminal":{
      id:"desktop-open-terminal",name:"Open a normal Ubuntu terminal",
      confirmation:{
        tone:"standard",symbol:"⌘",
        eyebrow:"UBUNTU · TERMINAL",
        title:"Open a new terminal?",
        message:"Open a normal Ptyxis window on the Ubuntu desktop.",
        note:"The terminal opens locally on Ubuntu. No shell commands are sent through the phone.",
        confirmText:"Open terminal",
      },
    },
  };
  let last=null;
  let busy=false;
  let fresh=false;

  function allowed(){
    if(typeof app==="undefined"||!app.canControl||!app.lastStatus||
       typeof commandAuthorizedAndReady!=="function")return false;
    return commandAuthorizedAndReady()&&last?.available===true&&!busy;
  }
  function count(value){return Number.isInteger(value)&&value>=0&&value<=180?String(value):"—";}
  function render(status){
    last=status&&typeof status==="object"?status:null;
    fresh=Boolean(last&&last.available===true);
    $("desktop-browser-count").textContent=count(last?.browser_windows);
    $("desktop-document-count").textContent=count(last?.document_windows);
    $("desktop-terminal-count").textContent=count(last?.terminal_windows);
    $("desktop-gpt-status").textContent=last?.gpt_remote_running===true
      ?"Desktop Commander Remote already active · connection preserved"
      : fresh?"Not currently active · start the installed connector"
      :"Remote desktop status unavailable";
    const canControl=allowed();
    const verifiedJobs=app.lastStatus?.desktop?.metrics?.power_safety?.real_power?.eligible===true;
    $("desktop-actions-capability").textContent=
      !canControl?"Unavailable":!verifiedJobs?"Protected":"Controls ready";
    $("desktop-close-documents").disabled=!canControl||!verifiedJobs;
    $("desktop-close-terminals").disabled=!canControl||!verifiedJobs;
    $("desktop-start-gpt").disabled=!canControl;
    $("desktop-open-terminal").disabled=!canControl;
    const done=last?.last_action;
    if(done&&Number.isInteger(done.timestamp)&&
       Date.now()/1000-done.timestamp<=86400&&Date.now()/1000-done.timestamp>=-15){
      const captions={
        "close-documents":"Files and web pages",
        "close-terminals":"Terminal windows",
        "open-terminal":"New terminal",
        "start-gpt-remote":"GPT Remote terminal",
      };
      let result=done.completed?"Confirmed closed":"Requested · verify desktop state";
      if(done.remaining>=0&&done.action.startsWith("close-")){
        result=done.remaining===0?"No target windows remain":done.remaining+" window(s) still open";
      }
      $("desktop-actions-receipt").textContent=
        (captions[done.action]||"Desktop action")+": "+result+
        " · "+new Date(done.timestamp*1000).toLocaleTimeString("en-GB");
    }else{
      $("desktop-actions-receipt").textContent=!fresh
        ?"Desktop accessibility is currently unavailable."
        :"Close actions are never performed automatically. An explicit confirmation is required.";
    }
  }

  function stale(){render(null);}
  async function run(action){
    if(!Object.hasOwn(ACTIONS,action)||busy||!allowed())return;
    const ownerReady=app.lastStatus?.desktop?.metrics?.power_safety?.real_power?.eligible===true;
    if(CLOSE.has(action)&&!ownerReady){
      window.UbuntuIOS.notify("Atlas or active work is not confirmed stopped.",true);
      return;
    }
    const approved=await window.UbuntuIOS.confirm(ACTIONS[action].confirmation);
    if(!approved||busy||!allowed())return;
    // Recheck local owner state after confirmation. The Ubuntu helper repeats
    // Atlas/job safety immediately before any destructive action.
    if(CLOSE.has(action)&&
       app.lastStatus?.desktop?.metrics?.power_safety?.real_power?.eligible!==true)return;
    busy=true;
    render(last);
    try {
      await submitCommand(action,null,ACTIONS[action].name,true);
      await refreshStatus(true);
    }finally{
      busy=false;
      render(app.lastStatus?.desktop?.metrics?.desktop_actions||null);
    }
  }
  function init(){
    for(const [name,definition] of Object.entries(ACTIONS)){
      $(definition.id).addEventListener("click",()=>void run(name));
    }
    stale();
  }
  window.UbuntuDesktopUI={init,render,stale,refresh:()=>render(app.lastStatus?.desktop?.metrics?.desktop_actions||null)};
})();
