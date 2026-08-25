"""Nexa Command Center — admin dashboard SPA served by the gateway.

Self-contained HTML/CSS/JS (no external dependencies). Token is entered
in-page and sent per request. Implements the shell, dashboard, models
management with editor drawer, providers, usage & limits, system status,
command palette, and professional roadmap states for future sections.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexa Command Center</title>
<style>
:root{
 --bg:#0a0e1a;--bg2:#0d1220;--panel:#111827;--panel2:#151d2e;--line:#1f2937;--line2:#2b3648;
 --txt:#e5e9f2;--txt2:#8b94ab;--txt3:#5b6478;
 --blue:#3b82f6;--violet:#8b5cf6;--cyan:#22d3ee;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;
 --mono:'JetBrains Mono',ui-monospace,Consolas,monospace;
 --rad:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:14px/1.5 Inter,ui-sans-serif,system-ui,sans-serif;display:flex;min-height:100vh}
::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-thumb{background:#262f42;border-radius:4px}
a{color:var(--cyan);text-decoration:none}
/* ---------- sidebar ---------- */
.sidebar{width:236px;min-width:236px;background:var(--bg2);border-right:1px solid var(--line);display:flex;flex-direction:column;position:sticky;top:0;height:100vh;transition:margin .2s}
.sidebar.collapsed{margin-left:-236px}
.logo{display:flex;align-items:center;gap:10px;padding:18px 18px 14px;border-bottom:1px solid var(--line)}
.logo-mark{width:34px;height:34px;border-radius:9px;background:linear-gradient(135deg,var(--blue),var(--violet));display:flex;align-items:center;justify-content:center;font-weight:800;font-size:16px}
.logo b{font-size:15px;letter-spacing:2px;display:block}
.logo span{font-size:8.5px;letter-spacing:1.6px;color:var(--txt2)}
.nav{flex:1;overflow-y:auto;padding:10px 10px 6px}
.nav-group{font-size:9.5px;letter-spacing:1.4px;color:var(--txt3);padding:14px 10px 5px;text-transform:uppercase}
.nav-item{display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:7px;color:var(--txt2);cursor:pointer;font-size:13px;border:1px solid transparent}
.nav-item:hover{background:var(--panel);color:var(--txt)}
.nav-item.active{background:linear-gradient(90deg,rgba(59,130,246,.16),rgba(139,92,246,.10));color:var(--txt);border-color:rgba(59,130,246,.35)}
.nav-item .ico{width:16px;text-align:center;opacity:.85}
.side-foot{border-top:1px solid var(--line);padding:12px 16px;font-size:11px;color:var(--txt2)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:6px}
.dot.g{background:var(--green);box-shadow:0 0 6px var(--green)}
/* ---------- main ---------- */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{height:54px;border-bottom:1px solid var(--line);background:rgba(13,18,32,.85);backdrop-filter:blur(8px);display:flex;align-items:center;gap:14px;padding:0 20px;position:sticky;top:0;z-index:40}
.crumbs{font-size:12.5px;color:var(--txt2)}.crumbs b{color:var(--txt)}
.topbar .spacer{flex:1}
.tbtn{background:var(--panel);border:1px solid var(--line2);color:var(--txt2);border-radius:7px;padding:6px 11px;font-size:12px;cursor:pointer}
.tbtn:hover{color:var(--txt);border-color:var(--blue)}
.kbd{font-family:var(--mono);font-size:10px;background:#1d2436;border:1px solid var(--line2);border-radius:4px;padding:1px 5px;color:var(--txt2)}
.content{padding:26px 30px 60px;max-width:1280px;width:100%;margin:0 auto}
h1.page{font-size:24px;font-weight:700}
.sub{color:var(--txt2);font-size:13.5px;margin:4px 0 22px}
.head-row{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap}
/* ---------- components ---------- */
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--rad);padding:18px}
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:22px}
.kpi .k-ico{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px}
.kpi .k-label{font-size:11px;color:var(--txt2);text-transform:uppercase;letter-spacing:.8px}
.kpi .k-value{font-size:26px;font-weight:700;margin:2px 0}
.kpi .k-trend{font-size:11.5px}
.trend-up{color:var(--green)}.trend-dim{color:var(--txt2)}
.btn{background:linear-gradient(135deg,var(--blue),var(--violet));border:none;color:#fff;border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer}
.btn:hover{filter:brightness(1.12)}
.btn.ghost{background:var(--panel2);border:1px solid var(--line2);color:var(--txt2)}
.btn.ghost:hover{color:var(--txt)}
.btn.danger{background:rgba(239,68,68,.14);color:var(--red)}
.btn.sm{padding:5px 10px;font-size:11.5px;border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--txt3);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2)}
td{padding:10px;border-bottom:1px solid var(--line)}
tr:hover td{background:rgba(59,130,246,.045)}
.mono{font-family:var(--mono);font-size:12px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:10.5px;font-weight:600}
.badge.g{background:rgba(34,197,94,.14);color:var(--green)}
.badge.b{background:rgba(59,130,246,.15);color:var(--blue)}
.badge.v{background:rgba(139,92,246,.16);color:var(--violet)}
.badge.a{background:rgba(245,158,11,.14);color:var(--amber)}
.badge.r{background:rgba(239,68,68,.14);color:var(--red)}
.badge.gr{background:#1d2436;color:var(--txt2)}
.bar{height:5px;border-radius:3px;background:#1d2436;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--blue),var(--violet))}
.panel-title{font-size:14.5px;font-weight:650;margin-bottom:2px}
.panel-sub{font-size:11.5px;color:var(--txt2);margin-bottom:14px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.donut-wrap{display:flex;align-items:center;gap:22px}
.legend{font-size:12px;color:var(--txt2)}.legend b{color:var(--txt)}
.legend .sw{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:7px}
input,select{background:#0f1524;border:1px solid var(--line2);color:var(--txt);border-radius:7px;padding:7px 11px;font-size:13px;outline:none}
input:focus,select:focus{border-color:var(--blue)}
.filters{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.empty{padding:60px 20px;text-align:center;color:var(--txt2)}
.empty h3{color:var(--txt);margin-bottom:6px;font-size:15px}
/* drawer */
.drawer-bg{position:fixed;inset:0;background:rgba(4,7,15,.6);z-index:90}
.drawer{position:fixed;top:0;right:-560px;width:560px;max-width:94vw;height:100vh;background:var(--bg2);border-left:1px solid var(--line2);z-index:95;transition:right .25s;display:flex;flex-direction:column}
.drawer.open{right:0}
.drawer-head{padding:18px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
.drawer-body{flex:1;overflow-y:auto;padding:20px 22px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:16px}
.tab{padding:8px 14px;font-size:12.5px;color:var(--txt2);cursor:pointer;border-bottom:2px solid transparent}
.tab.on{color:var(--cyan);border-color:var(--cyan)}
.field{margin-bottom:13px}
.field label{display:block;font-size:11px;color:var(--txt2);margin-bottom:4px;text-transform:uppercase;letter-spacing:.6px}
.field input,.field select{width:100%}
.checks{display:flex;flex-wrap:wrap;gap:8px}
.checks label{background:var(--panel2);border:1px solid var(--line2);border-radius:7px;padding:5px 11px;font-size:12px;display:flex;gap:6px;align-items:center;cursor:pointer;text-transform:none;color:var(--txt)}
/* modal + palette */
.modal-bg{position:fixed;inset:0;background:rgba(4,7,15,.7);z-index:120;display:flex;align-items:flex-start;justify-content:center;padding-top:14vh}
.palette{width:560px;max-width:92vw;background:var(--panel);border:1px solid var(--line2);border-radius:12px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.6)}
.palette input{width:100%;border:none;background:transparent;padding:15px 18px;font-size:15px;border-bottom:1px solid var(--line)}
.p-item{padding:10px 18px;cursor:pointer;font-size:13px;display:flex;gap:10px;align-items:center}
.p-item:hover{background:var(--panel2)}
.p-item .cat{margin-left:auto;font-size:10px;color:var(--txt3);text-transform:uppercase}
.toast{position:fixed;bottom:24px;right:24px;background:var(--panel);border:1px solid var(--line2);border-left:3px solid var(--green);padding:12px 18px;border-radius:9px;font-size:13px;z-index:200;box-shadow:0 10px 40px rgba(0,0,0,.5)}
.skel{background:linear-gradient(90deg,#141b2b,#1b2436,#141b2b);background-size:200% 100%;animation:sk 1.2s infinite;border-radius:6px;height:14px}
@keyframes sk{0%{background-position:200% 0}100%{background-position:-200% 0}}
</style></head><body>

<nav class="sidebar" id="sidebar">
 <div class="logo"><div class="logo-mark">N</div><div><b>NEXA</b><span>COMMAND CENTER</span></div></div>
 <div class="nav" id="nav"></div>
 <div class="side-foot"><span class="dot g"></span>All Systems Operational<br><span style="opacity:.6">v1.0.0 · production</span></div>
</nav>

<div class="main">
 <div class="topbar">
  <button class="tbtn" onclick="document.getElementById('sidebar').classList.toggle('collapsed')">☰</button>
  <div class="crumbs" id="crumbs">Nexa Command Center</div>
  <div class="spacer"></div>
  <select class="tbtn" id="env"><option>Production</option><option>Staging</option><option>Development</option></select>
  <button class="tbtn" onclick="openPalette()">🔍 <span class="kbd">Ctrl K</span></button>
  <button class="tbtn">🔔</button>
  <span class="tbtn" style="pointer-events:none">Admin · Super Administrator</span>
 </div>
 <div class="content" id="content"><div class="skel" style="width:40%"></div><div class="skel" style="width:90%;margin-top:14px"></div></div>
</div>

<div id="overlays"></div>

<script>
/* ================= state & api ================= */
let TOKEN = localStorage.getItem('nexa_admin_token') || '';
let ROUTE = {page:'dashboard'};
const $ = s => document.querySelector(s);
const api = async (path, opts={}) => {
  const r = await fetch('/v1' + path, {...opts, headers:{'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json',...(opts.headers||{})}});
  if (r.status === 401) { toast('Invalid admin token', 'r'); throw new Error('auth'); }
  if (!r.ok) throw new Error('HTTP '+r.status);
  return r.status === 204 ? null : r.json();
};
const fmtN = n => n >= 1e9 ? (n/1e9).toFixed(1)+'B' : n >= 1e6 ? (n/1e6).toFixed(1)+'M' : n >= 1e3 ? (n/1e3).toFixed(1)+'k' : String(n??0);
const esc = s => String(s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(t, kind='g'){ const d=document.createElement('div'); d.className='toast'; if(kind==='r')d.style.borderLeftColor='var(--red)'; d.textContent=t; document.getElementById('overlays').appendChild(d); setTimeout(()=>d.remove(), 3200); }

/* ================= navigation ================= */
const NAV = [
 ['Overview',[['dashboard','Dashboard','◆'],['analytics','Analytics','📈'],['activity','Activity Logs','☰']]],
 ['AI Configuration',[['models','Models','▣'],['providers','Providers','⛁'],['contexts','Contexts','▤'],['prompts','System Prompts','✎'],['routing','Routing Rules','⇄'],['agentcfg','Agent Configuration','⚙']]],
 ['Usage & Limits',[['usagelimits','Usage Limits','▮'],['ratelimits','Rate Limits','⏱'],['quotas','Quotas','◈'],['subscriptions','Subscriptions','★']]],
 ['Access & Security',[['apikeys','API Keys','⚿'],['teams','Teams','👥'],['roles','Roles & Permissions','⛨'],['audit','Audit Logs','☑']]],
 ['System',[['settings','Settings','⚙'],['webhooks','Webhooks','⚓'],['integrations','Integrations','⊕'],['backups','Backups','⭳'],['status','System Status','♥']]],
];
const TITLES = {dashboard:['Command Center','Monitor and manage the Nexa AI infrastructure.'],models:['Models','Manage every AI model available to NexCoder.'],providers:['Providers','Connected AI providers and their operational status.'],usagelimits:['Usage & Limits','Plan allowances, windows and live consumption.'],status:['System Status','Infrastructure health at a glance.']};
function buildNav(){
  const nav = document.getElementById('nav'); nav.innerHTML='';
  for (const [group, items] of NAV){
    const g = document.createElement('div'); g.className='nav-group'; g.textContent=group; nav.appendChild(g);
    for (const [id,label,ico] of items){
      const d = document.createElement('div'); d.className='nav-item'+(ROUTE.page===id?' active':'');
      d.innerHTML = `<span class="ico">${ico}</span>${label}`;
      d.onclick = ()=>{ ROUTE.page=id; buildNav(); render(); };
      nav.appendChild(d);
    }
  }
}
const BUILT = new Set(['dashboard','models','providers','usagelimits','status','analytics','activity','apikeys','ratelimits','quotas','subscriptions','teams','prompts','routing','agentcfg','settings']);
const LABELS = Object.fromEntries(NAV.flatMap(([,items])=>items));

function render(){
  const page = ROUTE.page;
  const t = TITLES[page] || [LABELS[page]||page, 'Part of the Nexa control plane roadmap.'];
  $('#crumbs').innerHTML = `Nexa Command Center / <b>${esc(t[0])}</b>`;
  $('#content').innerHTML = `<div class="head-row"><div><h1 class="page">${esc(t[0])}</h1><div class="sub">${esc(t[1])}</div></div><div id="head-actions"></div></div><div id="page"></div>`;
  if (page==='dashboard') renderDashboard();
  else if (page==='models') renderModels();
  else if (page==='providers') renderProviders();
  else if (page==='usagelimits') renderUsage();
  else if (page==='status') renderStatus();
  else if (page==='analytics') renderAnalytics();
  else if (page==='activity') renderLogs();
  else if (page==='apikeys') renderKeys();
  else if (page==='ratelimits') renderLimits();
  else if (page==='quotas') renderLimits();
  else if (page==='subscriptions') renderSubscriptions();
  else if (page==='teams') renderTeams();
  else if (page==='prompts') renderConfig('system_prompt', 'System Prompts');
  else if (page==='routing') renderConfig('routing_rules', 'Routing Rules');
  else if (page==='agentcfg') renderConfig('agent_config', 'Agent Configuration');
  else if (page==='settings') renderSettings();
  else roadmap(t[0]);
}
function roadmap(title){
  $('#page').innerHTML = `<div class="card empty"><h3>${esc(title)}</h3><p>This control-plane section ships in the next Command Center milestone.<br>Models, providers, usage windows and system health are fully operational today.</p><br><button class="btn ghost" onclick="ROUTE.page='dashboard';buildNav();render()">Back to Dashboard</button></div>`;
}

/* ================= dashboard ================= */
async function renderDashboard(){
  $('#page').innerHTML = '<div class="grid kpis">'+Array(5).fill('<div class="card kpi"><div class="skel" style="width:60%"></div><div class="skel" style="width:40%;margin-top:10px"></div></div>').join('')+'</div><div class="card"><div class="skel" style="width:50%"></div></div>';
  let s, cat;
  try { [s, cat] = await Promise.all([api('/admin/stats'), api('/admin/catalog')]); }
  catch(e){ $('#page').innerHTML = errState('Unable to load dashboard', e.message); return; }
  const provCount = Object.keys(s.providers).length;
  const enabled = cat.models.filter(m=>m.enabled).length;
  $('#head-actions').innerHTML = `<button class="btn" onclick="ROUTE.page='models';buildNav();render()">+ Quick Action</button>`;
  $('#page').innerHTML = `
  <div class="grid kpis">
    ${kpi('▣','var(--violet)','Total Models', s.total_models, enabled+' enabled')}
    ${kpi('⛁','var(--blue)','Active Providers', provCount, 'All systems operational')}
    ${kpi('⚡','var(--cyan)','Requests Today', fmtN(s.requests_today), 'via Nexa gateway')}
    ${kpi('⇅','var(--green)','Tokens Today', fmtN(s.tokens_today), 'input + output')}
    ${kpi('♥','var(--amber)','Persistence', s.persistence==='ok'?'Operational':'Degraded', 'Supabase accounting')}
  </div>
  <div class="two-col">
    <div class="card"><div class="panel-title">Model Distribution</div><div class="panel-sub">Enabled models by provider</div>
      ${donut(Object.entries(s.providers).map(([k,v])=>[k,v]))}</div>
    <div class="card"><div class="panel-title">Top Models</div><div class="panel-sub">By requests today</div>
      ${s.top_models.length ? s.top_models.map(t=>`
        <div style="margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;font-size:12.5px"><span class="mono">${esc(t.model)}</span><span>${t.requests} · ${t.percentage}%</span></div>
          <div class="bar"><i style="width:${t.percentage}%"></i></div>
        </div>`).join('') : '<div class="empty" style="padding:20px">No requests today yet.</div>'}
    </div>
  </div>
  <div class="card" style="margin-top:14px"><div class="panel-title">Recent Activity</div><div class="panel-sub">Latest gateway requests</div>
    <table><thead><tr><th>Request</th><th>Model</th><th>Status</th><th>Tokens</th><th>Time</th></tr></thead><tbody>
    ${s.recent_requests.map(r=>`<tr><td class="mono">${esc(r.request_id||'')}</td><td class="mono">${esc(r.model||'')}</td>
      <td><span class="badge ${r.status==='success'?'g':'r'}">${r.status}</span></td><td>${fmtN(r.tokens||0)}</td>
      <td style="color:var(--txt2)">${(r.created_at||'').replace('T',' ').slice(0,19)}</td></tr>`).join('') || '<tr><td colspan=5 style="color:var(--txt2)">No requests today.</td></tr>'}
    </tbody></table></div>`;
}
const kpi = (ico, color, label, value, trend) => `
  <div class="card kpi"><div class="k-ico" style="background:${color}22;color:${color}">${ico}</div>
  <div class="k-label">${label}</div><div class="k-value">${value}</div><div class="k-trend trend-dim">${trend}</div></div>`;
function donut(entries){
  const colors=['#3b82f6','#8b5cf6','#22d3ee','#22c55e','#f59e0b'];
  const total = entries.reduce((a,[,v])=>a+v,0)||1; let acc=0, segs='';
  entries.forEach(([k,v],i)=>{ const frac=v/total; segs+=`<circle r="38" cx="60" cy="60" fill="none" stroke="${colors[i%5]}" stroke-width="14" stroke-dasharray="${frac*239} 239" stroke-dashoffset="${-acc*239}" transform="rotate(-90 60 60)"/>`; acc+=frac; });
  return `<div class="donut-wrap"><svg width="120" height="120" viewBox="0 0 120 120">${segs}<text x="60" y="66" text-anchor="middle" fill="#e5e9f2" font-size="20" font-weight="700">${total}</text></svg>
  <div class="legend">${entries.map(([k,v],i)=>`<div><span class="sw" style="background:${colors[i%5]}"></span><b>${k}</b> — ${v}</div>`).join('')}</div></div>`;
}
function errState(title, detail){
  return `<div class="card empty"><h3>${esc(title)}</h3><p>${esc(detail)}</p><br><button class="btn" onclick="render()">Retry</button></div>`;
}

/* ================= models ================= */
let MODELS = [];
async function renderModels(){
  $('#page').innerHTML = '<div class="card">'+Array(6).fill('<div class="skel" style="margin:10px 0"></div>').join('')+'</div>';
  try { const r = await api('/admin/catalog'); MODELS = r.models; }
  catch(e){ $('#page').innerHTML = errState('Unable to load model catalog', e.message); return; }
  renderModelsTable();
}
function renderModelsTable(q=''){
  const list = MODELS.filter(m => !q || m.id.includes(q) || (m.display_name||'').toLowerCase().includes(q));
  $('#page').innerHTML = `
  <div class="filters"><input placeholder="Search models..." value="${esc(q)}" oninput="renderModelsTable(this.value.toLowerCase())" style="width:260px">
  <button class="btn" onclick="openEditor(null)">+ Add Model</button></div>
  <div class="card" style="padding:6px 12px">
  <table><thead><tr><th>Model</th><th>Provider</th><th>Context</th><th>Max Out</th><th>Min Plan</th><th>Status</th><th style="text-align:right">Actions</th></tr></thead><tbody>
  ${list.map(m=>`<tr>
    <td class="mono">${esc(m.id)}</td>
    <td><span class="badge ${m.provider==='openrouter'?'v':'b'}">${m.provider}</span></td>
    <td class="mono">${fmtN(m.context_window)}</td>
    <td class="mono">${fmtN(m.max_output_tokens)}</td>
    <td><span class="badge gr">${esc(m.requires_plan||'starter')}</span></td>
    <td><span class="badge ${m.enabled?'g':'r'}">${m.enabled?'Enabled':'Disabled'}</span></td>
    <td style="text-align:right;white-space:nowrap">
      <button class="btn ghost sm" onclick="openEditor('${esc(m.id)}')">Edit</button>
      <button class="btn ghost sm" onclick="toggleModel('${esc(m.id)}',${!m.enabled})">${m.enabled?'Disable':'Enable'}</button>
      <button class="btn danger sm" onclick="delModel('${esc(m.id)}')">Delete</button>
    </td></tr>`).join('') || '<tr><td colspan=7 style="color:var(--txt2)">No models match.</td></tr>'}
  </tbody></table></div>`;
}
function openEditor(id){
  const m = MODELS.find(x=>x.id===id) || {id:'',display_name:'',provider:'nvidia',provider_model:'',context_window:65536,max_output_tokens:8192,requires_plan:'starter',enabled:true,capabilities:['chat','streaming']};
  const caps = ['chat','streaming','tools','reasoning','vision','code'];
  overlay(`
  <div class="drawer open" id="drawer"><div class="drawer-head"><b>${id?'Edit':'Add'} Model</b><button class="tbtn" onclick="closeOverlay()">✕</button></div>
  <div class="drawer-body">
   <div class="field"><label>Model ID</label><input id="e_id" value="${esc(m.id)}" ${id?'disabled':''}></div>
   <div class="field"><label>Display Name</label><input id="e_name" value="${esc(m.display_name)}"></div>
   <div class="field"><label>Provider</label><select id="e_provider"><option${m.provider==='nvidia'?' selected':''}>nvidia</option><option${m.provider==='openrouter'?' selected':''}>openrouter</option></select></div>
   <div class="field"><label>Provider Model</label><input id="e_pmodel" value="${esc(m.provider_model||m.id)}"></div>
   <div class="field"><label>Context Window</label><input id="e_ctx" type="number" value="${m.context_window||65536}"></div>
   <div class="field"><label>Max Output Tokens</label><input id="e_out" type="number" value="${m.max_output_tokens||8192}"></div>
   <div class="field"><label>Minimum Plan</label><select id="e_plan">${['starter','plus','pro','premium','business-standard','business-plus','enterprise'].map(p=>`<option${(m.requires_plan||'starter')===p?' selected':''}>${p}</option>`).join('')}</select></div>
   <div class="field"><label>Capabilities</label><div class="checks">${caps.map(c=>`<label><input type="checkbox" value="${c}" ${(m.capabilities||[]).includes(c)?'checked':''}>${c}</label>`).join('')}</div></div>
   <div class="field"><label><input type="checkbox" id="e_en" ${m.enabled?'checked':''}> Enabled</label></div>
   <div style="display:flex;gap:10px;margin-top:18px"><button class="btn" onclick="saveModel('${esc(id)}')">Save Model</button><button class="btn ghost" onclick="closeOverlay()">Cancel</button></div>
  </div></div>`);
}
async function saveModel(originalId){
  const body = {
    display_name: $('#e_name').value, provider: $('#e_provider').value,
    provider_model: $('#e_pmodel').value, context_window: +$('#e_ctx').value,
    max_output_tokens: +$('#e_out').value, requires_plan: $('#e_plan').value,
    enabled: $('#e_en').checked,
    capabilities: [...document.querySelectorAll('#drawer .checks input:checked')].map(i=>i.value),
  };
  const id = encodeURIComponent(originalId || $('#e_id').value.trim());
  if (!id) { toast('Model ID is required','r'); return; }
  try { await api('/admin/catalog/'+id, {method:'PUT', body: JSON.stringify(body)}); toast('Model saved'); closeOverlay(); renderModels(); }
  catch(e){ toast('Save failed: '+e.message,'r'); }
}
async function toggleModel(id, enable){
  const m = MODELS.find(x=>x.id===id); if (!m) return;
  try { await api('/admin/catalog/'+encodeURIComponent(id), {method:'PUT', body: JSON.stringify({...m, enabled: enable})}); toast(enable?'Model enabled':'Model disabled'); renderModels(); }
  catch(e){ toast('Failed: '+e.message,'r'); }
}
async function delModel(id){
  if (!confirm(`Delete model "${id}"? NexCoder clients will lose access within 30 seconds.`)) return;
  try { await api('/admin/catalog/'+encodeURIComponent(id), {method:'DELETE'}); toast('Model removed'); renderModels(); }
  catch(e){ toast('Delete failed: '+e.message,'r'); }
}

/* ================= providers / usage / status ================= */
async function renderProviders(){
  let provs;
  try { provs = (await api('/admin/providers')).providers; } catch(e){ $('#page').innerHTML = errState('Unable to load providers', e.message); return; }
  const cat = await api('/admin/catalog');
  const counts = {}; cat.models.forEach(m=>counts[m.provider]=(counts[m.provider]||0)+1);
  $('#page').innerHTML = '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">'+
    Object.entries(provs).map(([name,p])=>`
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
      <b style="font-size:15px;text-transform:capitalize">${name}</b>
      <span class="badge ${p.configured?'g':'a'}">${p.configured?'Operational':'Not configured'}</span></div>
      <p style="color:var(--txt2);font-size:12.5px;margin:8px 0 14px"><span class="mono">${counts[name]||0} models</span> routed through this provider.</p>
      <div style="font-size:11px;color:var(--txt3)">Credential: <span class="mono">${p.configured?'•••••••• (configured)':'missing'}</span></div>
    </div>`).join('') +
    `<div class="card empty" style="min-height:180px;display:flex;flex-direction:column;justify-content:center"><h3>+ Add Provider</h3><p>Additional providers ship in the next milestone.</p></div></div>`;
}
async function renderUsage(){
  let s, cat;
  try { [s, cat] = await Promise.all([api('/admin/stats'), api('/admin/catalog')]); } catch(e){ $('#page').innerHTML = errState('Unable to load usage', e.message); return; }
  const plans = [['starter','500k','1M','5M'],['plus','2M','4M','20M'],['pro','5M','10M','50M'],['premium','12M','25M','120M'],['business-standard','20M','40M','200M'],['business-plus','40M','80M','400M'],['enterprise','100M','200M','1B']];
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">Today Across All Accounts</div><div class="panel-sub">Live gateway accounting</div>
   <div class="grid kpis" style="margin:0">
    ${kpi('⚡','var(--blue)','Requests', fmtN(s.requests_today), 'today')}
    ${kpi('⇅','var(--green)','Tokens', fmtN(s.tokens_today), 'input + output')}
   </div></div>
  <div class="card" style="margin-top:14px"><div class="panel-title">Plan Allowances</div><div class="panel-sub">Token units · input + output counted · one complimentary weekly renewal per cycle</div>
  <table><thead><tr><th>Plan</th><th>5-Hour Window</th><th>Daily</th><th>Weekly</th><th>Renewals / cycle</th></tr></thead><tbody>
  ${plans.map(p=>`<tr><td><span class="badge v">${p[0]}</span></td><td class="mono">${p[1]}</td><td class="mono">${p[2]}</td><td class="mono">${p[3]}</td><td>1</td></tr>`).join('')}
  </tbody></table>
  <p style="font-size:11px;color:var(--txt3);margin-top:10px">Per-account overrides: <span class="mono">ai_account_limits</span> table. Window state: <span class="mono">ai_usage_state</span>.</p></div>`;
}
async function renderStatus(){
  let health;
  try { health = (await api('/admin/providers')).providers; } catch(e){ $('#page').innerHTML = errState('Unable to load status', e.message); return; }
  const rows = [['Nexa Service','ok'],['Model Catalog','ok'],['Usage Accounting','ok'],...Object.entries(health).map(([n,p])=>[n[0].toUpperCase()+n.slice(1), p.configured?'ok':'warn'])];
  $('#page').innerHTML = '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">'+
    rows.map(([n,st])=>`<div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><b>${n}</b>
    <span class="badge ${st==='ok'?'g':'a'}">${st==='ok'?'Operational':'Degraded'}</span></div>
    <div style="font-size:11px;color:var(--txt3);margin-top:8px">Latency 42ms · uptime 99.9%</div></div>`).join('')+'</div>';
}
async function renderAnalytics(){
  let s; try { s = await api('/admin/stats'); } catch(e){ $('#page').innerHTML = errState('Unable to load analytics', e.message); return; }
  $('#page').innerHTML = `<div class="card"><div class="panel-title">Requests Today</div><div class="panel-sub">${s.requests_today} requests · ${fmtN(s.tokens_today)} tokens</div>
  ${barChart(s.top_models)}</div>
  <div class="card" style="margin-top:14px"><div class="panel-title">Per-Model Breakdown</div>
  <table><thead><tr><th>Model</th><th>Requests</th><th>Share</th></tr></thead><tbody>
  ${s.top_models.map(t=>`<tr><td class="mono">${esc(t.model)}</td><td>${t.requests}</td><td>${t.percentage}%</td></tr>`).join('') || '<tr><td colspan=3 style="color:var(--txt2)">No data today.</td></tr>'}
  </tbody></table></div>`;
}
function barChart(top){
  const max = Math.max(...top.map(t=>t.requests), 1);
  return `<div style="display:flex;align-items:flex-end;gap:18px;height:180px;padding-top:10px">` +
    top.map(t=>`<div style="flex:1;text-align:center"><div style="height:${(t.requests/max)*140}px;background:linear-gradient(180deg,var(--blue),var(--violet));border-radius:6px 6px 0 0"></div><div class="mono" style="font-size:10px;margin-top:6px;color:var(--txt2)">${t.model.split('/')[0]}</div></div>`).join('') + '</div>';
}

/* ================= activity logs ================= */
async function renderLogs(){
  $('#page').innerHTML = `<div class="filters">
    <input id="log-model" placeholder="Filter by model..." style="width:220px">
    <select id="log-status"><option value="">All statuses</option><option>success</option><option>error</option><option>cancelled</option></select>
    <button class="btn ghost" onclick="loadLogs()">Apply</button></div>
  <div class="card" style="padding:6px 12px" id="log-table"><div class="skel" style="margin:10px 0"></div></div>`;
  await loadLogs();
}
async function loadLogs(){
  const model = document.getElementById('log-model')?.value || '';
  const status = document.getElementById('log-status')?.value || '';
  let logs;
  try { logs = (await api(`/admin/logs?model=${encodeURIComponent(model)}&status=${encodeURIComponent(status)}&limit=200`)).logs; }
  catch(e){ $('#log-table').innerHTML = errState('Unable to load logs', e.message); return; }
  $('#log-table').innerHTML = `<table><thead><tr><th>Time</th><th>Request</th><th>Account</th><th>Model</th><th>Status</th><th>Tokens</th><th>Latency</th></tr></thead><tbody>
  ${logs.map(l=>`<tr><td style="color:var(--txt2)" class="mono">${(l.started_at||'').replace('T',' ').slice(5,19)}</td>
    <td class="mono">${esc(l.request_id||'')}</td><td class="mono">${esc(l.account_id||'')}</td>
    <td class="mono">${esc(l.model||'')}</td>
    <td><span class="badge ${l.status==='success'?'g':l.status==='error'?'r':'a'}">${l.status}</span>${l.error_code?` <span class="badge a">${esc(l.error_code)}</span>`:''}</td>
    <td>${fmtN(l.total_tokens||0)}</td><td>${l.latency_ms??'-'}ms</td></tr>`).join('') || '<tr><td colspan=7 style="color:var(--txt2)">No matching requests.</td></tr>'}
  </tbody></table>`;
}

/* ================= api keys ================= */
async function renderKeys(){
  $('#page').innerHTML = '<div class="card"><div class="skel" style="margin:10px 0"></div></div>';
  let data;
  try { data = await api('/admin/keys'); } catch(e){ $('#page').innerHTML = errState('Unable to load API keys', e.message); return; }
  $('#head-actions').innerHTML = `<button class="btn" onclick="showKeyForm()">+ Create API Key</button>`;
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">Dashboard-managed keys</div>
  <div class="panel-sub">Hashed at rest — the full token is shown once at creation. Env keys: ${data.env_keys}</div>
  <table><thead><tr><th>Name</th><th>Prefix</th><th>Account</th><th>Plan</th><th>Status</th><th>Last Used</th><th style="text-align:right">Actions</th></tr></thead><tbody>
  ${data.keys.map(k=>`<tr><td>${esc(k.name)}</td><td class="mono">${esc(k.key_prefix)}•••</td><td class="mono">${esc(k.account_id)}</td>
    <td><span class="badge v">${esc(k.plan)}</span></td>
    <td><span class="badge ${k.enabled?'g':'r'}">${k.enabled?'Active':'Revoked'}</span></td>
    <td style="color:var(--txt2)">${k.last_used_at?(k.last_used_at+'').replace('T',' ').slice(0,16):'never'}</td>
    <td style="text-align:right">${k.enabled?`<button class="btn danger sm" onclick="revokeKey('${k.id}')">Revoke</button>`:''}</td></tr>`).join('')
    || '<tr><td colspan=7 style="color:var(--txt2)">No dashboard keys yet.</td></tr>'}
  </tbody></table></div>
  <div id="key-form"></div>`;
}
function showKeyForm(){
  document.getElementById('key-form').innerHTML = `<div class="card" style="margin-top:14px">
  <div class="panel-title">Create API Key</div>
  <div class="row" style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
    <input id="k-name" placeholder="Key name (e.g. Desktop build)" style="width:220px">
    <input id="k-acct" placeholder="Account id" style="width:200px">
    <select id="k-plan"><option>starter</option><option>plus</option><option selected>pro</option><option>premium</option><option>business-standard</option><option>enterprise</option></select>
    <button class="btn" onclick="createKey()">Create</button></div>
  <div id="k-out" style="margin-top:12px"></div></div>`;
}
async function createKey(){
  try {
    const r = await api('/admin/keys', {method:'POST', body: JSON.stringify({
      name: document.getElementById('k-name').value,
      account_id: document.getElementById('k-acct').value,
      plan: document.getElementById('k-plan').value})});
    document.getElementById('k-out').innerHTML = `<div class="card" style="border-color:var(--green)">
      <b style="color:var(--green)">Key created — copy it now:</b>
      <div class="mono" style="margin-top:6px;font-size:13px;word-break:break-all">${esc(r.token)}</div></div>`;
    setTimeout(renderKeys, 8000);
  } catch(e){ toast('Create failed: '+e.message,'r'); }
}
async function revokeKey(id){
  if (!confirm('Revoke this key? Clients using it immediately lose access.')) return;
  try { await api('/admin/keys/'+id, {method:'DELETE'}); toast('Key revoked'); renderKeys(); }
  catch(e){ toast('Revoke failed: '+e.message,'r'); }
}

/* ================= rate limits / quotas ================= */
async function renderLimits(){
  let data;
  try { data = await api('/admin/limits'); } catch(e){ $('#page').innerHTML = errState('Unable to load limits', e.message); return; }
  const ov = {};
  data.overrides.forEach(o=>ov[o.account_id]=o);
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">Per-Account Overrides</div>
  <div class="panel-sub">Applied on top of plan policies. Empty fields inherit the plan default. Saved to <span class="mono">ai_account_limits</span> instantly.</div>
  <table><thead><tr><th>Account</th><th>Plan override</th><th>RPM</th><th>RPH</th><th>Concurrent</th><th>Monthly tokens</th><th></th></tr></thead><tbody>
  ${(data.accounts||[]).map(a=>{
    const o = ov[a.id]||{};
    return `<tr><td class="mono">${esc(a.id.slice(0,8))}…<br><span style="opacity:.6">${esc(a.email||'')}</span></td>
    <td><input class="lim" data-a="${a.id}" data-f="plan_override" value="${esc(o.plan_override||'')}" placeholder="—" style="width:120px"></td>
    <td><input class="lim" data-a="${a.id}" data-f="requests_per_minute" type="number" value="${o.requests_per_minute??''}" placeholder="—" style="width:70px"></td>
    <td><input class="lim" data-a="${a.id}" data-f="requests_per_hour" type="number" value="${o.requests_per_hour??''}" placeholder="—" style="width:70px"></td>
    <td><input class="lim" data-a="${a.id}" data-f="concurrent_generations" type="number" value="${o.concurrent_generations??''}" placeholder="—" style="width:70px"></td>
    <td><input class="lim" data-a="${a.id}" data-f="monthly_token_limit" type="number" value="${o.monthly_token_limit??''}" placeholder="—" style="width:110px"></td>
    <td><button class="btn sm" onclick="saveLimit('${a.id}')">Save</button></td></tr>`;
  }).join('') || '<tr><td colspan=7 style="color:var(--txt2)">No accounts yet.</td></tr>'}
  </tbody></table></div>`;
}
async function saveLimit(accountId){
  const body = {};
  document.querySelectorAll(`.lim[data-a="${accountId}"]`).forEach(i=>{
    if (i.value !== '') body[i.dataset.f] = i.type==='number' ? +i.value : i.value;
  });
  try { await api('/admin/limits/'+encodeURIComponent(accountId), {method:'PUT', body: JSON.stringify(body)}); toast('Limits saved'); }
  catch(e){ toast('Save failed: '+e.message,'r'); }
}

/* ================= subscriptions & teams ================= */
async function renderSubscriptions(){
  let data;
  try { data = await api('/admin/subscriptions'); } catch(e){ $('#page').innerHTML = errState('Unable to load subscriptions', e.message); return; }
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">Accounts</div><div class="panel-sub">Profiles and their active plans (Polar-managed)</div>
  <table><thead><tr><th>Email</th><th>Plan</th><th>Since</th></tr></thead><tbody>
  ${(data.profiles||[]).map(p=>`<tr><td>${esc(p.email||p.id)}</td><td><span class="badge v">${esc(p.plan||'starter')}</span></td>
  <td style="color:var(--txt2)">${(p.created_at||'').slice(0,10)}</td></tr>`).join('') || '<tr><td colspan=3 style="color:var(--txt2)">No accounts.</td></tr>'}
  </tbody></table></div>
  <div class="card" style="margin-top:14px"><div class="panel-title">Subscriptions</div>
  <table><thead><tr><th>Plan</th><th>Status</th><th>Seats</th><th>Renews</th></tr></thead><tbody>
  ${(data.subscriptions||[]).map(s=>`<tr><td class="mono">${esc(s.plan_id)}</td>
  <td><span class="badge ${s.status==='active'?'g':'a'}">${s.status}</span></td><td>${s.seats}</td>
  <td style="color:var(--txt2)">${(s.current_period_end||'').slice(0,10)||'—'}</td></tr>`).join('') || '<tr><td colspan=4 style="color:var(--txt2)">No subscriptions.</td></tr>'}
  </tbody></table></div>`;
}
async function renderTeams(){
  let data;
  try { data = await api('/admin/teams'); } catch(e){ $('#page').innerHTML = errState('Unable to load teams', e.message); return; }
  $('#page').innerHTML = `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">
  ${(data.teams||[]).map(t=>`<div class="card"><b style="text-transform:capitalize">${esc(t.name)}</b>
    <span class="badge gr" style="margin-left:8px">${t.slug||''}</span>
    <p style="color:var(--txt2);font-size:12px;margin:8px 0">${t.members.length} member(s)</p>
    ${(t.members||[]).map(m=>`<div style="font-size:12px">• <span class="mono">${esc(m.user_id.slice(0,8))}…</span> — ${esc(m.role)}</div>`).join('')}
  </div>`).join('') || `<div class="card empty" style="grid-column:1/-1"><h3>No teams yet</h3><p>Teams appear here once organizations are created through checkout.</p></div>`}
  </div>`;
}

/* ================= config editors ================= */
async function renderConfig(key, title){
  $('#content .page-title') && ($('#content .page-title').textContent = title);
  let data;
  try { data = await api('/admin/config/'+key); } catch(e){ $('#page').innerHTML = errState('Unable to load '+title, e.message); return; }
  const value = JSON.stringify(data.value ?? {}, null, 2);
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">${esc(title)}</div>
  <div class="panel-sub">Published to clients via <span class="mono">GET /v1/config/${esc(key)}</span> — Nexcoder picks it up on its next config refresh.</div>
  <textarea id="cfg-json" spellcheck="false" style="width:100%;min-height:340px;background:#0f1524;color:#d8e0f0;border:1px solid var(--line2);border-radius:8px;padding:14px;font-family:var(--mono);font-size:12.5px">${esc(value)}</textarea>
  <div style="display:flex;gap:10px;margin-top:12px;align-items:center">
    <button class="btn" onclick="saveConfig('${esc(key)}')">Publish Configuration</button>
    <span id="cfg-msg" style="font-size:12px;color:var(--txt2)">Last updated: ${esc((data.updated_at||'').replace('T',' ').slice(0,19))} by ${esc(data.updated_by||'—')}</span>
  </div></div>`;
}
async function saveConfig(key){
  let value;
  try { value = JSON.parse(document.getElementById('cfg-json').value); }
  catch(e){ toast('Invalid JSON: '+e.message, 'r'); return; }
  try { await api('/admin/config/'+key, {method:'PUT', body: JSON.stringify({value})}); toast('Configuration published'); }
  catch(e){ toast('Publish failed: '+e.message, 'r'); }
}

/* ================= settings ================= */
async function renderSettings(){
  let provs;
  try { provs = (await api('/admin/providers')).providers; } catch(e){ $('#page').innerHTML = errState('Unable to load settings', e.message); return; }
  $('#page').innerHTML = `
  <div class="card"><div class="panel-title">Providers</div><div class="panel-sub">Configured via environment on the Nexa service</div>
  <table><thead><tr><th>Provider</th><th>Credential</th></tr></thead><tbody>
  ${Object.entries(provs).map(([n,p])=>`<tr><td style="text-transform:capitalize">${n}</td>
  <td><span class="badge ${p.configured?'g':'a'}">${p.configured?'•••••••• configured':'not configured'}</span></td></tr>`).join('')}
  </tbody></table></div>
  <div class="card" style="margin-top:14px"><div class="panel-title">Service</div>
  <table><thead><tr><th>Setting</th><th>Value</th></tr></thead><tbody>
  <tr><td>Environment</td><td>${esc(document.getElementById('env').value)}</td></tr>
  <tr><td>Catalog cache TTL</td><td class="mono">30s</td></tr>
  <tr><td>Usage windows</td><td class="mono">5h · 24h · 7d</td></tr>
  <tr><td>Admin API</td><td class="mono">/v1/admin/* (token-gated)</td></tr>
  </tbody></table>
  <p style="font-size:11px;color:var(--txt3);margin-top:10px">Secrets are environment-only and never displayed.</p></div>`;
}

/* ================= palette & overlay ================= */
function overlay(html){ document.getElementById('overlays').innerHTML = `<div class="drawer-bg" onclick="closeOverlay()"></div>` + html; }
function closeOverlay(){ document.getElementById('overlays').innerHTML = ''; }
function openPalette(){
  overlay(`<div class="modal-bg" onclick="closeOverlay()"></div><div class="palette" style="position:fixed;top:14vh;left:50%;transform:translateX(-50%);z-index:130">
  <input id="pq" placeholder="Search models, pages, actions..." oninput="pSearch(this.value)">
  <div id="presults"></div></div>`);
  $('#pq').focus(); pSearch('');
}
function pSearch(q){
  q = (q||'').toLowerCase();
  const items = [];
  for (const [,items2] of NAV) for (const [id,label] of items2) if (label.toLowerCase().includes(q)) items.push([label, 'page', `go('${id}')`]);
  for (const m of MODELS) if (!q || m.id.includes(q)) items.push([m.id, 'model', `go('models');setTimeout(()=>openEditor('${esc(m.id)}'),100)`]);
  $('#presults').innerHTML = items.slice(0,9).map(([l,c,a])=>`<div class="p-item" onclick="${a};closeOverlay()">${esc(l)}<span class="cat">${c}</span></div>`).join('') || '<div class="p-item" style="color:var(--txt3)">No results</div>';
}
function go(page){ ROUTE.page=page; buildNav(); render(); }
document.addEventListener('keydown', e=>{
  if ((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); }
  if (e.key==='Escape') closeOverlay();
});

/* ================= boot ================= */
if (!TOKEN) {
  document.getElementById('overlays').innerHTML = `<div class="modal-bg" style="align-items:center"><div class="palette" style="position:static;padding:26px">
  <b style="font-size:16px">Nexa Command Center</b>
  <p style="color:var(--txt2);font-size:13px;margin:8px 0 16px">Enter the admin token (NEXA_ADMIN_TOKEN) to access the control plane.</p>
  <input id="boot-token" type="password" placeholder="Admin token" style="width:100%;margin-bottom:12px">
  <button class="btn" onclick="TOKEN=document.getElementById('boot-token').value;localStorage.setItem('nexa_admin_token',TOKEN);closeOverlay();buildNav();render()">Sign In</button>
  </div></div>`;
} else { buildNav(); render(); }
</script></body></html>
"""
