# 从历史回执学习维修边界的下一次查询

输入、可恢复性定义、最迟修复时限和模拟器沿用原单臂末道工序模型。学习器只能提出查询时刻。合法方案、不可行证明与上下界更新仍由原求解工具与模拟器负责。

## 训练

使用 `results/recovery/feedback-study/holdout` 与 `final-holdout` 的固定、普通函数、离线 Agent 历史轨迹。只抽取已真实执行且有工具回执的端点查询。下界目标查询 0 或已验证下界加一个刻度，上界目标查询当前已证上界。两端重合的样本、内点样本和没有回执的样本不参与拟合。

对每个目标拟合一个带 L2 正则的逻辑回归，预测当前查询取得合法见证或不可行结论的概率。训练信号是实际工具返回 WITNESS、FEASIBLE、OPTIMAL 或 INFEASIBLE；无见证和 UNKNOWN 计为这次未取得证据。正标签没有区分只排除一个刻度和直接闭合整个区间。在每个目标的拟合中，每个有记录的快照总权重相同。特征包含晶圆数、单选腔比例、最拥挤健康腔的独占需求、有无见证、剩余区间、预算档位、已查询次数和最近精确求解状态。不给模型输入快照编号、已知答案或本次查询结果。按历史快照留一验证评估的是对已发生动作的预测，无法知道在同一状态下改选另一动作会发生什么。

运行时在合法且未尝试的两个端点中取预测分较高的目标；如均已尝试，沿用原策略的内点。两组均使用既有 LangGraph 图、相同初始试探、容量松弛、构造、CP-SAT 及验证程序。基线为无历史见证时的原人工反馈策略 `feedback.policy.solve(mode="agent")`。

## 新快照与配对计时

同一生成器，新种子生成 18 个快照，按 16、20、24 片和中、高竞争分层，每格三个快照。通过输入内容去除设备名称后的指纹及种子检查历史重合。测试前冻结模型、训练来源、快照、运行代码和协议。首轮为主，所有样本交换顺序再测一轮。两组同实例同核心、单线程求解。1 秒与 30 秒均计入读输入、状态初始化、图编排、模型读取与推理、求解、方案重放和返回的时间。工作进程启动、导入公共依赖及存档在计时外；预算内预留 15% 用于收尾。超时返回的结果计 UNKNOWN，清空该次可计分上下界。缺少见证时区间宽度留空，只比较有依据的端点。计时后还用归档快照额外复核见证，这次复核不改变成绩。

默认输出在本地 `results/local/learned-query-001`。冻结后的文件包括 `model.json`、`training.json`、`protocol.json`、`manifest.json`、`freeze.json`。每个实测动作的预测、所选时刻、原默认时刻及精确回执在 `runs` 中。汇总文件为 `paired.csv`、`cases.md`、`audit.json`。

在仓库根目录，用已有研究环境复现。选用空的新目录；再次运行产生新的墙钟计时结果。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
$env:OPENBLAS_NUM_THREADS = '1'
$dest = 'results/local/learned-query-reproduction'
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.recovery.feedback.learned_study all --root $dest
.\.venv-langgraph\Scripts\python.exe scripts/review_learned_recovery.py --root $dest
```
