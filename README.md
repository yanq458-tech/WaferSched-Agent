# WaferSched-Agent

## 故障发生后，最迟可以等多久再修好？

一台多腔晶圆设备只有一只机械臂。故障发生时，有些晶圆还在加工，有些已加工完、必须在驻留期限内取走。给定故障快照 `x` 和修复延迟 `r`，若存在一份调度，能让**全部有效在制晶圆**按路线完成剩余工序，同时满足取移放顺序、单臂互斥、腔室容量、驻留和持片期限，就记为 `F(x,r)=1`。

我们求最迟修复延迟 **ρ\*(x) = sup{r ≥ 0 | F(x,r) = 1}**。对于有限边界，一份能在该时刻完成全部晶圆的合法方案给出下界，数学判据或精确求解给出上界；两者相遇才算证明边界。模拟器逐动作重放方案。系统也区分可无限延迟、即刻修复仍不可行，以及在预算内未能判定（`UNKNOWN`）。[模型、假设与证据](docs/recovery-evidence.md)

### 18 个新快照的盲测

这里验证的是**末道工序竞争**：每片晶圆还剩一道加工和一次出片，源腔与末道腔分离，单臂空手起步，异址移动等时长。使用 16、20、24 片晶圆和中、高两档腔室竞争，每种组合取 3 个新种子。输入、策略和计时规则在求解前冻结。表中数字是首轮在端到端时间预算内完成数学证明的快照数。[冻结协议](results/recovery/feedback-study/final-holdout/protocol.json)

| 每例预算 | 固定工具组合 | 同策略普通 Python 函数 | 离线 LangGraph Agent |
|---|---:|---:|---:|
| 1 秒 | 3/18 | 5/18 | 5/18 |
| 30 秒 | 11/18 | 11/18 | 11/18 |

三种入口共享求解工具和验证器。1 秒首轮，两种反馈入口优先尝试达到已有上界，都比固定组合多证明了同样的 2 例。反序复测时，Agent 相对固定组合的优势缩为 1 例。**这批数据支持短预算下调整工具顺序的价值，未显示 LangGraph 编排本身比执行相同策略的普通函数多取得证明。**

30 秒时，三种方法证明的是同样的 11 例：9 个中竞争快照得到精确有限边界，2 个高竞争快照通过同腔冲突判据证明即刻修复也不可行。其余 7 个高竞争快照均为 `UNKNOWN`，其中 Agent 相对固定组合有 1 例区间更紧、6 例更宽。162 次运行中有 71 次返回过调度方案；去重后的 11 份方案全部通过原模拟器的后缀和故障历史重放。[逐例结果与增退](results/recovery/feedback-study/final-holdout/instances.md) · [原始运行记录索引](results/recovery/feedback-study/final-holdout/runs.csv) · [重放审计](results/recovery/feedback-study/final-holdout/audit.json)

### 复现这批盲测

在仓库根目录使用 PowerShell。原实验使用 Python 3.13.13、OR-Tools 9.14.6206，将四个并行实验进程分别绑定到逻辑 CPU 2、4、6、8，每次求解使用一个线程。复测机需允许绑定这些编号；短预算结果会随主机负载波动。输出写到新目录，再次运行时请更换 `$dest`。[依赖清单](requirements-recovery.txt) · [完整实验说明](docs/recovery-closeout.md)

```powershell
python -m venv .venv-recovery
$py = ".\.venv-recovery\Scripts\python.exe"
& $py -m pip install -r requirements-recovery.txt
$env:PYTHONPATH = (Resolve-Path src).Path
$dest = "results/local/final-holdout-replication"

& $py -m pytest tests/wafer_sched/test_exclusive_terminal.py -q
& $py -m wafer_sched.recovery.feedback.study generate --final --root $dest
& $py -m wafer_sched.recovery.feedback.study benchmark --root $dest --budget 1
& $py -m wafer_sched.recovery.feedback.study benchmark --root $dest --budget 30
& $py -m wafer_sched.recovery.holdout_review --root $dest
```

