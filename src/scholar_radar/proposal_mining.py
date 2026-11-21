import json
from .db import database
from .factors import propose
from .models import ask
from .profile import get_profile


async def mine(run):
    with database() as db:
        earlier = (
            db.execute(
                "SELECT max(ended_at) FROM runs WHERE kind='weekly' AND id!=? AND status IN ('done','partial')",
                (run["id"],),
            ).fetchone()[0]
            or ""
        )
        from .recommendations import signals, outcome_examples

        feedback = [
            f
            for f in signals(db, limit=30)
            if f["created_at"] > earlier and f["reason"]
        ]
        actions = outcome_examples(db, earlier)
        existing = [
            json.loads(r[0]) for r in db.execute("SELECT definition FROM proposals")
        ]
        profile = get_profile(db, run["profile_id"])
    if not feedback and not actions:
        return
    result = await ask(
        "factor_proposal",
        profile["strong_model"],
        "根据用户给出的真实反馈，最多提出一个可前向检验的候选因子。没有新依据时返回 {proposal:null}。"
        "proposal 必须含 target,input,method,window_days,missing,overlap,comparison。已实现的规则名是 "
        "linked_resource、same_direction_work_count。其他方法可以建议，须开发实现后才能后台计算。"
        "已有定义重复则返回 null，暂缓和已读不能直接当成价值标签。",
        {"feedback": feedback, "actions": actions, "existing": existing},
        run["id"],
        max_tokens=1200,
    )
    candidate = result.get("proposal")
    if candidate:
        if (
            not isinstance(candidate.get("window_days"), int)
            or not 1 <= candidate["window_days"] <= 730
        ):
            return
        with database(write=True) as db:
            propose(db, candidate)
