# 单腔故障恢复边界的最终盲测

目标仍是判定故障后全部有效在制晶圆能否完成剩余工序，并求最迟维修延迟。这里评估空手单臂、源腔和末道腔分离、异址等长移动的末道竞争子类。输入是模拟器生成的可达故障快照。

## 可核查的不可行证据

令一组晶圆的末道工序都只能在腔室 C 加工。假设 j 是这组里最后从源腔取出的一片。取 j 之前，其他同组晶圆必须已从 C 取出并送往 OUT，否则机械臂持有 j 时无法再清空 C。设 P、L、d 分别是取片、放片和异址移动的刻度数，tᵢ 是 i 在 C 的加工时长。两次相邻的同组源取片开始之间，前一片至少需要 2P+2L+3d+tᵢ 个刻度。期间服务别的晶圆也不能提前清空 C。

令 a 为组内最早可能的第一次源取片开始时刻，Dⱼ 为 j 在源腔最迟允许的取完时刻。逐一尝试所有可能的最后一片 j。若每一个 j 都满足

    a + Σ(i ≠ j) [2P + 2L + 3d + tᵢ] > Dⱼ − P

则即刻维修也不可行。严格大于才产生证据。原始记录保留腔室、每片成本、每个 j 的左右端点、时钟精度和最小超限幅度。没有触发判据的实例继续求解。独立原语枚举覆盖移动时间为零及非零、两片加工时间不同、期限提前一刻度、恰好相等及延后一刻度。

## 三种入口及计时

固定组合、同策略普通函数、离线 LangGraph Agent 使用同一套可行性工具、数学证据和重放验证。固定组合先做先导求解和上界松弛，再尝试触达上界。短预算下，反馈入口若拿到路线证书则先调度到该上界，一次成功就能同时证明可行和最迟性；失败后视剩余预算尝试松弛、零延迟或区间内查询。长预算保留根据先导结果选择工具的策略。两种反馈入口共用决策函数。

三个入口都对有限边界的见证执行后缀重放和故障历史重放。限时运行在事件日志中仅保留质量核对所需的受影响晶圆状态，原模拟器仍执行每项动作、资源和状态检查。计时结束后另外用完整原模拟器重放归档方案。内部求解分配 85% 预算，端到端墙钟超过 1 秒或 30 秒整次记 UNKNOWN，即使稍后得到证明也同样计分。

## 如何复核

在具有项目恢复实验依赖（含 OR-Tools、LangGraph）的 Python 环境、仓库根目录下运行以下 PowerShell 命令。新输出目录须尚不存在。原实验固定在逻辑 CPU 2、4、6、8 上，每次 CP-SAT 使用一个工作线程。运行时间和短预算命中情况可能随机器负载变化。

```powershell
$env:PYTHONPATH = "src"
$dest = "results/local/final-holdout-replication"
python -m pytest tests/wafer_sched/test_exclusive_terminal.py -q
python -m wafer_sched.recovery.feedback.closeout_recheck --out results/local/final-dev-recheck
python -m wafer_sched.recovery.feedback.study generate --final --root $dest
python -m wafer_sched.recovery.feedback.study benchmark --root $dest --budget 1
python -m wafer_sched.recovery.feedback.study benchmark --root $dest --budget 30
python -m wafer_sched.recovery.holdout_review --root $dest
```

