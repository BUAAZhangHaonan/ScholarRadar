# ScholarRadar

ScholarRadar 把论文、开放资源和官方岗位放回各自的研究问题中。日报记录本次判断发生的变化，并给出研究历史、原文位置、可证伪的预测与下一步。周报从同一批证据中选出精读和小验证，月报汇总方向变化与真实反馈。

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

- **今日变化**查看历史证据与新判断，逐条打开原文，切换日、周、月报告。
- **方向库**查看近邻、因子、适用条件、历史名称和判断快照。分类变更保留关系，合并或拆分另行确认。
- **证据库**查论文、代码、团队与岗位，从引文跳到具体修订。个人阅读价值和已读状态分别记录。
- **行动与反馈**可接受、暂缓、开始或完成行动，记录原因、实际投入和结果。在相同候选集上盲评不同推荐。
- **设置与运行**管理画像、模型角色、时区、采集范围、候选因子和手工任务，查看实际调用和异常原因。

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

恢复命令写入新的本地文件，并检查数据库完整性、外键、作品、证据关系与任务。验证恢复库可通过 `SCHOLARRADAR_DATA_DIR` 指向项目内独立数据目录；工作数据库名为 `scholar_radar.sqlite`。切换生产库前先停止 API 与 worker，保留当前数据库和 WAL，核对恢复副本后再执行明确的切换。数据库采用本机 WAL，网络存储只承载版本化对象和一致性备份。暂存上限 `staging_limit_bytes` 默认 2 GiB，`local_backup_count` 默认保留最近 7 份本地备份，清理前检查 NAS 归档状态。

## 数据接口

`GET /api/daily`、`/api/directions`、`/api/works/{id}`、`/api/evidence/{id}`、`/api/actions`、`/api/runs` 和 `/api/profile` 使用浏览器会话鉴权。`POST /api/runs` 返回任务 ID，`POST /api/runs/{id}/resume` 恢复符合重试条件的阶段。已发送的付费调用优先恢复原来的上游 ID。来源收据包含历史费用时，账本区分历史数值和本次增量。

`GET /api/exports/internprep` 返回版本化 JSON。每个实际报告还写入 `exports/YYYY-MM-DD/{daily,weekly,monthly}/internprep.json` 和同目录 `report.md`。消费者按 `snapshot_id`、`direction_id` 与行动 ID 去重。历史版本留在 `report_versions` 和 NAS。`GET /api/replay?cutoff=...` 使用带时区的截止时间回放当时已有的材料和判断。`GET /api/evaluation` 查看已到期或待观察的前向评价。正式对接与写回在 InternPrepPipeline 侧单独实施。

## 验证

```bash
.venv/bin/python -B -m unittest discover -s tests -v
```

[实际环境](docs/environment.md) · [MCP 能力目录](docs/capabilities.json) · [来源与计算口径](docs/source_contracts.md)
