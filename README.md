# ScholarRadar

ScholarRadar 为研究者整理值得跟进的论文变化。日报解释新材料怎样改变先前的判断，再把个人研究切口和下一步放在一起。论文记录保留读过的版本、实验与原文。进入方向后，可以让 ARC 查最近邻、展开方案，再检查一个决定是否值得继续的前提。

## 在 g203 使用

工作目录为 `/home/g203/zhanghaonan/ScholarRadar`。以下命令均在项目根目录执行：

```bash
.venv/bin/scholar-radar login-link
.venv/bin/scholar-radar status
.venv/bin/scholar-radar run daily
.venv/bin/scholar-radar run weekly
systemctl --user status scholar-radar-api.service scholar-radar-worker.service
```

`login-link` 打印内网设备入口。新链接三天内可以使用一次，登录后的浏览器会话有效期为三十天。书签保存工作台首页即可。日任务在北京时间每天 07:30 启动，含周末。周日生成周报，每月 1 日复盘上一个自然月。离线期间遗漏的日期由同一 worker 补跑。手工和定时触发共用唯一队列。

- **日报、周报与月报**按日期阅读。首页优先展示一项完整变化，其他材料可独立作为论文动态。周报可展开期初判断、期间的支持或反例、仍待解决的问题和建议行动。
- **研究方向**提供独立地址。选择一个历史快照可以看到当时的判断；查看原文后关闭引文抽屉，即可回到原位置。“展开研究方案”和“检查关键前提”各启动一次 ARC 轻量预研，方向页及“研究任务”都可查看结果和技术分析。
- **文献**可以按版本查阅问题、方法、对照、实验条件和待补问题。点击“继续补读”可指定实际章节与一个具体问题。资源区链接到作者仓库及已核实的具体文件。
- **反馈和行动**附在对应论文或方向旁。可以记录一次推荐哪里有用、哪里与当前问题无关，也可以在行动完成后留下实际结果。阅读状态、关注和暂缓各自保存。
- **设置与运行**保留个人画像、采集时间、后台任务、用量与来源覆盖。内网访问需先用一次性登录链接建立浏览器会话。

## 部署与恢复

```bash
mkdir -p _scratch/tmp _scratch/cache/uv var/staging
export TMPDIR="$PWD/_scratch/tmp" UV_CACHE_DIR="$PWD/_scratch/cache/uv"
uv sync --frozen --python /usr/bin/python3
.venv/bin/python scripts/configure.py --help
.venv/bin/scholar-radar init
.venv/bin/scholar-radar inventory
bash scripts/install-services.sh
```

首次部署使用 `scripts/configure.py`，从既有 MCP 客户端、模型环境文件、镜像数据库和自己的画像 JSON 创建受限配置。画像字段示例见 [profile.example.json](config/profile.example.json)。先核验 NAS 的 SSH 主机密钥，并准备远端卷上的项目专属目录。两项 systemd 用户服务使用 g203 的既定部署目录。已运行环境可在 `var/private/deployment.json` 中调整端口、来源连接和 NAS 根目录，保存后重启对应服务。

```bash
.venv/bin/scholar-radar backup manual-checkpoint
.venv/bin/scholar-radar restore-copy backups/manual-checkpoint.sqlite var/restores/manual-checkpoint.sqlite
```

备份名标识一次固定快照，重用名称会返回已归档的版本。恢复命令写入新的本地文件，并检查数据库完整性、外键、作品、证据关系与任务。验证恢复库可通过 `SCHOLARRADAR_DATA_DIR` 指向项目内独立数据目录；工作数据库名为 `scholar_radar.sqlite`。切换生产库前先停止 API 与 worker，保留当前数据库和 WAL，核对恢复副本后再执行明确的切换。数据库采用本机 WAL，网络存储只承载版本化对象和一致性备份。暂存上限 `staging_limit_bytes` 默认 2 GiB，`local_backup_count` 默认保留最近 7 份本地备份，清理前检查 NAS 归档状态。

## 接入 ARC 轻量预研

在已配置 ScholarRadar 的项目根目录执行以下命令。脚本将 ARC 的轻量对接版本安装在项目的 `var/integrations/arc`，并使用已有 ARC 服务配置读取模型和研究工具。

```bash
bash scripts/install-arc.sh
arc_source=/home/g203/zhanghaonan/adversarial-research-copilot
.venv/bin/python scripts/configure-arc.py --config "$arc_source/configs/runtime.yaml" --env-file "$arc_source/.env"
systemctl --user restart scholar-radar-api.service scholar-radar-worker.service
```