比较采用 16、20、24 片和中、高竞争的六种组合，每种三个新种子。协议、求解源码摘要和输入清单在求解前冻结；一次求解只能读取当前快照。1 秒全部反序重测，30 秒在三组首轮证明状态不一致时反序重测。首轮为主要计分，复测单列。此前18例只用于定位和回归。[上一轮冻结代码](https://github.com/yanq458-tech/WaferSched-Agent/commit/733efd1a7ba7840e2fb369d2c99c893556bb93f2)可用于重跑此前协议。

- [冻结协议](../results/recovery/feedback-study/final-holdout/protocol.json) 与 [输入清单](../results/recovery/feedback-study/final-holdout/manifest.json)
- [逐例增退和 UNKNOWN 原因](../results/recovery/feedback-study/final-holdout/instances.md) 与 [全部运行记录索引](../results/recovery/feedback-study/final-holdout/runs.csv)
- [配对结果](../results/recovery/feedback-study/final-holdout/paired-effects.json) 与 [原模拟器重放及跨方法一致性](../results/recovery/feedback-study/final-holdout/audit.json)
- [原有短预算难例复查](../results/recovery/feedback-study/closeout-acceptance/) 与 [独立枚举测试](../tests/wafer_sched/test_exclusive_terminal.py)

## 单快照 DeepSeek 试验（可选）

运行以下命令将发起至多一次真实模型请求。需在项目根目录配置既有的 DeepSeek Flash 凭据，并提供尚不存在的输出目录。发送给模型的是晶圆数、候选腔数量和容量松弛的求解反馈。模型只选择在已证上界尝试构造，或在该时刻调用 CP-SAT。边界证明仍需数学上界和两层重放；构造失败或搜索超时保留 UNKNOWN。网络及模型时间计入试验总耗时。此单例与上文已冻结的离线盲测分别统计。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m wafer_sched.recovery.feedback.live_pilot results/recovery/feedback-study/holdout/inputs/new-16-m-f1.json --out results/local/my-deepseek-pilot --live
```

输出目录的 `result.json` 保存工具选择、数学结果、调度与用量，`llm_calls.jsonl` 保存脱敏的模型调用记录。

## 冻结的 18 个快照与真实 DeepSeek 对照

三组使用相同输入和本地工具。普通函数和离线 LangGraph 运行同一策略。在线组仅在首个尚需选择的查询点调用一次 DeepSeek Flash，选择维修延迟与工具，返回结果仍由本地数学判据及仿真复核。1 秒全部反序复测，30 秒仅在三组首轮证明状态不同时复测。原协议给搜索分配总预算的 85%，其余留作验证和返回。模型等待占用搜索时间。超过内部截止时刻的回复只用于回收用量。每次方法执行的外层墙钟仍须满足 1 秒或 30 秒。

首次本地实验共 162 次方法运行。普通函数、离线 Agent、在线 Agent 的首轮证明数在 1 秒下分别为 11、11、2，在 30 秒下均为 11。7 个历史 UNKNOWN 均未闭合。含复测的 47 次真实请求共 20,863 Token，按实验当天的周末费率估算约 0.01944 元。首轮配对结果与区间变化见输出目录的 instances.md 和 paired.csv，回执汇总见 usage.csv。

在项目根目录运行。第一条 Python 命令需要新输出目录，会发起付费调用。第二条可独立使用，只读取已有记录、重放方案并生成汇总。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_comparison --live --out results/local/deepseek-18-new --blocking-first-probe
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_review --root results/local/deepseek-18-paired-001
```

## 本地优先的异步 DeepSeek 对照

1 秒预算完全运行原离线 Agent。30 秒先执行本地优化，若晶圆的维修区间仍未闭合，且当前时刻的本地构造已尝试但没有找到可行方案，才考虑发出请求。至少还剩 2 秒、还有未查的候选时刻时，后台最多咨询一次，同时主线程继续原定的精确查询。只在下一次查询前无阻塞地检查建议，过期、重复或落在新区间之外的建议均不能改变证明。API 只可选择查询时刻和工具。

在项目根目录执行。第一条 Python 命令使用新的空路径并产生实际 API 费用。最后一条只读本地实验记录，并生成 18 例配对结果、回执用量和独立重放审计。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_comparison --live --out results/local/deepseek-18-async-new
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_review --root results/local/deepseek-18-async-002 --previous-live results/local/deepseek-18-paired-001
```

本次 18 例首轮在 1 秒下三组均按时证明 5 例，反序复测相同；30 秒下三组均证明 11 例。原 7 个未决例仍未闭合，对同期两组本地对照，异步组有 1 例区间改善、6 例退步。改善例的建议已过时并被丢弃。7 次真实请求合计 2,502 Token，按当日单价推算 0.002784 元。

## 按已完成的求解反馈选择研究目标

1 秒保留纯本地路径。30 秒在线组在定时刻精确查询已经返回、维修区间仍未闭合且内部剩余至少两秒时，才发起一次异步请求。输入包含真实回执、已证上下界、可行见证是否存在、剩余时间和设备特征。三个目标均由本地工具执行。

- 找可行方案：无见证时查立即修复，有见证时查比当前可行下界晚一个整数刻度，使用另一固定搜索种子。
- 收紧上界：若此前的容量松弛尚未证最优，给它额外时间，然后在当前上界直接做精确查询。
- 沿用本地：继续原有容量松弛、构造及定时刻精确查询。迟到、失效或格式无效的回复也保留本地执行路径。

在项目根目录使用现有虚拟环境。第一条模块命令会发出真实请求，输出目录必须是新目录。第二条只读取已完成的记录和原始快照进行审计。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_comparison --live --feedback-objectives --out results/local/deepseek-18-goals-new
& ./.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery.feedback.live_review --root results/local/deepseek-18-goals-003 --previous-live results/local/deepseek-18-async-002
```

对照使用相同冻结输入、核绑定和端到端截止。判断未决例预算去向时，旧日志可给出中点的 CP-SAT 求解秒数和构造次数，未单列每次构造的墙钟时间。独立运行容量松弛可查明其最优值；全模型边界仍需要可行见证或进一步证明。

本轮 162 次运行中，两个预算下三组均按时证明 11/18。30 秒原 7 个 UNKNOWN 的最终区间在三组之间逐例一致。模型 7 次都建议沿用本地；历史原始状态为 4 条采用、2 条因理由过长回退、1 条在结束前没有被消费。随后修正了理由截断，离线重验 7 条原始回复，均保留同一个有效目标。收费实验使用的原始接收代码保存在本批输出目录的 goal_advice_as_run.py，修正后的离线回放见 decision-replay.json。7 次请求共 4,578 Token，按实验日费率计 0.00505424 元。账户余额按分显示，前后读数相同。
