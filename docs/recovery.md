# 故障恢复：适用范围、命令与精确性

代码位于 `src/wafer_sched/recovery/`。这是在原 Simulator、OR-Tools CP-SAT、
SkillRegistry、CFAR FeedbackEvaluator 上新增的独立模块。原物理核心、PPO、历史结果均不改动。

## 安装与演示

Python 3.11+；在仓库根目录，PowerShell：

```powershell
python -m venv .venv-recovery
.venv-recovery/Scripts/python.exe -m pip install -r requirements-recovery.txt
.venv-recovery/Scripts/python.exe -m pip install --no-deps -e .
.venv-recovery/Scripts/python.exe -m wafer_sched.recovery demo
```

这是独立精简运行环境；`--no-deps` 是为了不安装本次不调用的历史 PPO/Torch 依赖。
复现整个历史项目则使用 `pip install -e ".[langgraph]"`，需要完整原依赖。
默认不读取 `.env`，无 LLM 网络调用、无训练。CLI 也提供 `wafer-recovery` 入口。

已有项目环境可直接一条命令：

```powershell
.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery demo
```

默认演示实际生成历史：3 片先在各自源腔加工完，故障时刻为绝对时间 7 秒。
2 个健康目标腔加 1 个空故障腔，源腔剩余期限 D=6、末工序 p=10、完成后驻留 δ=1。
预期：最迟修复延迟 12 秒（绝对时间 19 秒），边界处最短剩余完工时间 25 秒。
维修延迟 13 秒不可恢复。维修时间均指“恢复到可开始放片”的时刻。

```powershell
python -m wafer_sched.recovery solve --repair 13
python -m wafer_sched.recovery boundary --joint
python -m wafer_sched.recovery agent --input path/to/input.json
python -m wafer_sched.recovery benchmark
python -m pytest tests/wafer_sched/test_recovery.py -q
```

默认输出 `results/recovery/<UTC时间>-<随机后缀>/`。指定 `--output` 必须是新目录；
重用目录会报错，不覆盖结果。每次查询保存输入关联的结果、CP-SAT 模型文本、求解日志、
原 Simulator 事件日志及独立验证结论。JSON/CSV 不用 Infinity/NaN：无穷边界通过状态表示。

## 准确支持的物理语义

- 单机械臂、单夹爪、单位容量腔室、有限已投片 WIP、固定剩余路线与候选腔。
- 一个**空腔**在快照时失效，修复后永久可用。健康腔可正在加工或加工完成后被占用。
- 快照在机械臂动作边界：空闲空手，或取片完成后空闲持片；携片须补充真实 `carrying_since`。
- 已完成工序记录、原转运记录、正在加工的结束事件原样保留；剩余加工不重新计时。
- 多道剩余工序、不同加工时间/驻留期限、可选腔、同腔再加工、方向相关移动均可建模。
- 移动时间必须满足有向三角不等式。否则拒绝输入，避免直接路径建模漏掉更快的中间移动。
- 取放时间严格为正。用原 `pick / move / place` 重放；允许持片等待、提前空臂移动、空闲等待。
  健康腔从放片**开始**到下次取片**完成**独占，不在上游取片时过早预留。
- 硬驻留：`PickComplete - ProcessComplete <= δ`。取片开始前加工必须已完成。
  另可指定 `PlaceComplete - PickComplete <= Γ`；`null` 表示无此限制，不能混同驻留。
- 输入是已确认有效的晶圆；历史工艺质量有效性来自输入，不由调度器判定。
  每片必须完成全部余下工序并送 OUT，不允许提前退出、丢片或以回料代替完成。

输入 `RecoveryProblem.to_dict()`：设备配置、完整 Simulator.snapshot()、故障腔、
每片每工序的 `residency` 数组，以及每片每次转运的 `holding` 数组。
`schema_version=1`；详细实例可直接使用演示生成的 `input.json`。

不支持：故障腔内有片的质量/中断恢复、机器人动作中途故障、未执行完的承诺动作/预留、
第二次故障、新投片、不确定工时、跨设备、限制后的原语动作子集。均明确拒绝或不在输入范围内。
因此不能称为任意真实故障状态的通用控制器。求解发生在冻结快照上，未计入设备在线等待求解的时间。

## 边界状态与时间精度

`OPTIMAL/FEASIBLE/INFEASIBLE/UNKNOWN` 是单次 CP 查询状态。可行解必须通过原 Simulator
及新增驻留/携片校验；失败为 `VERIFICATION_FAILED`，不能作为可行下界。
只求可行性时 `OPTIMAL` 仅说明可行性问题求完，`makespan_optimal=false`。

边界状态：`FINITE`、`UNBOUNDED`、`INFEASIBLE_AT_ZERO`、`UNKNOWN`。
有限边界 0 与即刻修复也不可行严格区分。UNKNOWN 不移动不可行上界，返回已有可行下界、
已证不可行上界及已验证方案。有限边界输出延迟与绝对时间。无穷边界可能来自绕过故障腔，
也可能来自允许无限持片等待；后者仍要求所有晶圆最终完成，不能凭“必须使用故障腔”断定边界有限。

