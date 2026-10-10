# 第六阶段：CFAR约束反馈研究闭环

日期：2026-10-10。当前Windows研究环境真实执行；以下数据来自已提交实验记录，而非理论预期。

## 1. 完成范围与主要结论

在原设备仿真、规则策略、CP-SAT与预训练MaskablePPO上新增研究层，实际调用七个Skill、Semantica记忆/图上下文和平台任务执行器。正式134次实验，其中132次完整合法，2次CP `UNKNOWN`无计划，均被拒绝；另保留8轮暂停/恢复冒烟运行。没有重新训练或覆盖模型，没有改变铁路业务或原数值求解器。

CFAR在开发F/G的三个求解种子上均完成至少五轮真实反馈决策。与固定顺序相比，最终最佳Makespan相同，平均较早找到最佳方案，但整个研究流程耗时更长。新封存场景上的冻结输出策略出现退化/无解。本阶段支持“闭环能执行、约束拒绝可靠、实验可追溯”，**不支持CFAR整体优于固定流程的结论**。

两个规划模式均已实现。真实LLM配置不可用且研究外发默认关闭，只有确定性规划、固定流程及明确标记的LLM回退运行；单元测试里的注入接口不构成真实LLM研究效果证据。

## 2. 文件与既有接口

事前审计：[wafer_sched_stage6_agent_audit.md](wafer_sched_stage6_agent_audit.md)。保存2474个原有文件哈希：[保护基线](wafer_sched_stage6_preservation.json)。

| 新增路径 | 实现 |
| --- | --- |
| `src/wafer_sched/agent/schemas.py` | 严格ExperimentProposal、配置哈希、候选/预算/历史引用校验 |
| `skills.py` | 七个实际Skill及调用日志；直接调用原规则、CP和RL接口 |
| `planner.py` | 反馈规划、CP预算规划、固定顺序消融、受限LLM提案与回退 |
| `feedback.py` | 完成/约束优先的字典序接受器，保留当前最佳合法记录 |
| `research_memory.py` | 原子逐轮JSON、JSONL/CSV、真实Semantica存取与图关系、边界恢复 |
| `experiment_runner.py`、`worker.py` | 原平台独立有限队列，固定Python子进程、实验硬截止、失败记录 |
| `evaluation.py`、`reporting.py`、`cli.py` | 对照试验、封存/冻结/一次评价、图表与研究入口 |
| `_semantica/` | 12个未修改Semantica源码模块、3个轻量命名空间初始化文件、MIT许可证、逐文件来源SHA与说明 |
| `configs/wafer_sched/agent/` | 开发研究配置、两个新测试设备、封存哈希 |
| `experiments/wafer_sched/*stage6*.py` | 首次保护/源码提取、场景声明、运行、独立验收、自动汇总、图表布局修正及元数据补充检验 |
| `tests/wafer_sched/test_agent.py` | 28项新增验收（含参数化案例） |
| `requirements-wafer-agent.txt`、`requirements-wafer-agent.lock.txt` | 第六阶段直接依赖与39包实际环境锁 |
| `results/wafer_sched/stage6/` | 真实实验、完整事件/决策、验证、配置、图表及检查证据 |

本阶段增量修改README和`.gitignore`，后者忽略新增测试临时目录并允许保留第六阶段真实CP日志。原Simulator、规则、CP、MDP/PPO实现、既有测试、前五阶段结果和模型均未更改；与本任务开始时已有的未提交更改区分，不把它们计入第六阶段实现。

Semantica使用实际`AgentMemory.store/retrieve/save`与`ContextGraph.add_node/add_edge/get_neighbors/to_dict`。每次提案前检索场景摘要，检查与权威JSON指标一致，再构造可见历史。图边记录场景评价、Skill调用和历史反馈依赖。研究队列调用`WorkspaceRunScheduler.submit`，持久化调用`atomic_record`/`durable_replace`；不使用在线铁路租约或业务数据库。

