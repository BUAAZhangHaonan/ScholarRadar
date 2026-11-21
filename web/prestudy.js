import {$,api,esc,msg,reqid,safeURL,send} from "./common.js";
import {humanDate,pathFor,prose} from "./reader.js";

export const stageName = stage => stage==="run"?"检查关键前提":"展开研究方案";
const activeStates=new Set(["queued","pending","created","scheduled","running","working","submitting","importing","in_progress"]);
export const isActive = task => activeStates.has(task.status) || activeStates.has(task.execution_status);
const decisionNames={discuss:"值得进一步讨论",lead:"保留研究线索",drop:"暂不建议继续"};
export function stageStatus(task){
  if(isActive(task))return task.status==="queued"?"已加入研究任务":"正在查阅";
  if(["failed","error","interrupted","unknown_outcome","connection_unknown","paused_external","needs_attention","blocked"].includes(task.status)||
     ["failed","error","interrupted","unknown_outcome","connection_unknown","paused_external","needs_attention","blocked"].includes(task.execution_status)) return "需要处理";
  if(task.evidence_limited)return "现有材料受限";
  return decisionNames[task.research_decision]||"已有结果";
}
const readingLevels={metadata:"元数据",abstract:"摘要",snippet:"摘录",excerpt:"原文片段",partial:"部分原文",full:"全文",full_text:"全文",parsed_text:"解析文本",notes:"阅读笔记",
  title_only:"题名",fulltext:"全文",full_paper:"全文",paper_excerpt:"论文片段",content:"原文"};
