# blind-16-h-f1 的 16 秒与 16.875 秒定点核查

旧输入和界来自 `results/local/offline-endpoint-007`。专项输出在 `results/local/repair-resume-008`，同预算复测在 `results/local/offline-resume-008`。所有计算均在本地进行。

## 结论和证据

每秒 8 个刻度。原 10.75 秒见证保存在 `retained/schedule.json`，其后缀和故障前后原语重放结果在 `retained/replay-86.json`，剩余完工时间 84.5 秒。16 秒对应第 128 刻度。从原始快照、压缩 CP 模型及 SHA-256 复核上轮排除结果。最后进腔序号 28、30 及序号 29 下已排除的十个身份均直接复用。此终端模型里，提前修复只会提早允许向故障腔放片，因此较早刻度的一个固定分组无解，可以排除同一分组的所有较晚刻度。

| 序号 29 的最后进腔晶圆 | 第 128 刻度的新增证据 |
|---|---|
| W0、W13 | 分别用 3、2 刻度的年龄网格构建必要条件。整数重算的分离余量分别为 1911147/1000000、182158/1000000 个原时间刻度，均严格大于零 |
| W7、W14、W15 | 固定最后进腔身份后，CP-SAT 给出 INFEASIBLE；模型字节、SHA-256、搜索分支及求解器状态均保留 |
| W12 | 末次进入 H1 的路线由整数对偶界排除；末次进入 F 的路线按其他晶圆的合法候选腔分组。四个 F 子分支由整数界排除，两个由 CP-SAT 排除。整个 W12 分区树有七个叶节点 |

所有最后进腔情形均在第 128 刻度无解，因此第 135 刻度（16.875 秒）也无解。新的闭区间为 **[10.75, 15.875] 秒**。第 127 刻度（15.875 秒）的可达性仍未知。全树见 `result.json` 和 `tree-audit.json`。目录中也保留了先前未完成的单次求解模型和没有产生正界的松弛查询，仅最终树所引用的证据参与结论。

## 怎样复核数学判定

固定末次进腔身份后，用该晶圆自身的源腔取完期限限制最后一次进腔搬运，并保留所有合法腔室选择。对序号小于末次进腔的搬运，在同一腔室内把互不重叠的进腔至出腔区间相加；每一段至少需要相应搬运序号的基础时间，以及其中不可避免的加工等待。若为故障腔，其首次虚拟搬运起点（放片开始减取片和移动耗时）还受维修门槛限制。该资源界只舍弃超出可用时长的组合。

第二种证据把加工室年龄向外取整，忽略部分限制，构造所有合法方案都能投影进去的流模型。在最后一次进腔发生时锁定已完成的搬运数、仍在腔的片数，以及最后晶圆的身份；只有一片晶圆可使用的腔室在整条路径上至多装入一次。设最迟源腔取完时刻为 D，松弛最小化“最后一次从源腔取完的时刻减 D”。保存的对偶权重经过整数化，用每个流变量的上下界重新计算有理下界。下界严格大于零时，任何合法调度都会超过 D。对偶检查使用整数运算；浮点 LP 超时或未得到正界时，该方法没有排除权。CP-SAT 叶节点保存的是精确求解器结论和可重建模型，未生成形式化 SAT 证明文件。

## 计时口径

两臂都使用上轮冻结的输入、见证、界及已排除分组，同一个 1 秒和 30 秒墙钟协议。目标案例的对照只查询未决子模型；新方法增加身份专属期限、腔室占用界和年龄流判据。其余快照使用上轮的本地策略。满 1 秒运行两次并交换顺序；30 秒首轮两臂状态不同时才交换顺序再运行。此次专项证据不回填到计时输入。逐例的完成状态、区间、剩余完工时间和耗时都在 `paired-deltas.csv`。累计证据在 `frontiers.csv`。每次候选方案均另行重放。

实测 1 秒两次均为 12/18，30 秒首轮也为 12/18。其中 9 例证明有限边界，3 例证明立即修复仍不可行。与上轮同预算、与本轮同期对照逐例比较，新增完整证明和丢失完整证明均为 0。新策略在这三轮中均未超过墙钟预算。30 秒的目标实例在限时内排除了第 135 刻度的 W7、W15 两组，另四组 UNKNOWN，限时输出仍为 [10.75, 16.875] 秒。16 秒定点证明使用额外专项预算，只加入累计账本。blind-20-h-f2 的累计上界由 93.875 秒降至 93.75 秒，两条同期策略都获得了这一改善。blind-24-h-f1 的同期对照在 1 秒首轮逾期，未带回区间；新策略准时返回原见证。对照第二次也准时返回，单次差异不足以证明稳定加速。

18 例的独立审计覆核了 90 次返回方案记录，按案例与方案去重后重放了 25 份。专项树包含 7 个正有理下界和 5 个 CP-SAT 不可行叶节点。回归命令为 `python -m pytest -q tests/wafer_sched -k "recovery or simulator or verification"`，本轮 146 项通过，261 项未选入，3 个警告。

## 复现命令

在仓库根目录运行。下面使用新的输出目录以保留本次归档。若只想核对现有证书和重放，可直接对本次的两个目录执行最后两条审计命令，无需重新求解。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
$py = '.\.venv-langgraph\Scripts\python.exe'
$old = 'results/local/offline-endpoint-007'
$prior = 'results/local/repair-endpoint-007'
$case = 'blind-16-h-f1'
$extra = 'results/local/repair-resume-repeat'
$timed = 'results/local/offline-resume-repeat'
& $py -m wafer_sched.recovery.feedback.route_resume --src "$old/inputs/$case.json" --previous "$old/certificates/$case" --parent "$prior/probe-128/slot/$case" --children "$prior/last-job-128" --out $extra --seconds 155
& $py -m wafer_sched.recovery.feedback.frontier_study benchmark --root $timed --continue-from $old --scope-dir results/local/fixed-queries-005/scarce/blind-20-h-f3 --executable results/local/fixed-queries-005/OrderSearch.exe --grid-executable "$prior/GridCover.exe" --job-archive "$prior/last-job-128"
& $py -m wafer_sched.recovery.feedback.frontier_study audit --root $timed
& $py -m wafer_sched.recovery.feedback.resume_review --root $timed --previous $old --artifacts $extra
```

`route_resume` 支持继续同一专项目录，先检查已存在的模型和正对偶证书，再将预算分给未决路线。全新运行的 CP-SAT 并行搜索及限时 LP 可能走不同分支；复核归档时可直接重算正对偶下界、覆盖关系和模型哈希。小规模回归另对全部搬运顺序和合法目的腔做枚举，对照固定身份子模型及独立重放。

