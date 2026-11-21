from .models import ask


async def editorial(run, profile, cards, evidence, updates):
    if not cards and not updates:
        return {"summary": None, "items": []}
    packet = [
        {
            "snapshot_id": s["id"],
            "title": s["card"]["title"],
            "finding": s["card"]["judgment"],
            "change": s["card"]["change"],
            "question": s["card"]["question"],
            "history": s["card"]["history"],
            "limits": s["card"].get("limitation"),
            "action": s["card"].get("action"),
        }
        for s in cards
    ]
    if not packet:
        return {"summary": None, "items": []}
    result = await ask(
        "reading_edition",
        profile["strong_model"],
        "为研究者写简短的日报开篇和研究切口。返回 {summary,items:[{snapshot_id,title,change,personal_connection,next_step}]}。"
        "先交代材料实际改变的认识，再连接来源中确实存在的个人研究主题，最后用一句动词开头的具体动作说明预期产物。"
        "按为什么改变科研判断来排序，最重要的放第一项。开篇从具体实验现象或对照出发，为读者解释它为什么会改变先前的认识，不复述主卡。"
        "用具体的研究方法、论文短名或对照作主语。个人连接点可用给定的真实论文名称及其已知研究主题，"
        "说清该工作留下的下一道问题。避免“与已确认主题相关”“最新材料表明”“拟探索可能性”等抽象开场。"
        "下一步先给能实际产出的最小区分性对照；材料没有证明训练集可用时不要指定在评估集训练。"
        "只用提供的证据和已确认的资产主题。"
        "不要把论文/项目名称推断成可支配的数据、代码、设备或任务完成记录。保留生成时和生成前的区别。"
        "中文自然连贯，避免项目管理、账本术语、夸张修辞、固定小标签。不得写入新的数值结果。",
        {
            "snapshots": packet,
            "assets": profile["assets"],
            "evidence": [
                {"title": e["title"], "quote": e["quote"]} for e in evidence[:36]
            ],
            "goals": profile["goals"],
        },
        run["id"],
        max_tokens=2000,
    )
    titles = {s["id"]: s["card"]["title"] for s in cards}
    items = {}
    for entry in result.get("items", []):
        if not isinstance(entry, dict):
            continue
        sid = entry.get("snapshot_id")
        if sid in titles and sid not in items and all(
            isinstance(entry.get(k), str) and entry[k].strip()
            for k in ("change", "personal_connection", "next_step")
        ):
            items[sid] = {**entry, "title": titles[sid]}
    return {
        "summary": result.get("summary")
        if isinstance(result.get("summary"), str)
        else None,
        "items": list(items.values()),
    }
