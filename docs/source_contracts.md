# 采集与证据契约

**发现与观察。** ScholarTrace 以稳定 request_id 检索、精排和恢复。首批实际请求只有部分来源完成，返回 4 项。项目另用 Semantic Scholar 有日期限制的 bulk 查询补足本次检索缺口，结果保留为发现流。其发布日期保留源数据库语义。搜索排名、估算命中数和传播次数都不进入活动份额。 [Semantic Scholar API](https://api.semanticscholar.org/api-docs/graph)

**全文。** get_paper_text 记录 document_id、document_revision、mode、区间、下一偏移和总长。聚合连续区间时重新检查修订、模式、首尾与实际字符数。analyze_paper 用稳定 analysis_id，结构化答案回到相同模式的字符区间。网页引文遵循自己的固定版本。快照给出原文、条件、推断和待证伪预测，接受的行动单独记录。 [MCP 工具协议](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

**arXiv。** ScholarTrace 当前访问 legacy API，其限流器在进程内。ScholarAnalysis 使用本地 arXiv 镜像；本机镜像的同步状态表在盘点时为空。web-research 可访问网页，不能据其名称推定具备跨进程限流。当前部署只读本地镜像，并将不完整窗口标记为 partial。系统分别保存第一版时间、当前版本时间、可核验的公开时间、观察时间和获取时间。旧作品后补抓不会变成当天新作品。 [arXiv API 语义](https://info.arxiv.org/help/api/user-manual.html) · [接口访问条件](https://info.arxiv.org/help/api/tou.html)

启用完整观察前，把所有会访问同一限流规则覆盖的 legacy API、RSS、OAI-PMH 客户端登记并接入一个统一协调入口。入口串行转发，持久保存上次发起时间，连续请求间隔至少 3 秒。上游失败应结束等待并返回实际错误，保持原始 Atom 与分页行为。ScholarTrace 的 ArxivConnector 需要把 export API 的 base_url 指向该入口，其他实际访问这些接口的客户端也需要单独完成接入。经服务维护者验证后，在本地受限部署配置设置 `coordinated_arxiv_url` 为协调入口的 Atom query 地址、`all_arxiv_clients_coordinated` 为 true。观察任务使用两个持久水位和重叠窗口，分页受限时不提交完整水位。归类版本以方向定义集合生成，新增、合并或拆分后须用同一定义回标两个窗口。每个方向的分母是同一来源、同一范围内完成归类的独立作品数。

**岗位和开放资源。** 官方职位 ID 或稳定的官方详情链接建立岗位身份。岗位新抓、重复解析和页面刷新进入同一岗位的观察历史。暂不可访问保留最后的官方核验记录。作者归属、仓库链接与招聘分别保存。对于论文提到的代码库或模型卡分别记录“正文提及”“可以访问”“实际复现”等证据。岗位匹配使用官方要求和个人资产，准备建议不创建投递或训练任务。

**费用。** 对实际 provider request ID 去重，父收据和子调用不重复相加。原始费用、缓存取回的增量与未知费用分别保存。直接模型调用使用价格版本、模型返回名、用量及边界来估算，缺少数据会给出区间或未知。相同付费请求在连接中断后只允许持久 ID 恢复；没有恢复契约的调用保留 unknown_outcome。 [DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
