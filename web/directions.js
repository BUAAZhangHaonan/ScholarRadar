import {$,api,empty,esc,evid,msg} from "./common.js";
import {acceptControl,enableActions,followControl,humanDate,materialList,objectFeedback,pathFor,prose} from "./reader.js";
import {attachPrestudy} from "./prestudy.js";
import {editor} from "./direction-editor.js";

const layers={core:"核心",adjacent:"相邻",frontier:"前沿"};
const localUrl=(id,snapshot)=>pathFor("directions",id)+(snapshot?"?snapshot="+encodeURIComponent(snapshot):"");
function note(text){
  if(typeof text!=="string")return "";
  return text.replace(/[（(]\s*[a-f0-9]{32}(?:[\s,，、/]+[a-f0-9]{32})*\s*[)）]/gi,"（见原文）")
    .replace(/\b[a-f0-9]{32}\b/gi,"相应原文").replace(/\bJ\d+\s*[:：]\s*/g,"");
}
function section(title,content){
  return content?'<section class="rule-section"><h2 class="section-title">'+title+'</h2>'+content+'</section>':"";
}
function terms(definition){
  return definition.filter(([,v])=>typeof v==="string"&&v.trim()).map(([k,v])=>
    "<dt>"+esc(k)+"</dt><dd>"+prose(note(v))+"</dd>").join("");
}
function nearest(value){
  if(!value)return "";
  if(typeof value==="string")return prose(value);
  return (value.work_id?'<p><a href="'+pathFor("works",value.work_id)+'">'+esc(value.title||"最近邻论文")+'</a></p>':prose(value.title))+
    '<dl class="kv">'+terms([["相同点",value.similarity],["待区分之处",value.difference]])+'</dl>';
}
function timeline(d,snapshot){
  const records=snapshot?.history||[];
  const evidence=records.map(h=>'<li><time>'+esc(h.date||("首次读到 "+humanDate(h.first_observed)))+'</time>'+esc(h.event)+
    (h.work_id?'　<a href="'+pathFor("works",h.work_id)+'">论文</a>':"")+(h.evidence_ids?.length?'　'+evid(h.evidence_ids[0],"读引文"):"")+'</li>').join("");
  const snapshots=d.timeline.map(n=>'<li><a href="'+localUrl(d.id,n.snapshot_id)+'#history">'+esc(humanDate(n.date))+
    (n.verdict==="supported"?" 的研究判断":" 的观察记录")+'</a>'+
    (n.change?prose(n.change):"")+'</li>').join("");
  return '<details class="rule-section" id="history"><summary>研究脉络与历次判断</summary>'+
    (evidence?'<ol class="timeline">'+evidence+'</ol>':"")+(snapshots?'<ul class="list">'+snapshots+'</ul>':"")+'</details>';
}
async function detail(id,sid){
  const d=await api("/api/reading/directions/"+encodeURIComponent(id)+(sid?"?snapshot="+encodeURIComponent(sid):""));
  const cur=d.current, supported=cur?.verdict==="supported";
  document.title=d.title+" · ScholarRadar";
  const fit=cur?.feasibility||{}, hypothesis=cur?.forecast||{}, action=cur?.action||{};
  const opening=supported?prose(cur.judgment)+prose(cur.change):
    prose(cur?.open_issue?note(cur.open_issue):"这个问题正在跟踪中，尚待形成有材料支撑的判断。");
  const entry=supported?prose(hypothesis.hypothesis||d.question)+
    '<dl class="kv">'+terms([["可复用",fit.asset],["开展条件",fit.needed],["预计投入",fit.budget]])+'</dl>'+
    (cur.next_step?'<div class="story-next">'+prose(cur.next_step)+'</div>':"")+
    (cur.action_id?'<div class="story-actions">'+acceptControl(cur.action_id,cur.action_state)+'</div>':""):
    prose(d.question===d.title?d.method:d.question)+prose(d.setting);
  const methodology=supported?terms([["方法与对照",action.control||cur.method],["评估",action.metric||cur.setting],
    ["适用条件",cur.limitation],["支持条件",hypothesis.confirm],["反例条件",hypothesis.refute],["资料与资源",cur.resources]]):"";
  const career=supported&&cur.career?terms([["岗位要求",cur.career.requirement],["已有积累",cur.career.asset],["仍需准备",cur.career.gap]]):"";
  $("#app").innerHTML='<a class="breadcrumb" href="/directions">← 研究方向</a><header class="page-head"><div><h1>'+esc(d.title)+'</h1>'+
    (cur?'<p class="sub">'+esc(humanDate(cur.selected_at))+' · '+(supported?"研究判断":"观察中")+'</p>':"")+'</div>'+
    followControl(d.id,d.followed,cur?.snapshot_id)+'</header><div class="flow direction-reading">'+
    '<section class="reading"><h2 class="section-title">'+(supported?"当前认识":"仍待回答的问题")+'</h2>'+opening+'</section>'+
    '<section class="feature-story"><h2>可以推进的研究切口</h2><div class="story-body">'+entry+'</div></section>'+
    (cur?'<section id="prestudy" class="rule-section"></section>':"")+
    (cur?.materials?.length?section("关键材料",materialList(cur.materials)):"")+
    (supported?section("最近邻与差别",nearest(cur.nearest)):"")+
    (methodology?'<details class="rule-section" id="conditions"><summary>比较方法与判断条件</summary><dl class="kv">'+methodology+'</dl></details>':"")+
    (career?section("与你的目标如何相接",'<dl class="kv">'+career+'</dl>'+
      (cur.career.evidence_ids||[]).map(e=>evid(e,"岗位原文")).join(" ")):"")+
    (cur?timeline(d,cur):"")+objectFeedback("direction",id,cur?.snapshot_id)+
    '<div id="direction-management"></div></div>';
  enableActions($("#app"));
  await editor(d,()=>location.reload(),$("#direction-management"));
  if(cur)await attachPrestudy($("#prestudy"),d,cur.snapshot_id);
}
function options(values,current){
  return values.map(([v,name])=>'<option value="'+esc(v)+'"'+(v===current?" selected":"")+'>'+name+'</option>').join("");
}
async function listDirections(){
  const here=new URL(location.href),layer=here.searchParams.get("layer")||"",state=here.searchParams.get("status")||"";
  const query=new URLSearchParams();if(layer)query.set("layer",layer);if(state)query.set("status",state);
  const data=await api("/api/directions?"+query);
  document.title="研究方向 · ScholarRadar";
  $("#app").innerHTML='<header class="page-head"><h1>研究方向</h1><form id="filters" class="controls">'+
    '<label>范围<select name="layer">'+options([["","全部"],["core","核心"],["adjacent","相邻"],["frontier","前沿观察"]],layer)+'</select></label>'+
    '<label>状态<select name="status">'+options([["","全部"],["tracking","跟踪中"],["candidate","候选"],["accepted","已接受"],["active","进行中"],["deferred","暂缓"]],state)+'</select></label></form></header>'+
    '<div class="grid">'+(data.map(d=>'<article class="card direction-card"><p class="eyeline">'+esc(layers[d.layer]||"研究方向")+
    (d.followed?" · 已关注":"")+'</p><h2><a href="'+localUrl(d.id)+'">'+esc(d.title)+'</a></h2><div class="story-body">'+
    prose(d.latest_judgment||d.question)+((d.latest_change&&d.latest_change!==d.latest_judgment)?prose(d.latest_change):"")+
    (d.personal_fit_summary?prose(d.personal_fit_summary):"")+(d.next_action?'<div class="story-next">'+prose(d.next_action)+'</div>':"")+
    '</div><div class="story-actions"><a class="button quiet" href="'+localUrl(d.id)+'">打开方向</a>'+
    followControl(d.id,d.followed,d.latest_snapshot_id)+'</div></article>').join("")||empty("没有符合筛选条件的方向。"))+'</div>';
  $("#filters").onchange=e=>{const form=new FormData(e.currentTarget);const q=new URLSearchParams();for(const[k,v] of form)if(v)q.set(k,v);
    location.assign("/directions"+(q.size?"?"+q:""))};
  enableActions($("#app"));
}
export async function render(){
  const old=new URL(location.href);let id=old.pathname.startsWith("/directions/")?decodeURIComponent(old.pathname.slice(12)):old.searchParams.get("id");
  if(id&&old.pathname==="/directions"){
    old.pathname=localUrl(id);old.searchParams.delete("id");history.replaceState(history.state,"",old);
  }
  if(id)await detail(id,old.searchParams.get("snapshot"));else await listDirections();
}
