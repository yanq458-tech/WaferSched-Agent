# 两个困难状态的维修边界与配对复测

输入与数学问题沿用 v1.3 后的 [故障恢复对照研究](recovery-evidence.md)。历史对照为提交 8a5952fb2c53ed22c8fe1b04730a4be484107263。原 120 个快照和历史运行保存在 results/recovery/evidence-study；本轮证据单独保存在 results/recovery/hard-case-policy。

| 每例预算 | 旧 Agent 准时证明 | 新 Agent 准时证明 | 两次均新增证明 | 两次均丢失证明 |
|---|---:|---:|---:|---:|
| 1 秒 | 91/120 | 104/120 | 13 | 0 |
| 30 秒 | 101/120 | 110/120 | 9 | 0 |

两组的新增证明全部为无穷边界。主对照共 738 次运行，574 份归档方案通过独立重放。首轮两种预算各有 20 例实际命中全程绕开故障腔的见证。历史 W7 的延后放片推论另用原始方案单独验证。

[1 秒逐例得失](../results/recovery/hard-case-policy/paired1/changes.md) · [30 秒逐例得失](../results/recovery/hard-case-policy/paired30/changes.md)

另行事后筛查表现下降的记录。30 秒组有 7 例首轮得到相同结论但新策略慢至少 0.05 秒且慢至少 20%。反序复核后，仅 kim-01 与 terminal-04-02 仍达到该门槛，二者都走原有的有限边界分支，无法将时差归因于新增的绕行算法。1 秒组第二对中 kim-04 的下界由 1143.375 秒降至 1137.75 秒，追加复测中两种方法都未准时返回，此项下降没有复现。追加复测不计入总体证明率。[30 秒退化复核](../results/recovery/hard-case-policy/paired30/secondary/results.json) · [1 秒退化复核](../results/recovery/hard-case-policy/paired1/secondary/results.json)

## 8 片：已保存的可行方案隐含无穷边界

在 terminal-08-03，历史直接优化的见证在健康腔上完成所有加工，56 秒出完全部晶圆，因此对任意维修延迟都可执行。旧 Agent 首轮用 7.14 秒预算优化立即修复时的完工时间，随后用已验证提示和约 17.11 秒预算最大化维修延迟。其 100.875 秒是一次可行见证。历史首轮的完整提示没有归档。用重建提示、同样的 17.112407 秒分配做冷/暖启动对照，两者这次均证明无穷。不能把历史差异唯一归因于提示或某个秒数。

历史见证本身提供了更强推论：另外七片在故障后 32.625 秒前出片。W7 在 43.625 秒取完，100.875 秒开始放入 F。W7 的该次持片上限未设，且此前没有依赖故障腔的动作。设实际维修延迟为 R，把 W7 的放片及之后所有时刻整体后移 max(0,R−100.875) 秒，保持取片时刻。持片期间没有其他在制晶圆需要机械臂，末工序的加工时长和驻留时长均不变。因此对任意有限 R 都有完工调度。检查程序还将原表移至原模型的无穷探测点 64010.375 秒，并从原始状态重放。

## 12 片：机械臂顺序与狭窄的取片窗口耦合

terminal-12-03 含 24 次搬运，使用健康腔时有 31104 种逐片目的腔组合（未计可行性）。源腔最迟取完时刻为 71.875–74.125 秒；末道加工后须在 0.875–3.375 秒内取完。一次错序可能让机械臂赶不上另一片的取完期限。5 秒 CP 可行性诊断固定同一个维修探测点 211296.375 秒，关闭目标函数。原模型、仅放松末道驻留、仅告知健康腔分配均返回 UNKNOWN。仅告知一份已验证见证中的机器人顺序得到可行解，同时给出顺序和腔分配只需 33 个分支。固定选择使用已知答案，只用于定位搜索困难。此实验表明这些选择影响本例的证明成本，不能把超时解释成某条约束导致物理不可行。

新控制器构造了一份 71 秒出完 12 片且没有触碰 F 的调度。W2、W3 的末道取完都只比期限早 0.125 秒。对照历史 12 片计划，W8 放入 F 时仍有其他片未完成，不能直接套用 8 片的末尾持片推论。各片的选腔、加工和搬运时刻、剩余余量均可在 [原始见证分析](../results/recovery/hard-case-policy/diagnosis/witness-analysis.json) 中复核。

## 控制策略和保证

1. 没有已知有限上界时，对处于不同源腔、各剩一个末工序的在制晶圆先尝试健康腔完工。按源截止或加工时长确定候选顺序，构造单片或两片交错的进腔/出片小段。所有时刻使用整数刻度。时间和候选构造只限制这条快速探测路径。探测失败继续原精确求解。
2. 拿到已验证但边界未知的方案后，再检查是否全程绕过 F，或只有最后一片在无持片期限的夹爪中等待 F。仅当满足对应条件时构造无穷见证。后缀 Simulator 和从故障快照起算的全程重放都必须通过。无穷边界下报告见证的完工时间，不主张该时间最优。
3. 两条策略对全部实例使用相同的结构条件，不读取实例名称、历史标签、归档答案或诊断时固定的顺序。

## 实验口径

逐例比较旧 LangGraph 与改进 LangGraph，两者使用同一求解器、同一硬件核、单求解线程和同一独立验证器。每种方法预留相同的 15% 返回开销。墙钟从求解 API 调用前开始，包括建模、框架和重放，迟到按 UNKNOWN 计。输入读盘与事后审计不计时。不同配对分四条物理核并发，同一配对的两个方法在同一核上依次执行。比较同期的配对结果；机器负载和框架冷启动会造成时限附近的波动。

两个预算均覆盖全部 120 个快照。1 秒组对每例做两对反序重复；30 秒组做一对，首次分类有差异的再反序复核。总体率只使用第一次的 120 对，避免重复加权难例。instances.csv 列出所有实例；consistent_gain/loss 表示两次反序重复中都出现同向的证明得失，variable 表示该得失未稳定复现。两个 UNKNOWN 还单独比较已验证下界和已证上界；同一有限边界下另列完工时间差。事后重新读入所有可行时间表做两层重放，核对历史与同期已证分类。

## 复现

在工作树根目录使用原恢复环境。以下输出写到新目录。Windows 测试机器上 2、4、6、8 为不同物理核的逻辑核编号；其他机器可省略 --cores 以串行运行。

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python -m wafer_sched.recovery.diagnose_hard hint --out results/local/hard-repeat
python -m wafer_sched.recovery.diagnose_hard constraints --out results/local/hard-repeat
python -m wafer_sched.recovery.diagnose_hard witness --out results/local/hard-repeat
python -m wafer_sched.recovery.policy_retest run --budget 30 --cores 2 4 6 8 --confirm-discordant --out results/local/hard-repeat/paired30
python -m wafer_sched.recovery.policy_retest audit --out results/local/hard-repeat/paired30
python -m wafer_sched.recovery.policy_retest run --budget 1 --cores 2 4 6 8 --out results/local/hard-repeat/paired1
python -m wafer_sched.recovery.policy_retest audit --out results/local/hard-repeat/paired1
python -m wafer_sched.recovery.confirm_regressions results/local/hard-repeat/paired30
python -m wafer_sched.recovery.confirm_regressions results/local/hard-repeat/paired1
python -m wafer_sched.recovery.evidence_cli agent results/recovery/evidence-study/inputs/terminal-12-03.json --budget 30 --out results/local/hard-repeat/twelve.json
python -m pytest tests/wafer_sched/test_unbounded_witness.py tests/wafer_sched/test_recovery_evidence.py -q
```
