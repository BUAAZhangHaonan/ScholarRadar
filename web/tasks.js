import {$,api,empty,esc,heading,msg,send} from "./common.js";
import {humanDate,pathFor} from "./reader.js";
import {isActive,presentation,stageName,stageStatus} from "./prestudy.js";
import {actionArea} from "./actions.js";

const stagePath=t=>pathFor("tasks",t.id);
const original=t=>pathFor("directions",t.direction_id)+"?snapshot="+encodeURIComponent(t.snapshot_id)+"#prestudy-"+encodeURIComponent(t.id);
async function detail(id){
  const task=await api("/api/prestudies/"+encodeURIComponent(id));
  const title=task.focus||stageName(task.stage);document.title=title+" · ScholarRadar";
  $("#app").innerHTML='<a class="breadcrumb" href="/tasks">← 研究任务</a><header class="page-head"><div><h1>'+esc(title)+'</h1>'+
    '<p class="sub">'+esc([stageName(task.stage),stageStatus(task),humanDate(task.updated_at||task.created_at)].join(" · "))+'</p></div></header>'+
    '<div class="flow"><div><a href="'+original(task)+'">回到'+esc(task.direction_title||"原方向")+'</a></div>'+
    presentation(task)+(["connection_unknown","paused_external"].includes(task.status)?'<p><button id="resume-task">恢复原任务</button></p>':"")+'</div>';
  if($("#resume-task"))$("#resume-task").onclick=async e=>{const b=e.currentTarget;b.disabled=true;try{
    await send("/api/prestudies/"+encodeURIComponent(id)+"/resume",{});await detail(id)
  }catch(ex){b.disabled=false;msg(ex.message)}};
  if(isActive(task)){
    setTimeout(()=>{if(!document.hidden && location.pathname===stagePath(task))detail(id).catch(e=>msg(e.message))},9000);
  }
}
async function overview(){
  document.title="研究任务 · ScholarRadar";
  $("#app").innerHTML=heading("研究任务")+'<div class="flow"><section><h2 class="section-title">方向预研</h2><div id="prestudy-list"></div></section><section id="action-list" class="rule-section"></section></div>';
  async function loadStages(){
    const target=$("#prestudy-list");
    try{
      const list=await api("/api/prestudies");
      target.innerHTML=list.length?'<ul class="list">'+list.map(t=>'<li><h3><a href="'+stagePath(t)+'">'+esc(t.focus||t.direction_title)+'</a></h3>'+
        '<p class="sub">'+esc([stageName(t.stage),stageStatus(t),humanDate(t.updated_at||t.created_at)].join(" · "))+'</p>'+
        '<a href="'+original(t)+'">'+esc(t.direction_title||"回到研究方向")+'</a></li>').join("")+'</ul>':
        empty("还没有提交预研任务。")+'<a href="/directions">选择研究切口</a>';
      if(list.some(isActive))setTimeout(()=>{if(target.isConnected&&!document.hidden)loadStages()},12000);
    }catch(ex){target.innerHTML='<p class="error">'+esc(ex.message)+'</p>'}
  }
  await Promise.all([loadStages(),actionArea($("#action-list"))]);
}
export async function render(){
  if(location.pathname==="/actions")history.replaceState(history.state,"","/tasks"+location.search);
  const id=location.pathname.startsWith("/tasks/")?decodeURIComponent(location.pathname.slice(7)):null;
  if(id)await detail(id);else await overview();
}
