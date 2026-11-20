# 1 秒故障恢复边界实验

120 个哈希锁定的故障快照。正序和反序分别指同一快照上两种策略的执行顺序对换，首轮起始策略按既有协议平衡。两者都执行离线 LangGraph 策略，旧版为 graph_ranked，新版为 graph_fast。单线程、相同核、相同 85% 内部预算。建模、前后缀验证与图执行都计入外层墙钟；超过预算返回 UNKNOWN。基准在预先载入 Python 和依赖的工作进程内计时，输入解码、另行归档审计和进程冷启动单独进行。

| 墙钟预算与轮次 | 历史旧版 | 同场旧版 | 新版 | 新版中位用时 / 最大用时 |
|---|---:|---:|---:|---:|
| 1 秒首轮 | 104 | 117 | 120 | 0.067 / 0.634 秒 |
| 1 秒反序 | 102 | 115 | 120 | 0.061 / 0.581 秒 |
| 30 秒首轮 | 120 | 120 | 120 | 0.137 / 2.069 秒 |

每一轮新版均得到 79 个有限边界、20 个无穷边界、21 个立即修复仍不可恢复。两档预算均与上一版 30 秒逐例结论、有限边界相符。两策略共同证明有限边界的记录中，无完工时间退步或已有完工最优保证丢失。样本为既有固定语料，绝对用时取决于机器负载。逐次配对和历史对齐见 [comparison.csv](comparison.csv)，汇总见 [comparison.json](comparison.json)。

## 旧策略为什么会丢证明

首轮 16 个 UNKNOWN 与两次配对中 4 个偶发丢证明实例的并集有 17 个。对每个输入在同一固定核心单独复测两次，按平均互斥阶段用时归类。该归类反映本次剖析的最大消耗项，无法从历史整段计时反推旧运行的精细分解。一个实例可同时受搜索与重放影响。

| 用时最大项 | 实例 |
|---|---|
| Simulator 重放 | terminal-06-02、06-08、08-02、08-05、08-08、08-11、12-03、12-05、12-09、12-11，以及 kim-02、kim-11、kim-23 |
| CP-SAT 搜索 | terminal-06-04 |
| 搬运序号模型编码与提取 | terminal-08-04 |
| 故障历史重建和后缀准备 | terminal-12-02、terminal-12-08 |

偶发丢证明的四例为 terminal-08-11、kim-02、kim-11、kim-23，其中 kim-11 的旧首轮已经证明。见 [逐例耗时（秒）](diagnostics.csv) 及 [34 次剖析的求解回执和原始轨迹](diagnostics/)。

## 新策略如何得到证明

- 每个输入单独重建其合法前缀。在该次求解内复用准备结果和基础时间刻度；固定修复延迟可细化自己的时间刻度。三角不等式检查先精确缩放到整数。Simulator 保留原事件和合法性检查，按已知标量字段复制完整状态，减少每个事件反复递归序列化的成本。计时外仍以旧 Simulator 重放。
- 对末道角色分离、统一移动时间且加工时间至少为移动时间的适用子类，沿用原来的源取片序号上下界。最后一次源取片的可能序号很少且片数至多 8 时，按每片的“进腔序号、出腔序号、候选腔”建立精确覆盖。每个序号恰用一次，同腔占用区间互斥。按候选数最少的空位分支，用位集删除与已选组合互斥的候选。
- 固定组合后，动作先后、取完与持片期限、加工时间、机械臂互斥都能写为差分约束。沿反向边传播得到各故障腔放片时刻可达到的最晚时间，上界取这些时间与外部证书上界的最小值；正向传播直接求该修复时刻最早出片的时间表。修复下界相等的分支保留，以比较最短工期。穷尽可能序号和兼容组合才关闭对应上界；提前中断保留未关闭分支。
- 若既有判据已把可能达到上界的尾部限制为两片等待，则优先在该上界搜索可重放的见证。程序枚举允许的尾部顺序和目的腔，尝试不同的前缀时间网格，用精确覆盖安放剩余晶圆。网格上找到的方案达到独立的全域上界即证边界。找不到时保留原来的精确求解回退。求解代码只接收快照，不从结果目录、案例编号或历史见证载入解答。

## 三个重点实例

| 快照 | 精确边界 | 下一不可能刻度 | 边界处最短完工 | 1 秒档两次实际用时 |
|---|---:|---:|---:|---:|
| terminal-08-04 | 10.250 秒 | 10.375 秒 | 38.250 秒 | 0.383 / 0.426 秒 |
| terminal-12-02 | 55.625 秒 | 55.750 秒 | 63.250 秒 | 0.244 / 0.238 秒 |
| terminal-12-08 | 55.625 秒 | 55.750 秒 | 63.250 秒 | 0.251 / 0.373 秒 |

8 片例最后一次源取片序号只能为 10 或 11（从零计）。两支精确上界分别为 82 和 65 刻度，82 刻度有合法见证。两个 12 片例的数学上界各为 445 刻度，网格搜索分别在第 19 和第 1 个候选网格上得到合法见证。三例每秒均为 8 刻度。完整方案、序号搜索与证书保存在 [1 秒运行目录](paired1/runs/)；[六个下一刻度 CP-SAT 子模型的独立复算](next-tick.txt) 为另行审计，未向计时策略提供模型或答案。

## 新增证明和耗时退步

同场两次均新增 terminal-12-02 和 terminal-12-08；仅首轮新增 terminal-08-04；仅反序新增 terminal-06-04、terminal-12-03、terminal-12-11。所有已知历史首轮遗漏和偶发丢证明输入本轮均两次按时证明。没有丢失边界证明。1 秒反序中 kim-38 用时从 0.248 增至 0.328 秒，仅一次触及“多用至少 50 毫秒且慢至少 20%”的筛查线。30 秒首轮有 chain-08、kim-28、terminal-06-02 触线，三者单独反序复测均未复现。原始筛查和反序数值见 [30 秒二次复测](paired30/secondary/results.json)。

两档正式配对合计 720 次求解。按旧 Simulator 独立重放其中 395 + 198 = 593 份归档方案。重复运行产生的方案也各自重放，这个数字计重放次数。回归为 [334 项通过，1 项跳过，1 项训练测试排除](pytest.txt)。

## 本地复现

在研究工作树根目录激活已有环境。归档控制版本为 c7d4732aa2c28ca40e1fecd80da9c485cfa916c3。以下命令重测时写入新目录。CPU 编号与本次 Windows 主机一致，其它机器应换为实际可用核心。

~~~powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python -m wafer_sched.recovery.evidence_cli agent results/recovery/evidence-study/inputs/terminal-08-04.json --budget 0.85 --out results/local/short-demo.json
python -m wafer_sched.recovery.policy_retest run --fast --budget 1 --cores 2 4 6 8 --repeats 2 --out results/local/short/paired1
python -m wafer_sched.recovery.policy_retest run --fast --budget 30 --cores 2 4 6 8 --repeats 2 --confirm-discordant --out results/local/short/paired30
foreach ($b in 1,30) {
  python -m wafer_sched.recovery.policy_retest audit --out "results/local/short/paired$b"
  python -m wafer_sched.recovery.confirm_regressions "results/local/short/paired$b"
}
python -m wafer_sched.recovery.rank_review recheck --seconds 30
python -m pytest tests/wafer_sched -q --deselect=tests/wafer_sched/test_rl_training.py::test_real_short_training_save_load_masked_prediction_and_policy_runner
~~~

[两档的逐例增退](paired1/changes.md) · [30 秒配对](paired30/changes.md) · [适用条件与原始数学判据](../../../docs/recovery-tail-ranks.md)
