import {$,api,esc,evid,safeURL,empty,heading,list,modal,send,msg,reqid} from "./common.js";
async function work(id){
 const w=await api("/api/works/"+encodeURIComponent(id));
 const loc=w.metadata.canonical_url;
 modal(w.title,(loc?'<p><a target="_blank" rel="noopener" href="'+safeURL(loc)+'">原始材料 ↗</a></p>':'')+'<p>'+esc(w.metadata.abstract||"")+'</p><h3>文档修订</h3>'+ (w.revisions.length?list(w.revisions.map(v=>esc([v.version,v.mode,v.upstream_revision].filter(Boolean).join(" · "))+'<br><small>已读取区间 '+esc(v.coverage)+'，解析文本共 '+v.total_chars+' 字符</small>')):empty("此作品目前仅有元数据。"))+'<h3>原文证据</h3>'+(w.evidence.length?list(w.evidence.map(e=>evid(e.id,"第 "+e.line_start+" 行")+"　"+esc(e.quote.slice(0,170)))):empty("尚未生成原文定位。"))+'<h3>阅读反馈</h3><div class="buttons"><button class="quiet" data-v="useful">有实质帮助</button><button class="quiet" data-v="average">一般</button><button class="quiet" data-v="irrelevant">无关</button><button class="quiet" data-v="read">标为已读</button></div><label>原因（可选）<input id="reading-reason"></label>');
 document.querySelectorAll("[data-v]").forEach(b=>b.onclick=async()=>{await send("/api/feedback",{entity_type:"work",entity_id:id,dimension:b.dataset.v==="read"?"reading_status":"reading_value",value:b.dataset.v,reason:$("#reading-reason").value,request_id:reqid()});msg("已记录阅读反馈")});
}
async function job(id){const p=await api("/api/postings/"+encodeURIComponent(id));modal(p.title,'<a target="_blank" rel="noopener" href="'+safeURL(p.url)+'">官方岗位详情 ↗</a>'+list(p.observations.map(o=>esc(o.verified_at+" · "+o.status)+'<div class="row">'+(o.details.evidence_ids||[]).map((e,i)=>evid(e,"要求 "+(i+1))).join(" ")+'</div>')))}
export async function render(){
 $("#app").innerHTML=heading("证据库","查找作品、固定修订和支撑判断的原文。")+'<form id="filter" class="controls"><label>来源类型<select id="kind"><option value="paper">论文</option><option value="code">代码与资源</option><option value="job">岗位</option><option value="team">团队</option></select></label><label>搜索<input id="q" type="search" placeholder="标题或原文关键词"></label><button>查询</button></form><div class="panel"><ul class="list" id="items"></ul><div id="pager" class="buttons"></div></div>';
 let offset=0;const limit=25;
 async function load(){const k=$("#kind").value;const params=new URLSearchParams({kind:k,q:$("#q").value.trim(),offset,limit});
 const result=await api("/api/library?"+params);$("#items").innerHTML=result.map(x=>'<li>'+ (k==="paper"||k==="job"?'<button class="link" data-id="'+esc(x.id)+'">'+esc(x.title)+'</button>':x.url?'<a target="_blank" rel="noopener" href="'+safeURL(x.url)+'">'+esc(x.title)+'</a>':esc(x.title))+(k==="paper"?'<div class="sub">'+esc([x.published,x.evidence_count?x.evidence_count+" 处引文":"元数据"].filter(Boolean).join(" · "))+'</div>':'')+'</li>').join("")||empty("没有找到符合条件的材料。");
 document.querySelectorAll("[data-id]").forEach(b=>b.onclick=()=>k==="job"?job(b.dataset.id):work(b.dataset.id));$("#pager").innerHTML=(offset?'<button id="prev" class="quiet">上一页</button>':'')+(result.length===limit?'<button id="next" class="quiet">下一页</button>':'');
 if($("#prev"))$("#prev").onclick=()=>{offset-=limit;load()};if($("#next"))$("#next").onclick=()=>{offset+=limit;load()}}
 $("#filter").onsubmit=e=>{e.preventDefault();offset=0;load()};$("#kind").onchange=()=>{offset=0;load()};await load();
 const id=new URL(location).searchParams.get("work");if(id)await work(id);
}