完整Semantica未安装到研究环境。源码子集来自本项目现存vendor，不重写记忆实现；完整KG/RAG能力不在此子集内。旧vendor没有独立Git元数据，不能证明与原锁文件上游提交完全相同；精确复现以交付[PROVENANCE.json](../src/wafer_sched/agent/_semantica/PROVENANCE.json)中的实际SHA为准，[MIT许可证](../src/wafer_sched/agent/_semantica/LICENSE)保留原版权。不是对整个平台许可证作新的授权声明。

## 3. 数学方法和统一Skill边界

研究状态为`H_k=(设备配置、已提交候选、验证、接受记录、剩余预算)`；实验提案`p_k=Planner(H_k)`，数值Skill产生真实计划/轨迹，原Simulator验证后得到`v_k`，接受器更新incumbent。研究层不修改设备状态，不生成加工完成时间，不替代调度Policy。

ExperimentProposal必须恰含：experiment_id、scenario_id、proposed_method、parameters、expected_reason、evidence_from_history、estimated_budget、selection_reason。方法仅`rule/cpsat/rl`；参数分别只允许`policy/max_seconds/model_id`。禁止未知字段、路径式ID、不存在的历史证据、重复参数、白名单外预算/模型；RL只从只读模型目录映射加载。Schema不能接受Python、Shell或训练操作。

七个Skill对应分析、规则执行、CP执行、RL执行、统一验证、结果分析和下一轮规划。验证使用原合法动作检查、事件推进、状态检查及独立重放；计划CP预测还使用原`validate_solution`逐项比较。没有实现新增RL训练、场景自动生成或任意工具扩展；这些操作不会被注册为空功能。

反馈接受按以下顺序：

1. 必须完成全部晶圆，否则拒绝。
2. 必须状态合法、独立重放一致、无动作违反/死锁；CP预测与原事件不一致也拒绝。
3. 与incumbent配置哈希和观察窗口一致，比较Makespan；不同配置/窗口不直接比较。
4. Makespan在1e-7秒内相同时，仅真实墙钟成本更小才替换；同样成本/更差性能保持incumbent。

每轮记录verified、improves_incumbent、lower_cost、accepted与明确原因。约束验证是必要条件，不是较好的结果能够抵偿约束违反的加权目标。本阶段未实现Pareto档案。

## 4. 反馈规划的具体依据

ProblemAnalysis计算已知路线的名义最短负载：每阶段最短加工时长除以可选腔室数分摊；这只是分析近似，异构腔室不被当作完全可替代资源。当前输出还显式列举可调用方法/参数，依据已有CP状态建议下一未试预算和实验开销估计，已验证最优则不再建议证明预算，最终仍由规划器作剩余预算准入。真实反馈量包括：

`b = 总阻塞秒 / 总实际加工秒`，`u = 机器人动作秒 / Makespan`。

DeterministicPlanner以FIFO建立基准；首个针对性规则在`b>=0.2`时选瓶颈规则，否则考虑SPT/ECT。随后在已有规则记录基础上试兼容的验证集选模RL；以当前已验证incumbent作为CP hint，先用较小预算。CP `UNKNOWN`或相对gap>0.01且预算允许时，考虑下一更大预算；连续两次CP没有Makespan改善时，优先测试未用的RL种子/廉价规则。候选是否已经运行也是历史约束，禁止重复调用同方法同参数。

这些探索不是最优采样算法：后续未试RL种子的顺序来自固定只读模型目录；触发探索的依据是CP停滞与历史已尝试集合。阻塞比例阈值同样是事前启发式，不保证选出的规则改进。单元测试在相同轮数、相同合法基准下改变阻塞反馈，实际使下一提案从SPT变为bottleneck；最优证明和无解状态也产生不同的停止/预算决策。

CPBudgetPlanner单独研究预算：FIFO基准后尝试1秒，根据CP状态/gap、下界、incumbent改善与剩余预算升级到3/10/30秒；已验证OPTIMAL即停止，连续两次CP目标和下界都未改善则停止。因此不会预先运行全部预算。固定预算控制组则分别用FIFO初始化，再独立调用一个指定预算。

