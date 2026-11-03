/* Non-destructive browser regressions against localhost mock APIs ONLY.
 * Run: PUPPETEER_MODULE=/path/to/puppeteer CHROME_PATH=/path/to/chrome node tests/browser_unified_power.cjs
 * Never navigates to a live Hub and never starts a systemd/power command. */
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const puppeteer=require(process.env.PUPPETEER_MODULE||'puppeteer');
const ROOT=path.resolve(__dirname,'../web/static');
const MIME={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webmanifest':'application/manifest+json'};
const now=()=>Math.floor(Date.now()/1000);
const ID='a'.repeat(32),ID2='b'.repeat(32);
const empty=()=>({state:'absent',schedule_id:null,remaining_seconds:0,can_cancel:false,action:null,created_at:null,deadline:null});
let schedule,eligible,ttl,failRead,loseArm,delayRead,owner,posts,reads;
function reset(){schedule=empty();eligible=true;ttl=15;failRead=false;loseArm=false;delayRead=0;owner=true;posts=[];reads=[];}
function gate(){return {eligible,atlas_owner_paused:eligible,codex_owner_paused_count:eligible?3:0,active_jobs:0,
  cpuwm_verified:true,processes_verified:true,blockers:eligible?[]:['Atlas RUN remains armed even without current work.'],warnings:['Unsaved files may be lost permanently.']};}
function inspection(){return {status:'fresh',atlas_state:'active',atlas_control:{status:eligible?'owner_stop_no_active_attempts':'armed_idle',
  scheduler_mode:eligible?'STOP':'RUN',codex_stop:{status:'unsupported'}},cpuwm:{status:'fresh',managed_scopes:0},desktop_work:{status:'unverifiable',app_categories:['Editor']}};}
function live(){return {schedule:{...schedule},real_power:gate(),ready_to_arm:eligible&&ttl>0,
  safety_checked_at:new Date().toISOString(),safety_valid_for_seconds:ttl,inspection:inspection()};}
function telemetry(){return {desktop:{control_agent:'online',ping_reachable:true,mac_configured:true,last_agent_report_unix:now(),metrics:{
  schema_version:1,checked_at_unix:now(),hostname:'Test Ubuntu',os:'Ubuntu',uptime_s:3600,
  cpu:{logical_cores:32,usage_percent:5,per_core:[],history:[]},memory:{used_percent:20,total_mib:16000,available_mib:12800},storage:{free_gib:300},gpus:[],fans:[],
  audio:{available:true,volume_percent:40,muted:false},network:{available:true,connected:true,connections:[]},workload_manager:{available:true,profile:'balanced'},power_safety:{real_power:gate()}}},
  tv:{paired:false,ping_reachable:false,webos_api_reachable:false,power_state:'unknown'}};}
function send(res,obj,code=200){res.statusCode=code;res.setHeader('Content-Type','application/json');res.end(JSON.stringify(obj));}
const server=http.createServer((req,res)=>{
  const uri=new URL(req.url,'http://127.0.0.1').pathname;
  if(uri.startsWith('/api/')){
    if(req.method==='GET')reads.push(uri);
    if(uri==='/api/status')return send(res,telemetry());
    if(uri==='/api/session')return send(res,{csrf:'fake-test-token'});
    if(uri==='/api/control/capabilities')return send(res,{can_control:owner});
    if(uri==='/api/history')return send(res,{events:[]});
    if(uri==='/api/power/live'){
      const answer=live(),fail=failRead;
      return setTimeout(()=>{if(!res.destroyed)send(res,fail?{error:'simulated outage'}:answer,fail?503:200);},delayRead);
    }
    if(req.method==='POST'){
      let body='';req.on('data',b=>body+=b);req.on('end',()=>{
        const data=JSON.parse(body);posts.push({uri,data});
        if(uri==='/api/power/live/arm'){
          assert.equal(req.headers['x-uc-power-protocol'],'2');
          if(!eligible||!owner)return send(res,{error:'Current gate denied'},409);
          if(['armed','dispatching','sent'].includes(schedule.state))return send(res,{error:'Existing request'},409);
          assert.equal(data.ack_unsaved_loss,true);assert.equal(data.confirm,true);
          const seconds=data.delay_minutes===0?30:data.delay_minutes*60;
          schedule={state:'armed',schedule_id:ID,action:data.action,created_at:now(),deadline:now()+seconds,
            remaining_seconds:seconds,can_cancel:true,detail:'Owner-confirmed mock timer'};
          if(loseArm){failRead=true;res.writeHead(200,{'Content-Type':'application/json'});res.flushHeaders();res.write('{\"ok\":');setTimeout(()=>res.destroy(),15);return;}
          return send(res,{ok:true,...live()},202);
        }
        if(uri==='/api/power/live/cancel'){
          if(schedule.schedule_id&&data.schedule_id!==schedule.schedule_id)return send(res,{error:'Timer changed'},409);
          if(['sent','dispatching'].includes(schedule.state))return send(res,{error:'Already dispatched'},409);
          schedule={...schedule,state:'canceled',remaining_seconds:0,can_cancel:false};return send(res,{ok:true,schedule});
        }
        return send(res,{error:'Non-power commands are not part of this test'},403);
      });return;
    }
    return send(res,{error:'Unexpected API'},404);
  }
  const file=path.resolve(ROOT,'.'+(uri==='/'?'/index.html':uri));
  if(!file.startsWith(ROOT+path.sep)){res.statusCode=404;res.end();return;}
  fs.readFile(file,(err,bytes)=>{if(err){res.statusCode=404;res.end();return;}res.setHeader('Content-Type',MIME[path.extname(file)]||'application/octet-stream');res.end(bytes);});
});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const click=async(page,id)=>{await page.$eval(id,n=>n.scrollIntoView({block:'center',behavior:'instant'}));await page.click(id);};
async function fresh(page){await page.evaluate(()=>window.UbuntuRealPower.refresh());}
async function consent(page){await fresh(page);if(!await page.$eval('#live-power-loss-accepted',e=>e.checked))await click(page,'#live-power-loss-accepted');await page.waitForFunction(()=>!document.querySelector('#live-power-arm').disabled);}
async function arm(page){await consent(page);await click(page,'#live-power-arm');await page.waitForFunction(()=>document.querySelector('#ios-confirm-dialog').open);await page.click('#ios-confirm-submit');}
(async()=>{
  reset();await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await puppeteer.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  let checks=0;
  const results=[];
  async function open(width){const page=await browser.newPage();await page.setViewport({width,height:width>600?900:844,isMobile:width<600,deviceScaleFactor:width===390?2:1});await page.setBypassServiceWorker(true);
    page.on('pageerror',e=>results.push({uncaught:String(e)}));
    await page.goto('http://127.0.0.1:'+server.address().port+'/',{waitUntil:'networkidle2'});
    await page.evaluate(()=>document.querySelector('[data-tab=control]').click());
    await page.waitForFunction(()=>document.querySelector('#live-details-status').textContent==='Ready with warnings');return page;}
  try{
    for(const width of [320,390,1440]){
      reset();const page=await open(width);
      const first=await page.evaluate(()=>({cards:document.querySelectorAll('#real-power-card').length,
        preview:!!document.querySelector('#power-preview-card'),collapsed:!document.querySelector('#live-power-more').open,
        locked:document.querySelector('#live-power-arm').disabled,overflow:document.documentElement.scrollWidth>innerWidth}));
      assert.deepEqual(first,{cards:1,preview:false,collapsed:true,locked:true,overflow:false});checks++;
      await click(page,'#live-power-more summary');assert.equal(posts.length,0);
      assert.equal(await page.$eval('#live-proof-details',e=>e.hidden),true);
      if(width===390){await page.screenshot({path:'/tmp/uc-unified-power-expanded.png',fullPage:true});}
      await click(page,'#live-power-more summary');
      await click(page,'#live-custom-picker');await page.waitForFunction(()=>document.querySelector('#ios-picker-sheet').open);
      await page.evaluate(()=>{document.querySelector('#ios-hours-wheel').scrollTop=44;document.querySelector('#ios-minutes-wheel').scrollTop=25*44;});
      await page.waitForFunction(()=>document.querySelector('#ios-sheet-duration-summary').textContent.includes('1 hour 25 min'));
      await page.click('#ios-sheet-done');assert.match(await page.$eval('#live-custom-picker',e=>e.textContent),/1 hour 25 min/);checks++;
      await click(page,'[data-live-delay="0"]');await consent(page);await click(page,'#live-power-arm');
      await page.waitForFunction(()=>document.querySelector('#ios-confirm-dialog').open);await page.click('#ios-confirm-cancel');assert.equal(posts.length,0);checks++;
      await arm(page);await page.waitForFunction(()=>document.querySelector('#live-timer-state').textContent.includes('is armed'));
      assert.equal(posts[0].data.ack_unsaved_loss,true);assert.equal(posts[0].data.delay_minutes,0);
      await click(page,'#live-power-cancel');await page.waitForFunction(()=>document.querySelector('#live-timer-state').textContent==='Timer canceled');
      assert.equal(posts[1].data.schedule_id,ID);assert.equal(posts.length,2);checks++;
      assert.equal(reads.includes('/api/power/preview'),false);
      if(width===390){await page.screenshot({path:'/tmp/uc-unified-power-collapsed.png',fullPage:true});}
      results.push({width,startup:first,mock_arm_cancel:'passed',preview_requests:0});await page.close();
    }
    reset();const page=await open(390);
    schedule={state:'armed',schedule_id:ID,action:'restart',created_at:now(),deadline:now()+1800,remaining_seconds:1800,can_cancel:true};
    await fresh(page);
    assert.equal(await page.$eval('[data-live-mode="restart"]',e=>e.getAttribute('aria-pressed')),'true');
    assert.equal(await page.$eval('[data-live-delay="30"]',e=>e.getAttribute('aria-pressed')),'true');checks++;
    failRead=true;await fresh(page);
    assert.match(await page.$eval('#live-timer-state',e=>e.textContent),/may still run/);
    assert.equal(await page.$eval('#live-power-cancel',e=>e.disabled),false);
    assert.equal(await page.$eval('#live-power-arm',e=>e.disabled),true);checks++;
    await click(page,'#live-power-cancel');await page.waitForFunction(()=>document.querySelector('#live-timer-state').textContent==='Timer canceled');
    assert.equal(posts.at(-1).data.schedule_id,ID);checks++;
    failRead=false;ttl=0;await fresh(page);
    assert.equal(await page.$eval('#live-details-status',e=>e.textContent),'Unverified');
    assert.equal(await page.$eval('#live-power-arm',e=>e.disabled),true);checks++;
    ttl=15;eligible=false;await fresh(page);
    assert.equal(await page.$eval('#live-details-status',e=>e.textContent),'Blocked');
    assert.equal(await page.$eval('#guard-atlas-dispatch',e=>e.textContent),'RUN · can dispatch');checks++;
    eligible=true;schedule=empty();loseArm=true;await fresh(page);const before=posts.length;
    await arm(page);await page.waitForFunction(()=>document.querySelector('#live-timer-state').textContent.includes('may still run'),{timeout:12000});
    assert.equal(posts.length,before+1);assert.equal(schedule.state,'armed');
    assert.equal(await page.$eval('#live-power-cancel',e=>e.disabled),false);checks++;
    failRead=false;loseArm=false;await click(page,'#live-power-cancel');
    await page.waitForFunction(()=>document.querySelector('#live-timer-state').textContent==='Timer canceled');
    assert.equal(posts.at(-1).data.schedule_id,ID);checks++;
    // Simulate a stale client attempting to cancel a different device's timer.
    schedule={state:'armed',schedule_id:ID,action:'shutdown',created_at:now(),deadline:now()+60,remaining_seconds:60,can_cancel:true};
    await fresh(page);schedule={...schedule,schedule_id:ID2,action:'restart'};
    await click(page,'#live-power-cancel');await delay(400);
    assert.equal(schedule.state,'armed');assert.equal(schedule.schedule_id,ID2);
    assert.notEqual(await page.$eval('#live-timer-state',e=>e.textContent),'Timer canceled');checks++;
    schedule={...schedule,state:'sent',can_cancel:false,remaining_seconds:0};await fresh(page);
    assert.match(await page.$eval('#live-timer-state',e=>e.textContent),/outcome unverified/);
    assert.equal(await page.$eval('#live-power-cancel',e=>e.disabled),true);checks++;
    schedule=empty();await fresh(page);ttl=.2;await fresh(page);await delay(1250);
    assert.equal(await page.$eval('#live-power-arm',e=>e.disabled),true);
    assert.equal(await page.$eval('#live-details-status',e=>e.textContent),'Unverified');checks++;
    // A hung fetch must time out; stale authorization may not remain green.
    ttl=15;delayRead=9000;
    const hungAt=Date.now();await fresh(page);
    assert.ok(Date.now()-hungAt<8800,'Power fetch did not honor its 8s timeout');
    assert.equal(await page.$eval('#live-power-arm',e=>e.disabled),true);
    assert.equal(await page.$eval('#live-details-status',e=>e.textContent),'Unverified');checks++;
    delayRead=0;await fresh(page);
    assert.equal(await page.$eval('#live-details-status',e=>e.textContent),'Ready with warnings');checks++;
    assert.equal(results.some(r=>r.uncaught),false);
    await page.close();console.log(JSON.stringify({checks,results,edge_cases:'restored restart, offline cancel, stale readiness, RUN idle, lost arm response, stale-client cancel, sent state, lease expiry all passed'},null,2));
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error('UNIFIED_POWER_TEST_FAILED',e.stack);server.close();process.exitCode=1;});
