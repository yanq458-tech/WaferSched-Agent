# 末道工序快照的恢复判定

研究对象仍为单臂设备暂时单腔故障后的全片恢复与最迟维修延迟。此处在原始故障前缀执行完毕后才选择求解模型。全部时间式使用后缀的整数刻度，对外时间还要加上前缀偏移。

## 专用模型的适用条件

机械臂空闲且空手，每片在制晶圆在独占的源腔中，剩余路线恰有一道加工和一次出片。所有候选末道腔初始为空，与源腔集合不相交。故障腔为空。相关位置之间的非对角移动时间统一为 $d$，同址移动为零。候选加工时间至少为 $d$。实现仍保留故障腔作为合法候选，实际工艺决定每片可用的腔。新策略对至少四片且通过适用性检查的后缀启用专用分支。其它输入沿用通用模型。

## 可手算的冲突

令 $P,L$ 为取片、放片时间。连续两次搬运之间至少间隔 $d$。下一次取片若恰好在刚放下晶圆的同一个位置，只可能是再取出刚放下的同一片，此时须先加工，因而该间隔仍然成立。一次完整搬运加上到下一次取片的间隔至少为 $s=P+L+2d$。

取一个源腔取完期限 $D$，共有 $n$ 片须在该时刻前取完。最后一片开始取时，这一组已有至少 $n-1$ 片进过末道腔。这些片合计只可用 $m$ 个末道腔，故其中至少 $k=\max(0,n-1-m)$ 片已经出腔并放到出口。于是最后一次取完至少要等到

```text
(n−1+k) × (P+L+2d) + P
```

严格大于 $D$ 即证立即修复仍不可行。式中初始机械臂就位耗时取零，以保证下界安全。对按期限划分的各个前缀都可检查此证书。复核入口为 `terminal_exact.verify_workload`。

## 横跨最后一次源腔取片的驻留总量

设最后一片从源腔开始取片的时刻为 $a$。其余 $N=n-1$ 片都已送入过末道腔。设全部源期限的最大值为 $D$，设备初始位置和各源加工完成时刻给出的首笔搬运开始下界为 $t_0$。在 $a$ 之前完整搬运次数至多为 $M=\lfloor(D-P-t_0)/s\rfloor$。若有 $k=2N-M>0$，至少有 $k$ 片已放入末道腔、尚未取出。

任选这 $k$ 片，按末道放完时间从晚到早排序，逐项上界为 $a-d, a-d-s,\ldots$。再按末道取完时间从早到晚排序。机械臂必须先把最后一片从源腔取出并放好，因此这些取完时间的下界为 $a+s+P,a+s+P+s,\ldots$。两列分别求和再相减，时刻 $a$ 消去。这 $k$ 片从放完到取完的时长合计至少为 $k(ks+P+d)$。另一方面，每片可用时长最多是其最长候选加工时间加末道驻留上限，取全体中最大的 $k$ 项求和即可得安全上界。所需总量严格大于可用总量，立即修复也无解。上下界相等时不作删除。该证书允许任意合法选腔和取放顺序，复核器 `verify_pending` 从输入独立重算两列时间和。

## 必经故障腔的维修上界

设晶圆 $i$ 的末道只能去故障腔，其源腔取完期限为 $D_i$。若它后面还有其它源腔取片，则维修时刻 $q$ 至多为其它源期限的最大值减 $L+d+P$。设置分界值 $T=\max(D_i,\max_{j\ne i} D_j-L-d-P)$。若 $q>T$，晶圆 $i$ 必然最后从源腔取出，且这以前放下的所有晶圆都只能使用健康末道腔。

