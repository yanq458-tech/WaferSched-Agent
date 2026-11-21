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