汇总结果在 `$dest/summary.json`，逐例证明、退步及 UNKNOWN 原因在 `$dest/instances.md`。

## 历次故障恢复算法对照实验

[临界例反馈求解、容量上界与第二批 18 例盲测](results/recovery/feedback-study/README.md)

[16–24 片新快照上的 Agent 与直接工具对照实验](results/recovery/holdout-scale/README.md)

[1 秒维修边界求解、逐例瓶颈与原预算配对复测](results/recovery/one-second/README.md)

[末道搬运顺序、跨工序上界与复现命令](docs/recovery-tail-ranks.md) · [三个精确边界、调度见证和逐例配对结果](results/recovery/tail-ranks/README.md)

[末道资源冲突的数学判据与复现命令](docs/terminal-proofs.md) · [剩余十个快照的逐例诊断与最终配对复测](results/recovery/terminal-proofs/accepted/README.md)

[8 片与 12 片难例的原因、改进策略及复现方法](docs/recovery-hard-cases.md) · [30 秒逐例增退](results/recovery/hard-case-policy/paired30/changes.md) · [1 秒逐例增退](results/recovery/hard-case-policy/paired1/changes.md)

从同一故障快照比较直接最大化维修延迟、边界搜索以及离线反馈策略。附独立 SCIP 整数规划、可复算冲突上界和分层算例。
[数学模型与复现命令](docs/recovery-evidence.md) · [固定输入索引](results/recovery/evidence-study/manifest.json) · [逐次对照结果](results/recovery/evidence-study/benchmark/results.csv)

## v1.3.0 故障恢复

支持单机械臂取片、移动和放片中途故障，以及经过明确工艺授权的已加工晶圆等待与撤离。
用历史动作复原快照，执行不可取消前缀，再计算从故障时刻起的修复边界与剩余完工时间。
在已安装项目及 LangGraph 的环境中运行以下离线演示：

```powershell
python -m wafer_sched.recovery.study
```

[输入格式、工艺条件、算法及实验复现](docs/recovery-v1.3.md) · [v1.3.0实验结果](results/recovery/v1.3.0-acceptance/summary.json)

### v1.3.0 十分钟研究汇报

