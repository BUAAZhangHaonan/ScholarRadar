"""Short labels for model input; all persisted links resolve to database identities."""


def label_inputs(papers, jobs):
    forward = {}
    for i, (wid, p) in enumerate(papers.items(), 1):
        forward[wid] = f"W{i}"
        for j, eid in enumerate(p["quotes"], 1):
            forward[eid] = f"W{i}E{j}"
    for i, j in enumerate(jobs, 1):
        forward[j["id"]] = f"J{i}"
    reverse = {v: k for k, v in forward.items()}

    def rewrite(obj, lookup):
        if isinstance(obj, str):
            return lookup.get(obj, obj)
        if isinstance(obj, list):
            return [rewrite(x, lookup) for x in obj]
        if isinstance(obj, dict):
            return {lookup.get(k, k): rewrite(v, lookup) for k, v in obj.items()}
        return obj

    return (
        rewrite(list(papers.values()), forward),
        rewrite(jobs, forward),
        lambda card: rewrite(card, reverse),
    )
