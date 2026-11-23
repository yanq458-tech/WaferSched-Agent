# 两个固定时刻的核查与 18 例离线复测

输入取自 `results/local/offline-target-final-005/inputs`。单位为故障后的秒，本批快照每秒 8 刻度。新目录 `results/local/branch-check-006` 保存专项证据，`results/local/offline-branch-compact-006` 保存最终计时实验。两条计时策略共享上轮账本、计时前已经验证的 W16→F 排除证据、核数、构造器和总墙钟预算。此次定向排除与新取得的调度未放入计时输入。1 秒全部重复并反转执行顺序，30 秒仅在两方法的首次状态不同时反序再跑。

## 立即修复的 20 片快照

只保留 W16→H2。已有互补路线的证明通过原输入、排除项和模型系数重建核对。下面的冲突来自所有工艺期限里最晚一次源腔取片，不是最终出片的截止时间。

在统一移动的末工序子类中，P、L、d 分别为取片、放片、移动耗时，S=P+L+2d。对一次进腔搬运，以放片开始减去 P+d 定义虚拟进腔开始 B。这样，实际取片与放片间的额外等待可以记在 B 之前。记 A 为这一片后续出腔时的取片开始，t 为加工时长，R 为末道加工后驻留期限。每份合法时间表均满足

    P+d+L+t ≤ A−B ≤ d+L+t+R。

端口与源腔、末道腔互异，相邻搬运的对应开始时间至少间隔 S。若机器人留在原地从刚放入的腔中取出同一片，则 t≥d 仍保证此间隔。将开始时钟分别向下取整到 6 刻度的格点，年龄差的下限向下取整，上限向上取整。由于 S=18 可以被 6 整除，此映射保留每份合法方案。图节点记录各腔为空或已占用多久；搬运、等待、选中最后一次进腔搬运对应图的边。选中最后一次取片后允许继续持片等待才放下，避免多算取片前的时间。

一条合法轨迹产生一单位起终点流，且每片恰好在其候选腔的一次合法年龄的出腔边上被计数。松弛允许分数流，也省去部分工艺约束。弧容量只需覆盖上述映射。在最后一次源腔取片开始之前，总等待和搬运次数由最大取片截止时间限制；在其后没有新的待选进腔搬运，非空腔的年龄由最大驻留窗口限制，空状态的等候可以省略。设 T 为最后一次源腔取片的完成时刻，D 为最后取的那片晶圆自己的源腔截止时间。合法方案要求 T−D≤0。

GLOP 为线性行求出权重后，检查器按整数运算组合各行，并用弧变量与分配变量的上下界处理剩余系数。原始证书的起终点项为 23−808，20 个晶圆计数等式合计 789，剩余变量边界修正为 −2。因此松弛给出 T−D≥2 刻度。这个正下界就足以排除本分支。20 片查询的 6 刻度格点仅用于必要条件；结论以原来的 1/8 秒刻度表述。更粗的 9、18 刻度试验未能给出排除结论。

`flow6/age-flow.pb.gz` 是单独保存的 CP-SAT 模型；`flow6/rational-check.json` 保存全部行权重；`verified.json` 保存重建模型及整数证书核验。限时策略使用直接生成的稀疏矩阵；事后使用独立的 CP-SAT 建模入口构造行并核对返回的权重。构造器未找到方案、LP 未在时限内返回可核验正下界时，都不能据此判不可行。

## 17.875 秒的 16 片快照

在第 143 刻度固定维修完成。按最后一次进腔搬运的序号穷尽 28、29、30，保存每组的模型和求解回执。三个排除结论合在一起才排除该刻度。依据修复仅放宽操作起点的单调性，新上界为第 142 刻度，等于 17.75 秒。原始 8.375 秒方案单独保留。此判据并不证明第 142 刻度可达。

## 在项目根目录复现

下列 PowerShell 命令使用新的输出目录；先前的归档和本地编译的构造器按原路径保留。专项和计时运行各自从冻结输入开始。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$env:PYTHONHASHSEED = '0'
$py = '.\.venv-langgraph\Scripts\python.exe'
$old = 'results/local/offline-target-final-005'
$prior = 'results/local/fixed-queries-005/scarce/blind-20-h-f3'
$exe = 'results/local/fixed-queries-005/OrderSearch.exe'
$extra = 'results/local/branch-check-repeat'
$timed = 'results/local/offline-branch-repeat'
& $py -m wafer_sched.recovery.feedback.branch_probe --src "$old/inputs/blind-20-h-f3.json" --out "$extra/flow6" --wafer W16 --chamber H2 --tick 0 --tool flow --quantum 6 --budget 70
& $py -m wafer_sched.recovery.feedback.target_queries --inputs "$old/inputs" --out $extra --case blind-16-h-f1 --tick 143 --seconds 150
& $py -m wafer_sched.recovery.feedback.branch_verify --inputs "$old/inputs" --artifacts $extra --prior-route $prior --seconds 95
& $py -m wafer_sched.recovery.feedback.frontier_study benchmark --root $timed --continue-from $old --scope-dir $prior --executable $exe
& $py -m wafer_sched.recovery.feedback.frontier_study audit --root $timed
& $py -m wafer_sched.recovery.feedback.branch_results --root $timed --previous $old --artifacts $extra
& $py -m pytest -q tests/wafer_sched/test_recovery_age_flow.py
```

`paired-deltas.csv` 区分同期对照和上轮归档，列出两种预算、执行顺序、墙钟时间、原始状态、预算内状态及上下界。`frontiers.csv` 汇合已核查的最强证据，与单次运行的限时成绩分别记录。
