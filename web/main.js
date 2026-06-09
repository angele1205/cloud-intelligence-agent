import { Amplify } from 'aws-amplify';
import { signIn, signOut, fetchAuthSession } from 'aws-amplify/auth';
import { SignatureV4 } from '@smithy/signature-v4';
import { Sha256 } from '@aws-crypto/sha256-js';

Amplify.configure({Auth:{Cognito:{userPoolId:window.COSTOP_CONFIG?.userPoolId||'',userPoolClientId:window.COSTOP_CONFIG?.clientId||'',identityPoolId:window.COSTOP_CONFIG?.identityPoolId||''}}});

const AGENT_ARN=window.COSTOP_CONFIG?.agentArn||'';
const REGION=window.COSTOP_CONFIG?.region||'us-east-1';
let sessionId='s-'+Date.now();

// --- DARK MODE ---
window.toggleDark=()=>{
  const html=document.documentElement;
  const isDark=html.getAttribute('data-theme')==='dark';
  html.setAttribute('data-theme',isDark?'':'dark');
  localStorage.setItem('theme',isDark?'light':'dark');
  document.querySelector('.dark-toggle').textContent=isDark?'🌙':'☀️';
};
if(localStorage.getItem('theme')==='dark'){document.documentElement.setAttribute('data-theme','dark');setTimeout(()=>{const b=document.querySelector('.dark-toggle');if(b)b.textContent='☀️'},0)}

// --- AUTO-REFRESH (every 60s) ---
let refreshInterval=null;
function startAutoRefresh(){refreshInterval=setInterval(()=>{loadAlerts()},60000)}

// --- COST WIDGET ---
async function loadCostWidget(){
  try{
    const session=await fetchAuthSession();
    const signer=new SignatureV4({service:'monitoring',region:REGION,credentials:session.credentials,sha256:Sha256});
    const now=new Date();
    const start=new Date(now.getTime()-86400000).toISOString(); // last 24h
    const body=`Action=GetMetricData&Version=2010-08-01&StartTime=${start}&EndTime=${now.toISOString()}&MetricDataQueries.member.1.Id=input&MetricDataQueries.member.1.MetricStat.Metric.Namespace=AWS/Bedrock&MetricDataQueries.member.1.MetricStat.Metric.MetricName=InputTokenCount&MetricDataQueries.member.1.MetricStat.Period=3600&MetricDataQueries.member.1.MetricStat.Stat=Sum&MetricDataQueries.member.2.Id=output&MetricDataQueries.member.2.MetricStat.Metric.Namespace=AWS/Bedrock&MetricDataQueries.member.2.MetricStat.Metric.MetricName=OutputTokenCount&MetricDataQueries.member.2.MetricStat.Period=3600&MetricDataQueries.member.2.MetricStat.Stat=Sum`;
    const signed=await signer.sign({method:'POST',hostname:`monitoring.${REGION}.amazonaws.com`,path:'/',headers:{'Content-Type':'application/x-www-form-urlencoded',host:`monitoring.${REGION}.amazonaws.com`},body});
    const res=await fetch(`https://monitoring.${REGION}.amazonaws.com/`,{method:'POST',headers:signed.headers,body});
    const xml=await res.text();
    // Parse all values for input and output - sum all hourly datapoints
    const inputMatch=xml.match(/<Id>input<\/Id>[\s\S]*?<Values>([\s\S]*?)<\/Values>/);
    const outputMatch=xml.match(/<Id>output<\/Id>[\s\S]*?<Values>([\s\S]*?)<\/Values>/);
    let inputTokens=0,outputTokens=0;
    if(inputMatch){[...inputMatch[1].matchAll(/<member>([\d.]+)<\/member>/g)].forEach(m=>{inputTokens+=parseFloat(m[1])})}
    if(outputMatch){[...outputMatch[1].matchAll(/<member>([\d.]+)<\/member>/g)].forEach(m=>{outputTokens+=parseFloat(m[1])})}
    const cost=(inputTokens*0.003+outputTokens*0.015)/1000;
    document.getElementById('costWidget').textContent=cost>0.01?`~$${cost.toFixed(2)} (24h)`:'';
  }catch(e){document.getElementById('costWidget').textContent=''}
}

// --- NOTIFICATION BADGE ---
let lastSeenCount=parseInt(localStorage.getItem('lastSeenAlerts')||'0');
function updateBadge(count){
  const badge=document.getElementById('alertBadge');
  const newCount=count-lastSeenCount;
  if(newCount>0){badge.textContent=`🔔 ${newCount}`;badge.style.display='inline-block'}
  else{badge.style.display='none'}
}
window.clearBadge=()=>{const badge=document.getElementById('alertBadge');badge.style.display='none';lastSeenCount=parseInt(localStorage.getItem('lastSeenAlerts')||'0')}