设其它晶圆共 $N$ 片，第一笔搬运最早允许开始时间的下界为 $t_0$。在取出 $i$ 前最多完成 $M=\lfloor(D_i-P-t_0)/s\rfloor$ 笔搬运。至少 $k=\max(0,2N-M)$ 片仍在末道腔。如果它们超过健康腔数量，该分支不可能。否则取其中 $k>0$ 片，其放完时刻最晚为 $D_i-P-d$，任意两个放完时刻相距至少 $s$（后一次搬运的最短耗时加间隔）。它们的取完时刻最早为 $q+L+d+P$，相邻的取完时刻同样相距至少 $s$。这 $k$ 片的“放完到取完”总可用时长，至多是各片最大健康加工时间加驻留上限中最大的 $k$ 项之和 $A_k$。两边求和，消去排序，得到

```text
q ≤ D_i − 2P − 2d − L + floor(A_k/k) − (k−1)s   （仅 q > T 分支）
```

与 $T$ 取最大值，得到全局上界。它可以排除过晚的修复时间，是否可达到还要找合法方案。具体分支、整数刻度和界见 certificates.json。

## 等价建模和求解保证

每片选一个合法末道腔。三个主要变量分别为源腔取片开始 $a$、末道放片开始 $b$、末道取片开始 $c$。加工开始于 $b+L$。末道腔从 $b$ 至 $c+P$ 独占。取放、加工、源与末道驻留、持片上限、初始位置和维修门限都保留。机械臂两个互斥区间为

```text
[a, b+L+d)        [c, c+P+d+L+d)
```

第二个区间采用取出后最早放到出口的时刻。出口无限容量，提前放下只会释放夹爪，也不会加重持片约束。任一通用模型方案都可作此规范化，末片完工时间不会增大。反向把区间按开始时间排序，间隔足以实际空移，装片移动、等待和各次加工均可按原语执行。于是两模型在上述子类内有相同的可行维修时刻和最短完工时间。程序在完整安全时域内直接最大化维修延迟，有限边界处再固定延迟最小化完工时间。每份见证都经过后缀和完整故障轨迹重放。UNKNOWN 保留可核查上下界，在严格墙钟预算之后才返回的结论单列为逾时。

## 反馈如何改变下一次调用

若必经腔上界降至分界值 $T$，先用可分配时间的 30% 直接最大化维修延迟。已得到可行解时保留其下界，再继续搜索。若这一轮仍无见证，切换到固定 $q=0$ 的纯可行性问题，恢复全部原始期限，关闭两条算术剪枝。证明立即修复无解即可排除所有更晚的修复；只找到零点见证时，仅能报告可行下界。这个切换由实例结构和本次求解反馈触发。专用模型在不足一秒的内部预算下为见证提取和重放另留时间。两种策略的外部墙钟门槛相同。

## 复现

在本工作树根目录激活已有项目环境，PowerShell 中执行以下命令。对比输出目录必须是新的。四条并行测量通道分别绑定 CPU 2、4、6、8，同一对新旧策略在同一个核上顺序运行。精确优化使用单求解线程和种子 0。单独的约束消融及零点诊断使用种子 1，耗时和结论不计入配对成绩。

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python -m wafer_sched.recovery.policy_retest run --refined --budget 1 --cores 2 4 6 8 --out results/local/recheck/paired1
python -m wafer_sched.recovery.policy_retest audit --out results/local/recheck/paired1
python -m wafer_sched.recovery.policy_retest run --refined --budget 30 --cores 2 4 6 8 --confirm-discordant --out results/local/recheck/paired30
python -m wafer_sched.recovery.policy_retest audit --out results/local/recheck/paired30
python -m wafer_sched.recovery.confirm_regressions results/local/recheck/paired30
python -m wafer_sched.recovery.terminal_diagnostics profile --out results/local/recheck
python -m wafer_sched.recovery.terminal_diagnostics relax --out results/local/recheck
python -m wafer_sched.recovery.terminal_diagnostics zero --seconds 25.5 --out results/local/recheck
python -m wafer_sched.recovery.terminal_diagnostics summarize --out results/local/recheck
python -m pytest tests/wafer_sched/test_terminal_exact.py -q
```

[120 例配对复测与诊断数据](../results/recovery/terminal-proofs/)
