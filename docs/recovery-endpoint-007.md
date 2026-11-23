# 17.75 秒定点核查与 1 秒限时退步诊断

本轮输入是 `results/local/offline-branch-compact-006` 归档的原 18 个快照。专项查询单独存入 `results/local/repair-endpoint-007`，计时对照单独存入 `results/local/offline-endpoint-007`。两臂共享相同的历史界和见证；对上轮已经证明立即无解的 20 片实例，双方仅收到证明之前的输入区间、已排除的路线和快照，必须在钟内重新证明，无解结论没有作为答案传入。

## 边界和证据怎样读

时间原点为故障瞬间，此例每秒 8 个刻度。17.75 秒对应第 142 刻度，17 秒对应第 136 刻度。两次查询均枚举最后一次进腔搬运的全部三个可能序号 28、29、30；仅在三组均获 CP-SAT 不可行结论时排除该刻度。维修越早，原时间表仍可执行。因此第 136 刻度不可行将上界降至第 135 刻度，即 16.875 秒。16 秒查询的序号 29 进一步按最后进腔的晶圆身份分组；仍有超时分组，此查询不能用来降低上界。

原 8.375 秒方案及重放见 `retained/`；新 10.75 秒方案及重放见 `construct/86/`。两套记录均包含源快照 SHA-256 或其对应账本、原语决策以及所有晶圆的最终出片记录。最终上下界和对应证据统一见计时目录的 `frontiers.csv`；额外定点查询获得的证据不计入 1 秒或 30 秒成绩。年龄流松弛也试验了维修门槛：用虚拟进腔时钟 B 等于放片起点减取片和移动耗时，实际可用时需要 B≥r−P−d。在粗格点的首段保存取整后的绝对时钟，达到门槛后合并状态。6 和 3 刻度的附加测试均未产生正的不可行下界，本轮上界证据来自分组精确查询。

## 1 秒策略的改动

旧记录已有互斥计时。若原始结果为 FINITE、后缀重放在 1 秒前成功、整次在完整历史重放期间越过 1 秒，则归为完整重放逾期。若所有构造和精确查询都没有可验证方案、没有后缀见证通知，则归为搜索未命中。

短预算下，新策略对适用的终端快照尝试构造上界处的时间表。C# 稀疏精确覆盖搜索要求每个搬运序号和每片晶圆各选一次，每一腔室占用区间互斥。采样时钟只生成候选顺序，失败不排除任何维修时刻。Python 随后用精确刻度重新计算时间，并用 Simulator 验证。子进程启动、搜索与两次验证均计时；历史证据恢复也计时。新策略在一次求解内只校验一次故障前的不可变动作历史，保存该次核验得到的状态与事件日志，每次续算使用独立副本。校验仍覆盖加工完成事件、驻留、持片和全部晶圆出片；最终审计再从原始快照独立重放。共享验证器中固定的晶圆/腔室状态对应关系移至常量，两条同期策略均获得这项小优化。

## 复现

在仓库根目录运行下列 PowerShell 命令。使用新的目录名称以保留历史结果。计时实验与专项核查应顺序执行，避免 CPU 争抢。原硬件绑定为 2、4、6、8 号逻辑核。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
$py = '.\.venv-langgraph\Scripts\python.exe'
$old = 'results/local/offline-branch-compact-006'
$branch = 'results/local/fixed-queries-005/scarce/blind-20-h-f3'
$order = 'results/local/fixed-queries-005/OrderSearch.exe'
$extra = 'results/local/repair-endpoint-repeat'
$timed = 'results/local/offline-endpoint-repeat'
New-Item -ItemType Directory -Path $extra
$grid = Join-Path (Resolve-Path $extra) 'GridCover.exe'
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize+ "/out:$grid" scripts\TerminalGridCover.cs
& $py -m wafer_sched.recovery.feedback.endpoint_review --probe --root $timed --previous $old --artifacts $extra --executable $order
& $py -m wafer_sched.recovery.feedback.frontier_study benchmark --root $timed --continue-from $old --scope-dir $branch --executable $order --grid-executable $grid
& $py -m wafer_sched.recovery.feedback.frontier_study audit --root $timed
& $py -m wafer_sched.recovery.feedback.endpoint_review --root $timed --previous $old --artifacts $extra --seconds 65
& $py -m pytest -q tests/wafer_sched -k "recovery or simulator or verification"
```

`one-second-diagnosis.csv` 对应上轮五次丢证明的运行。`paired-deltas.csv` 逐例列出相对上轮和相对同期旧策略的限时状态、上下界、完工时间和墙钟时间。没有证据把运行速度的跨轮波动全部归因于算法。
