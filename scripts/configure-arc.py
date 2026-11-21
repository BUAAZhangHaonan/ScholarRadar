"""Connect an installed ARC CLI to this Radar deployment."""

import argparse
import json
from pathlib import Path

from scholar_radar.settings import PRIVATE, VAR, atomic_text, dump


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="ARC runtime.yaml")
    parser.add_argument(
        "--env-file", required=True, type=Path, help="ARC service environment"
    )
    parser.add_argument("--checkout", type=Path, default=VAR / "integrations" / "arc")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=VAR / "arc-research",
        help="用于这些想法、阶段与来源笔记的 ARC 数据目录",
    )
    args = parser.parse_args()
    checkout = args.checkout.resolve(strict=True)
    executable = checkout / ".venv" / "bin" / "arc"
    for path in (args.config, args.env_file, executable):
        if not path.is_file():
            parser.error(f"找不到 {path}")
    settings_path = PRIVATE / "deployment.json"
    settings = json.loads(settings_path.read_text())
    settings["arc_runtime"] = {
        "cwd": str(checkout),
        "executable": str(executable),
        "config": str(args.config.resolve()),
        "env_file": str(args.env_file.resolve()),
        "data_dir": str(args.data_dir.resolve()),
    }
    atomic_text(settings_path, dump(settings))
    print("ARC 轻量预研已关联到本机部署配置。")


if __name__ == "__main__":
    main()