// --- MOBILE TOGGLE ---
window.togglePanel=()=>{document.querySelector('.left-panel').classList.toggle('panel-open')}
window.openAlertPanel=()=>{
  const panel=document.querySelector('.left-panel');
  panel.classList.add('panel-open');
  panel.classList.add('highlight');
  setTimeout(()=>panel.classList.remove('highlight'),1500);
  clearBadge();
}

// --- STOP GENERATION ---
let abortController=null;
window.stopGeneration=()=>{
  if(abortController){abortController.abort();abortController=null}
  document.getElementById('stopBtn').classList.remove('active');
  document.getElementById('btn').disabled=false;
  document.getElementById('typing').classList.remove('active');
  document.getElementById('typingText').style.display='';
  hideProgress();
};

// --- AUTH ---
window.doLogin=async()=>{
  const u=document.getElementById('emailInput').value,p=document.getElementById('passInput').value,err=document.getElementById('loginError');
  try{try{await signOut()}catch(e){}
    const result=await signIn({username:u,password:p});
    if(result.nextStep&&result.nextStep.signInStep==='CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED'){
      document.getElementById('loginForm').style.display='none';
      document.getElementById('newPassForm').style.display='block';
      return;
    }
    document.getElementById('loginOverlay').style.display='none';loadAlerts();startAutoRefresh();loadCostWidget()}
  catch(e){err.textContent=e.message;err.style.display='block'}
};

window.doNewPassword=async()=>{
  const newPass=document.getElementById('newPassInput').value;
  const confirm=document.getElementById('confirmPassInput').value;
  const err=document.getElementById('loginError');
  if(newPass!==confirm){err.textContent='Passwords do not match';err.style.display='block';return}
  try{
    const {confirmSignIn}=await import('aws-amplify/auth');
    await confirmSignIn({challengeResponse:newPass});
    document.getElementById('loginOverlay').style.display='none';loadAlerts();startAutoRefresh();loadCostWidget();
  }catch(e){err.textContent=e.message;err.style.display='block'}
};

window.doForgotPassword=async()=>{
  const u=document.getElementById('resetUser').value;
  const err=document.getElementById('loginError');
  try{
    const {resetPassword}=await import('aws-amplify/auth');
    await resetPassword({username:u});
    document.getElementById('resetCode').style.display='block';
    document.getElementById('resetNewPass').style.display='block';
    document.getElementById('resetConfirmBtn').style.display='block';
    err.textContent='Code sent to your email';err.style.display='block';err.style.background='#F0FFF4';err.style.color='#10B981';
  }catch(e){err.textContent=e.message;err.style.display='block'}
};

window.doResetConfirm=async()=>{
  const u=document.getElementById('resetUser').value;
  const code=document.getElementById('resetCode').value;
  const newPass=document.getElementById('resetNewPass').value;
  const err=document.getElementById('loginError');
  try{
    const {confirmResetPassword}=await import('aws-amplify/auth');
    await confirmResetPassword({username:u,confirmationCode:code,newPassword:newPass});
    err.textContent='Password reset! Please login.';err.style.background='#F0FFF4';err.style.color='#10B981';err.style.display='block';
    document.getElementById('resetForm').style.display='none';
    document.getElementById('loginForm').style.display='block';
  }catch(e){err.textContent=e.message;err.style.display='block'}
};

// --- AGENT CALL ---
const INVESTIGATION_STEPS=[
  {label:'Checking alarm status',finding:'Identifying active alarms...'},
  {label:'Reading Bedrock usage',finding:'Token counts and invocation rate'},
  {label:'Querying CloudTrail',finding:'Recent changes and deployments'},
  {label:'Checking invocation logs',finding:'Per-agent session details'},
  {label:'Correlating findings',finding:'Connecting cause → effect'},
  {label:'Generating response',finding:null},
];
let progressTimer=null;
let stepIndex=0;

function renderTrail(){
  const el=document.getElementById('progressTrail');
  let html='';
  // Only render steps up to current stepIndex (not all)
  for(let i=0;i<=stepIndex&&i<INVESTIGATION_STEPS.length;i++){
    const step=INVESTIGATION_STEPS[i];
    const cls=i<stepIndex?'done':'active';
    html+=`<div class="trail-step ${cls}"><div class="trail-dot"></div><div class="trail-label">${step.label}</div>`;
    if(i<stepIndex&&step.finding) html+=`<div class="trail-finding">${step.finding}</div>`;
    html+=`</div>`;
  }
  el.innerHTML=html;
}

