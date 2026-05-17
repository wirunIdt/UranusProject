/* ARIA v5 — Shared JavaScript */
'use strict';

// ── Navigation ────────────────────────────────────────────────────────────
function toggleMobileNav(){
  const n=document.getElementById('mobile-nav');
  if(n)n.classList.toggle('open');
}
document.addEventListener('click',e=>{
  if(!e.target.closest('#mobile-nav')&&!e.target.closest('.aria-hamburger')){
    const n=document.getElementById('mobile-nav');
    if(n)n.classList.remove('open');
  }
});

// ── Realtime SSE System Stats ─────────────────────────────────────────────
let _sysSSE=null;
const _sysHandlers=[];

function onSysData(fn){ _sysHandlers.push(fn); }

function startSysStream(){
  if(_sysSSE) _sysSSE.close();
  _sysSSE=new EventSource('/api/stream');
  _sysSSE.onmessage=e=>{
    try{ const d=JSON.parse(e.data); _sysHandlers.forEach(h=>h(d)); }catch{}
  };
  _sysSSE.onerror=()=>{ setTimeout(startSysStream, 5000); };
}

// ── Format helpers ────────────────────────────────────────────────────────
function fmtB(b){
  if(!b||isNaN(b))return'0B';
  if(b<1024)return b+'B';
  if(b<1048576)return(b/1024).toFixed(1)+'KB';
  if(b<1073741824)return(b/1048576).toFixed(1)+'MB';
  return(b/1073741824).toFixed(2)+'GB';
}
function fmtRate(bps){
  if(bps<1024)return bps+'B/s';
  if(bps<1048576)return(bps/1024).toFixed(1)+'KB/s';
  return(bps/1048576).toFixed(2)+'MB/s';
}
function fmtUp(s){
  const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return(d?d+'d ':'')+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0');
}
function fmtNum(n,decimals=2){
  if(n===undefined||n===null||isNaN(n))return'--';
  return Number(n).toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
}
function fmtPct(n){return(n>=0?'+':'')+n.toFixed(2)+'%';}
function barColor(p,w=60,c=80){return p>c?'var(--red)':p>w?'var(--yellow)':'var(--green)';}
function chgClass(v){return v>0?'pos':v<0?'neg':'neu';}

function setBar(id,pct,color){
  const el=document.getElementById(id); if(!el)return;
  el.style.width=Math.min(pct,100)+'%';
  el.style.background=color||barColor(pct);
}
function setText(id,txt,cls){
  const el=document.getElementById(id); if(!el)return;
  el.textContent=txt;
  if(cls){el.className=cls;}
}

// ── API helper ────────────────────────────────────────────────────────────
async function api(method,url,body){
  try{
    const o={method,headers:{'Content-Type':'application/json'}};
    if(body&&method!=='GET')o.body=JSON.stringify(body);
    const r=await fetch(url,o);
    return await r.json();
  }catch(e){return{error:e.message};}
}

// ── Mini sparkline canvas ─────────────────────────────────────────────────
function drawSpark(canvas,data,color='var(--green)'){
  if(!canvas||data.length<2)return;
  const w=canvas.parentElement?.clientWidth||200,h=canvas.height||30;
  canvas.width=w;
  const ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,w,h);
  const max=Math.max(...data,0.1);
  ctx.beginPath();
  data.forEach((v,i)=>{
    const x=i/(data.length-1)*w,y=h-(v/max)*(h-4)-2;
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  // Resolve CSS variable to actual color for canvas
  const resolved=getComputedStyle(document.documentElement).getPropertyValue(
    color.replace('var(','').replace(')','').trim()
  ).trim()||color;
  ctx.strokeStyle=resolved||'#3fb950';
  ctx.lineWidth=1.5;ctx.stroke();
  ctx.lineTo(w,h);ctx.lineTo(0,h);ctx.closePath();
  ctx.fillStyle=(resolved||'#3fb950')+'22';ctx.fill();
}

// ── Toast notifications ───────────────────────────────────────────────────
function toast(msg,type='ok',dur=3000){
  let box=document.getElementById('toast-box');
  if(!box){box=document.createElement('div');box.id='toast-box';
    box.style.cssText='position:fixed;bottom:16px;right:16px;z-index:999;display:flex;flex-direction:column;gap:6px';
    document.body.appendChild(box);}
  const t=document.createElement('div');
  const bg={'ok':'rgba(63,185,80,.9)','err':'rgba(248,81,73,.9)','warn':'rgba(210,153,34,.9)','info':'rgba(88,166,255,.9)'}[type]||'rgba(33,38,45,.9)';
  t.style.cssText=`background:${bg};color:#fff;padding:8px 14px;border-radius:6px;font-size:12px;font-family:var(--font);max-width:280px;opacity:0;transition:opacity .2s`;
  t.textContent=msg;box.appendChild(t);
  requestAnimationFrame(()=>{t.style.opacity='1';});
  setTimeout(()=>{t.style.opacity='0';setTimeout(()=>t.remove(),200);},dur);
}

// ── Auto-start SSE on page load ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded',()=>{
  startSysStream();
  // Update topbar status dot from SSE
  onSysData(d=>{
    const dot=document.getElementById('sys-dot');
    if(dot)dot.className='aria-status-dot green';
  });
});