LLM规划器复用`model_transport.model_completion`和平台端点校验。需要显式研究外发设置及环境变量，JSON候选再次经过同一Schema/上下文校验，失败只记类型并回退。记录actual_planner；回退不计为LLM规划证据。没有发送本轮研究数据到外部模型。

## 5. 设备、预算和数据划分

| 场景 | 晶圆/腔室/工序 | 取/默认移动/放(s) | 已知工艺时间(s) | 公共窗口(s) |
| --- | --- | --- | --- | --- |
| 开发F | 4/3/2 | 1/1/1 | CLEAN c_x=2,c_y=13；ALT反向13,2；RINSE均7 | 250 |
| 开发G | 4/3/3 | 2/3/2 | CLEAN 10,18；RINSE 20,8；DRY 4,14；固定阶段顺序 | 400 |
| 封存U_recipe_mix | 5/3/2 | 1/2/1 | CLEAN 4,15；ALT 12,3；RINSE 10,6 | 500 |
| 封存U_slow_transport | 6/3/3 | 3/4/2 | CLEAN 11,19；RINSE 21,7；DRY 6,12 | 800 |

全部晶圆0秒释放，单片机器人/容量1/无中间缓冲，原事件时长与资源保留语义不变。新设备在开发实验前声明并保存字节哈希，物理参数/任务与训练、验证及旧测试不同。H和第五阶段T系列属于已使用评估场景，未伪装为本阶段新封存测试。

候选集：五规则；CP预算1/3/10/30秒；第五阶段medium种子0/7/13的best.zip。开发固定流程与CFAR均使用相同候选集、80秒总上限、40秒单实验硬截止、最多8轮/4096调度步。CP单线程、求解种子0/7/13；设备静态，这些是搜索种子，不是随机故障样本。RL加载为CPU确定性Policy，不新增训练。

总预算包括启动、规划、数值执行、验证与保存；候选wall_seconds包括子进程启动/导入/加载/仿真/验证/写产物，不能当作纯推理时间。单次CP search limit不等于整个Skill耗时；例如1秒搜索实际略超1秒，加上构模/重放/进程开销后墙钟更长。日志同时保存solver_seconds和实验wall_seconds。8轮上限相同，最优证明可提前停止；并非人为强制两规划器消耗相同的实际秒数。

冻结选择仅用开发数据，要求候选在三个种子都有合法记录，按平均Makespan、平均实际成本选择。F/G均选1秒CP。冻结后两新场景按事前设备族映射各执行一次该方法，另外一次性运行事前声明的五规则/三个RL模型/两个CP预算作参考。**封存评价的是开发选出的单个Skill及预算，不是在测试场景继续运行自适应研究循环**；没有把测试指标送回规划器或补训。

## 6. 真实闭环与接受轨迹

主记录：[experiments.jsonl](../results/wafer_sched/stage6/experiments.jsonl)、[decisions.csv](../results/wafer_sched/stage6/decisions.csv)。每个研究目录有manifest/config、每轮input/record JSON、worker结果、simulation下完整events.json.gz/CSV/TXT、decisions.json、指标及验证；CP另有完整schedule/solver.json/solver.log。

F、求解seed0的八轮示例：

| 轮 | 数值Skill/参数 | 真Makespan(s) | 选择所见反馈 | 接受含义 |
| --- | --- | --- | --- | --- |
| 1 | FIFO | 74 | 无历史，建立基准 | 首个合法候选 |
| 2 | bottleneck | 74 | FIFO阻塞/加工=0.525，机器人动作/span=0.608108 | 仅因本次墙钟较低替换，性能未改善 |
| 3 | RL seed0 | 65 | 针对性规则未改善74秒，试兼容预训练模型 | Makespan改善 |
| 4 | CP 1秒 | 63 | 当前65秒合法hint，寻找更好计划和证明界 | Makespan改善；FEASIBLE，界51 |
| 5 | CP 3秒 | 63 | 上轮FEASIBLE，gap=12/63，仍有预算 | 拒绝较高成本同值计划 |
| 6 | CP 10秒 | 63 | 3秒仍未证明最优，gap仍正，预算允许 | 拒绝同值计划 |
| 7 | RL seed7 | 65 | 连续CP未改善，测试尚未运行种子 | 更差，拒绝 |
| 8 | RL seed13 | 65 | 仍有CP停滞证据，seed7已运行且未改善，候选集合缩小 | 更差，拒绝；到8轮停止 |

