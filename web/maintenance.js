import {$,api,esc,heading,list,modal,msg,send} from "./common.js";
import {controls} from "./research-settings.js";

const labels={trace:"ScholarTrace",analysis:"ScholarAnalysis",web:"webresearch-mcp",queued:"排队中",running:"运行中",done:"完成",
  partial:"部分完成",failed:"失败",daily:"日报",weekly:"周报",monthly:"月报",arc:"预研",pending:"待归档",archived:"已归档"};
const label=x=>labels[x]||x;
export async function render(){
  const [s,runs]=await Promise.all([api("/api/status"),api("/api/runs")]);
  document.title="运行维护 · ScholarRadar";
  $("#app").innerHTML=heading("运行维护")+'<div class="layout"><div class="stack" id="ops-controls"><section class="panel"><h2>采集与报告</h2>'+
    '<div class="controls"><label>手工任务<select id="run-kind"><option value="daily">日报</option><option value="weekly">周报</option><option value="monthly">月报</option></select></label>'+
    '<button id="run-submit">加入队列</button><button class="quiet" id="run-refresh">刷新</button></div>'+
    (runs.length?list(runs.map(r=>'<button class="link" data-run="'+esc(r.id)+'">'+esc(r.as_of+" · "+label(r.kind))+'</button>　'+esc(label(r.status)))):'<p class="sub">尚无运行记录。</p>')+
    '</section></div><aside class="stack"><section class="panel"><h2>服务连接</h2>'+list(Object.entries(s.services).map(([k,v])=>'<strong>'+esc(label(k))+
    '</strong><p class="sub">'+esc(v.status==="ok"?"已连接":v.status)+' · '+esc(v.tools.join("、"))+'</p>'))+'</section>'+
    '<section class="panel"><h2>累计用量</h2><p>已知下界 ¥'+esc(s.cost.known_lower)+'，已知上界 '+esc(s.cost.known_upper==null?"待核算":"¥"+s.cost.known_upper)+
    '。</p><p class="sub">待核算 '+esc(s.cost.unknown)+' 项</p></section><section class="panel"><h2>NAS 归档</h2>'+
    list(s.archive.map(x=>esc(label(x.status))+'　'+esc(x.count)))+'</section></aside></div>';
  await controls($("#ops-controls"));
  $("#run-refresh").onclick=render;
  $("#run-submit").onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{const result=await send("/api/runs",{kind:$("#run-kind").value});
    msg(result.reused?"已复用既有任务":"已加入队列");await render()}catch(ex){b.disabled=false;msg(ex.message)}};
  document.querySelectorAll("[data-run]").forEach(b=>b.onclick=async()=>{
    try{
      const r=await api("/api/runs/"+encodeURIComponent(b.dataset.run));
      modal(r.as_of+" · "+label(r.kind),'<h3>采集覆盖</h3>'+list(r.coverage.map(x=>esc([x.source,label(x.status),x.reason].filter(Boolean).join(" · "))))+
        '<h3>阶段</h3>'+list(r.jobs.map(j=>esc(j.stage+" · "+label(j.status))+(j.status==="failed"?'<p class="sub">'+esc(j.outcome)+'</p>':"")))+
        '<h3>调用</h3>'+list(r.calls.map(v=>esc(v.service+"/"+v.tool+" · "+label(v.status)+(v.cached?" · 已复用":""))))+
        (r.status==="partial"?'<button id="resume-run" class="quiet">恢复可重试阶段</button>':""));
      if($("#resume-run"))$("#resume-run").onclick=async()=>{try{const x=await send("/api/runs/"+encodeURIComponent(b.dataset.run)+"/resume",{});msg(x.queued_stages?.length?"已安排恢复":"当前没有可重试阶段")}catch(ex){msg(ex.message)}}
    }catch(ex){msg(ex.message)}
  });
}
