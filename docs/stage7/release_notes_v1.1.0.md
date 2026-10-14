# WaferSched-Agent v1.1.0 — LangGraph LLM Research Agent

该版本基于开源 LangGraph 1.2.15（MIT）二次开发，以 DeepSeek `deepseek-flash` 提供真实研究规划与反思。Semantica 仅承担辅助上下文与研究记忆功能。复用既有数学算法、Simulator 与 PPO 权重，没有重新训练历史模型。

## 智能体与数学工具

九节点有状态反馈流程覆盖问题理解、真实 LLM 规划、结构化提案验证、Skill 执行、Simulator 独立数学验证、结果分析、LLM 反思、研究记忆和预算终止控制。SQLite 检查点支持实验边界恢复。

工具包括规则调度、CP-SAT、已有 MaskablePPO 策略推理、设备仿真、约束验证、实验比较和历史查询。LLM 只选择受 Schema 与白名单约束的提案，不执行任意生成的命令或代码，不能独立判定调度合法或全局最优。真实 LLM、确定性 CFAR、固定流程和失败回退记录分别标识。

## 真实研究证据

保存的正式实验包括 12 轮真实 LLM 自主规划与 8 轮完整有效反思；确定性 CFAR 和固定流程各 16 轮，三组共 44 个候选方案均通过独立数学验证。

| 规划机制 | 实验轮数 | F/G 最佳 Makespan（秒） | 工具累计时间（秒） | 活动总墙钟时间（秒） |
| --- | --- | --- | --- | --- |
| 固定流程 | 16 | 63 / 183 | 25.441605 | 28.005070 |
| 原确定性 CFAR | 16 | 63 / 183 | 52.558026 | 55.418993 |
| LangGraph + DeepSeek | 12 | 63 / 183 | 31.635618 | 134.136869 |

21 次正式实际 API 请求均保存 HTTP 200，合计 107826 Token；另有 4 条预算阻止记录没有发出请求。完整反思、响应截断、预算阻止和早期确定性回退均保留。配置费率计算的 0.043860228 美元仅为峰值费用估计，不是账户账单。99.635916 秒是全部 LLM 客户端调用段，含准备与未发送检查，不等于服务端纯推理时间。

LLM 未改善 F/G 两场景最终解质量，活动总运行时间高于 CFAR 与固定流程。目前不能证明 LLM 规划整体优于确定性 CFAR。独立验证证明保存候选的合法性，不构成一般全局最优性证明。

## 验证与复现

- 239 项测试通过、1 项 Windows 符号链接权限测试跳过；Ruff 与依赖一致性检查通过。
- 保存的 44 条调度可离线重放；发布审计不调用付费 API。
- 702 项阶段七归档哈希核对一致；原数学代码、PPO 模型及第一至第六阶段研究数据保持不变。
- [复现说明](https://github.com/yanq458-tech/WaferSched-Agent/blob/v1.1.0/docs/stage7/reproducibility.md)
- [发布审计](https://github.com/yanq458-tech/WaferSched-Agent/blob/v1.1.0/docs/stage7/github_release_audit.md)
- [18 页可编辑 Word 报告](https://github.com/yanq458-tech/WaferSched-Agent/blob/v1.1.0/docs/stage7/WaferSched-Agent_%E8%AF%BE%E7%A8%8B%E7%A0%94%E7%A9%B6%E6%8A%A5%E5%91%8A_v1.1.0.docx)
- [18 页最终 PDF 报告](https://github.com/yanq458-tech/WaferSched-Agent/blob/v1.1.0/docs/stage7/WaferSched-Agent_%E8%AF%BE%E7%A8%8B%E7%A0%94%E7%A9%B6%E6%8A%A5%E5%91%8A_v1.1.0.pdf)

## 已知局限

尚未实现 LLM 自主改写强化学习算法代码，CodeImprovementSkill 仅提供禁用接口。未解决一般动态故障调度；场景与预算规模有限，尚无严格收敛性、普遍性能优势或一般全局最优性保证。LLM 增加时间与 Token 成本，仍有截断、预算终止与回退。上游 LangGraph commit 尚未独立核验；跨 Windows 磁盘的部分输出路径存在相对路径限制。

根据用户确认，main 的两个旧报告路径已移除，当前仅使用 18 页脱敏报告；旧提交与 v1.0.0 未重写。
