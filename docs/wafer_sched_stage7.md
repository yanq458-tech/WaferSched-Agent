# WaferSched-Agent 第七阶段：LangGraph + DeepSeek 真实研究验收

日期：2026-10-14（Asia/Shanghai）。当前分支：`feature/langgraph-research-agent`。没有提交或推送。

阶段验收通过：一次最小请求成功后，真实 LLM 自主规划完成 12 轮，全部通过原 Simulator 独立验证，并保存 8 轮完整有效的真实反思。A 原确定性 CFAR 和 C 固定流程各完成 16 轮，合计 44 个候选方案全部合法。真实失败、截断、预算阻止和停止来源均保留。

## 认证与最小测试

运行时只从项目根目录 `.env` 显式读取三项 ASSISTANT_LLM 配置，不读取或回退到进程环境。密钥非空、加载长度 35、无首尾空白；没有记录内容、前后缀或摘要。`.env` 已被 Git 忽略且未跟踪。

请求为 `POST https://api.deepseek.com/chat/completions`，使用 Bearer；请求与返回模型 ID 均为 `deepseek-flash`。`preflight-006` 只发出一次请求，HTTP **200**，回复 `{"ok":true}`，输入 186、输出 5，共 191 Token，耗时 1.189289 秒，无自动重试。

## 最小改造与开源来源

LangGraph 1.2.15 的 StateGraph 与 SqliteSaver 是新增 Agent 主体。Semantica 仍服务原 ResearchMemory 的上下文，未将其宣称为研究智能体主体。上游为 https://github.com/langchain-ai/langgraph，MIT 许可证及版权保存在 `provenance/langgraph/`；包版本已核验，上游 commit 尚未核验，记录为 null。

九节点：ProblemUnderstanding → ResearchPlanner → ProposalValidator → SkillExecutor → MathematicalVerifier → ResultAnalyzer → ResearchReflection → ResearchMemory → TerminationController。终止节点反馈至问题理解，允许按历史结果选择场景、工具、CP 时间和既有 PPO 模型。结构化 Schema 与白名单限制输入，没有任意执行 LLM 生成代码或命令。

七个工具：rule_scheduling、cpsat_optimization、rl_policy_evaluation、equipment_simulation、constraint_verification、experiment_comparison、research_history_query。复用原 Simulator、规则、CP-SAT、MaskablePPO 推理和验证；CodeImprovementSkill 仅有禁用接口，没有自主改写源码。

## 相同预算与口径

A/B/C 使用同一 F/G 开发配置、同一候选集合、种子 0 和预算上限：16 轮、600 秒活动总时间、单轮工具 40 秒、36 条 LLM 调用记录、120000 Token、0.20 美元峰值费用估算、60 秒 CP 搜索分配。候选集合包括 5 种规则、CP 1/3/10/30 秒以及已有 medium-seed-0/7/13 模型。A/C 交替分配场景，B 自主选择；预算上限相同，不要求实际消耗相同。

本次 A/B/C 数值运行顺序执行。活动时间包含工具、LLM、验证、图和记忆开销，排除人工检查时的挂起时间和最终图表导出。工具时间包括子进程启动、原验证和 Agent 二次重放；这是阶段七测量，不能替代历史阶段六时间。CP 分配值与实际求解器时间分列：A 18 / 18.010487，B 28 / 18.030150，C 8 / 8.006659 秒。求解器检查及终止开销可能使实测时间略超分配值。

## 实测效果与成本

“最佳”指本次观测到且验证合法的最佳 Makespan。轮次分别列本场景轮次和全局轮次；累计工具时间分别列本场景和此前全部场景，避免混淆。

