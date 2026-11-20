# 故障可恢复性、维修边界与重调度

本地验收的五项交付可以从下表复核。

| 阶段 | 实现 | 验收数据 |
|---|---|---|
| 模型与独立整数规划 | [SCIP 参考模型](../src/wafer_sched/recovery/milp_reference.py) | [43 次固定维修查询](../results/recovery/evidence-study/validation/milp-vs-oracle.json)，CP-SAT 和 SCIP 全部相符。原语枚举 42 次一致，分数例立即修复时达到 250001 个状态返回 UNKNOWN。 |
| 直接最大化维修延迟 | [直接优化](../src/wafer_sched/recovery/direct.py) | [15 个状态的直接优化与二分核对](../results/recovery/evidence-study/validation/direct-vs-binary.json)，包括 3 个超出工艺范围的输入。 |
| 可核查冲突上界 | [生成与检查](../src/wafer_sched/recovery/conflict_evidence.py) | [带路线分支的证书](../results/recovery/evidence-study/validation/certificates.json)和[12 个样例的受控消融](../results/recovery/evidence-study/ablation/results.csv)。2 秒预算下，两种直接优化各证明 11 个。 |
| 扩大数据 | [生成器](../src/wafer_sched/recovery/study_data.py) | [120 份快照索引](../results/recovery/evidence-study/manifest.json)，每项包含来源及内容摘要值。 |
| 相同预算下对比 | [反馈策略](../src/wafer_sched/recovery/study_policy.py)与[对照运行器](../src/wafer_sched/recovery/evidence_study.py) | [1 秒逐次结果](../results/recovery/evidence-study/benchmark/results.csv)、[同实例配对审计](../results/recovery/evidence-study/benchmark/audit.json)、[30 秒重复实验](../results/recovery/evidence-study/matched30/results.csv)、[30 秒压力实验](../results/recovery/evidence-study/stress30/results.csv)。 |

1 秒预算、120 个快照下，二分、直接优化、普通脚本自适应、LangGraph 自适应分别准时完成 79、88、89、89 个确定分类。普通脚本与图各自单独证明 1 个快照，另有 88 个两者均证明。上述样本不足以支持框架带来普遍提速。[配对图](../results/recovery/evidence-study/benchmark/paired-results.svg)

30 秒压力复核另选 8 片、12 片的短预算难例及双品种路线对照。8 片例中，二分和直接优化均证明无有限边界，LangGraph 只验证了可至少等到 100.875 秒。12 片例的四种方法都未证明精确边界。Kim 路线派生例 kim-47 的四种方法均证明边界 447.875 秒及边界处最短完工 894.75 秒。这三例用于说明失败与成功机制，不能估计总体成功率。

设备为单臂、容量一的多腔设备，单一暂时故障，禁止新投片。输入为 v1.3 的 schema 2，包含物理历史、已承诺动作、各片路线、各腔工时、移动矩阵、驻留/持片限制与故障腔策略。先重放历史和已承诺的不可取消动作。记故障为时间零，后缀起点为 h，修复延迟 r 在后缀的剩余量为 q=max(0,r−h)。封闭等待和允许取出只用于已完工晶圆。加工中断的质量未知、未约定的执行中宏动作等仍返回 UNSUPPORTED。

## 完整模型

以下变量以同一精确整数刻度表示，以后缀起点为零。每片 w 的剩余搬运 i 包括最后一次出片。决策为目的腔 b_i∈A_i（末次为 OUT）、源 a_i（首项来自快照，以后等于前项目的）、机械臂全排列及各腔占用顺序、取始 u_i、取完 v_i、放始 s_i、放完 e_i。参数 P、L 为取放耗时，d 为满足有向三角不等式的空/载移动时间，p_ib 为所选腔的工时，D_i、H_i 为可选的驻留和持片上限。

