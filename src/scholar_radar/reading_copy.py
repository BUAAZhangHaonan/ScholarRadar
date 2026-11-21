from .models import ask


async def editorial(run,profile,cards,evidence,updates):
    if not cards and not updates:return {"summary":None,"items":[]}
    packet=[{"snapshot_id":s["id"],"title":s["card"]["title"],"finding":s["card"]["judgment"],
             "change":s["card"]["change"],"question":s["card"]["question"],"history":s["card"]["history"],
             "limits":s["card"].get("limitation"),"action":s["card"].get("action")} for s in cards]
    if not packet: return {"summary":None,"items":[]}
    result=await ask("reading_edition",profile["strong_model"],
        "为研究者写简短的日报开篇和研究切口。返回 {summary,items:[{snapshot_id,title,change,personal_connection,next_step}]}。"
        "先交代材料实际改变的认识，再连接来源中确实存在的个人研究主题，最后用一句动词开头的具体动作说明预期产物。"
        "开篇一句解释为何最该看，避免重复卡片标题或改变科学判断；最多一张主卡。只用提供的证据和已确认的资产主题。"
        "不要把论文/项目名称推断成可支配的数据、代码、设备或任务完成记录。保留生成时和生成前的区别。"
        "中文自然连贯，避免项目管理、账本术语、夸张修辞、固定小标签。不得写入新的数值结果。",
        {"snapshots":packet,"assets":profile["assets"],"evidence":[{"title":e["title"],"quote":e["quote"]} for e in evidence[:36]],
         "goals":profile["goals"]},run["id"],max_tokens=2000)
    ids={s["id"] for s in cards}
    items=[x for x in result.get("items",[]) if isinstance(x,dict) and x.get("snapshot_id") in ids and
           all(isinstance(x.get(k),str) and x[k].strip() for k in ("title","change","personal_connection","next_step"))]
    return {"summary":result.get("summary") if isinstance(result.get("summary"),str) else None,"items":items}