G、seed0依次为185、199、183、183、183、183、189、194秒；第2轮瓶颈规则退化，第3轮RL改善，第4轮CP同值但墙钟较低，第5轮CP仍未改善，继而探索不同模型和ECT，均未取代183秒。实际原因、完整历史证据ID、gap和约束结果都在逐轮JSON/CSV中，不用最终最优值反推早期决策。

F的其他搜索种子在第5/6轮获得63秒、下界63秒的OPTIMAL证明后提前结束；不为了凑八轮继续求解。最佳低成本方案可能来自较早FEASIBLE轮，最优性证明来自后续同值OPTIMAL轮；两种来源分开记录。

## 7. 固定流程与CFAR消融

全部真实汇总：[comparison.csv](../results/wafer_sched/stage6/comparison.csv)、[analysis.json](../results/wafer_sched/stage6/analysis.json)、[自动数据表](../results/wafer_sched/stage6/analysis_tables.md)。三个搜索种子的描述性结果：

| 场景 | 规划器 | 最佳Makespan均值±样本标准差(s) | 找到最佳平均墙钟(s) | 完整研究平均墙钟(s) | 实调用数 |
| --- | --- | --- | --- | --- | --- |
| F | 固定顺序 | 63±0 | 7.503 | 11.747 | 8/8/8 |
| F | CFAR | 63±0 | 6.464 | 19.068 | 8/6/5（seed0/7/13） |
| G | 固定顺序 | 183±0 | 5.236 | 11.812 | 8/8/8 |
| G | CFAR | 183±0 | 4.490 | 18.923 | 8/8/8 |

固定流程为FIFO→SPT→ECT→bottleneck→adaptive→RL0→CP1→CP3，是明确的非自适应消融。两组全部开发实验约束通过。没有重复同研究内的方法/参数；最终性能一致。CFAR的较早最佳发现与更高总成本同时存在，不能只选择前一指标声称效率整体提升。小样本墙钟不做显著性或普遍速度结论。

LLM配置检查仅记录configured=false、research_egress_enabled=false。实际fallback-check里规划器记录DeterministicPlanner及research_egress_not_enabled；没有LLM消融性能行/虚构曲线。

## 8. CP预算自适应的实测结果

| 场景 | 固定1秒：目标/界 | 固定3秒：目标/界 | 固定10秒：目标/界 | 固定30秒：目标/界 | 自适应实际尝试/停止 |
| --- | --- | --- | --- | --- | --- |
| F | FEASIBLE 63/51 | OPTIMAL 63/63 | OPTIMAL 63/63 | OPTIMAL 63/63 | 1秒FEASIBLE→3秒OPTIMAL，证明后停 |
| G | FEASIBLE 183/142 | FEASIBLE 183/142 | OPTIMAL 183/183 | OPTIMAL 183/183 | 1秒→3秒，目标/界未变后停 |

F固定1/3/10/30秒完整流程实际墙钟为2.216/4.069/4.245/3.444秒；自适应6.645秒。较大限额允许提前证明并结束，不能把30秒限额当作30秒消耗。G对应2.192/4.286/10.123/10.934秒；自适应6.063秒。G停滞停止保留了正确183秒方案，省去更大搜索，但未获得固定10秒的最优性证明。这是研究停止规则在“找更好计划”与“证明最优”之间的真实代价。

本阶段因此新增F=63、G=183的受支持静态模型最优性证据；未改写第四/第五阶段当时FEASIBLE的历史状态，更未声称完整动态设备问题全局最优。