1. v_i=u_i+P，s_i≥v_i+d(a_i,b_i)，e_i=s_i+L。初始已持片则其搬运排第一，u_i=v_i=0 只作后缀标记。
2. 机械臂从快照位置 z 出发，首项 u_i≥d(z,a_i)。每两个连续任务满足 u_j≥e_i+d(b_i,a_j)，从取到放期间独占机械臂。
3. 对同一晶圆连续两次搬运 i,j，加工完 c_i=e_i+p_ib，u_j≥c_i；若有期限，v_j≤c_i+D_i。快照中在制晶圆首项使用实际完工时刻（或仍在加工的 ready_at）C，u_i≥max(0,C)，v_i≤C+D。C 可为负。
4. 有持片期限则 e_i≤v_i+H_i；初始已持片改用历史真实取完时刻。占用加工腔的区间为 [s_i,v_j)，已有占腔则为 [0,v_first)。同腔所有区间两两不重叠。
5. 若 b_i 为故障腔，则 s_i≥q。封闭策略下故障腔已有晶圆的首次取片另有 u_i≥q。全部有效晶圆必须出片。允许等待。
6. F(x,r)=1 当且仅当以上约束有解。ρ*=sup{r≥0:F(x,r)=1}。先最大化维修延迟，再在已证有限边界处最小化 Cmax=max_w e_(w,OUT)。对外报告加回 h。立即无解、无穷和未知分别输出，无穷不定义“在无穷处”的最短完工时间。

固定腔选择及资源顺序后，只剩整数常数的差分约束。可行势函数可以由整数边权的最短路给出，因而有理输入按公分母缩放不会漏掉更优的分数边界。缩放上限及完整时域的推导见 [原证明](recovery.md)。B 为原模型证明的有限边界上界，直接优化使用 0≤q≤B+1 和对整个区间有效的时域。达到哨兵 B+1 即可判无穷。有限结果须有可重放的见证和已封闭的目标界。单次可行解不能替代最优证明。

## 独立整数规划

参考实现枚举小实例的候选腔组合，对每个组合用 SCIP 求解独立的整数线性模型。每一对搬运（以及每一对同腔占用）有独立的二元先后变量，约束采用有效大 M。所有活动时刻限制在 [0,T]，M=T+max(d) 足以松开机械臂排序约束。同臂即使两次搬运不相邻，有向三角不等式仍给出安全的空臂行程下界。T 从该分配的事件数量和差分常数保守构造。各分配得到的最小值取最小。任一分配未证明时只报告已验证可行或未知；输入规模超限另记。SCIP 使用浮点 LP 运算，交叉结果属于独立实现复核，不是任意精度的不可行证明。小例另用独立动作枚举和原 Simulator 检查。

对已固定目的腔的一对搬运 i,j，引入 y_ij∈{0,1}，加入

    u_j ≥ e_i + d(b_i,a_j) − M(1−y_ij)
    u_i ≥ e_j + d(b_j,a_i) − M y_ij

同腔区间 [a,b)、[c,d) 的次序 z 用 c≥b−T(1−z)、a≥d−Tz 表示。初始已持片占据后缀的第一项。每一项还有 u_i≥d(机械臂初始位置,a_i)，对任意次序均由三角不等式成立。对各工时精确转刻度后，参考模型取 T=(6N+3)(1+q+最大历史偏移绝对值+最大工时+最大期限+取时+放时+最大移动)，N 为搬运数。时间差图至多有 6N+3 个顶点，括号内支配任一约束的常数绝对值，简单路径给出完整时域。各个目的腔分配下 SCIP 最小化 Cmax。只要一个独立分配还未关闭，就不能用“其余分配无解”断言全局无解。

## 如何复现

