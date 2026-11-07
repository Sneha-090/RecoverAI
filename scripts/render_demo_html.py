"""Self-contained replay of recorded offline evidence; no backend or CDN calls."""

import json


def render_demo_html(report):
    payload = json.dumps(report).replace('<', '\\u003c').replace('&', '\\u0026')
    return TEMPLATE.replace('__DEMO_JSON__', payload)


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RecoverAI — offline evidence walkthrough</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0c1424;color:#eef3fc}*{box-sizing:border-box}body{margin:0}main{max-width:1200px;margin:auto;padding:38px 24px}h1{font-size:clamp(28px,5vw,44px);letter-spacing:-1px;margin:14px 0}h2{font-size:25px;line-height:1.3}p{line-height:1.65;color:#b9c7df}.label{font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:#83ddcc}.notice{border:1px solid #56688c;background:#182640;border-radius:12px;padding:14px 18px;font-size:14px;line-height:1.6}.layout{display:grid;grid-template-columns:300px 1fr;gap:22px;margin-top:28px}nav{display:grid;gap:9px;align-content:start}button{font:inherit;color:#eff5ff;background:#1a2942;border:1px solid #445677;border-radius:9px;padding:12px 15px;cursor:pointer;text-align:left}button:hover{border-color:#8ce7d1}button[aria-pressed=true]{background:#16463f;border-color:#75d9bf}button:focus-visible{outline:3px solid #b5ffde;outline-offset:3px}.panel{background:#121f35;border:1px solid #334664;border-radius:16px;padding:26px}.counter{color:#aabbd7;font-size:13px}.step{border-left:3px solid #81dcc6;padding:10px 0 10px 18px;font-size:20px;line-height:1.6;min-height:145px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:24px}.card{background:#0d192b;border-radius:10px;padding:14px;font-size:13px;color:#b8c7e1}.card strong{display:block;color:#d5ffee;font-size:21px;margin-top:9px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}progress{width:100%;height:8px;accent-color:#81dcc6;margin:22px 0 4px}code{color:#bbefd9;font-size:13px;overflow-wrap:anywhere}details{margin-top:25px;font-size:13px}li{line-height:1.7;margin-bottom:8px}footer{margin-top:30px;font-size:13px;color:#a7b9d5}@media(max-width:800px){.layout{grid-template-columns:1fr}.cards{grid-template-columns:1fr}main{padding:22px 16px}.panel{padding:20px}.step{min-height:130px}}
</style></head><body><main>
<div class="label">RecoverAI / engineering evidence</div><h1>Recovery, including the difficult cases.</h1>
<p>Six reproducible scenarios exercise the real application services with a fake payment provider and a fresh SQLite database.</p>
<div class="notice"><strong>Offline simulation — no merchant revenue claim.</strong> Buttons replay a recorded run; they do not send payments or rerun the backend. Generate fresh evidence with <code>python -m scripts.offline_demo</code>. External networking is blocked during that run; Windows loopback IPC is allowed.</div>
<div class="layout"><nav id="scenarios" aria-label="Choose a recorded scenario"></nav><section class="panel" aria-live="polite">
<div class="counter" id="counter"></div><h2 id="title"></h2><p class="step" id="step"></p>
<progress id="progress" aria-label="Recorded walkthrough progress"></progress>
<div class="actions"><button id="prev">Previous step</button><button id="next">Next step</button><button id="play">Replay all</button></div>
<div class="cards"><div class="card">Recorded final case state<strong id="state"></strong></div><div class="card">Simulated provider creations<strong id="creates"></strong></div><div class="card">Stored outcomes<strong id="outcomes"></strong></div></div>
<details><summary>Recorded audit events</summary><ol id="audit"></ol></details>
</section></div><footer>The separately documented Razorpay Test Mode checkout is a different verification. This walkthrough demonstrates failure handling with controlled fixtures, not production performance.</footer>
</main><script type="application/json" id="run-data">__DEMO_JSON__</script><script>
const report=JSON.parse(document.getElementById('run-data').textContent);let scenario=0,step=0,timer=null;
const byId=id=>document.getElementById(id);const buttons=[];
report.scenarios.forEach((item,index)=>{const button=document.createElement('button');button.textContent=(index+1)+'. '+item.name;button.onclick=()=>{stop();scenario=index;step=0;render()};byId('scenarios').appendChild(button);buttons.push(button)});
function render(){const item=report.scenarios[scenario];buttons.forEach((button,index)=>button.setAttribute('aria-pressed',String(index===scenario)));byId('counter').textContent='SCENARIO '+(scenario+1)+' / '+report.scenarios.length+' · STEP '+(step+1)+' / '+item.steps.length;byId('title').textContent=item.name;byId('step').textContent=item.steps[step];byId('state').textContent=item.final_status;byId('creates').textContent=item.provider_creations;byId('outcomes').textContent=item.outcomes;byId('progress').max=item.steps.length;byId('progress').value=step+1;byId('audit').replaceChildren();item.audit_events.forEach(value=>{const li=document.createElement('li');li.textContent=value;byId('audit').appendChild(li)})}
function stop(){if(timer)clearInterval(timer);timer=null;byId('play').textContent='Replay all'}
function next(){const item=report.scenarios[scenario];if(step+1<item.steps.length)step++;else if(scenario+1<report.scenarios.length){scenario++;step=0}else{stop();return}render()}
byId('next').onclick=()=>{stop();next()};byId('prev').onclick=()=>{stop();if(step>0)step--;else if(scenario>0){scenario--;step=report.scenarios[scenario].steps.length-1}render()};byId('play').onclick=()=>{if(timer){stop();return}scenario=0;step=0;render();byId('play').textContent='Pause replay';timer=setInterval(next,6000)};render();
</script></body></html>'''