function sourceList(task){
  const sources=task.sources||[];
  if(!sources.length)return "";
  return '<section class="source-fold"><h3>这一阶段查阅的材料</h3><ul class="list">'+sources.map(s=>
    '<li>'+(s.url?'<a href="'+safeURL(s.url)+'" target="_blank" rel="noopener">'+esc(s.title||s.url)+' ↗</a>':esc(s.title||"引用材料"))+
    '<div class="sub">'+esc([s.version,readingLevels[s.reading_level]].filter(Boolean).join(" · "))+'</div></li>').join("")+'</ul></section>';
}
function originalText(value,sources){
  if(typeof value!=="string")return "";
  const node=document.createElement("div");
  node.innerHTML=prose(value);
  const indexed=new Map((sources||[]).filter(s=>s.source_id&&s.title).map(s=>[s.source_id,s]));
  if(!indexed.size)return node.innerHTML;
  const escaped=[...indexed.keys()].sort((a,b)=>b.length-a.length).map(x=>x.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"));
  const pattern=new RegExp("(?<![\\w-])(?:"+escaped.join("|")+")(?![\\w-])","g");
  const walks=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
  const texts=[];while(walks.nextNode())texts.push(walks.currentNode);
  for(const t of texts){
    if(t.parentElement.closest("a, code"))continue;
    const matches=[...t.textContent.matchAll(pattern)];if(!matches.length)continue;
    const fragment=document.createDocumentFragment();let at=0;
    for(const m of matches){
      fragment.append(t.textContent.slice(at,m.index));
      const s=indexed.get(m[0]);const link=document.createElement(s.url?"a":"span");link.textContent=s.title;
      if(s.url){try{const parsed=new URL(s.url);if(["http:","https:"].includes(parsed.protocol))link.href=parsed.href;}catch{}link.target="_blank";link.rel="noopener"}
      fragment.append(link);at=m.index+m[0].length;
    }
    fragment.append(t.textContent.slice(at));t.replaceWith(fragment);
  }
  return node.innerHTML;
}
function draftBody(task){
  if(task.draft_text)return task.draft_text;
  if(typeof task.draft==="string")return task.draft;
  const draft=task.draft||{};
  return [draft.current_understanding,draft.text,draft.overview,draft.decision_reason].filter(x=>typeof x==="string").join("\n\n")||task.current_understanding||"";
}
export function presentation(task){
  const p=task.presentation||{},sources=task.sources||[];
  const seen=new Set();
  function once(text){if(typeof text!=="string"||!text.trim()||seen.has(text))return "";seen.add(text);return originalText(text,sources)}
  const candidates=(p.candidates||[]).map(c=>'<section class="stage-text">'+
    (c.presentation_title?'<h3>'+esc(c.presentation_title)+'</h3>':"")+once(c.text)+
    (c.technical_analysis?'<details><summary>技术分析</summary>'+once(c.technical_analysis)+'</details>':"")+'</section>').join("");
  const polished=Boolean(p.overview||p.stage_summary||p.candidates?.some(c=>c.text));
  const raw=polished?once(p.stage_summary)+once(p.overview)+candidates:
    (draftBody(task)?'<h3>研究原稿</h3>'+once(draftBody(task)):"");
  return '<div class="stage-result">'+(task.focus?'<div class="label">本次问题</div>'+prose(task.focus):"")+
    (raw||prose(isActive(task)?"研究结果准备好后会出现在这里。":(task.error_message||"本阶段还没有可阅读的正文。")))+
    (p.technical_analysis?'<details><summary>技术分析</summary>'+once(p.technical_analysis)+'</details>':"")+
    (task.next_question?'<h3>下一步要明确的问题</h3>'+once(task.next_question):"")+
    sourceList(task)+'</div>';
}
function requestKey(did,sid,stage,focus,idea){
  const key="radar-prestudy:"+JSON.stringify([did,sid,stage,focus,idea||""]);
  let val=sessionStorage.getItem(key);
  if(!val){val=reqid();sessionStorage.setItem(key,val)}
  return val;
}

export async function attachPrestudy(root, direction, snapshot) {
  if(!snapshot)return;
  const did=direction.id;let existing=[];
  try {existing=await api("/api/directions/"+encodeURIComponent(did)+"/prestudies")}
  catch{root.innerHTML='<p class="sub">预研任务暂时无法读取。</p>';return}
  async function draw(focusId){
    root.innerHTML='<h2 class="section-title">从这个切口继续</h2><div class="buttons">'+
      '<button data-stage="develop">展开研究方案</button><button class="quiet" data-stage="run">检查关键前提</button></div>'+
      '<div data-entry></div><div class="stack stage-history"></div>';
    const records=$(".stage-history",root);
    for(const t of existing){
      const box=document.createElement("details");box.className="prior-stage";box.id="prestudy-"+t.id;
      box.innerHTML='<summary>'+esc(stageName(t.stage))+'　<span class="sub">'+esc(stageStatus(t))+' · '+esc(humanDate(t.updated_at||t.created_at))+'</span></summary><div data-output></div>';
      records.appendChild(box);
      let loaded=false;
      async function refresh(){
        if(!box.isConnected||!box.open)return;
        try{const task=await api("/api/prestudies/"+encodeURIComponent(t.id));if(!box.isConnected)return;
          $("[data-output]",box).innerHTML=presentation(task)+'<p><a href="'+pathFor("tasks",t.id)+'">单独打开此任务</a></p>';
          loaded=true;
          if(isActive(task))setTimeout(refresh,9000);
        }catch(e){$("[data-output]",box).innerHTML='<p class="error">'+esc(e.message)+'</p>'}
      }
      box.ontoggle=()=>{if(box.open&&(!loaded||isActive(t)))refresh()};
      if(t.id===focusId || location.hash===("#"+box.id)){box.open=true}
    }
    root.querySelectorAll("[data-stage]").forEach(b=>b.onclick=()=>{
      const stage=b.dataset.stage, seen=new Map();
      for(const t of existing){if(t.status==="completed"&&t.idea_id&&!seen.has(t.idea_id))seen.set(t.idea_id,t)}
      const options=[...seen].map(([id,t])=>'<option value="'+esc(id)+'">'+esc(t.focus||t.direction_title||stageName(t.stage))+'</option>').join("");
      const entry=$("[data-entry]",root);
      entry.innerHTML='<form class="form research-form"><h3>'+stageName(stage)+'</h3>'+
        (options?'<label>沿用的研究想法<select name="idea">'+(stage==="develop"?'<option value="">从当前方向新建切口</option>':'')+options+'</select></label>':"")+
        '<label>想进一步查清的问题<textarea name="focus" required maxlength="2000" placeholder="'+(stage==="develop"?"例如，哪项对照能区分两种解释？":"例如，已有工作是否已经回答了这个问题？")+'"></textarea></label>'+
        '<div class="buttons"><button type="submit">开始预研</button><button type="button" class="quiet" data-cancel>取消</button></div></form>';
      const form=$("form",entry);form.elements.focus.value=stage==="run"?(existing.find(t=>t.next_question)?.next_question||direction.question):direction.question;form.elements.focus.focus();
      $("[data-cancel]",form).onclick=()=>{entry.replaceChildren();b.focus()};
      form.onsubmit=async ev=>{
        ev.preventDefault();const values=new FormData(form),focus=String(values.get("focus")||"").trim(),idea=values.get("idea")||null;
        const button=$('[type="submit"]',form);button.disabled=true;
        try{const result=await send("/api/directions/"+encodeURIComponent(did)+"/prestudies",
          {snapshot_id:snapshot,stage,focus,idea_id:idea,request_id:requestKey(did,snapshot,stage,focus,idea)});
          existing=await api("/api/directions/"+encodeURIComponent(did)+"/prestudies");
          msg(result.reused?"已打开已有研究任务":"研究任务已提交");await draw(result.id||result.task_id);
          document.getElementById("prestudy-"+(result.id||result.task_id))?.scrollIntoView({block:"nearest"});
        }catch(e){button.disabled=false;msg(e.message)}
      };
    });
  }
  await draw();
}