所有十进制输入精确转整数刻度，不四舍五入；最高 10000 ticks/s，超过则拒绝。
维修查询也必须处于同一精确刻度。对于此模型，固定腔分配、机器人顺序、腔占用顺序后，
全部时间约束是整数常数的差分约束；若连续时间可行，存在整数刻度解。
有限修复最大值也在该刻度上。因此求得的是该确定性有理输入模型的连续时间精确边界，
不是把任意实数系统粗采样后的近似。改变计时端点/物理规则需重新证明，不能套用这一保证。

## 有限上界和无穷检测依据

修复越早只增加可用时间，原计划仍可等待执行，故可行性对修复延迟单调不增。
不含自动触发加工、强制立即使用修复腔、后续故障等会破坏这一前提的机制。

固定完整离散决策后，以时间点为顶点，约束 `t_v-t_u<=c` 是边 u→v。
修复限制 `load_start>=r` 添加边 load_start→0，权 -r。
所有新边都指向同一个原点，一个简单环最多含一条此类边。基础图无负环时，
对该决策，可行 iff `r <= min_v dist(0,v)`；没有有限路径时无上界。

若时间点至多 V 个，基础边常数绝对值至多 C，任何有限最短路有至多 V-1 条边，
有限边界 <= VC。这里 V=5T+1（T 为剩余转运数），C 使用全部相关常数绝对值的和加1，
刻意宽松但完整。所有腔分配及资源次序只有有限种，故全局若有有限边界，也 <= B=VC。
在 B+1 tick 可行即证明至少一个离散决策允许任意迟修复；不只是“搜索截止前还可行”。
固定 r 的完整求解时域取 `V*(C+r+1)`：去掉正环的下界最长简单路构造可行时间点，
无需超过此值。代码拒绝超出安全整数范围，不使用会截掉可行解的用户自定短时域。

这是本模块的标准差分约束推论，不作为已确认的新颖定理宣传。

## 联合资源必要条件与对称公式

安全剪枝只在 `bounds.py` 检查全部条件后启用：所有片在不同源腔已完成上一工序；
每片只剩一道末工序；共享 m 个空健康目标腔及一个空故障腔；无其它目标；
取、放各1秒，移动0秒；源片最迟取完时间 d_i>0，D=max d_i；
每片在所有目标上加工时长相同为 p_i>=D；末工序 δ_i>=1。

若 r>D，则 D 前所有源片已被取出、所有末工序尚未完成。
健康腔加夹爪仅有 m+1 个槽位；n>m+1 时 r<=D 是必要条件。
n=m+1 时，设 j 是 D 时夹爪中那片，先放入 F 才能释放机械臂。
每个健康腔装片完成 z_i<=d_j-1，截止时间 <=d_j-1+p_i+δ_i。
F 放完时 v>=r+1；完成 k 个健康腔取片至少需 2k-1 秒，因每两次取片间必须卸片。
将除 j 外的 q_i=p_i+δ_i 升序排列，有：

`r <= U_j = min_k(d_j-1+q_(k)^(-j)-2k)`；全局 `r <= max(D,max_j U_j)`。

这是必要条件，不宣称一般充分；未命中条件则完全回退基础 CP-SAT。有限 Γ 只会缩小可行集，
上述必要界仍安全。排序仅用于证明的放松截止，不强制删去其它调度顺序。

对称条件 n=m+1、d_i=D>=2m+1、p_i=p>=D、δ_i=δ>=1，且无持片上限：
`rho*=D+p+δ-2m-1`。上界由 k=m 得到。可达构造：健康腔 k 的放完时刻
`z_k=D-1-2(m-k)`，先取再放连续执行；最后一片于 [D-1,D] 取出；
F 于 [rho*,rho*+1] 放入，记 v=rho*+1；健康腔 k 于 [v+2k-2,v+2k-1] 取出再卸片。
取完时恰为 z_k+p+δ，且取片开始不早于加工完。最后卸 F 即完成。
该式依赖 PickComplete 端点，不可直接替换成文献的 PickStart 约定。
独立逐 tick 枚举器不调用此式、剪枝器或 CP 模型，并核验小例的边界两侧及全部中间维修时刻。

## 离线 Agent 与实验解释

图为 plan → execute → feedback → plan。通过已有 ResearchPlanningSkill 与 SkillRegistry
执行恢复 Skill，以 CFAR FeedbackEvaluator 保留同一状态、同一维修时刻的更优合法方案。
UNKNOWN 增加当前查询预算；可行/不可行分别更新边界；证实边界后转最短完工时间优化。
相同查询与相同预算不重复；耗尽预算保留已验证方案。轨迹保存每次提议、上次状态、
实际求解状态、预算、CFAR 接受结果和 Skill 耗时。该模式是确定性自主数值闭环，**不是真实 LLM 决策**。
未调用已有 PPO：旧环境明确不支持故障/硬驻留，强行调用会造成不公平比较。

固定9类实例 × 3方法：相同恢复模型的基础 CP-SAT、加联合必要界、离线 LangGraph。
历史静态 CP-SAT 不支持这些输入，明确标记不适用，不伪装成可比基线。
另记录 UNKNOWN 提升预算与预算耗尽的真实执行。输出数值为实际工具统计，branches 是 CP-SAT
分支数，不冒称所有搜索节点。耗时包含模型构建/重放/落盘，分别另记求解器时间。
总预算约束求解分配；构建与重放不可中断，故不是硬实时墙钟保证。
一次固定种子的合成实验不能证明普遍算法优势或工业实时性。
