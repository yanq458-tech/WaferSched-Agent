# WaferSched-Agent

基于事件驱动 MDP、CP-SAT、MaskablePPO 与约束反馈的多腔体晶圆传输调度研究。项目在 Semantica 工作区内开发，现已整理为独立仓库；所有调度方法共享同一个真实离散事件仿真器。

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

CP-SAT 当前支持初始空设备、已知静态工艺、单片机器人、完整传输和离散精确时间刻度，以 Makespan 为目标。求解结果必须经原仿真器验证。`FEASIBLE` 表示找到合法解，不能声称全局最优；`OPTIMAL` 也仅对已声明的完整或受限模型范围有效。动态故障不在当前 CP 优化模型的验收范围。

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

当前静态工况实验已完成。当前未验证 LLM 自主规划：默认禁止 LLM 网络出口，历史记录中的未配置或失败 fallback 不算成功调用 LLM。动态故障下的优化表现、自主修改 RL 代码以及更大规模泛化属于后续研究计划。PPO 训练奖励不等价于生产性能证明。

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

最大待上传文件约 3.19 MB，所有模型约 1.09 MB，可直接纳入 Git；未来大模型的版本化分发方案见 [模型存储说明](docs/model_storage.md)。Windows 符号链接权限导致 1 项测试跳过。网络 LLM 接口和多工作区任务公平性没有完整验收，模型 ZIP 内可能留有不参与运行的原调试文件名。

## 引用与许可证

新研究代码与独立适配层使用 [MIT](LICENSE)。Semantica 子集保留原 MIT 许可证、版权与出处，见 [NOTICE](NOTICE.md)；具体上游 commit 尚未核验。

参考：[Semantica](https://github.com/semantica-agi/semantica)、[OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)、[Gymnasium](https://gymnasium.farama.org/)、[Stable-Baselines3](https://stable-baselines3.readthedocs.io/)、[MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)、Schulman 等人的《Proximal Policy Optimization Algorithms》(2017)。各阶段研究记录见 `docs/wafer_sched_stage2.md` 至 `wafer_sched_stage6.md`；当前发布状态以发布审计为准。
