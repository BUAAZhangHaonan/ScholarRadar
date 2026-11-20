# g203 部署

2026-11-21 实测。项目位于 g203 的本地 ext4，运行 Python 3.12.3、SQLite 3.45.1（WAL、外键、FTS5）。FastAPI 与 worker 是两个用户级 systemd 服务；用户已启用 linger。局域网浏览器通过一次性设备链接建立会话。数据库、锁、私有配置与导出均位于项目内。

ScholarTrace、ScholarAnalysis 和 webresearch-mcp 使用各自既有的 SSE 服务。当前能力目录见 [capabilities.json](capabilities.json)。模型目录返回 `deepseek-flash` 与 `deepseek-v4-pro`。前者初筛，后者综合和复核。以服务实际返回的收据记录各 MCP 内部模型。现有 g203 RTX 2080 Ti 用于 MinerU；本项目的定时任务无需额外训练 GPU。

NAS 是独立的 SSH 主机。归档器通过既有主机密钥校验身份，再检查专属目录、实际卷与可写性，在同一远端目录内原子发布。活跃 SQLite 保存在本地。NAS 地址、账号、私人目录及密钥保存在受限运行配置。个人画像从既有 InternPrepPipeline 配置导入，论文描述只保留核实的主题与资产，完整画像不随代码发布。
