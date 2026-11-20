import {$,api,esc,txt,evid,empty,heading,list,modal} from "./common.js";
const layers={core:"核心",adjacent:"相邻",frontier:"前沿观察"},states={tracking:"跟踪中",candidate:"候选",merged:"已归并"};
const names={activity_share_change:"观察份额变化",evidence_progress:"证据进展",reproducibility:"复现条件",research_opening:"研究切入点",personal_feasibility:"个人可行性",career_match:"岗位关联"};
export async function detail(id){
 const d=await api("/api/directions/"+encodeURIComponent(id));
 const detail=d.snapshots.map(s=>{const b=s.body;return '<section class="card"><span class="meta">'+esc(s.as_of.slice(0,10))+'</span><h2>'+esc(b.judgment)+'</h2><p>'+esc(b.change)+'</p><dl class="kv"><dt>最近邻工作</dt><dd>'+esc(b.nearest)+'</dd><dt>现有资产</dt><dd>'+esc(txt(b.feasibility))+'</dd><dt>适用条件</dt><dd>'+esc(b.limitation)+'</dd><dt>待验证预测</dt><dd>'+esc(b.forecast.hypothesis)+'</dd></dl><details><summary>六组因子及依据</summary>'+list(s.factors.map(f=>'<strong>'+esc(names[f.factor_id]||f.factor_id)+'</strong><br>'+esc(f.value===null?f.reason:txt(f.value)||JSON.stringify(f.value))+' '+(f.evidence_ids||[]).slice(0,1).map(x=>evid(x)).join("")))+'</details><div class="row">'+(b.evidence_ids||[]).slice(0,4).map((e,i)=>evid(e,"证据 "+(i+1))).join(" ")+'</div></section>'}).join("");
 modal(d.title,'<dl class="kv"><dt>研究问题</dt><dd>'+esc(d.question)+'</dd><dt>方法抓手</dt><dd>'+esc(d.method)+'</dd><dt>评估场景</dt><dd>'+esc(d.setting)+'</dd></dl><h3>判断历史</h3><div class="stack">'+(detail||empty("正在积累可定位的证据，尚无方向快照。"))+'</div>');
}
export async function render(){
 $("#app").innerHTML=heading("方向库","按研究问题查看最近邻工作、判断历史和下一步验证。")+'<div class="controls"><label>观察层次<select id="layer"><option value="">全部</option><option value="core">核心</option><option value="adjacent">相邻</option><option value="frontier">前沿观察</option></select></label><label>跟踪或行动状态<select id="state"><option value="">全部</option><option value="tracking">跟踪中</option><option value="candidate">候选</option><option value="accepted">已接受</option><option value="active">进行中</option><option value="deferred">暂缓</option></select></label></div><div id="dirs" class="grid"></div>';
 async function load(){const query=new URLSearchParams();if($("#layer").value)query.set("layer",$("#layer").value);if($("#state").value)query.set("status",$("#state").value);
 const dirs=await api("/api/directions?"+query);$("#dirs").innerHTML=dirs.map(d=>'<article class="card"><span class="tag">'+esc(layers[d.layer]||d.layer)+'</span><h2>'+esc(d.title)+'</h2><p>'+esc(d.method)+'</p><p class="sub">'+esc(states[d.status]||d.status)+' · '+d.snapshot_count+' 份快照</p><button class="link" data-dir="'+esc(d.id)+'">查看方向</button></article>').join("")||empty("没有符合当前筛选的方向。");
 document.querySelectorAll("[data-dir]").forEach(b=>b.onclick=()=>detail(b.dataset.dir))}
 $("#layer").onchange=load;$("#state").onchange=load;await load();const id=new URL(location).searchParams.get("id");if(id)await detail(id);
}