在方向页选快照和问题后，Radar 固定画像、可用资产、引用版本和阅读笔记。本机将 ARC 数据保存在本项目的 `var/arc-research`。部署时也可用 `--data-dir` 指定已有 ARC 档案。后续阶段沿用首次提交的运行配置、研究想法与已有笔记。阶段各自使用 ARC 现有预算配置。中断后可从研究任务恢复同一次提交。成文失败时仍可查看研究原稿。[ARC 对接协议](https://github.com/BUAAZhangHaonan/adversarial-research-copilot/blob/radar-selected-idea/docs/EXTERNAL_SELECTED_IDEAS.md)

## 把整理结果交给 ChatGPT 阅读

可将每次保存的日报、周报、月报，以及完成的 ARC 研究方案或前提检查，自动提交到一个 GitHub 结果仓库。导出直接使用已经生成的正文，不追加模型调用。结果保留判断、论文动态、研究切口、验证条件与下一步，不包含费用、控制台日志、服务配置或论文全文。

结果仓库中的固定入口为 `results/LATEST.md`，其中包含最新一份结果正文和各类最新结果的链接；`results/README.md` 列出所有历史版本。日、周、月报分别在 `results/daily/`、`results/weekly/`、`results/monthly/`，ARC 结果在 `results/arc/`。文件名包含原始日期和版本编号，同一天的多次整理各自保留。补传旧结果不会将最新入口倒退到旧日期。

### 启用自动提交

1. 创建一个**私有**结果仓库，例如 `BUAAZhangHaonan/ScholarRadar-Results`，勾选初始化 README。代码仓库当前公开，默认不允许将个人研究结果写入公开仓库。确实希望公开时，需明确添加 `"allow_public": true`。
2. 为结果仓库准备 GitHub fine-grained token，仅授予该仓库 `Contents: Read and write`。令牌保存在 g203，不写入 GitHub，也不放入报告。
3. 将以下字段**合并**到 `var/private/deployment.json`；保留原有 MCP、模型与 NAS 配置：

```json
"github_results": {
  "enabled": true,
  "repository": "BUAAZhangHaonan/ScholarRadar-Results",
  "branch": "main",
  "token_env": "SCHOLARRADAR_GITHUB_TOKEN"
}
```

4. 在本机 `var/private/github-results.env` 中写入 `SCHOLARRADAR_GITHUB_TOKEN=实际令牌`，设置文件权限为 `600`。用 `systemctl --user edit scholar-radar-worker.service` 添加以下内容，使后台 worker 能读取令牌：

```ini
[Service]
EnvironmentFile=%h/zhanghaonan/ScholarRadar/var/private/github-results.env
```

5. 重启 worker，并把已有结果加入补传队列：

```bash
systemctl --user daemon-reload
systemctl --user restart scholar-radar-worker.service
.venv/bin/scholar-radar github-sync
```

后续结果保存后会自动入队。`github-sync` 只补传已经保存的结果，修复配置或更换目标仓库后也可再次执行；它不会重新采集论文、调用 ARC 或生成报告。一次提交包含正文和索引，重复补传相同内容不创建空提交，不覆盖仓库内其他文件。临时连接错误与并发提交冲突按现有队列重试，间隔至少 30 分钟、最多 3 次；超过次数后可用同一命令重新排队。未配置此功能时，原有工作方式保持不变。

为 ChatGPT 的 GitHub 连接器开放结果仓库权限后，可以直接说：

> 读取 BUAAZhangHaonan/ScholarRadar-Results 的 results/LATEST.md，并根据 results/README.md 查阅最近七天的结果与关联 ARC 预研。比较判断如何变化，指出最值得继续的研究切口、目前缺少的证据，以及我下一步应该做的实验。

## 数据接口

`GET /api/reading/report` 接受 `kind` 与 `date`。方向和文献的阅读视图分别位于 `/api/reading/directions/{id}` 与 `/api/reading/works/{id}`。提交 `POST /api/directions/{id}/prestudies` 后可以用 `GET /api/prestudies/{id}` 查询状态、中文正文、技术分析及其来源；不同阶段通过返回的 ARC idea ID 承接。

`GET /api/daily`、`/api/directions`、`/api/works/{id}`、`/api/evidence/{id}`、`/api/actions`、`/api/runs` 和 `/api/profile` 使用浏览器会话鉴权。`POST /api/runs` 返回任务 ID，`POST /api/runs/{id}/resume` 恢复符合重试条件的阶段。已发送的付费调用优先恢复原来的上游 ID。来源收据包含历史费用时，账本区分历史数值和本次增量。

`GET /api/exports/internprep` 返回版本化 JSON。每个实际报告还写入 `exports/YYYY-MM-DD/{daily,weekly,monthly}/internprep.json` 和同目录 `report.md`。消费者按 `snapshot_id`、`direction_id` 与行动 ID 去重。历史版本留在 `report_versions` 和 NAS。`GET /api/replay?cutoff=...` 使用带时区的截止时间回放当时已有的材料和判断。`GET /api/evaluation` 查看已到期或待观察的前向评价。正式对接与写回在 InternPrepPipeline 侧单独实施。

## 验证

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

[阅读与 ARC 验收](docs/refactor-acceptance.md) · [首版真实验收](docs/acceptance.md) · [实际环境](docs/environment.md) · [MCP 能力目录](docs/capabilities.json) · [来源与计算口径](docs/source_contracts.md)