// ══════════════════════════════════════════════════════════
//  PWA — Service Worker Registration
// ══════════════════════════════════════════════════════════
if('serviceWorker' in navigator){
  window.addEventListener('load',()=>{
    navigator.serviceWorker.register('/sw.js',{scope:'/'})
      .then(r=>console.log('SW registered:',r.scope))
      .catch(e=>console.warn('SW failed:',e));
  });
}

// PWA install prompt
let _pwaInstall=null;
window.addEventListener('beforeinstallprompt',e=>{
  e.preventDefault(); _pwaInstall=e;
  const btn=document.getElementById('pwa-install-btn');
  if(btn)btn.style.display='flex';
});
function installPWA(){
  if(!_pwaInstall)return;
  _pwaInstall.prompt();
  _pwaInstall.userChoice.then(r=>{
    if(r.outcome==='accepted'){toast('ARIA installed as app ✓','ok');const btn=document.getElementById('pwa-install-btn');if(btn)btn.style.display='none';}
    _pwaInstall=null;
  });
}

// ══════════════════════════════════════════════════════════
//  VOICE I/O — Speech Recognition + TTS
// ══════════════════════════════════════════════════════════
const Voice = (() => {
  const SpeechRecog = window.SpeechRecognition || window.webkitSpeechRecognition;
  let _recog = null, _listening = false, _ttsEnabled = true;
  const _handlers = [];

  function onTranscript(fn){ _handlers.push(fn); }

  function startListening(lang='th-TH'){
    if(!SpeechRecog){ toast('Speech not supported in this browser','warn'); return false; }
    if(_listening){ stopListening(); return false; }
    _recog = new SpeechRecog();
    _recog.lang = lang;
    _recog.continuous = false;
    _recog.interimResults = true;
    _recog.maxAlternatives = 1;

    _recog.onstart = () => {
      _listening = true;
      const btn = document.getElementById('voice-btn');
      if(btn){ btn.style.color='#f85149'; btn.style.borderColor='#f85149'; btn.title='Listening... (click to stop)'; }
      toast('🎤 Listening...','info',2000);
    };
    _recog.onresult = e => {
      let interim='', final='';
      for(let i=e.resultIndex;i<e.results.length;i++){
        const t=e.results[i][0].transcript;
        e.results[i].isFinal ? final+=t : interim+=t;
      }
      const preview=document.getElementById('voice-preview');
      if(preview) preview.textContent = interim || final;
      if(final) _handlers.forEach(h=>h(final.trim()));
    };
    _recog.onend = () => {
      _listening=false;
      const btn=document.getElementById('voice-btn');
      if(btn){ btn.style.color=''; btn.style.borderColor=''; btn.title='Voice input (click to speak)'; }
      const preview=document.getElementById('voice-preview');
      if(preview) preview.textContent='';
    };
    _recog.onerror = e => {
      _listening=false; console.warn('Speech error:',e.error);
      if(e.error!=='aborted') toast('Voice error: '+e.error,'warn');
    };
    try{ _recog.start(); return true; }
    catch(e){ console.error(e); return false; }
  }

  function stopListening(){
    if(_recog){ try{_recog.stop();}catch{} }
    _listening=false;
  }

  function speak(text, lang='th-TH'){
    if(!_ttsEnabled || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const clean = text.replace(/[#*`>]/g,'').slice(0,500);
    const utt = new SpeechSynthesisUtterance(clean);
    utt.lang = lang;
    utt.rate = 1.0; utt.pitch = 1.0; utt.volume = 0.9;
    // Try to find a Thai voice
    const voices = window.speechSynthesis.getVoices();
    const thVoice = voices.find(v=>v.lang.startsWith('th')) ||
                    voices.find(v=>v.lang.startsWith('en'));
    if(thVoice) utt.voice = thVoice;
    window.speechSynthesis.speak(utt);
  }

  function toggle(){ _ttsEnabled=!_ttsEnabled; return _ttsEnabled; }
  function isListening(){ return _listening; }
  function ttsOn(){ return _ttsEnabled; }

  return { startListening, stopListening, speak, toggle, onTranscript, isListening, ttsOn };
})();

// ══════════════════════════════════════════════════════════
//  MEMORY — Client-side helpers
// ══════════════════════════════════════════════════════════
const Memory = {
  _session: 'sess_' + Date.now(),

  async save(content, role='user', important=false){
    try{
      await fetch('/api/memory/save',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({content,role,session:this._session,important})});
    }catch{}
  },

  async search(q){ return await api('GET',`/api/memory/search?q=${encodeURIComponent(q)}`); },
  async recent(n=20){ return await api('GET',`/api/memory/recent?limit=${n}&session=${this._session}`); },
  async stats(){ return await api('GET','/api/memory/stats'); },
  async saveFact(key,value){ return await api('POST','/api/memory/facts',{key,value}); },

  setSession(id){ this._session = id; },
  getSession(){ return this._session; },
};

// ══════════════════════════════════════════════════════════
//  SCHEDULER — Client-side helpers
// ══════════════════════════════════════════════════════════
const Scheduler = {
  async list(){ return await api('GET','/api/scheduler/jobs'); },
  async add(name,cmd,interval_s=3600,type='interval'){
    return await api('POST','/api/scheduler/jobs',{name,cmd,interval_s,type});
  },
  async remove(id){ return await fetch(`/api/scheduler/jobs/${id}`,{method:'DELETE'}).then(r=>r.json()); },
  async runNow(id){ return await api('POST',`/api/scheduler/jobs/${id}/run`); },
  async logs(id){ return await api('GET',`/api/scheduler/logs?job_id=${id}`); },
};