| 场景 | 方法 | 最佳 Makespan 秒 | 首次最佳：场景 / 全局轮 | 首次本场景工具秒 | 首次全局工具秒 | 本场景总工具秒 |
| --- | --- | --- | --- | --- | --- | --- |
| F | A | 63 | 4 / 7 | 6.966 | 12.035 | 31.328 |
| F | B | 63 | 2 / 2 | 2.387 | 2.387 | 14.652 |
| F | C | 63 | 7 / 13 | 7.858 | 14.783 | 12.109 |
| G | A | 183 | 3 / 6 | 5.068 | 10.041 | 21.230 |
| G | B | 183 | 2 / 6 | 2.361 | 13.705 | 16.984 |
| G | C | 183 | 6 / 12 | 6.926 | 12.901 | 13.332 |

| 方法 | 实验轮数 | 总工具秒 | 活动总时间秒 | LLM 额外秒 | 服务端 Token | 峰值费用估计美元 |
| --- | --- | --- | --- | --- | --- | --- |
| A | 16 | 52.558 | 55.419 | 0.000 | 0 | 0.000000 |
| B | 12 | 31.636 | 134.137 | 99.636 | 107826 | 0.043860 |
| C | 16 | 25.442 | 28.005 | 0.000 | 0 | 0.000000 |

A/B/C 合法实验比例均为 100%，重复同场景同工具同参数比例均为 0%。CP 时间预算变化视为不同参数实验；相同 Makespan 不等同于重复实验。

B 在 F/G 本场景第 2 轮找到 63/183 秒，A 为第 4/3 轮，C 为第 7/6 轮。但 B 的活动总时间约 134 秒，高于 A 约 55 秒和 C 约 28 秒，不能宣称总计算成本更低。G 的首次最佳全局累计工具时间，B 也高于 A/C；场景自主分配影响这种口径。

B 共 25 条决策调用记录，其中 21 次实际 API 请求全部 HTTP 200，4 条为预算检查阻止，未发送请求。B 服务端用量为 107826 Token，峰值费用估计约 0.043860 美元。这是按配置费率计算的估计，不是账户账单。本次成功连通性测试、早期提案失败试跑及正式 B 合计 113020 Token，峰值估计 0.04645973 美元；此前 401 未返回用量，不视为实测 0 Token。

## 真实逐轮轨迹

下列 12 轮的 actual_planner 均为 LangGraphLLMPlanner，全部原 Simulator 合法。原始英文提案、假设、真实回复和后续提案均在 JSONL/CSV 中，未以确定性结果替代。

| 全局轮 | 场景 | LLM 选择 | Makespan 秒 | 求解 / 验证状态 | 真实反思 |
| --- | --- | --- | --- | --- | --- |
| 1 | F | 规则 bottleneck | 74 | Simulator 合法 | 完整有效 |
| 2 | F | CP-SAT 1 秒 | 63 | FEASIBLE | 完整有效 |
| 3 | F | CP-SAT 3 秒 | 63 | FEASIBLE | 完整有效 |
| 4 | F | PPO medium-seed-0 | 65 | Simulator 合法 | 完整有效 |
| 5 | G | 规则 bottleneck | 199 | Simulator 合法 | 完整有效 |
| 6 | G | CP-SAT 1 秒 | 183 | FEASIBLE | 完整有效 |
| 7 | G | CP-SAT 3 秒 | 183 | FEASIBLE | 完整有效 |
| 8 | G | CP-SAT 10 秒 | 183 | OPTIMAL | 输出截断 |
| 9 | F | CP-SAT 10 秒 | 63 | OPTIMAL | 完整有效 |
| 10 | F | 规则 adaptive | 65 | Simulator 合法 | 预算预留阻止调用 |
| 11 | G | 规则 adaptive | 185 | Simulator 合法 | 预算预留阻止调用 |
| 12 | F | 规则 spt | 65 | Simulator 合法 | 预算预留阻止调用 |