[17 页中文 PPT](docs/presentations/v1.3.0-project-review/WaferSched-Agent_v1.3.0_研究汇报.pptx) · [逐页 Word 讲稿](docs/presentations/v1.3.0-project-review/WaferSched-Agent_v1.3.0_逐页讲稿.docx) · [图表数据与资料](docs/presentations/v1.3.0-project-review/README.md) · [正式 Release](https://github.com/yanq458-tech/WaferSched-Agent/releases/tag/v1.3.0)

基于事件驱动 MDP、CP-SAT、MaskablePPO 与约束反馈的多腔体晶圆传输调度研究。项目在 Semantica 工作区内开发，现已整理为独立仓库；所有调度方法共享同一个真实离散事件仿真器。

当前 `main` 包含 v1.3.0 故障恢复代码、汇报材料及后续维修边界研究。各版本的原始发布代码与实验可通过历史标签查阅。

## v1.2.0 历史项目研究汇报（18页，约20分钟）

- [可编辑PowerPoint](docs/presentations/v1.2.0-project-review/WaferSched-Agent_v1.2.0_项目研究汇报.pptx)
- [逐页Word讲稿](docs/presentations/v1.2.0-project-review/WaferSched-Agent_v1.2.0_逐页汇报讲稿.docx)
- [项目技术摘要](docs/presentations/v1.2.0-project-review/项目技术摘要.md)
- [图表、源数据、生成脚本与检查说明](docs/presentations/v1.2.0-project-review/README.md)

汇报制作时的Git状态保留为历史快照；本节说明当前main整合状态。汇报严格区分阶段七
真实DeepSeek实验和v1.2.0的离线确定性LangGraph故障恢复闭环。

## 新增：故障恢复与最迟修复时限

独立模块 `src/wafer_sched/recovery/` 支持真实在制快照下的单空腔暂时故障，计算全部有效
晶圆完成剩余工序的可恢复性、最迟修复时限与精确重调度。原 Simulator 逐动作重放，
严格区分不可行、UNKNOWN、有限/无穷边界。离线 LangGraph 依据求解反馈调整查询与预算，
默认不调用付费 API。已有历史模块及下文历史结果保持原有范围。

```powershell
.venv-langgraph/Scripts/python.exe -m wafer_sched.recovery demo
```

从干净环境安装、输入格式、支持范围、数学保证与实验命令见 [故障恢复使用说明](docs/recovery.md)。
验收数据位于 [固定实验结果](results/recovery/v1.2.0-acceptance/summary.json)，
包括9类实例、3种方法、独立穷举及预算耗尽轨迹。不宣称已确认的全球首创或一般开放问题已解决。

## 研究背景与数学问题

设备含装载单元、单片容量中央机器人及多个工艺腔室。晶圆必须按指定工艺路线完成取片、移动、放片、加工和卸载。研究目标是在资源互斥、容量和工艺顺序约束下，比较不同调度策略的批次完成时间、产出、利用率、等待与阻塞。

Makespan 是批次全部完成的时刻减批次起点。`finite_batch_wph` 为观测窗口内完成晶圆数乘 3600 除以窗口秒数；腔室利用率只计实际加工，不计阻塞；机器人利用率计真实动作占用时间。固定窗口实验的 WPH 与按完成时长计算的 `completion_batch_wph` 必须区分，也不能称为稳态 WPH。不同规模、不同窗口的 WPH 不用于直接证明策略改进。

## 架构与七个 Skill

```text
设备与工艺 JSON → EquipmentConfig → Simulator / 统一动作合法性检查
                                  ├─ FIFO / SPT / ECT / Bottleneck / Adaptive
                                  ├─ CP-SAT → 原 Simulator 重放验证
                                  └─ MaskablePPO → 同一动作检查器生成 mask
真实事件 → 指标积分 → 约束反馈 → 研究规划 → 下一轮实验
                           ↕ Semantica 研究记忆与上下文图
```

研究实现放在 `src/wafer_sched/`，独立通用适配层放在 `infrastructure/`，保留来源与许可证的 Semantica 子集位于 `agent/_semantica/`。没有迁移铁路业务 API、数据库或铁路优化模型。详细验收见 [发布审计](docs/github_release_audit.md)。

| Skill | 实际职责 |
| --- | --- |
| ProblemAnalysisSkill | 分析已知工艺负载、历史阻塞与瓶颈，提供预算建议 |
| RuleSchedulingSkill | 经统一 Policy 和 Simulator 执行规则调度 |
| CPSATOptimizationSkill | 求解支持范围内的静态问题，以合法历史决策作 hint |
| RLPolicySkill | 加载已有 MaskablePPO，在统一合法动作 mask 下推理 |
| VerificationSkill | 独立重放与约束检查，从事件计算真实指标 |
| ExperimentAnalysisSkill | 分析通过与失败的实验，比较候选方案与成本 |
| ResearchPlanningSkill | 根据历史反馈选择允许的方法、参数和搜索预算 |

这些是实际 Python SkillRegistry 中注册的可执行工具，不是只写在文档里的名称。

## 事件驱动 MDP

采用 `M=(S,A,P,R,gamma)`。状态包括当前时刻、机器人位置与携片、腔室占用和剩余加工时间、晶圆位置与阶段、等待和完成数量。策略观察由 ObservationBuilder 生成，不能读取隐藏事件队列或修改仿真状态；合法动作由原 Simulator 的约束检查器提供。

取片、移动和放片均占用真实仿真时间；事件队列按时间和稳定优先级推进。机器人只能执行一个动作，腔室容量受限，未加工完的晶圆不得进入下一工序，加工完成不会自动释放腔室。没有合法动作时等待下一事件；没有未来进展时报告死锁。

决策间隔不等长，因此物理过程是事件驱动的半马尔可夫过程。PPO 默认奖励按相邻决策间真实事件积分计算。设晶圆数为 n、腔室数为 c、参考时间为 100 秒：

`r = 10*新增完成数/n - 0.5*等待晶圆秒/(n*100) - 0.1*阻塞腔室秒/(c*100) - 0.1*机器人动作秒/100 - 2*经过秒/100 - 10*死锁未完成比例`。

正式训练采用有限 episode、`gamma=1`；没有实现按物理时间定制折扣。完成收益仅在完成事件出现时计一次，吞吐和利用率仍作为独立评价指标。

## CP-SAT 与 MaskablePPO

历史批次调度 CP-SAT 模型支持初始空设备、已知静态工艺、单片机器人、完整传输和离散精确时间刻度，以 Makespan 为目标。求解结果必须经原仿真器验证。`FEASIBLE` 表示找到合法解，不能声称全局最优；`OPTIMAL` 也仅对已声明的完整或受限模型范围有效。动态故障恢复使用上文的独立恢复模型。

MaskablePPO 基于 Gymnasium 与 sb3-contrib。当前编码容量为最多 8 片晶圆、4 个腔室、3 个工艺阶段；超范围场景不能直接套用已有模型。较大规模 CP 或规则场景可运行，不代表 PPO 编码同样支持。

训练、验证、测试配置分开保存，best checkpoint 依验证完成率和平均 Makespan 选择。第五阶段真实训练包含 small/medium 两组、seed 0/7/13、共 36,864 步和 3,311 个 episode；正式模型为 12 个 best/final，另保留 2 个 smoke 模型。迁移未重新训练这些模型。

## CFAR 反馈闭环与真实结果

CFAR（Constraint-First Adaptive Research）先检查方案是否约束合法且批次完成，再按 Makespan 和计算成本选择方案。它依据历史事件中的阻塞、机器人占用、已验证最优界、CP 状态及预算决定下一轮工具调用。研究记忆与图使用保留的 Semantica 子集。

下表取自原始 `results/wafer_sched/stage6/analysis.json`；是各场景多个运行种子的均值，不是本次迁移生成的新比较结果。

| 场景 | 方法 | 最佳 Makespan（秒） | 首次找到最佳方案（秒） | 总计算时间（秒） |
| --- | --- | ---: | ---: | ---: |
| F_competition | CFAR 确定性反馈规划 | 63 | 6.464 | 19.068 |
| F_competition | 固定顺序消融 | 63 | 7.503 | 11.747 |
| G_dual_bottleneck | CFAR 确定性反馈规划 | 183 | 4.490 | 18.923 |
| G_dual_bottleneck | 固定顺序消融 | 183 | 5.236 | 11.812 |

CFAR 在这两个开发场景中更早找到最佳方案，但总体计算成本更高，并未得到更好的最终 Makespan。第六阶段主比较的 134 次实验中，132 次通过、2 次失败，失败记录完整保留。冻结方案在 U_recipe_mix 上为 118 秒，其他部分方法可达 108 秒；在 U_slow_transport 上，冻结的 1 秒 CP 返回 UNKNOWN，FIFO 可完成于 331 秒。不能据此宣称跨场景普遍优于固定策略。

v1.0.0 静态工况实验已完成，当时尚未验证 LLM 自主规划；该版本的未配置或失败 fallback 不算成功调用 LLM。第七阶段真实 LLM 规划及反思证据见下文。动态故障下的优化表现、自主修改 RL 代码以及更大规模泛化属于后续研究计划。PPO 训练奖励不等价于生产性能证明。

本次独立发布验收另外保存于 `results/release_validation/`：最小案例 47 秒，CP-SAT 对应案例 OPTIMAL 47 秒；14 个原模型成功独立加载推理，6 个正式 best 模型的保存事件序列精确复现；实际五轮反馈过程为 FIFO 185 秒、Bottleneck 199 秒、原 PPO 183 秒、1 秒 CP 183 秒、3 秒 CP 183 秒，均通过约束检查。该验收不是新一轮多种子性能研究。

## 安装与复现

已验收环境为 Windows、CPython 3.13.13、CPU PyTorch 2.8.0、OR-Tools 9.14.6206、Gymnasium 1.2.1、SB3/sb3-contrib 2.7.1。项目声明 Python >=3.11，但其他系统和 Python 版本尚未完整验收。依赖锁定为 39 个版本；不提交虚拟环境。

在仓库根目录执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest tests/wafer_sched -v
.\.venv\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched experiments/wafer_sched scripts
.\.venv\Scripts\python.exe -m pip check
```

Linux 可将解释器路径改为 `.venv/bin/python`，但尚未完成该平台验收。无需设置 PYTHONPATH，也不能指向原铁路项目。当前验收基于可编辑安装和完整仓库目录；不宣称仅安装 wheel 就包含全部配置、历史模型和研究数据。

运行演示、原模型推理、CP 求解和历史指标复核：

```powershell
.\.venv\Scripts\python.exe -m wafer_sched.demo --run-id local-demo-001 --print-events
.\.venv\Scripts\python.exe scripts/validate_release.py numerical --output results/local/numerical-001
.\.venv\Scripts\python.exe scripts/verify_history.py --output results/local/history-check.json
```

演示命令在晶圆 results 下建立新的 run-id 目录；不要复用历史 run-id。其余命令使用独立的 `results/local/` 输出，不覆盖第一至第六阶段产物。数值验收脚本主动阻止铁路 API 导入和旧项目文件访问。

运行五轮真实反馈并测试边界恢复：

```powershell
.\.venv\Scripts\python.exe scripts/validate_release.py cfar --output results/local/cfar-001 --pause-after 3
.\.venv\Scripts\python.exe scripts/validate_release.py cfar --output results/local/cfar-001 --resume
```

恢复要求配置、模型和源代码身份一致；迁移已经结束的旧会话不等于可以忽略身份检查继续旧源码下的会话。本次已实际验证新发布版本换根目录后从第 3 轮恢复至第 5 轮，无需旧项目。

其他对照实验命令：

```powershell
.\.venv\Scripts\python.exe -m wafer_sched.experiments --output results/local/stage3-001
.\.venv\Scripts\python.exe -m wafer_sched.stage4_experiments --output results/local/stage4-001
.\.venv\Scripts\python.exe -m wafer_sched.agent.cli --scenario G_dual_bottleneck --output results/local/cfar-full-001
.\.venv\Scripts\python.exe -m wafer_sched.rl.evaluation --help
```

每次选择新的输出目录。上述复核和推理不训练原模型；单元测试会在临时目录训练一个新的 64 步小模型，以验证梯度更新、保存和加载，不会替换历史权重。

## 历史数据、来源与局限

`results/wafer_sched/` 完整保留事件、决策、CP 输入与输出、训练轨迹、评价 CSV、模型 metadata、图表和反馈验证记录。`provenance/original_research_sha256.json` 记录原研究文件哈希，`path_normalization.json` 说明路径规范化，`migration_manifest.json` 保存 4,631 个历史产物的原始和发布哈希。4,227 个保持原字节，404 个只规范化路径或机器文字；CSV、PNG、模型 ZIP 未改写。

378 组历史指标已从事件重算且一致；148 组已完成决策轨迹独立重放成功，另 2 个未完成记录没有算作通过。14 个模型 ZIP 完整，12 个正式模型还与历史验证记录中的 SHA 一致。源仓库没有保存每个阶段完整源码快照，无法仅凭现有代码重新构建所有旧版本的过程；保存的事件、配置和模型可以迁移与复核。旧保护清单保留其原意，适配测试通过迁移哈希清单确认合法路径变更，不修改数学约束。

最大待上传文件约 3.19 MB，所有模型约 1.09 MB，可直接纳入 Git；未来大模型的版本化分发方案见 [模型存储说明](docs/model_storage.md)。Windows 符号链接权限导致 1 项测试跳过。v1.0.0 时网络 LLM 接口尚未完整验收；阶段七真实 DeepSeek 接口已通过，多工作区任务公平性仍未完整验收，模型 ZIP 内可能留有不参与运行的原调试文件名。

## 引用与许可证

新研究代码与独立适配层使用 [MIT](LICENSE)。Semantica 子集保留原 MIT 许可证、版权与出处，见 [NOTICE](NOTICE.md)；具体上游 commit 尚未核验。

参考：[Semantica](https://github.com/semantica-agi/semantica)、[OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)、[Gymnasium](https://gymnasium.farama.org/)、[Stable-Baselines3](https://stable-baselines3.readthedocs.io/)、[MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)、Schulman 等人的《Proximal Policy Optimization Algorithms》(2017)。各阶段研究记录见 `docs/wafer_sched_stage2.md` 至 `wafer_sched_stage6.md`；当前发布状态以发布审计为准。

## 第七阶段 LangGraph 研究智能体

新增 `wafer_sched.langgraph_agent` 以真实 LangGraph 1.2.15 StateGraph 为开源 Agent 编排主体；Semantica 子集继续提供旧研究记忆上下文。九节点反馈循环、七个有类型工具、SQLite 实验边界恢复、结构化 LLM 规划与反思、预算和独立验证已实现，数学算法与原模型不改写。

原 215 项基线保持通过，当前共 239 通过、1 跳过；新增工具与恢复测试见 `tests/wafer_sched/test_langgraph_agent.py`。DeepSeek 最小请求已返回 HTTP 200，B 完成 12 轮真实自主规划和 8 轮完整有效反思；A/C 各 16 轮，44 个方案全部验证通过。B 在 F/G 本场景第 2 轮取得 63/183 秒，但 LLM 额外时间使总成本高于 A/C。真实预算阻止、反思截断及早期回退完整保存，模拟测试不算研究成果。新结果独立保存于 `results/stage7_langgraph/live-study-002/`，验收与限制见 [阶段七报告](docs/wafer_sched_stage7.md)。

安装和递进验收见 [运行说明](docs/langgraph_runbook.md)，架构及预算见 [LangGraph 架构](docs/langgraph_architecture.md)，来源和完整 MIT 许可证见 `provenance/langgraph_source.json` 与 `provenance/langgraph/LICENSE`。使用 `pip install -r requirements-langgraph-agent.lock.txt` 并重新可编辑安装当前 checkout 后运行新增 CLI；凭据仅放入被 Git 忽略的 `.env`。

## v1.1.0 — LangGraph LLM Research Agent

### LangGraph真实LLM智能体

LangGraph 1.2.15 提供有状态工作流与 SQLite 检查点，DeepSeek 提供真实规划与反思，原数学 Skill 和 Simulator 独立求解及验证。Semantica 仅为记忆与图上下文辅助设施。未启用 LLM 自主代码改写。

### 第七阶段实验

12 轮真实 LLM 规划、8 轮完整有效反思；三组共 44 个候选方案全部合法。F/G 最佳 Makespan 均为 63/183 秒，LLM 未提升最终解质量，总活动时间 134.137 秒，高于原 CFAR 55.419 秒及固定流程 28.005 秒。预算阻止、输出截断和真实回退均完整保存。方法与原 CSV arm 字段的对应见 [第七阶段目录](docs/stage7/README.md)。

### 研究报告下载

- [可编辑 Word 报告](docs/stage7/WaferSched-Agent_课程研究报告_v1.1.0.docx)
- [最终 PDF 报告](docs/stage7/WaferSched-Agent_课程研究报告_v1.1.0.pdf)
- [GitHub 发布审计](docs/stage7/github_release_audit.md)

### 复现方法

依照 [独立安装及实验说明](docs/stage7/reproducibility.md) 安装。仅需离线验证时执行 `python experiments/wafer_sched/stage7/reproduce_saved.py`，不需要 API Key；真实 LLM 运行仅从项目根目录被忽略的 `.env` 加载配置，不读取旧进程环境。原测试及 PPO 只读推理命令见发布审计。

v1.1.0 内容已整合至 `main`；正式版本快照及发布状态见 [GitHub Releases](https://github.com/yanq458-tech/WaferSched-Agent/releases/tag/v1.1.0)。v1.0.0 标签、原数学代码与历史模型保持不变。课程报告下载使用上方 18 页脱敏验收版本；旧报告仅保留于 Git 历史中。
