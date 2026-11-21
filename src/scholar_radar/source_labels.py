"""Short labels for model input; all persisted links resolve to database identities."""

import re


def label_inputs(papers, jobs):
    forward = {}
    for i, (wid, p) in enumerate(papers.items(), 1):
        forward[wid] = f"W{i}"
        for n, record in enumerate(p.get("reading_records", []), 1):
            forward[record["id"]] = f"W{i}R{n}"
            forward[record["revision_id"]] = f"W{i}V"
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

    names = {
        forward[wid]: ("《" + p["title"].split(":", 1)[0] + "》")
        for wid, p in papers.items()
    }

    def prose(value):
        if isinstance(value, str):
            if value in reverse:
                return reverse[value]
            # Structured evidence IDs remain in their own fields. Remove purely
            # parenthetical model labels and name works when referenced in prose.
            value = re.sub(
                r"[（(]\s*(?:W\d+E\d+|J\d+)(?:[\s,，、/]*(?:W\d+E\d+|J\d+))*\s*[)）]",
                "",
                value,
            )
            return re.sub(
                r"(?<![A-Za-z0-9_])W(\d+)(?:E\d+|R\d+)?(?![A-Za-z0-9_])",
                lambda m: names.get("W" + m[1], m[0]),
                value,
            )
        if isinstance(value, list):
            return [prose(v) for v in value]
        if isinstance(value, dict):
            return {reverse.get(k, k): prose(v) for k, v in value.items()}
        return value

    return (
        rewrite(list(papers.values()), forward),
        rewrite(jobs, forward),
        prose,
    )