function showProgress(){
  const area=document.getElementById('chatArea');
  // Add trail inside chat area so it scrolls with content
  let trailEl=document.getElementById('progressTrail');
  if(!trailEl.parentElement.classList.contains('chat-area')){
    area.appendChild(trailEl);
  }
  trailEl.classList.add('active');
  document.getElementById('typingText').textContent='Investigating...';
  stepIndex=0;
  renderTrail();
  progressTimer=setInterval(()=>{
    stepIndex++;
    if(stepIndex>=INVESTIGATION_STEPS.length){clearInterval(progressTimer);return}
    renderTrail();
    area.scrollTop=area.scrollHeight;
  },3500);
}

function hideProgress(){
  clearInterval(progressTimer);
  const trailEl=document.getElementById('progressTrail');
  trailEl.classList.remove('active');
  trailEl.innerHTML='';
  // Remove trail from chat area if it was appended there
  if(trailEl.parentElement&&trailEl.parentElement.classList.contains('chat-area')){
    trailEl.remove();
    // Re-add to its original position (after typing)
    document.querySelector('.typing').after(trailEl);
  }
}

async function callAgent(prompt){
  document.getElementById('btn').disabled=true;
  document.getElementById('stopBtn').classList.add('active');
  document.getElementById('typing').classList.add('active');
  abortController=new AbortController();
  // Only show trail for investigations, not simple questions
  const isInvestigation=prompt.toLowerCase().match(/investigate|alarm|spike|anomaly|what.*cost|why.*high/);
  if(isInvestigation){showProgress();document.getElementById('typingText').style.display='none'}
  else{document.getElementById('typingText').style.display=''}
  try{
    const session=await fetchAuthSession();
    const endpoint=`https://bedrock-agentcore.${REGION}.amazonaws.com`;
    const path=`/runtimes/${encodeURIComponent(AGENT_ARN)}/invocations`;
    const body=JSON.stringify({prompt,sessionId,userId:'console',model:document.getElementById('modelSelect').value});
    const signer=new SignatureV4({service:'bedrock-agentcore',region:REGION,credentials:session.credentials,sha256:Sha256});
    const signed=await signer.sign({method:'POST',hostname:`bedrock-agentcore.${REGION}.amazonaws.com`,path,headers:{'Content-Type':'application/json',host:`bedrock-agentcore.${REGION}.amazonaws.com`},body});
    const res=await fetch(endpoint+path,{method:'POST',headers:signed.headers,body,signal:abortController.signal});
    const data=await res.json();
    addMsg(data.result||data.response||JSON.stringify(data),'agent');
  }catch(e){if(e.name!=='AbortError')addMsg('Error: '+e.message,'agent')}
  hideProgress();
  document.getElementById('btn').disabled=false;
  document.getElementById('stopBtn').classList.remove('active');
  document.getElementById('typing').classList.remove('active');
  document.getElementById('typingText').style.display='';
}

// --- STRUCTURED RESPONSE RENDERER ---
function parseStructuredResponse(text){
  // Try to extract JSON from ```json ... ``` fences
  const fenceMatch=text.match(/```json\s*([\s\S]*?)```/);
  if(fenceMatch){
    try{return JSON.parse(fenceMatch[1].trim())}catch(e){}
  }
  // Try raw JSON parse
  const trimmed=text.trim();
  if(trimmed.startsWith('{')){
    try{return JSON.parse(trimmed)}catch(e){}
  }
  return null;
}

