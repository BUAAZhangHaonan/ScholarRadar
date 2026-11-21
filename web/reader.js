import {api,esc,evid,msg,reqid,safeURL,send} from "./common.js";

export const pathFor = (section,id) => "/" + section + "/" + encodeURIComponent(id);
export const humanDate = value => {
  if (!value) return "";
  const raw=String(value);
  if (/^\d{4}(?:-\d{2}-\d{2})?$/.test(raw)) return raw;
  const d=new Date(raw);
  return Number.isNaN(d.getTime()) ? raw : new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai",dateStyle:"medium"}).format(d);
};

function inline(text) {
  const mark=/\*\*([^*\n]+)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let out="",last=0;
  for(const m of text.matchAll(mark)){
    out+=esc(text.slice(last,m.index));
    if(m[1]) out+="<strong>"+esc(m[1])+"</strong>";
    else if(m[2]) out+="<code>"+esc(m[2])+"</code>";
    else out+='<a rel="noopener" target="_blank" href="'+safeURL(m[4])+'">'+esc(m[3])+"</a>";
    last=m.index+m[0].length;
  }
  return out+esc(text.slice(last));
}

export function prose(text) {
  if (typeof text!=="string" || !text.trim()) return "";
  const blocks=[];
  let paragraph=[],bullets=[],numbered=false;
  function flushParagraph(){if(paragraph.length){blocks.push("<p>"+inline(paragraph.join("\n")).replaceAll("\n","<br>")+"</p>");paragraph=[];}}
  function flushList(){if(bullets.length){const tag=numbered?"ol":"ul";blocks.push("<"+tag+">"+bullets.map(x=>"<li>"+inline(x)+"</li>").join("")+"</"+tag+">");bullets=[];}}
  for(const line of text.trim().split(/\r?\n/)){
    if(!line.trim()){flushParagraph();flushList();continue}
    const head=line.match(/^#{1,6}\s+(.+)$/);
    if(head){flushParagraph();flushList();blocks.push("<h3>"+inline(head[1])+"</h3>");continue}
    const item=line.match(/^\s*(?:([-*])|(\d+)[.、)])\s+(.+)$/);
    if(item){flushParagraph();if(bullets.length && numbered!==!!item[2])flushList();numbered=!!item[2];bullets.push(item[3]);continue}
    flushList();paragraph.push(line.trim());
  }
  flushParagraph();flushList();
  return '<div class="prose">'+blocks.join("")+"</div>";
}

export function materialLink(m) {
  if (!m) return "";
  if (m.work_id) {
    const query=new URLSearchParams();
    if(m.snapshot_id)query.set("snapshot",m.snapshot_id);
    if(m.recommendation_id)query.set("recommendation",m.recommendation_id);
    return '<a href="'+pathFor("works",m.work_id)+(query.size?"?"+esc(query.toString()):"")+'">'+esc(m.title)+'</a>';
  }
  return m.url?'<a href="'+safeURL(m.url)+'" rel="noopener" target="_blank">'+esc(m.title)+' ↗</a>':esc(m.title);
}

export function materialList(items,withQuotes=true) {
  if (!items?.length) return "";
  return '<ul class="list reading-links">'+items.map(m=>'<li>'+materialLink(m)+
    (withQuotes&&m.citations?.length?'　'+evid(m.citations[0],"读引文"):"")+'</li>').join("")+"</ul>";
}

export function followControl(did,followed,sid="") {
  return '<button class="quiet" type="button" data-follow="'+esc(did)+'" data-snapshot="'+esc(sid||"")+
    '" aria-pressed="'+!!followed+'">'+(followed?"已关注":"加入关注")+"</button>";
}
export function acceptControl(aid,status) {
  if(!aid) return "";
  if(["active","accepted","completed"].includes(status))return '<a class="text-action" href="/tasks">查看我的行动</a>';
  if(!["proposed","deferred"].includes(status))return "";
  return '<button class="quiet" type="button" data-accept="'+esc(aid)+'">加入我的行动</button>';
}

export function objectFeedback(type,id,snapshot="",recommendation="") {
  return '<details class="feedback"><summary>记录阅读反馈</summary><form data-feedback="'+esc(type)+
    '" data-entity="'+esc(id)+'" data-snapshot="'+esc(snapshot||"")+'" data-rec="'+esc(recommendation||"")+'" class="form">'+
    '<label>阅读后的判断<select name="value"><option value="useful">有帮助</option><option value="average">一般</option>'+
    '<option value="irrelevant">与我无关</option><option value="read">已读</option></select></label>'+
    '<label>哪一点影响了你的判断（可选）<textarea name="reason"></textarea></label><button>保存反馈</button></form></details>';
}

export function enableActions(root=document) {
  root.querySelectorAll("[data-follow]").forEach(button=>button.onclick=async()=>{
    const on=button.getAttribute("aria-pressed")!=="true";
    button.disabled=true;
    try{
      await send("/api/feedback",{entity_type:"direction",entity_id:button.dataset.follow,dimension:"follow",
        value:on?"followed":"unfollowed",reason:"",snapshot_id:button.dataset.snapshot||null,request_id:reqid()});
      button.setAttribute("aria-pressed",String(on));button.textContent=on?"已关注":"加入关注";msg(on?"已加入关注":"已取消关注");
    }catch(e){msg(e.message)}finally{button.disabled=false}
  });
  root.querySelectorAll("[data-accept]").forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    try {
      await send("/api/actions/"+encodeURIComponent(button.dataset.accept)+"/decision",
        {decision:"accept",reason:"",actual:{},request_id:reqid()});
      const a=document.createElement("a");a.className="text-action";a.href="/tasks";a.textContent="查看我的行动";button.replaceWith(a);msg("已加入我的行动");
    }catch(e){button.disabled=false;msg(e.message)}
  });
  root.querySelectorAll("form[data-feedback]").forEach(form=>form.onsubmit=async ev=>{
    ev.preventDefault(); const values=new FormData(form);const choice=values.get("value");
    const button=form.querySelector("button");button.disabled=true;
    try {
      await send("/api/feedback",{entity_type:form.dataset.feedback,entity_id:form.dataset.entity,
        dimension:choice==="read"?"reading_status":"reading_value",value:choice,reason:values.get("reason")||"",
        snapshot_id:form.dataset.snapshot||null,recommendation_id:form.dataset.rec||null,request_id:reqid()});
      form.closest("details").open=false;msg("已保存你的反馈");
    }catch(e){msg(e.message)}finally{button.disabled=false}
  });
}
