# 末道工序的搬运顺序与维修边界

沿用故障后暂停投片、完成全部有效在制晶圆的目标。输入、工艺语义和时钟均沿用[上一版末道模型](terminal-proofs.md)。以下是整数刻度上的判据。三个归档实例均为每秒 8 刻度。

## 紧前缀为什么能排除“只剩一片”

把一次取、移、放称为一笔搬运，按先后从 0 编号。设取片、放片、移动分别用 $P,L,d$ 个刻度，$s=P+L+2d$。相邻两次取片至少隔 $s$。源腔、末道腔角色分离，末道加工时间至少为 $d$，因此同址接续取片也满足这个间隔。允许装片后持片等待，所有原候选腔保留。

设 W0 必须进入故障腔，源腔取完期限为 $D_0$。在上一版已证明的晚修分支，W0 最后从源腔取出，其余 $n-1$ 片在此之前只能使用健康末道腔。如有 $k$ 片已经放入而尚未取出，W0 的取片编号恰为 $t=2(n-1)-k$。令 $f$ 为首笔取片开始时间的安全下界，此前所有等待与额外持片的总和至多为 $E=D_0-P-f-ts$。

若晶圆在 W0 之前就完成了一进一出，设这两笔编号相差 $g$。把放片结束到下一次取片开始的工艺约束移项，可得一个必要的整数区间相交条件：

$$
[gs,gs+E]\;\cap\;[P+d+L+p,\ d+L+p+\delta]\ne\varnothing .
$$

$p$ 是选定健康腔的加工时间，$\delta$ 是这一片的末道驻留上限。对一片晶圆，若所有健康候选和所有 $1\le g<t$ 都无法相交，该片就必须留到 W0 之后。若必须留下的片数大于 $k$，该分支无解。此判据允许前缀里任意分配等待时间。

## 多片共同等待时的次序

给尚未取出的每一片分别指定两个编号：从最后往前数的放完次序 $i$，以及从最先往后数的取完次序 $j$。二者均从 0 开始。设维修延迟为 $q$，必须满足

$$
q \le D_0-2P-2d-L+p+\delta-(i+j)s .
$$

原因是这一片最晚在 W0 取片开始前 $d+is$ 放完，而取完不早于 $q+L+d+P+js$。每个次序只能用一次，晶圆和同时占用的腔室也必须互异。代码对两片穷尽次序与腔室；对三、四片检查四类互异条件能否同时成立。大于四片时保留安全的驻留总量上界。各个 $k$ 分支取最大值，并计入较早维修的分支。

## 用最后一次源腔取片划分全部调度

即使 W0 并非最后取片，最后一次源腔取片仍有确定编号 $t$。共有 $m$ 个可用末道腔，这片放入后须同时容纳 $k+1$ 片。由容量、初始位置及最大源期限 $D$ 得

$$
\max(n-1,2(n-1)-(m-1))\le t\le
\min(2n-2,\lfloor(D-P-f)/s\rfloor).
$$

对每个可能的 $t$ 单独建完整 CP-SAT 子模型。每片恰好选一个“进腔编号、出腔编号、腔室”组合；每个搬运编号恰好用一次；同一腔室持有晶圆的编号区间互斥。每个编号各有独立取片开始和放片开始时刻。这两个时刻保留原加工、取片完成期限、持片、移动及维修约束。最后一次源腔取片之后只可出片。去出口时提前放片能释放机械臂，可令出片搬运只用其最短时间。按编号还原即可得到原模型的合法时间表。固定边界时，再在所有仍可能达到边界的分支上最小化完工时间。任何限时未关闭的分支均保留其上界。

## 跨工序期限传递

当某片的故障腔位于后续必经工序时，若当前取完期限为 $D$、送往下一道的持片上限为 $H$，则下一道的取完期限至多为 $D+H+p_{\max}+\delta$。对必经故障腔的最后一笔，放片开始至多为 $D+H-L$。缺少有限持片或驻留上限时，停止传递。该上界只有被完整设备的一份合法方案达到，才能宣告为精确边界。

## 复现

从本工作树根目录运行，激活原项目虚拟环境。每次配对实验使用新的输出目录。命令中的 2、4、6、8 是归档 Windows 主机的 CPU 编号。求解器均为单线程，预算含建模和重放。

~~~powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python -m wafer_sched.recovery.policy_retest run --ranked --budget 1 --cores 2 4 6 8 --out results/local/tail/paired1
python -m wafer_sched.recovery.policy_retest audit --out results/local/tail/paired1
python -m wafer_sched.recovery.policy_retest run --ranked --budget 30 --cores 2 4 6 8 --confirm-discordant --out results/local/tail/paired30
python -m wafer_sched.recovery.policy_retest audit --out results/local/tail/paired30
python -m wafer_sched.recovery.confirm_regressions results/local/tail/paired30
python -m wafer_sched.recovery.confirm_regressions results/local/tail/paired1
python -m wafer_sched.recovery.rank_review profile --out results/local/tail
python -m wafer_sched.recovery.rank_review proofs --seconds 60 --out results/local/tail
python -m wafer_sched.recovery.rank_review compare --out results/local/tail
python -m pytest tests/wafer_sched/test_tail_ranks.py -q
~~~

要复查已归档的下一刻度，不需要重新跑 120 例。执行以下命令即可校验模型 SHA-256，并直接把保存的模型交给 CP-SAT：

~~~powershell
python -m wafer_sched.recovery.rank_review recheck --seconds 60
~~~

[逐例结果与调度文件](../results/recovery/tail-ranks/README.md)