function renderStructured(data){
  const severityColors={critical:'#EF4444',warning:'#F59E0B',info:'#3B82F6'};
  const statusColors={danger:'#EF4444',warning:'#F59E0B',ok:'#10B981'};
  let html='<div class="investigation-result">';

  // Summary card
  const sevColor=severityColors[data.severity]||'#6B7280';
  html+=`<div class="result-summary" style="border-left-color:${sevColor}">
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${sevColor};margin-right:8px"></span>
    ${escHtml(data.summary)}
  </div>`;

  // If this is a prose answer wrapped in envelope, show the full message
  if(data.message&&(!data.findings||data.findings.length===0)){
    html+=`<div class="result-section"><div class="raw-response">${renderMarkdown(data.message)}</div></div>`;
    html+='</div>';
    return html;
  }

  // Findings
  if(data.findings&&data.findings.length){
    html+='<div class="result-section"><h4>Findings</h4><div class="findings-grid">';
    data.findings.forEach(f=>{
      if(!f)return;
      const label=f.label||f.name||f.title||f.key||Object.keys(f)[0]||'Finding';
      const value=f.value||f.description||f.detail||f.details||f[Object.keys(f)[1]]||'';
      const cls=(f.status||'')=='danger'?'danger':'';
      html+=`<div class="finding-card ${cls}"><strong>${escHtml(String(label))}</strong><br/>${escHtml(String(value))}</div>`;
    });
    html+='</div></div>';
  }

  // Timeline
  if(data.timeline&&data.timeline.length){
    html+='<div class="result-section"><h4>Timeline</h4><div class="timeline">';
    data.timeline.forEach(t=>{
      if(!t||!t.time)return;
      html+=`<div class="timeline-item"><span class="tl-time">${escHtml(t.time||'')}</span><span class="tl-event">${escHtml(t.event||'')}</span></div>`;
    });
    html+='</div></div>';
  }

  // Actions
  if(data.actions&&data.actions.length){
    html+='<div class="result-section"><h4>Actions</h4><div class="action-buttons">';
    data.actions.forEach(a=>{
      if(!a)return;
      const label=a.label||a.action||a.name||a.title||'Action';
      const prompt=a.prompt||a.command||a.description||label;
      const destructive=a.destructive||false;
      const cls=destructive?'destructive':'';
      html+=`<button class="action-btn ${cls}" onclick="executeAction('${escAttr(prompt)}')">${escHtml(String(label))}</button>`;
    });
    html+='</div></div>';
  }

  // Blind spots
  if(data.blind_spots){
    html+=`<div class="result-section" style="font-size:11px;color:#6B7280;background:#F9FAFB;padding:10px 14px;border-radius:8px">
      ⚠️ <strong>Blind spots:</strong> ${escHtml(data.blind_spots)}
    </div>`;
  }

  html+='</div>';
  return html;
}

