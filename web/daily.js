import {$,api,empty,esc,evid} from "./common.js";
import {acceptControl,enableActions,followControl,humanDate,materialList,pathFor,prose} from "./reader.js";

const periods={daily:"日报",weekly:"周报",monthly:"月报"};
function directionLink(id,snapshot){
  return pathFor("directions",id)+(snapshot?"?snapshot="+encodeURIComponent(snapshot):"");
}
function shortFinding(text){
  if(typeof text!=="string")return "";
  const opening=text.trim().split(/\n\s*\n/)[0];
  return opening.match(/^.{1,210}?[。！？](?=\s|[^”’]|$)/u)?.[0] || opening;
}
function reportUrl(kind,date=""){
  const q=new URLSearchParams();
  if(kind!=="daily")q.set("kind",kind);
  if(date)q.set("date",date);
  return "/"+(q.size?"?"+q:"");
}
function paperUpdateUrl(item) {
  const base=pathFor("works",item.work_id);
  return item.record_id ? base+"?record="+encodeURIComponent(item.record_id)+"#record-"+encodeURIComponent(item.record_id) : base;
}
function mainStory(item){
  const target=directionLink(item.direction_id,item.snapshot_id);
  return '<article class="feature-story"><div class="eyeline">重点变化</div><h2>'+esc(item.title)+'</h2>'+
    '<div class="story-body">'+prose(item.change)+prose(item.personal_fit)+
    (item.next_step?'<div class="story-next"><p>'+esc(item.next_step)+'</p></div>':"")+
    '</div><div class="story-actions"><a class="button" href="'+target+'">查看研究切口</a>'+
    followControl(item.direction_id,item.followed,item.snapshot_id)+'</div>'+
    (item.materials?.length?'<details class="source-fold"><summary>关键材料</summary>'+materialList(item.materials)+'</details>':"")+
    '</article>';
}
function restStory(item){
  return '<li><h3><a href="'+directionLink(item.direction_id,item.snapshot_id)+'">'+esc(item.title)+'</a></h3>'+
    prose(item.change||item.judgment)+'</li>';
}
function weeklyProposal(p){
  if(!p)return "";
  const detail=p.details||{};
  return '<section class="rule-section"><h2 class="section-title">可推进的验证</h2><h3>'+esc(p.title)+'</h3>'+
    '<div class="story-body">'+prose(p.why)+prose(detail.control)+'</div><div class="story-actions">'+
    (p.direction_id?'<a class="button" href="'+directionLink(p.direction_id,p.snapshot_id)+'">查看研究切口</a>':"")+
    acceptControl(p.action_id,p.status||"proposed")+'</div></section>';
}
function nodeEvents(n){
  const actionNames={accepted:"接受",deferred:"暂缓",rejected:"拒绝",active:"开始",completed:"完成"};
  const values={read:"已读",known:"已有了解",useful:"有帮助",average:"一般",irrelevant:"无关",followed:"已关注",unfollowed:"取消关注",try:"值得试",skip:"暂不选"};
  const events=[];
  for(const a of n.actions||[]){
    let details=a.actual;
    if(typeof details==="string"){try{details=JSON.parse(details)}catch{details=null}}
    events.push([actionNames[a.decision]||a.decision,a.title,a.reason,details?.note].filter(Boolean).join(" · "));
  }
  for(const f of n.feedback||[]){const label=f.dimension==="comparison"&&f.value==="read"?"值得读":values[f.value];
    if(label||f.reason)events.push(["阅读反馈",label,f.reason].filter(Boolean).join(" · "))}
  return events.map(t=>'<p class="sub">'+esc(t)+'</p>').join("");
}
function periodEvolution(chains){
  if(!chains?.length)return "";
  return '<section class="rule-section"><h2 class="section-title">这一期如何演变</h2>'+
    chains.map(d=>'<details><summary>'+esc(d.title)+'</summary><ol class="timeline">'+
      d.nodes.map(n=>'<li><time>'+esc((n.baseline?'期初 · ':'')+humanDate(n.date))+'</time>'+
        (n.verdict==="needs_evidence"?"材料仍不足，保留为观察问题。":esc(n.change||n.judgment||""))+nodeEvents(n)+
        (n.snapshot_id&&d.direction_id?'　<a href="'+directionLink(d.direction_id,n.snapshot_id)+'">查看当时判断</a>':"")+
        (n.evidence_ids?.length?'　'+evid(n.evidence_ids[0],"读引文"):"")+'</li>').join("")+
      '</ol></details>').join("")+'</section>';
}
export async function render(){
  const q=new URLSearchParams(location.search);
  const kind=Object.hasOwn(periods,q.get("kind"))?q.get("kind"):"daily";
  const selectedDate=q.get("date")||"";
  const request=new URLSearchParams({kind});if(selectedDate)request.set("date",selectedDate);
  const report=await api("/api/reading/report?"+request);
  const [lead,...other]=report.items||[];
  const updates=[...(report.updates||[])];
  const standalone=lead?null:updates.shift();
  const heading=kind==="daily"?"研究动态":kind==="weekly"?"每周研究判断":"每月研究复盘";
  document.title=heading+" · ScholarRadar";
  const controls='<div class="section-tools"><div class="periods" aria-label="报告周期">'+Object.entries(periods).map(([v,n])=>
    '<a href="'+reportUrl(v,selectedDate)+'"'+(v===kind?' aria-current="page"':"")+'>'+n+'</a>').join("")+
    '</div><label class="compact-date">报告日期<input id="period-date" type="date" value="'+esc(selectedDate||report.date||"")+'"></label></div>';
  const headline=report.summary?'<section class="reading"><h2 class="section-title">本期判断</h2>'+prose(report.summary)+'</section>':"";
  const news=updates.length?'<section class="rule-section"><h2 class="section-title">'+(lead?"其他值得读的工作":"近期值得读的工作")+
    '</h2><ul class="list">'+updates.map(u=>'<li><h3><a href="'+paperUpdateUrl(u)+'">'+esc(u.title)+'</a></h3>'+
    prose(shortFinding(u.body))+'</li>').join("")+'</ul></section>':"";
  const watch=report.watch?.length?'<section class="rule-section"><h2 class="section-title">观察线索</h2><ul class="list">'+
    report.watch.map(w=>'<li><a href="'+directionLink(w.direction_id,w.snapshot_id)+'">'+esc(w.question)+'</a></li>').join("")+'</ul></section>':"";
  const solo=standalone?'<article class="feature-story"><div class="eyeline">重点阅读</div><h2>'+esc(standalone.title)+'</h2>'+
    prose(shortFinding(standalone.body))+'<div class="story-actions"><a class="button" href="'+paperUpdateUrl(standalone)+'">阅读研究记录</a></div></article>':"";
  const none=(!lead&&!standalone&&!updates.length)?'<section class="panel">'+empty(report.state==="working"?"正在查阅这一期的材料。":report.state==="empty"?
    "这个日期还没有发布报告。":"这一期还没有形成新的研究判断。")+'<a href="/directions">继续阅读已有方向</a></section>':"";
  $("#app").innerHTML='<header class="page-head"><div><h1>'+heading+'</h1>'+(report.date?'<p class="sub">'+esc(report.date)+'</p>':"")+'</div>'+controls+
    '</header><div class="flow">'+headline+(lead?mainStory(lead):solo)+none+
    (other.length?'<section class="rule-section"><h2 class="section-title">其他变化</h2><ul class="list">'+other.map(restStory).join("")+'</ul></section>':"")+
    news+weeklyProposal(report.proposal)+periodEvolution(report.evolution)+
    (report.unresolved?.length?'<section class="rule-section"><h2 class="section-title">仍待回答的问题</h2><ul class="list">'+report.unresolved.map(q=>'<li>'+prose(q)+'</li>').join("")+'</ul></section>':"")+
    (report.readings?.length?'<section class="rule-section"><h2 class="section-title">本期精读</h2>'+materialList(report.readings)+'</section>':"")+watch+'</div>';
  $("#period-date").onchange=e=>location.assign(reportUrl(kind,e.target.value));
  enableActions($("#app"));
}
