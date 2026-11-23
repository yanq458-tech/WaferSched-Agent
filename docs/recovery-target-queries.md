# 四个固定维修时刻的离线核查

本次使用 offline-frontier-final-004 的原始 18 个输入、7 份历史区间和已验证方案。输入、来源及 SHA-256 记录在 results/local/offline-target-final-005 的 manifest.json、memory 和 protocol.json。专项诊断单独存入 results/local/fixed-queries-005，其结论没有预置到计时实验。重复实验应选择新的输出目录。全部结果来自本地 CPU。

## 如何读证据

- 原始 Simulator 重放经过故障前历史、不可取消动作和剩余调度；每份最终方案另有在指定维修延迟下的重放结果。schedule.json 使用快照的整数刻度。replay-0.json 记录立即修复的逐动作决策及所有晶圆的出片时刻。completed 字段是设备的绝对时钟，makespan 是故障后的剩余完工时间。
- 固定时刻的可行性和最迟维修边界是两个指标。固定时刻找到一份有效方案即可证明可行。一个模型分支搜索超时只留下 UNKNOWN。局部顺序搜索与限制邻域均只贡献经重放的下界。
- 优先保存能承受更晚维修的方案，同一延迟下才比较完工时间。不同维修延迟得到的完工时间不能直接用于判断调度质量优劣。
- paired-deltas.csv 列出全部预算、实例、重复和对照。paired_control 是本轮同机旧策略，双方共用同一份实验前证据。previous_run 是上次归档，机器运行时间会波动。ledger.csv 另汇合历史、两条计时策略和预算外诊断，适合回答目前知道的最强结论。

## 固定维修时刻的穷尽分组

适用于源腔与末道加工腔分离、每片只剩一次加工及出片、初始夹爪与目标腔为空的终端子类。不同地点间移动耗时一致，每道末工序加工时间不少于一次移动，源驻留、末道驻留与入腔持片期限有限。原始模型负责其他设备状态。

每片晶圆有一次进腔搬运和一次出片搬运。按机械臂的先后给这 2n 次搬运从 0 编号。设 K 为最后一次进腔搬运的序号，B 为这次搬运开始前已经进腔、仍待出片的晶圆数，则 K = 2(n−1)−B。目标腔此时必须可以接片，因此 0 ≤ B ≤ min(n−1, 候选目标腔总数−1)。这些 K 分组无遗漏。

给每片恰好选择一个 (目标腔, 进腔序号 u, 出片序号 v)。每个序号恰好用一次，同腔占用的序号区间 [u,v] 互斥。取片、放片和移动耗时分别记作 P、L、d，设 S=P+L+2d。第 k 次搬运的取片开始为 kS+I[k]，放片开始为 kS+P+d+Z[k]，其中 I[k]≤Z[k]≤I[k+1]。当目的地恰好也是下一次取片地时，中间的该片加工时间至少为 d，因此这一必要间隔仍成立。模型还约束取片完成时限、夹爪持片期限、放片开始与维修时刻、加工完成时间和末道取片完成时限。相同顺序下，出片搬运可在到达输出端时立即放片。

若某片加工时长 t、驻留上限 R，则其出片必须满足 (v−u)S ≤ d+L+t+R；这来自出片取完期限和 I[v]≥Z[u]。若整批最晚的源取完期限为 D，则 I[K]≤D−P−KS，用来排除明显不可能的列。只有覆盖全部 K 且各模型都返回 INFEASIBLE 才整体排除该维修时刻。归档包含每组 CP-SAT 模型、哈希和求解回执，提供可重新求解的证据。固定时刻不可行可向更迟维修推广，条件是维修仅放宽可操作时间。8 刻度/秒是本批快照的精度。

## 复现

仓库根目录中使用 PowerShell 和项目已有的 .venv-langgraph。离线顺序构造器用本机 .NET Framework 的 C# 编译器编译。编译在计时前完成，每次调用的进程启动、搜索和校验均计入预算。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
$python = '.\.venv-langgraph\Scripts\python.exe'
$old = 'results/local/offline-frontier-final-004'
$repeat = 'results/local/offline-target-reproduction'
$extra = 'results/local/fixed-queries-reproduction'
New-Item -ItemType Directory -Path $extra
$exe = Join-Path (Resolve-Path $extra) 'OrderSearch.exe'
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize+ "/out:$exe" scripts\TerminalOrderSearch.cs
& $python -m wafer_sched.recovery.feedback.frontier_study benchmark --root $repeat --continue-from $old --executable $exe
& $python -m wafer_sched.recovery.feedback.frontier_study audit --root $repeat
& $python -m wafer_sched.recovery.feedback.target_queries --inputs "$old/inputs" --out $extra --seconds 96
& $python -m wafer_sched.recovery.feedback.order_probe --archive $old --out "$extra/order" --executable $exe --seconds 95
& $python -m wafer_sched.recovery.feedback.target_queries --inputs "$old/inputs" --out "$extra/check-144" --case blind-16-h-f1 --tick 144 --seconds 90
& $python -m wafer_sched.recovery.feedback.scarce_route_probe --src "$old/inputs/blind-20-h-f3.json" --out "$extra/scarce/blind-20-h-f3" --seconds 60
& $python -m wafer_sched.recovery.feedback.scarce_route_probe --src "$old/inputs/blind-20-h-f3.json" --out "$extra/scarce/blind-20-h-f3" --verify --seconds 10
& $python -m wafer_sched.recovery.feedback.order_neighborhood --src "$old/inputs/blind-20-h-f3.json" --exe $exe --out "$extra/neighborhood/blind-20-h-f3" --upper 81 --seconds 145
& $python -c "from pathlib import Path; import sys; from wafer_sched.recovery.feedback.order_probe import run; old,out,exe=map(Path,sys.argv[1:]); print(run(old/'inputs',old,out/'mid-64',exe,'blind-16-h-f1',64,9491,10))" $old $extra $exe
& $python -m wafer_sched.recovery.feedback.target_review --root $repeat --prior $old --target $extra
& $python -m pytest -q tests/wafer_sched/test_recovery_slot_query.py tests/wafer_sched/test_recovery_frontier.py
```

最终账本会复核快照哈希，从输入重建各不可行分组模型并逐字节比较归档，重新运行原 Simulator 验证最佳方案。在相同机器上，限时多线程 CP-SAT 亦可能返回不同状态。
