# WaferSched-Agent v1.1.0 GitHub发布准备审计

日期：2026-10-14（Asia/Shanghai）。本地验收通过；本轮停止于发布准备，未git add、未commit、未push、未合并main、未创建本地v1.1.0标签或远程Release。待用户确认后再执行版本管理操作。

## 仓库与交付材料核查

当前分支 `feature/langgraph-research-agent`，origin 为 https://github.com/yanq458-tech/WaferSched-Agent.git。本地v1.0.0标签对象 `90f14ebcb57a6090f44e2d95e7edcad691e85f1a`，其提交、main和HEAD均为 `9e96ff3c1de467eb49e56cb2f8d47ea09075d255`，与改造前一致。只读远程核查遇到连接重置，不能宣称远程最新标签已核实；发布前应在网络恢复后再次核对。

交付ZIP CRC通过，25个代码及集成文件在初次核查时均已位于独立仓库且与ZIP字节一致，因此未重复迁移覆盖。原始逐轮CSV的44行与JSONL日志指标一致。继续使用现有 `results/stage7_langgraph/`，保留检查点及产物引用路径；docs/stage7归档公开报告与复现说明。

原包元数据是0.1.0，本轮更新为1.1.0；Git v1.0.0基线未改。原5044个跟踪文件中5041个字节一致，仅已授权的README、pyproject.toml和.gitignore集成改动；Simulator、CP-SAT、PPO核心、历史模型与第1—6阶段结果均未改。

## 新增代码与来源

- `configs/wafer_sched/langgraph/stage7_smoke.json`
- `configs/wafer_sched/langgraph/stage7_study.json`
- `experiments/wafer_sched/stage7/reproduce_saved.py`
- `src/wafer_sched/langgraph_agent/__init__.py`
- `src/wafer_sched/langgraph_agent/cli.py`
- `src/wafer_sched/langgraph_agent/code_improvement.py`
- `src/wafer_sched/langgraph_agent/graph.py`
- `src/wafer_sched/langgraph_agent/http_worker.py`
- `src/wafer_sched/langgraph_agent/llm.py`
- `src/wafer_sched/langgraph_agent/memory.py`
- `src/wafer_sched/langgraph_agent/reporting.py`
- `src/wafer_sched/langgraph_agent/schemas.py`
- `src/wafer_sched/langgraph_agent/tools.py`
- `tests/wafer_sched/test_langgraph_agent.py`

LangGraph实际包为1.2.15，开源来源 https://github.com/langchain-ai/langgraph。采用StateGraph九节点反馈循环及SqliteSaver，复用原数学Skill，没有重写数学算法。许可证文件 `provenance/langgraph/LICENSE` 为MIT，完整保留Copyright (c) 2024 LangChain, Inc.；SHA256为 `d9bb52f2e3540d60ff50d8f0f5b6ba649b7fd346948c4c3d086c8afb120763c7`，与来源记录一致。上游commit尚未核验，来源JSON保留null。Semantica仅辅助上下文与记忆，非本阶段Agent主体。

## 真实运行证据

保存字段arm A=原CFAR，B=LLM，C=固定流程；课程报告使用方法名称，明确映射而不重写原CSV。

| 方法 | 真实实验轮 | F/G最佳Makespan秒 | 工具累计秒 | 活动总墙钟秒 | 实测Token |
| --- | --- | --- | --- | --- | --- |
| 固定流程（原C） | 16 | 63 / 183 | 25.441605 | 28.005070 | 0 |
| 原确定性CFAR（原A） | 16 | 63 / 183 | 52.558026 | 55.418993 | 0 |
| LangGraph + DeepSeek（原B） | 12 | 63 / 183 | 31.635618 | 134.136869 | 107826 |

12轮LLM提案均引用真实API并通过独立验证；8轮完整有效反思，前7轮构成连续真实因果轨迹。25条调用记录中21次真实请求全部HTTP200，4条预算检查阻止未发送。21次实际调用段为99.621940秒，未发送检查0.013976秒，总LLMClient段99.635916秒；包含客户端准备，不是服务端纯推理时间。

第8轮反思截断（finish_reason=length，1536输出Token），第10—12轮反思预算阻止；最后规划被预算预留阻止，由确定性回退停止。正式12轮实验回退0次，早期live-study-001有1次提案错误后的确定性实验回退，不算LLM自主轮次。全部保留，不伪造成功。107826Token的0.043860228美元是配置峰值费用估计，不是账单。

单次最小认证preflight-006保存HTTP200、deepseek-flash回复、191Token、1.189289秒；本轮仅读取这些证据，新增API请求0次。预算、失败、raw提案、tool调用、独立Simulator验证、接受理由、反思及next_plan保存在JSONL/CSV与SQLite中。

## 测试与独立复现

本轮完整测试239通过、1跳过（Windows符号链接权限）；包括原215基线与新增24项。测试覆盖StateGraph、7种工具、物理约束、配置仅从.env读取、预算、异常回退与实验边界恢复。Ruff与pip check均通过。测试模拟响应使用unit_test_mock标签，未计入真实实验。

独立导出候选树没有.env、.git、虚拟环境或缓存。数值验收使用导出源码：仿真与CP-SAT均47秒，CP OPTIMAL；14个历史PPO模型只读加载，6组历史最佳策略事件逐条一致；阻止旧铁路平台导入与旧项目文件访问。没有训练历史模型。依赖使用现有独立环境，未声称重新联网安装全套依赖已经验证。