首轮瓶颈规则未优于其他规则；第 3 轮增加 CP 预算仍为 63 秒 FEASIBLE；第 4 轮 RL 为 65 秒，劣于当前 63 秒；G 增加搜索预算后仍为 183 秒，但第 8 轮获得 OPTIMAL；F 第 9 轮获得 OPTIMAL。第 10—12 轮便宜规则为 65/185/65 秒，未达到当前最佳。以上均保留，不把未实现的 LLM 假设改写为成功结果。

FEASIBLE 只表示求解器找到可行方案，不能写成已证明最优；OPTIMAL 仅对应原 CP-SAT 编码声明的数学模型，不能擅自扩大为所有物理调度策略的全局最优。UNKNOWN 与失败不能算合法完成；本次主对照未出现 UNKNOWN，历史 UNKNOWN 记录保持原样。

## 失败、预算与终止真实性

保留 `live-study-001/B` 的早期真实失败：规划 API 与反思 API 成功，但原提案使用 `rule` 参数而实际工具要求 `policy`，并把解释文字当证据 ID，被验证器拒绝。其调度由 DeterministicPlanner 回退完成，真实自主轮次为 0，未混入正式 B。随后仅补齐 LLM 可见的参数与证据契约，数学工具及验证规则不改动。

正式 B 的第 8 轮反思 HTTP 200，但 `finish_reason=length`、输出 1536 Token，JSON 截断而无效；第 10—12 轮反思被保守 Token 预留检查阻止。仅 8 轮完整有效反思计入验收，前 7 轮已构成超过五轮的连续真实规划—实验—反思轨迹。

最后新规划请求同样被 Token 预留检查阻止，确定性回退给出停止。`stop_reason` 的原始文本为“No affordable useful candidate remains”，不能据此声称由 LLM 自主作出最终停止决定。实际终止规划器为 `DeterministicPlanner`，原因为 `LLMUnavailable:llm_call_token_or_fee_budget_exhausted`。107826 小于 120000，但下一次请求保守上界无法容纳，故没有越预算发请求。详见 `llm_execution_audit.json`。

## 检查点、测试与成果保护

正式 B 在第 1 轮完整提交研究记忆后退出，随后从 SQLite 实验边界恢复至第 12 轮，没有重复首轮工具；完整图节点、状态、工具调用及原 ResearchMemory 每场景记录均保留。

全部测试：**239 通过，1 跳过**，包含原 215 项基线和新增 24 项测试；Windows 符号链接权限导致该跳过。Ruff 与 pip check 通过。原基线的 64 步训练测试仅创建临时模型，不重训或替换历史 PPO 权重。

5044 个原跟踪文件审计：允许的集成改动仅 `.gitignore`、`pyproject.toml`、`README.md`；其余 5041 个文件字节保持一致，没有缺失。v1.0.0、main 和 HEAD 均与改造前一致，分支仍为 feature/langgraph-research-agent。44 条新决策又在最终审计中通过原 Simulator 重放并重算 Makespan，一致率 100%。

## 文件与人工核对项

- `all_rounds.csv`：44 条真实逐轮对照；每组 `decisions.csv` 与 `experiments.jsonl` 保存提案、接受理由、反思和下一轮提案。
- `B/llm_calls.jsonl`：完整脱敏 API 决策轨迹；`graph_trace.jsonl`、`tool_calls.jsonl`、`checkpoints.sqlite` 为实际运行证据。
- `comparison.csv`、`best_so_far_comparison.png`、`time_token_costs.png`：实测比较及曲线。
- `audit/final_tests.xml`、`audit/final.json`、`independent_replay_audit.json`：测试、保护和重放证据。
- `docs/langgraph_architecture.md`、`docs/langgraph_runbook.md`、`provenance/langgraph/`：二次开发架构、复现与许可证。

仍需人工核对 DeepSeek 账户账单与估算费用是否一致，以及 LangGraph 上游版本对应 commit。一次开发场景对照不提供统计显著性或跨设备泛化结论；后续多种子/保留场景研究须独立执行。当前没有启用 LLM 自主代码改写。