在本工作树根目录运行，Python 使用 requirements-recovery.txt 的离线恢复环境。SCIP 随此版本 OR-Tools 的线性求解接口提供。已有环境只需把本工作树的 src 放在 PYTHONPATH 首位。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m wafer_sched.recovery.evidence_cli direct data/recovery-study/fractional-seed.json --out results/local/direct.json
python -m wafer_sched.recovery.evidence_cli check data/recovery-study/fractional-seed.json --certificate results/local/direct.json
python -m wafer_sched.recovery.evidence_cli milp data/recovery-study/fractional-seed.json --repair 9.3125
python -m wafer_sched.recovery.evidence_study all --budget 1 --out results/local/repeat
python -m wafer_sched.recovery.evidence_audit --out results/local/repeat
python -m wafer_sched.recovery.evidence_study benchmark --out results/local/repeat --budget 30 --label matched30 --repeats 2 --cases chain-00 kim-01 terminal-04-01 terminal-08-00
python -m wafer_sched.recovery.evidence_audit --out results/local/repeat --label matched30
python -m wafer_sched.recovery.evidence_study benchmark --out results/local/repeat --budget 30 --label stress30 --cases terminal-08-03 terminal-12-03 kim-47
python -m wafer_sched.recovery.evidence_audit --out results/local/repeat --label stress30
python -m wafer_sched.recovery.evidence_ablation --out results/local/repeat --budget 2
python -m wafer_sched.recovery.evidence_plot --folder results/local/repeat/benchmark
python -m pytest tests/wafer_sched/test_recovery.py tests/wafer_sched/test_continuation.py tests/wafer_sched/test_recovery_evidence.py -q
```

generate、validate、benchmark 可分别运行。归档输入、逐次运行、交叉验证和对应机器上的墙钟耗时保存在 results/recovery/evidence-study。复跑使用独立输出目录。相同输入、精确边界和已证目标可核对，时限内能否返回以及具体耗时会受机器负载影响。

单个输入可用 evidence_cli 的 binary、direct、milp、plain、agent、check 入口。plain 和 agent 运行同一策略。返回 UNKNOWN 时检查 verified_feasible_lower_seconds 和 finite_upper_seconds；makespan_optimal 描述已验证方案对应维修时刻的完工目标。

## 可核查的必要上界

单片也可留下证据。封闭腔最晚取完为 D 时，有 q+P≤D。若某片下一站必须是故障腔，最迟取完 D 且持片上限 H，则 q+L≤D+H。两条条件对其他同时在制晶圆数不作限制。

联合判据处理末工序前手中片 K、源腔 S 中另一片 J，源片最晚取完 D。遍历两片的每一对候选目的腔。若 K 去故障腔 F，则 q+L+d(F,S)+P≤D。若 K 去健康腔 A，先核对即使用最短移动，K 也无法在 D 前加工完。此时 J 取出后不能放回仍由 K 占用的 A。若 J 必须放 F，K 最迟放完为 D−d(A,S)−P，其最迟取完为该值加 p_KA+D_K。机械臂放 J 再取 K 至少需 L+d(F,A)+P，得到对 q 的上界。存在无法排除的其他合法去向时，联合判据直接放弃。各可行分支上界取最大，可与其他必要界取最小。原始数据、路线覆盖及不等式可用 check 命令重新核算。命中上界仍需合法见证才能证明紧性。

## 数据来源与对照口径

数据包含 60 个异构末工序竞争、48 个双品种六腔路线、12 个取片中故障实例。双品种路线与 10–300 秒加工时间范围来自 [Kim 与 Kim 的公开单臂实验](https://github.com/yeoneee/ClusterToolSchedulingRL/blob/6a03fb457e86a1bb7423bad47b8868df23d7471d/single_arm_cluster_tool/concurrent_flow/notebook.ipynb)。路线为 PM1→PM2→PM3、PM4→PM5→PM6。本项目独立生成具体工时、转运历史、维修、驻留和持片条件；全部快照均为仿真生成。三族分开报告；论文路线族用于检查换路线后的表现。每个输入附种子、WIP、剩余搬运数、来源和 SHA-256。

每个算例分别运行原二分、直接优化、普通 Python 自适应流程、LangGraph 运行的同一自适应流程。后二者使用同一份决策代码。从已验证上界开始试探（无证书则测试立即修复），根据回报停止、切换到最大维修延迟并传递已重放的提示，或继续最小化边界处完工时间。全部方法离线、单线程，顺序按固定种子打乱。每次预留相同 15% 总预算用于返回和重放，计时从公开求解调用前开始，包括建模和框架调用，不含导入、JSON 磁盘读写和事后独立审计。严格按墙钟截止评分，迟到的返回保留原始数据但计 UNKNOWN。首次见证延迟指首次通过共同后缀 Simulator 的时刻。一个未完成搜索可以有合法见证。区间宽度只在有上下界时统计；无穷和没有上界的情形不当作零误差。30 秒复测的四个固定快照各运行两遍，单独出表。