```powershell
.\.venv-langgraph\Scripts\python.exe -m pytest tests/wafer_sched -q
.\.venv\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched experiments/wafer_sched scripts
.\.venv-langgraph\Scripts\python.exe -m pip check
.\.venv-langgraph\Scripts\python.exe experiments/wafer_sched/stage7/reproduce_saved.py
```

离线复核入口已再次重放44条保存决策，全部事件指标与summary一致；不需要密钥，不求解新调度。结果在 `results/stage7_langgraph/v1.1.0-audit/`：tests.xml、saved_evidence.json、independent_export_acceptance.json、release_verification.json。

## 报告与数据哈希

公开报告：`docs/stage7/WaferSched-Agent_课程研究报告_v1.1.0.docx` 和同名PDF，均18页。逐页渲染查看，修正后变化页再次复核。Word/PDF正文覆盖100%，关键数字一致，自动PAGE页码全部正确，A4纵向，长表行不可拆且重复表头。原5张图字节与全部历史研究表保留，新增5张图及阶段七表。公开版本隐藏姓名学号、作者和修改者元数据；原本机报告不变。

每个研究数据、图表、报告、许可证和验收文件的SHA256及字节数在 `results/stage7_langgraph/v1.1.0-audit/data_sha256.json`（702个文件），不包含.env及密钥摘要。Word SHA256 `6aa89e7e28b5a64e1aec8b7494f7f26f00194f80da9f3c53c42e470e4bd8d108`；PDF SHA256 `ed7a0d440872e3c420d89eecbc0a1574539590c0ff0708a53887c28aa61a6457`。数据哈希在最终归档后核对，原始日志不改写。

## 待提交范围与安全

当前只有3个原跟踪集成文件修改，以及新增代码、配置、许可证、公开报告、选定真实研究日志和新审计。详细734项清单见 `docs/stage7/pending_commit_files.txt`；未暂存或提交。旧认证诊断、旧试跑及本机临时材料继续留存但被阶段七白名单规则排除，不覆盖或删除。

本次提交候选检查排除.env、实际密钥与已保存认证头、个人姓名学号及作者元数据、无关铁路业务代码、虚拟环境和缓存。实现代码中的Authorization构造及单元测试假凭据是必要测试与接口代码，不是保存的请求认证头或真实密钥；未对其作误删。安全结果见 `safety_audit.json`。

## 发布条件与已知局限

本地代码、实验、文档及保护验收满足v1.1.0发布准备条件。仍须用户确认后提交、推送、合并或创建Release；远程最新状态因连接重置待复核。上游commit和DeepSeek账单需人工核对，不写成已完成。

LLM没有提升F/G最终解质量，总墙钟成本更高；有限静态场景与预算不构成统计显著性、严格收敛或一般全局最优理论保证。未实现LLM自主修改RL代码，未解决一般动态故障调度。OPTIMAL只针对原CP编码声明的模型。反思截断、预算阻止及最终确定性回退属于真实运行限制，不隐藏。

## 2026-10-14 用户授权后的提交与推送前复核

上文是已完成的发布准备快照，保留当时的状态。本次用户明确授权在现有开发分支提交并推送，不合并 main、不创建 v1.1.0 标签或远程 Release。

再次核对原 734 项范围，所有阶段七源码、真实实验、许可证及 18 页公开 Word/PDF 均已在仓库，报告与最终验收 outputs 版本逐字节一致，因此无需另行复制过期或含个人信息的报告。README 下载链接指向 docs/stage7 的公开验收版本。702 项归档哈希全部一致，原 5,041 个非集成跟踪文件字节不变，main 和 v1.0.0 标签保持原对象。

必要复测结果为 239 通过、1 跳过（Windows 符号链接权限），Ruff 与 pip check 通过，44 个保存候选独立重放通过；没有调用付费 API。首轮受旧 pytest 临时目录权限影响，随后跨盘临时目录触发已有相对路径限制；使用同盘新目录 `.pytest-tmp-publish-20261014` 后全套通过。没有修改源码或测试绕过限制，跨盘输出限制仍是已知平台兼容性事项。

待提交内容再次通过安全扫描：.env 被忽略且未跟踪，无实际密钥、认证头转储、个人姓名学号或用户目录、虚拟环境与缓存；扫描包括 SQLite 原始字节及 DOCX XML。Git diff --check 通过。实现认证头的代码和脱敏测试用假凭据予以保留。此次仅刷新 README 与发布状态说明，归档数学数据、PPO 权重和报告文件未改。

推送结果以本次完成回复及 GitHub 远端分支查询为准；本段为提交前记录，不预先宣称远端上传成功。

暂存后补充：默认 Git 空白检查把原始 Windows CRLF 行尾视作空白；按 `cr-at-eol` 识别换行后，仅 15 份原始 CP-SAT solver.log 第 8 行包含求解器生成的行尾空格。为保留真实实验原字节，不改写这些日志。排除这 15 份原始日志后，源码、文档及其他提交内容的空白检查通过；暂存内容还需按归档哈希复核。这是原始证据的格式例外，不声称默认全树空白检查无警告。