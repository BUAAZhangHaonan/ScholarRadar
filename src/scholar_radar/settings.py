import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(
    os.environ.get("SCHOLARRADAR_ROOT", Path(__file__).resolve().parents[2])
).resolve()
VAR = Path(os.environ.get("SCHOLARRADAR_DATA_DIR", ROOT / "var")).resolve()
if not VAR.is_relative_to(ROOT):
    raise ValueError("数据目录须位于项目目录内")
PRIVATE = VAR / "private"
DB = VAR / "scholar_radar.sqlite"


def deployment():
    return json.loads((PRIVATE / "deployment.json").read_text())


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def atomic_text(path, content):
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as f:
        temp = Path(f.name)
        try:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp, path)