## 9. 封存测试与失败分析

| 场景 | FIFO | SPT/ECT | bottleneck | adaptive | RL 0/7/13 | CP 1秒/3秒 | 冻结CFAR输出 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| U_recipe_mix | 114 | 108/108 | 114 | 108 | 108/108/108 | 118/110，均FEASIBLE，界77 | 1秒CP=118，完整合法但退化 |
| U_slow_transport | 331 | 348/348 | 347 | 348 | 339/337/345 | UNKNOWN/UNKNOWN，均无目标值，界236 | 1秒CP无可验证方案 |

开发候选CP使用前轮合法hint；新实例的一次性CP参考与冻结输出没有该实例历史hint（solver.incumbent_hint=false）。开发集选出的短预算工具并不等价于把“规则/RL生成hint→CP”的整个协作流程迁移。这一初始化上下文差异与规模/配方变化共同解释退化，不能把所有差值都归因于CFAR或仅归因于规模。本阶段没有在看到测试失败后补充hint、加时或替换冻结方案。

2次UNKNOWN不等于INFEASIBLE，也不是物理死锁证明；程序没有以规则计划冒充CP输出，也没有给失败方案编造Makespan。这些失败的空仿真轨迹/零完成数和求解界原样保留。新慢传输设备下RL也未胜过FIFO，不能声称学得策略普遍泛化。

## 10. 指标、图表与数据来源

窗口WPH=`3600×完成片数/T`，各研究中的T事前固定；全部完成的F、G分别为57.6、36片/小时，所以同场景所有完整候选这一指标相同。以Makespan计算的有限批次吞吐可以另由完成数推得，但两者均不是稳态WPH。平均腔室利用率只计实际processing积分/T，不计blocking；机器人利用率计原动作积分/T；等待和阻塞延续第二阶段定义。

F示例的FIFO→63秒CP：平均等待23.75→23.25秒，总阻塞42→29秒，平均腔室加工利用率0.106667→0.048，机器人利用率均0.18。利用率下降来自改用较快加工选腔、加工秒从80降至36，不代表产能退步。因此不能只最大化原始加工占用比例；Makespan、实际工艺负载和利用率需一起解释。

正式记录共66次规则、42次CP、26次RL和134次Verification调用，真实求解状态31 FEASIBLE、9 OPTIMAL、2 UNKNOWN。接受原因41首个合法、28更低Makespan、13同值更低成本、50未改善、2未完成。总记录实验墙钟266.803秒不含绘图/测试，也不是所有终端工作时长。

生成并人工视觉检查10张图：[figures目录](../results/wafer_sched/stage6/figures/)：循环架构、决策轨迹、best-so-far、规划器预算—性能、Skill分布、CP/RL、F/G两张真实甘特、失败/拒绝、CP预算反馈。全部读取实际配置/记录；绘图布局修正只改变展示代码，未改实验数据与研究模型。

## 11. 验证、恢复和复现

晶圆套件实际212通过、1跳过（Windows符号链接权限测试，原有跳过）；其中28项新增。平台非破坏性文件替换/租约回归4通过。ruff对研究自有代码通过（未修改的第三方子集排除，逐文件SHA另检验）；pip check无损坏依赖。独立验收复算全部事件指标、重放132个完整候选、复核接受、保护哈希、模型哈希及封存/冻结顺序，见[verification.json](../results/wafer_sched/stage6/verification.json)。这不是完整铁路HTTP/数据库/UI端到端验收。

交付检查额外补充了ProblemAnalysis的预算建议/显式候选目录（此前预算准入已由规划器和执行器完成）。只增加分析输出，没有更改调度或规划选择规则：保留[正式实验使用的skills源码](../results/wafer_sched/stage6/metadata-extension/skills_before.py.txt)和前后SHA，逐项重算50个已有反馈规划提案，方法/参数全部一致，并在独立开发目录实际运行更新后八轮闭环，全部合法、最佳63秒。该验证实际总墙钟76.645秒，系统负载/启动耗时明显变化，不混入原消融的性能均值。补充不重新评价封存测试、不改正式指标；正式134次之外另有8轮原冒烟和8轮更新验证，共150次数值执行。`analysis.json.generalization_feedback`另保存真实ExperimentAnalysisSkill对每个封存候选与同场景FIFO的事后结构化比较，这些分析不会传给规划器。

