# LangGraph 阶段七运行与验收

本阶段代码使用原 v1.0.0 仓库的配置、历史 PPO 模型和数学工具。新增结果只写入 `results/stage7_langgraph/`，每次选择新目录。本次真实 API 已成功，B 完成 12 轮；新环境运行 B 前仍须先通过自己的连通性测试。

## 安装

实测环境为 Windows CPython 3.13.13。新环境不要覆盖原 `.venv`：

```powershell
py -3.13 -m venv .venv-langgraph
.\.venv-langgraph\Scripts\python.exe -m pip install -r requirements-langgraph-agent.lock.txt
.\.venv-langgraph\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv-langgraph\Scripts\python.exe -m pip check
```

完整锁定文件不含本机可编辑安装地址。开发验收时新环境通过 `.pth` 复用原数值依赖，并独立安装 LangGraph；上述命令用于独立重新安装，不依赖本机 `.pth` 或原 Semantica 工作区。

## 本机配置

```powershell
Copy-Item .env.example .env
```

在本机编辑 `.env` 填入服务商凭据。已有 `.env` 时不要覆盖。三个变量名为 ASSISTANT_LLM_BASE_URL、ASSISTANT_LLM_MODEL、ASSISTANT_LLM_API_KEY；后者不得写入公共配置、实验数据或课程报告。运行时仅显式读取项目根目录 `.env`，不读取或回退旧进程环境变量。

```powershell
git check-ignore .env
```

## 真实调用的递进验收

先执行一次最小测试，成功请求报告须来自真实 API；401/403/402/超时不能作为通过：

```powershell
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.langgraph_agent.cli check-llm --output results/stage7_langgraph/preflight-new
```

成功后，先执行一轮真实 LLM Agent，并在完整实验边界暂停：

```powershell
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.langgraph_agent.cli run --mode llm --config configs/wafer_sched/langgraph/stage7_smoke.json --preflight results/stage7_langgraph/preflight-new/summary.json --output results/stage7_langgraph/live-smoke-new --pause-after 1
```

检查该目录的 `llm_calls.jsonl`、`graph_trace.jsonl`、`tool_calls.jsonl`、`experiments.jsonl`、`decisions.csv`、SQLite 检查点及各场景记录：提案须合法、工具实际运行、原 Simulator 独立验证通过、实际规划器标签正确、研究记忆已提交。不能用模拟响应或回退来代替这一轮真实验收。

同一配置和目录恢复，最多执行五轮；若 LLM 提前停止、失败或未达五轮，验收结果会如实保留为未通过：

```powershell
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.langgraph_agent.cli run --mode llm --config configs/wafer_sched/langgraph/stage7_smoke.json --preflight results/stage7_langgraph/preflight-new/summary.json --output results/stage7_langgraph/live-smoke-new --resume
```

随后开展相同预算和工具集合的完整 A/B/C 对照：

```powershell
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.langgraph_agent.cli suite --preflight results/stage7_langgraph/preflight-new/summary.json --output results/stage7_langgraph/development-new
```

未提供有效 preflight 时 suite 仍运行真实 A/C，但将 B 明确标记 blocked，结果 CSV 中其性能与成本字段留空。套件在 B 未通过真实 LLM 验收时返回非零状态，不能只根据 A/C 成功宣称全阶段完成。

## 测试

```powershell
.\.venv-langgraph\Scripts\python.exe -m pytest tests/wafer_sched -q
.\.venv\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched experiments/wafer_sched scripts
git diff --check
```

新增测试中的假 LLM 均用 `unit_test_mock` 标签。其五轮工作流使用真实数值工具，验证软件循环和恢复，不能用于性能比较或计入真实 API 五轮。原基线的 64 步训练测试只创建临时小模型，不重新训练或替换历史 PPO 模型。

## CodeImprovementSkill

本阶段仅提供请求接口和设计。`enabled=False`，执行直接拒绝。下一阶段须独立设计经过审核的补丁、隔离测试和明确启用流程；当前禁止执行 LLM 生成的 Python、系统命令或源码修改。