function renderMarkdown(text){
  return text
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/\n/g,'<br>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/### (.*?)(<br>|$)/g,'<h3 style="font-size:14px;margin:12px 0 6px">$1</h3>')
    .replace(/## (.*?)(<br>|$)/g,'<h3 style="font-size:15px;margin:14px 0 6px">$1</h3>');
}

function escHtml(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function escAttr(s){return String(s||'').replace(/'/g,'\\\'').replace(/"/g,'&quot;')}

// --- ALERTS (direct CloudWatch + Budgets + DynamoDB investigations) ---
async function loadAlerts(){
  const alertList=document.getElementById('alertList');
  // Don't blank the panel during refresh - only update when new content is ready
  const tempDiv=document.createElement('div');
  try{
    const session=await fetchAuthSession();
    const signer=new SignatureV4({service:'monitoring',region:REGION,credentials:session.credentials,sha256:Sha256});

    // Load past investigations from DynamoDB
    const investigations=await loadInvestigations(session);

    // Load budget alerts
    const budgetAlerts=await loadBudgetAlerts(session);

    // Load cost anomalies
    const anomalies=await loadCostAnomalies(session);

    const b1='Action=DescribeAlarms&Version=2010-08-01&AlarmNamePrefix='+window.ALARM_PREFIX+'';
    const s1=await signer.sign({method:'POST',hostname:`monitoring.${REGION}.amazonaws.com`,path:'/',headers:{'Content-Type':'application/x-www-form-urlencoded',host:`monitoring.${REGION}.amazonaws.com`},body:b1});
    const r1=await fetch(`https://monitoring.${REGION}.amazonaws.com/`,{method:'POST',headers:s1.headers,body:b1});
    const x1=await r1.text();
    const curNames=[...x1.matchAll(/<AlarmName>(.*?)<\/AlarmName>/g)];
    const curStates=[...x1.matchAll(/<StateValue>(.*?)<\/StateValue>/g)];

    const start=new Date(Date.now()-86400000*3).toISOString();
    const b2=`Action=DescribeAlarmHistory&Version=2010-08-01&HistoryItemType=StateUpdate&StartDate=${start}&MaxRecords=100`;
    const s2=await signer.sign({method:'POST',hostname:`monitoring.${REGION}.amazonaws.com`,path:'/',headers:{'Content-Type':'application/x-www-form-urlencoded',host:`monitoring.${REGION}.amazonaws.com`},body:b2});
    const r2=await fetch(`https://monitoring.${REGION}.amazonaws.com/`,{method:'POST',headers:s2.headers,body:b2});
    const x2=await r2.text();
    const hNames=[...x2.matchAll(/<AlarmName>(.*?)<\/AlarmName>/g)];
    const hTimes=[...x2.matchAll(/<Timestamp>(.*?)<\/Timestamp>/g)];
    const hSummaries=[...x2.matchAll(/<HistorySummary>(.*?)<\/HistorySummary>/g)];

    const byDate={};
    hNames.forEach((n,i)=>{
      if(!n[1].startsWith(''+window.ALARM_PREFIX+''))return;
      const ts=hTimes[i]?new Date(hTimes[i][1]):new Date();
      const sum=hSummaries[i]?hSummaries[i][1]:'';
      const isAlarm=sum.includes('to ALARM');
      const dateKey=ts.toLocaleDateString('en-US',{month:'short',day:'numeric'});
      if(!byDate[dateKey])byDate[dateKey]=[];
      byDate[dateKey].push({name:n[1],label:n[1].replace(''+window.ALARM_PREFIX+'-',''),time:ts.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}),isAlarm});
    });

    let html='';

    // Current firing alarms
    const live=curNames.filter((_,i)=>curStates[i]&&curStates[i][1]==='ALARM');
    html+=`<div class="section-label">Current Status</div>`;
    if(live.length||budgetAlerts.breached.length){
      if(live.length) html+=live.map(a=>`<div class="alert-item" onclick="investigateAlert('${a[1]}')"><div class="title"><span class="severity critical"></span>${a[1].replace(''+window.ALARM_PREFIX+'-','')}</div><div class="meta">🔴 ALARM — click to investigate</div></div>`).join('');
      if(budgetAlerts.breached.length) html+=budgetAlerts.breached.map(b=>`<div class="alert-item" onclick="investigateAlert('Budget-${b.name}')"><div class="title"><span class="severity critical"></span>💰 ${escHtml(b.name)}</div><div class="meta">🔴 BREACHED — ${b.actual} of ${b.limit}</div></div>`).join('');
    }else{
      html+=`<div style="padding:8px 14px;font-size:12px;color:#10B981">✅ All Clear</div>`;
    }

    // Budget warnings (approaching limit)
    if(budgetAlerts.warnings.length){
      html+=`<div class="section-label">Budget Warnings</div>`;
      html+=budgetAlerts.warnings.map(b=>`<div class="alert-item" onclick="executeAction('What is my budget status? Am I over budget for ${b.name}?')"><div class="title"><span class="severity warning"></span>💰 ${escHtml(b.name)}</div><div class="meta">⚠️ ${b.pct}% used — ${b.actual} of ${b.limit}</div></div>`).join('');
    }

    // Cost anomalies
    if(anomalies.length){
      html+=`<div class="section-label">Cost Anomalies <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${anomalies.length}</span></div>`;
      anomalies.forEach(a=>{
        html+=`<div class="alert-item" onclick="executeAction('Investigate cost anomaly: ${escAttr(a.service)} anomaly detected on ${escAttr(a.start)}, impact $${a.impact}')"><div class="title"><span class="severity ${a.impact>50?'critical':'warning'}"></span>${escHtml(a.service)}</div><div class="meta">$${a.impact} impact — ${a.start}</div></div>`;
      });
    }

    // Past investigations from DynamoDB
    if(investigations.length){
      html+=`<div class="section-label date-header" onclick="this.nextElementSibling.classList.toggle('hidden')" style="cursor:pointer">Investigation History <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${investigations.length}</span></div>`;
      html+=`<div class="tree-section hidden">`;
      const invByDate={};
      investigations.forEach(inv=>{
        const ts=new Date(inv.timestamp);
        const dateKey=ts.toLocaleDateString('en-US',{month:'short',day:'numeric'});
        if(!invByDate[dateKey])invByDate[dateKey]=[];
        invByDate[dateKey].push(inv);
      });
      Object.entries(invByDate).forEach(([date,invs])=>{
        html+=`<div class="section-label" onclick="this.nextElementSibling.classList.toggle('hidden')" style="cursor:pointer;font-size:11px;font-weight:600;border-top:none">${date} <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${invs.length}</span></div>`;
        html+=`<div class="tree-section hidden">`;
        invs.forEach(inv=>{
          const sevClass=inv.severity==='critical'?'critical':inv.severity==='warning'?'warning':'info';
          const timeStr=new Date(inv.timestamp).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
          html+=`<div class="alert-item" onclick='showInvestigation(${JSON.stringify(inv).replace(/'/g,"&#39;")})'>`;
          html+=`<div class="title"><span class="severity ${sevClass}"></span>${escHtml(inv.alarm_name||'Investigation')}</div>`;
          html+=`<div class="meta">${timeStr} — ${escHtml((inv.summary||'').substring(0,60))}</div>`;
          html+=`</div>`;
        });
        html+=`</div>`;
      });
      html+=`</div>`;
    }

    // Alarm history
    const todayKey=new Date().toLocaleDateString('en-US',{month:'short',day:'numeric'});
    const todayEvents=byDate[todayKey]||[];
    const pastDates=Object.entries(byDate).filter(([k])=>k!==todayKey);

    // Alarm history - all under one parent
    const allSpikes=Object.values(byDate).flat().filter(e=>e.isAlarm).length;
    if(allSpikes){
      html+=`<div class="section-label date-header" onclick="this.nextElementSibling.classList.toggle('hidden')" style="cursor:pointer">Alarm History <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${allSpikes}</span></div>`;
      html+=`<div class="tree-section">`;

      // Today
      if(todayEvents.length){
        const spikes=todayEvents.filter(e=>e.isAlarm).length;
        if(spikes){
          html+=`<div class="section-label" onclick="this.nextElementSibling.classList.toggle('hidden')" style="cursor:pointer;font-size:11px;font-weight:600;border-top:none">Today <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${spikes}</span></div>`;
          html+=`<div class="tree-section">`;
          const byAlarm={};
          todayEvents.forEach(e=>{if(!byAlarm[e.label])byAlarm[e.label]=[];byAlarm[e.label].push(e)});
          Object.entries(byAlarm).forEach(([label,alarmEvents])=>{
            const fires=alarmEvents.filter(e=>e.isAlarm).length;
            if(!fires)return;
            html+=`<div class="alert-item tree-parent" onclick="const c=this.querySelector('.tree-children');if(c)c.classList.toggle('hidden')">`;
            html+=`<div class="title" style="display:flex;justify-content:space-between;align-items:center"><span><span class="severity critical"></span>${label} <span style="font-size:10px;color:#DC2626;font-weight:400">(${fires}x)</span></span><button class="investigate-btn" onclick="event.stopPropagation();investigateAlert('${alarmEvents[0].name}')">Investigate All</button></div>`;
            html+=`<div class="meta">${alarmEvents[0].time} — ${alarmEvents[alarmEvents.length-1].time}</div>`;
            html+=`<div class="tree-children hidden" onclick="event.stopPropagation()">`;
            alarmEvents.forEach(e=>{html+=`<div class="tree-child"><span>${e.time} ${e.isAlarm?'🔴 Fired':'✅ Resolved'}</span>${e.isAlarm?`<button class="investigate-btn" onclick="investigateAlert('${e.name}')">Investigate</button>`:''}</div>`});
            html+=`</div>`;
            html+=`</div>`;
          });
          html+=`</div>`;
        }
      }

      // Past dates
      pastDates.forEach(([date,events])=>{
        const spikes=events.filter(e=>e.isAlarm).length;
        html+=`<div class="section-label" onclick="this.nextElementSibling.classList.toggle('hidden')" style="cursor:pointer;font-size:11px;font-weight:600;border-top:none">${date} <span class="badge" style="display:inline-block;font-size:9px;padding:1px 5px">${spikes}</span></div>`;
        html+=`<div class="tree-section hidden">`;
        const byAlarm={};
        events.forEach(e=>{if(!byAlarm[e.label])byAlarm[e.label]=[];byAlarm[e.label].push(e)});
        Object.entries(byAlarm).forEach(([label,alarmEvents])=>{
          const fires=alarmEvents.filter(e=>e.isAlarm).length;
          if(!fires)return;
          html+=`<div class="alert-item tree-parent" onclick="const c=this.querySelector('.tree-children');if(c)c.classList.toggle('hidden')">`;
          html+=`<div class="title" style="display:flex;justify-content:space-between;align-items:center"><span><span class="severity warning"></span>${label} <span style="font-size:10px;color:#DC2626;font-weight:400">(${fires}x)</span></span><button class="investigate-btn" onclick="event.stopPropagation();investigateAlert('${alarmEvents[0].name}')">Investigate All</button></div>`;
          html+=`<div class="meta">${alarmEvents[0].time} — ${alarmEvents[alarmEvents.length-1].time}</div>`;
          html+=`<div class="tree-children hidden" onclick="event.stopPropagation()">`;
          alarmEvents.forEach(e=>{html+=`<div class="tree-child"><span>${e.time} ${e.isAlarm?'🔴 Fired':'✅ Resolved'}</span>${e.isAlarm?`<button class="investigate-btn" onclick="investigateAlert('${e.name}')">Investigate</button>`:''}</div>`});
          html+=`</div>`;
          html+=`</div>`;
        });
        html+=`</div>`;
      });

      html+=`</div>`;
    }

    alertList.innerHTML=html||'<div style="padding:12px;color:var(--text-faint);font-size:11px">No data</div>';
    // Update badge
    const totalAlerts=live.length+budgetAlerts.breached.length+investigations.length+anomalies.length;
    localStorage.setItem('lastSeenAlerts',String(totalAlerts));
    updateBadge(totalAlerts);
  }catch(e){if(!alertList.innerHTML.trim())alertList.innerHTML='<div style="padding:12px;color:#EF4444;font-size:11px">'+e.message+'</div>'}
}

async function loadBudgetAlerts(session){
  try{
    const signer=new SignatureV4({service:'budgets',region:REGION,credentials:session.credentials,sha256:Sha256});
    const body=JSON.stringify({AccountId:window.COSTOP_CONFIG?.accountId||'',MaxResults:20});
    const signed=await signer.sign({method:'POST',hostname:`budgets.amazonaws.com`,path:'/',headers:{'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'AWSBudgetServiceGateway.DescribeBudgets',host:'budgets.amazonaws.com'},body});
    const res=await fetch('https://budgets.amazonaws.com/',{method:'POST',headers:{...signed.headers,'X-Amz-Target':'AWSBudgetServiceGateway.DescribeBudgets','Content-Type':'application/x-amz-json-1.1'},body});
    const data=await res.json();
    const breached=[],warnings=[];
    (data.Budgets||[]).forEach(b=>{
      const limit=parseFloat(b.BudgetLimit?.Amount||0);
      const actual=parseFloat(b.CalculatedSpend?.ActualSpend?.Amount||0);
      const pct=limit>0?Math.round((actual/limit)*100):0;
      const item={name:b.BudgetName,limit:`$${limit}`,actual:`$${actual.toFixed(2)}`,pct};
      if(pct>=100)breached.push(item);
      else if(pct>=80)warnings.push(item);
    });
    return {breached,warnings};
  }catch(e){return {breached:[],warnings:[]}}
}

async function loadCostAnomalies(session){
  try{
    const signer=new SignatureV4({service:'ce',region:'us-east-1',credentials:session.credentials,sha256:Sha256});
    const end=new Date().toISOString().split('T')[0];
    const start=new Date(Date.now()-7*86400000).toISOString().split('T')[0];
    const body=JSON.stringify({DateInterval:{StartDate:start,EndDate:end},MaxResults:5});
    const signed=await signer.sign({method:'POST',hostname:'ce.us-east-1.amazonaws.com',path:'/',headers:{'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'AWSInsightsIndexService.GetAnomalies',host:'ce.us-east-1.amazonaws.com'},body});
    const res=await fetch('https://ce.us-east-1.amazonaws.com/',{method:'POST',headers:{...signed.headers,'X-Amz-Target':'AWSInsightsIndexService.GetAnomalies','Content-Type':'application/x-amz-json-1.1'},body});
    const data=await res.json();
    return (data.Anomalies||[]).map(a=>({
      service:(a.RootCauses||[{}])[0].Service||'Unknown',
      start:a.AnomalyStartDate||'',
      impact:Math.round(parseFloat(a.Impact?.TotalImpact||0))
    }));
  }catch(e){return []}
}

async function loadInvestigations(session){
  try{
    const signer=new SignatureV4({service:'dynamodb',region:REGION,credentials:session.credentials,sha256:Sha256});
    const body=JSON.stringify({TableName:window.COSTOP_CONFIG?.investigationsTable||window.INVESTIGATIONS_TABLE||'cost_investigations',Limit:20,ScanIndexForward:false});
    const signed=await signer.sign({method:'POST',hostname:`dynamodb.${REGION}.amazonaws.com`,path:'/',headers:{'Content-Type':'application/x-amz-json-1.0','X-Amz-Target':'DynamoDB_20120810.Scan',host:`dynamodb.${REGION}.amazonaws.com`},body});
    const res=await fetch(`https://dynamodb.${REGION}.amazonaws.com/`,{method:'POST',headers:{...signed.headers,'X-Amz-Target':'DynamoDB_20120810.Scan','Content-Type':'application/x-amz-json-1.0'},body});
    const data=await res.json();
    return (data.Items||[]).map(item=>({
      investigation_id:item.investigation_id?.S||'',
      alarm_name:item.alarm_name?.S||'',
      severity:item.severity?.S||'info',
      summary:item.summary?.S||'',
      findings:item.findings?.S||'[]',
      timeline:item.timeline?.S||'[]',
      actions:item.actions?.S||'[]',
      timestamp:item.timestamp?.S||'',
      status:item.status?.S||''
    })).filter(i=>i.timestamp&&!i.investigation_id.startsWith('dedup-')&&!isNaN(new Date(i.timestamp).getTime())).sort((a,b)=>b.timestamp.localeCompare(a.timestamp));
  }catch(e){return []}
}

// --- UI ---
window.showInvestigation=(inv)=>{
  const area=document.getElementById('chatArea');
  area.innerHTML='';
  const data={
    type:'investigation',
    severity:inv.severity||'info',
    summary:inv.summary||'',
    findings:JSON.parse(inv.findings||'[]'),
    timeline:JSON.parse(inv.timeline||'[]'),
    actions:JSON.parse(inv.actions||'[]'),
    blind_spots:null
  };
  const div=document.createElement('div');div.className='msg agent';
  div.innerHTML=`<div class="bubble">${renderStructured(data)}</div>`;
  area.appendChild(div);
};

window.investigateAlert=(name)=>{
  const area=document.getElementById('chatArea');
  const empty=area.querySelector('.empty-state');if(empty)empty.remove();
  addMsg(`Investigate: ${name.replace(''+window.ALARM_PREFIX+'-','')}`,'user');
  callAgent(`Investigate alarm "${name}". What's causing it, what changed, and how do I fix it?`);
};

window.newChat=()=>{sessionId='s-'+Date.now();document.getElementById('chatArea').innerHTML='<div class="empty-state"><h3>Select an alert or start an investigation</h3><p>Click an alert to investigate, or type a question below.</p></div>'};

window.send=()=>{
  const input=document.getElementById('input');const msg=input.value.trim();if(!msg)return;input.value='';
  const area=document.getElementById('chatArea');const empty=area.querySelector('.empty-state');if(empty)empty.remove();
  addMsg(msg,'user');callAgent(msg);
};

window.executeAction=async(prompt)=>{
  const area=document.getElementById('chatArea');
  const actionDiv=document.createElement('div');actionDiv.className='msg user';
  actionDiv.innerHTML=`<div class="bubble">${escHtml(prompt)}</div>`;
  area.appendChild(actionDiv);
  area.scrollTop=area.scrollHeight;
  // Show executing state
  const resultDiv=document.createElement('div');resultDiv.className='msg agent';
  resultDiv.innerHTML=`<div class="bubble"><div class="raw-response" style="opacity:0.6">⏳ Executing...</div></div>`;
  area.appendChild(resultDiv);
  area.scrollTop=area.scrollHeight;
  try{
    const session=await fetchAuthSession();
    const endpoint=`https://bedrock-agentcore.${REGION}.amazonaws.com`;
    const path=`/runtimes/${encodeURIComponent(AGENT_ARN)}/invocations`;
    const body=JSON.stringify({prompt:`User confirmed action: "${prompt}". Execute it now. Show: 1) What you're doing and why, 2) The exact API call, 3) The result or error. If it fails, explain how to fix manually.`,sessionId,userId:'console',model:document.getElementById('modelSelect').value});
    const signer=new SignatureV4({service:'bedrock-agentcore',region:REGION,credentials:session.credentials,sha256:Sha256});
    const signed=await signer.sign({method:'POST',hostname:`bedrock-agentcore.${REGION}.amazonaws.com`,path,headers:{'Content-Type':'application/json',host:`bedrock-agentcore.${REGION}.amazonaws.com`},body});
    const res=await fetch(endpoint+path,{method:'POST',headers:signed.headers,body});
    const data=await res.json();
    const text=data.result||data.response||JSON.stringify(data);
    const structured=parseStructuredResponse(text);
    if(structured&&structured.summary){
      resultDiv.innerHTML=`<div class="bubble"><button class="copy-btn" onclick="copyResponse(this)" title="Copy">⎘</button>${renderStructured(structured)}</div>`;
    }else{
      resultDiv.innerHTML=`<div class="bubble"><button class="copy-btn" onclick="copyResponse(this)" title="Copy">⎘</button><div class="raw-response">${renderMarkdown(text)}</div></div>`;
    }
  }catch(e){resultDiv.innerHTML=`<div class="bubble"><div class="raw-response" style="color:#EF4444">❌ ${e.message}</div></div>`}
  area.scrollTop=area.scrollHeight;
};

function addMsg(text,role){
  const area=document.getElementById('chatArea');
  const div=document.createElement('div');div.className='msg '+role;
  if(role==='agent'){
    const structured=parseStructuredResponse(text);
    if(structured&&structured.summary){
      div.innerHTML=`<div class="bubble">${renderStructured(structured)}<button class="copy-btn" onclick="copyResponse(this)" title="Copy">⎘</button></div>`;
    }else{
      div.innerHTML=`<div class="bubble"><div class="raw-response">${renderMarkdown(text)}</div><button class="copy-btn" onclick="copyResponse(this)" title="Copy">⎘</button></div>`;
    }
  }else{
    div.innerHTML=`<div class="bubble">${escHtml(text)}</div>`;
  }
  area.appendChild(div);area.scrollTop=area.scrollHeight;
}

window.copyResponse=async(btn)=>{
  const bubble=btn.parentElement;
  const text=bubble.innerText.replace('⎘','').trim();
  await navigator.clipboard.writeText(text);
  btn.textContent='✓';setTimeout(()=>{btn.textContent='⎘'},1500);
};
// Stack-specific config (set by deploy-ui.sh)
window.INVESTIGATIONS_TABLE = window.COSTOP_CONFIG?.investigationsTable || '';
window.ALARM_PREFIX = window.COSTOP_CONFIG?.stackName || 'CostOp';