失败测试经历也保留：初次新增测试有演示晶圆ID写错，已改测试；最后回归首次因pytest basetemp父目录未创建出现setup错误，原XML/TXT在validation-attempt-1，创建父目录后重跑通过。它们不参与正式性能统计。

以下命令在仓库根目录执行，使用新的输出目录避免覆盖本轮证据：

```powershell
.venv_wafer\Scripts\python.exe -m pip install -r requirements-wafer-agent.lock.txt
.venv_wafer\Scripts\python.exe -m experiments.wafer_sched.prepare_stage6
.venv_wafer\Scripts\python.exe -m experiments.wafer_sched.run_stage6 --output results/wafer_sched/stage6-replay
.venv_wafer\Scripts\python.exe -m pytest tests/wafer_sched -v --junitxml results/wafer_sched/stage6-replay/wafer_tests.xml
.venv_wafer\Scripts\python.exe -m pytest tests/test_local_runtime_compatibility.py -v --junitxml results/wafer_sched/stage6-replay/platform_regression.xml
.venv_wafer\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched tests/conftest.py experiments/wafer_sched --exclude _semantica
.venv_wafer\Scripts\python.exe -m pip check
.venv_wafer\Scripts\python.exe -m experiments.wafer_sched.verify_stage6 --root results/wafer_sched/stage6-replay
```

`prepare`只检查/创建已有声明，不改变封存参数；`bootstrap_stage6`是本轮首次保护/提取工具，不是复现必需入口，不应覆盖保护基线。研究依赖已含真实源码子集，不需要启动旧失效虚拟环境、铁路API或向量服务。

单场景实验与边界恢复示例：

```powershell
.venv_wafer\Scripts\python.exe -m src.wafer_sched.agent.cli --scenario F_competition --output results/wafer_sched/cfar-boundary-replay --pause-after 2
.venv_wafer\Scripts\python.exe -m src.wafer_sched.agent.cli --scenario F_competition --output results/wafer_sched/cfar-boundary-replay --resume
```

实际smoke已执行上述暂停/恢复。恢复读取已提交record.json重建Semantica摘要/图；配置、模型/源码哈希、候选集与预算必须一致。未提交子进程中途状态保留并明确拒绝当作完成实验；不支持训练梯度或研究suite任意位置恢复。已有完整研究目录拒绝覆盖。每轮JSON/CSV可直接查询，Semantica检索结果也记录于semantica_recall。

## 12. 现有局限和后续研究

现有局限：仅两个开发设备与两个新测试设备；预算自适应/最终测试只有搜索seed0，规划消融有三个搜索种子；不是独立随机扰动的统计检验。墙钟成本受导入/磁盘/系统负载影响，同值成本接受可能随运行改变，CP按墙钟截止也不保证逐字轨迹一致。相同规则/RL调度仍使用原确定性仿真；复现保留配置、种子、实际时间和求解状态。

冻结输出只转移了单个方法/预算，缺少开发协作初始化；测试显示这个缺口显著。启发式阻塞判断会选到退化规则，通用CFAR也会付出无收益探索成本；CP停滞不代表后续证明没有价值。LLM效果、动态故障的跨方法闭环、受控新增训练、完整Semantica安装与跨机器边界恢复均未验收。历史记录包含本机绝对产物路径，重新运行会产生本机路径；已有日志不保证直接跨机器恢复。

后续计划是预先定义并冻结完整hint生成+CP组合Skill、区分解改进与证明预算、重复测量成本并采用稳健接受阈值、扩大独立封存设备/动态扰动、在具备授权配置时评价真实LLM。它们尚未实现。best-so-far单调来自保留更优合法方案，不能作为CFAR理论收敛性证明。
