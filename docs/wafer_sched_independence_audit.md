# WaferSched-Agent 项目来源、数据依赖与独立运行审计

审计日期：2026-10-10。工作区：`.`。

本次只读取代码、配置、已有结果、依赖元数据和 Git 状态，只新增本报告。没有上传 GitHub，没有执行训练、求解、新实验、pytest、依赖安装、数据库连接，也没有修改、移动或删除原文件。诊断用 Python 均加 `-B`，指标复核直接读取既有事件，不产生新实验文件。

## 结论与证据范围

**晶圆数值研究没有发现使用铁路业务数据、数据库记录或铁路优化模型的执行链；完整项目仍依赖少量原平台基础设施，单独复制 `src/wafer_sched/` 不足以运行全部阶段。现有结果及模型文件可以完整保存和迁移，但换目录后直接恢复历史研究会话、执行原保护清单验收，并非当前代码支持的能力。**

这里的“没有发现”依据实际 Python AST/import、文件读取调用、运行配置与保存产物，不是对过去所有进程进行过动态数据污点追踪的绝对证明。历史测试成绩取自现存 JUnit XML；本次独立执行了文件哈希、模型 ZIP CRC、保存事件的指标重算和禁止 `api` 导入的隔离探针。文档用于定位文件，不作为功能实现的唯一证据。

必须区分两种读取：第一阶段源码审计曾读取铁路 CSV、TTL 等文件字节作哈希；后续保护清单曾读取铁路模块、配置、ontology、queries 作哈希。它们没有作为晶圆加工时间、路线、训练样本或优化输入。不能笼统声称“从未读取过任何铁路文件”。

## 1. 第一至第六阶段代码的实际位置

`src/wafer_sched/` 当前有 **59 个 Python 文件**：44 个本项目文件、15 个内置 Semantica 子集文件（12 个上游模块和3个包初始化文件）。阶段划分是现有模块职责和产物归档，不代表保存了六套完整源码版本；当前新增研究代码在 Git 状态中仍为未跟踪文件，无法依据六个阶段提交重建全部历史版本。

| 阶段 | 真实代码位置与职责 | 配置、测试和产物 |
| --- | --- | --- |
| 一：架构审计 | `scripts/63_audit_wafer_workspace.py`：只读遍历、哈希、AST与依赖元数据检查 | `tests/wafer_sched/test_workspace_audit.py`；`docs/workspace_inventory.json`；`docs/architecture_analysis.md`。没有这一阶段的数值训练模型 |
| 二：离散事件仿真 | `src/wafer_sched/{actions,config,equipment,events,simulator,verification,metrics,driver,demo,artifacts}.py` | `configs/wafer_sched/minimal_demo.json`；`test_simulator.py`、`test_artifacts.py`；`results/wafer_sched/stage2-single-wafer/`、`stage2-verified/` |
| 三：规则与自适应启发式 | `src/wafer_sched/{observation,policy_runner,scenarios,experiments,reporting}.py`；`policies/rules.py` | `configs/wafer_sched/stage3_suite.json`、A至E案例；`test_policies.py`；`results/wafer_sched/stage3/` |
| 四：CP-SAT | `src/wafer_sched/{cpsat_model,cpsat_solver,cpsat_validator,schedule_adapter,stage4_metrics,stage4_scenarios,stage4_experiments}.py` | `stage4_suite.json`、`stage4_large_retry.json`及F/G/H/S/M/L配置；`test_cpsat.py`、`test_stage4_experiments.py`；`results/wafer_sched/stage4/`（含`large_retry/`） |
| 五：事件驱动MDP与PPO | `src/wafer_sched/rl/{encoding,environment,reward,policy,training,evaluation,reporting}.py` | `configs/wafer_sched/rl/`；`experiments/wafer_sched/{run_stage5,verify_stage5}.py`；`test_rl_environment.py`、`test_rl_training.py`；`results/wafer_sched/stage5/` |
| 六：研究规划、反馈与记忆 | `src/wafer_sched/agent/{schemas,skills,planner,feedback,research_memory,experiment_runner,worker,evaluation,reporting,cli}.py`；`agent/_semantica/` | `configs/wafer_sched/agent/`；`experiments/wafer_sched/{bootstrap_stage6,prepare_stage6,run_stage6,verify_stage6,summarize_stage6,refine_stage6_plots,verify_stage6_metadata}.py`；`test_agent.py`；`results/wafer_sched/stage6/` |

上述测试均位于 `tests/wafer_sched/`，阶段说明和模型审计在 `docs/wafer_sched_stage*.md`。运行依赖是 `requirements-wafer.txt`、`requirements-wafer.lock.txt`、`requirements-wafer-agent.txt`、`requirements-wafer-agent.lock.txt`，实际研究解释器在 `.venv_wafer/Scripts/python.exe`。

IDE当前打开的 `scripts/01_build_opening_case.py` 属于原铁路项目，不是晶圆研究入口。根目录 `data/`、`metadata/`、`models/` 与 `configs/wafer_sched/`、`results/wafer_sched/stage5/.../models/` 是不同用途，不能混为晶圆数据或PPO权重。

## 2. 仿真、场景、PPO和CP-SAT的数据来源

### 仿真与实验场景

数据入口是 [`config.py:193`](../src/wafer_sched/config.py#L193) 的 `load_config()`：读取指定JSON，调用 `EquipmentConfig.from_dict()` 验证。[`simulator.py:14`](../src/wafer_sched/simulator.py#L14) 从该设备配置建立晶圆、机器人、腔室和事件；第16行明确 seed 在确定性核心中只是元数据，不产生加工时间随机样本。

`minimal_demo.json` 明确规定3片晶圆、CLEAN/RINSE路线、加工4/6秒、取/移/放各1秒。`scenarios.py:9`、`stage4_scenarios.py:10` 分别从本地套件JSON读取设备JSON，未调用业务数据库或铁路场景服务。实际设备配置共有20份，全部位于 `configs/wafer_sched/`：

| 配置 | 晶圆数 / 腔室数 | 来源性质 |
| --- | --- | --- |
| `minimal_demo.json` | 3 / 2 | 可手检的合成案例 |
| `B_batch.json`、`C_bottleneck.json`、`D_parallel.json`、`E_long_robot.json` | 12/2、12/2、12/3、10/2 | 明确声明批量、瓶颈、并行、长运输时间的合成设备 |
| `F_competition.json`、`G_dual_bottleneck.json`、`H_heterogeneous.json` | 4/3、4/3、6/3 | 异构配方与工艺路线的合成案例 |
| `S_small.json`、`M_medium.json`、`L_large.json` | 2/2、8/4、20/6 | CP规模对照案例 |
| `rl/V_small.json`、`V_demo.json`、`V_competition.json`、`V_dual.json` | 2/2、3/2、4/3、4/3 | 验证集独立设备配置 |
| `rl/T_count.json`、`T_noalt.json`、`T_transport.json` | 5/3、5/2、5/3 | 数量、可替代资源与运输条件变化的测试配置 |
| `agent/U_recipe_mix.json`、`U_slow_transport.json` | 5/3、6/3 | 第六阶段预声明留出配置 |

这20份正式设备配置均没有 downtime、延迟释放任务；不能将这些正式对照结果称为真实工厂数据实验或故障随机扰动实验。仿真器支持的故障等行为与测试中的构造状态，也不等同于已经开展该类正式研究。

第六阶段留出数据有可审查的生成代码：`experiments/wafer_sched/prepare_stage6.py:11` 从F/G晶圆JSON复制工艺路线，显式更改配方时间、晶圆数和机器人时间；`EquipmentConfig`验证后保存，并在 `configs/wafer_sched/agent/holdout_seal.json` 记录哈希。它没有调用铁路数据、LLM生成数值或采集真实设备记录。

### PPO训练数据

训练是**仿真环境在线生成交互轨迹**，并非导入铁路CSV或数据库的离线监督学习：

1. `rl/training.py:191` 读取 `train_scenarios` 对应的设备JSON；第197–208行创建 `Monitor(WaferSchedulingEnv(...))`、`MaskablePPO`并调用真实 `model.learn()`。
2. `rl/environment.py:70` 的 reset 通过带种子的随机数选择训练设备；第79行创建同一个 `Simulator`。step由真实动作、事件推进、原约束和 `rl/reward.py` 的时间积分生成观测、掩码、奖励。随机性来自训练初始化、动作采样和案例抽样，不是模拟铁路数据或随机填写设备指标。
3. `small_training.json` 的训练集为S_small和minimal_demo，验证集V_small/V_demo；`medium_training.json` 的训练集为F/G，验证集V_competition/V_dual。`rl/training.py:67` 对物理配置签名检查训练/验证不重叠，checkpoint用验证完成率和Makespan选择。
4. 正式训练6次：small的seed 0/7/13各4096步，medium的seed 0/7/13各8192步，合计 **36,864步、3,311个完成训练episode**。本次逐文件统计 `transition_rewards.csv`、`episodes.csv`，行数与同目录 `models/metadata.json` 一致：small完成episode数538/543/568，medium为547/560/555（按seed 0/7/13）。

证据目录：`results/wafer_sched/stage5/training/{small,medium}/`，其中有 `training_config.json`、`source_sha256.json`、`evaluation_suite_before_training.json`；各 `seed-*/` 下有 `monitor.csv`、`episodes.csv`、`episode_summaries.json`、`transition_rewards.csv`、`validation.json`、`updates/` 和 `models/`。`metadata.json` 还保存完整 `train_equipment`、`validation_equipment`、奖励权重、编码和硬件版本。

日志记录了训练过程，但不等于保存了每个梯度步骤的完整内存rollout buffer、全部随机数状态与任意中途恢复快照。当前 `RLTrainingRunner` 是新训练流程，不应宣称模型迁移后能精确续接任意梯度步骤。

第五阶段测试套件 `configs/wafer_sched/rl/evaluation_suite.json` 包含训练分布内案例及H/T_count/T_noalt/T_transport测试案例。第六阶段明确标注这些已被测试，不能再次称为新的未见留出集。

### CP-SAT输入

[`cpsat_solver.py:38`](../src/wafer_sched/cpsat_solver.py#L38) 的 `solve_schedule(config, options, incumbent=...)` 调用 `cpsat_model.build_model()`，输入就是上述 `EquipmentConfig` 的配方时间、工艺先后、可选腔室、运输时间和释放时间。`cpsat_model.py:81` 建立本项目的晶圆传输/加工变量、资源占用与机器人排序约束；第204行的hint必须来自**同一配置、已完成且验证合法的Simulator轨迹**。

第六阶段 `agent/skills.py:104` 会读取先前合法晶圆实验的 `config.json`、`decisions.json`，重放验证后作为CP hint。它没有读取 `api/services/railway_solver.py`、铁路时刻表或铁路优化模型。通用数学求解依赖是 `ortools.sat.python.cp_model`。

实际输入和求解证据保存在各CP实验目录的 `config.json`、`solver.json`、`schedule.json`、求解日志、事件与验证结果。第五阶段 `rl/evaluation.py` 还会重用第四阶段保存的CP参考，但必须核对设备配置一致；引用的是晶圆历史对照结果，不是根目录铁路模型。

CP实现范围见 `cpsat_solver.py:73`：静态、初始空设备、单携片、完整传输、无故障、精确时间刻度。不是铁路求解器迁移，也不是动态完整设备问题的无条件全局最优证明。

## 3. 铁路业务数据、数据库和铁路模型是否被使用

| 对象 | 审计发现 | 具体证据 |
| --- | --- | --- |
| 铁路CSV、TTL、业务配置等文件 | 第一阶段审计读过文件字节作来源盘点；没有发现进入晶圆数值输入 | `scripts/63_audit_wafer_workspace.py:125` 读取字节并记录SHA；`docs/workspace_inventory.json` 列出53个 `data/` 文件，包括 `data/case_review/FINTRAFFIC_HKI_JNS_20260929_V1/00_case_manifest.csv`，以及铁路源码/模型等元数据 |
| 铁路数据库记录、Oxigraph、SQLite | 晶圆运行链没有数据库读取/连接接口 | 审计脚本第25–31行排除 `storage/`、`outputs/`，第54–63行排除sqlite/db等；晶圆自有代码AST中无pyoxigraph、sqlite、SPARQL、铁路数据服务导入，配置入口只有设备JSON及晶圆历史产物 |
| 铁路CP/优化模型 | 被源码审计识别，未被晶圆求解调用 | 第一阶段 `CAPABILITY_EVIDENCE` 含 `api/services/railway_solver.py`，只是静态符号证据；实际CP入口只导入晶圆 `cpsat_model` 和OR-Tools |
| 铁路模块、ontology、queries和config保护清单 | 后续防破坏验收读过字节作哈希，不是调度参数 | `experiments/wafer_sched/bootstrap_stage6.py:15` 枚举保护目录；`docs/wafer_sched_stage6_preservation.json` 含api57、scripts29、ontology9、queries11、config2个文件 |
| 铁路平台测试fixture | 文件存在，但晶圆测试未请求这些fixture | `tests/conftest.py:12`、`:46` 的铁路数据库导入、复制和求解位于非autouse fixture函数内；晶圆测试函数参数AST没有 `app`、`analysis_project` 或 `analysis_project_spec` |
| 已执行的平台回归 | 是通用文件/进程边界测试，不是铁路数值对照 | `tests/test_local_runtime_compatibility.py` 的4项测试使用临时路径验证锁、原子替换与journal，不读取铁路数据；各阶段独立保存 `platform_regression.xml` |

所以，对于“是否使用过”的准确回答是：**来源审计和防破坏哈希涉及原铁路文件；所审查晶圆仿真、PPO训练、CP输入及设备指标没有发现使用铁路业务数值、数据库记录或铁路模型。**

## 4. 哪些功能复用了Semantica或平台基础设施

### 原平台通用模块

| 调用位置 | 实际复用 | 对设备数值的作用 |
| --- | --- | --- |
| `artifacts.py:12` → `api/contracts/optimization.py` | `safe_run_id`，限制结果目录标识 | 不计算工艺或产能 |
| `artifacts.py:13` → `api/persistence/local_runtime.py` | `durable_replace`，跨Windows/POSIX原子替换 | 结果持久化，不改变仿真时间 |
| `artifacts.py:14` → `api/services/run_artifacts.py` | `new_run_id`，时间戳/UUID编号 | 研究自身使用 `results/wafer_sched/`，不调用铁路 `read_solution` 或 `reserve_artifacts` |
| `artifacts.py:15`及实验、训练、agent模块 → `api/services/run_journal.py` | `atomic_record`，JSON原子保存 | 没有为晶圆实验创建铁路live-workspace journal或数据库 |
| `agent/experiment_runner.py:13` → `api/services/run_scheduler.py` | callable任务队列、并发和超时管理 | 用独立scheduler实例，提交标识为 `wafer-research-...`，worker为 `src.wafer_sched.agent.worker` |
| `agent/planner.py:182`（条件导入） | `model_transport`、`model_endpoint`和transport的 `model_http_worker` | 仅可选LLM候选方案传输；不代替仿真和数值验算 |

传递依赖不能漏掉：`run_artifacts.py:9` 导入 `api/workspaces.py` 的路径工具；导入 `api.persistence` 还会执行其 `__init__.py`，加载 `annotations.py` 的纯dataclass/Protocol定义。这些模块含原平台名称、数据库路径字符串或未调用业务辅助函数，**存在字符串/定义不等于执行数据库读取**。相关初始化与导入闭包只有标准库，不会初始化铁路数据库。

### Semantica上游代码

`agent/research_memory.py:10–11` 直接使用 `agent/_semantica/context/agent_memory.py` 和 `context_graph.py`。第27–28行创建真实 `AgentMemory` 与 `ContextGraph`；第50–79行store/retrieve晶圆实验摘要，并创建设备—实验—方法—反馈证据图关系。第六阶段保存的 `semantica_memory/`、`context_graph.json` 和调用记录可与已提交晶圆history对应。这是晶圆研究上下文，不是铁路RDF知识库。

`src/wafer_sched/agent/_semantica/PROVENANCE.json` 声明来源为 `https://github.com/semantica-agi/semantica`、版本0.7.0、本地来源 `.venv/vendor/semantica/semantica`。本次核对：**12个上游模块的当前SHA全部匹配PROVENANCE，且与仍存在的本地vendor文件逐字节一致**。3个包初始化文件为本项目最小初始化。`LICENSE` 是MIT，版权行 `Copyright (c) 2026 Semantica`，迁移必须保留。

这证明本地拷贝来源一致，不能证明具体上游Git提交：PROVENANCE明确 `commit_verified: false`，本次未联网核验。该子集不包含完整KG/RAG包；`context_graph.py:178–193` 捕获缺失的可选KG导入，研究初始化关闭 advanced_analytics、实体/关系抽取，当前功能不需要KG。若未来启用额外decision/KG方法，需要相应上游模块和额外依赖。

晶圆Policy接口、SkillRegistry、反馈接受规则与数值工具属于 `src/wafer_sched/` 自己的实现，不能把它们都描述为直接沿用了Semantica完整Agent框架。已保存 `results/wafer_sched/stage6/llm_availability.json` 表明configured=false、egress=false、actual_llm_comparison_run=false：第六阶段实际结果是结构化规划/反馈和真实记忆图调用，LLM fallback不构成LLM实验成功证据。

## 5–6. 能否独立运行，以及缺少什么

### 当前结论

**核心仿真、约束、事件指标和纯规则策略的源码没有原铁路业务依赖；完整研究入口不是可直接复制安装的独立包。** `src/` 是namespace目录，代码与启动命令使用 `src.wafer_sched`；根 `pyproject.toml` 只有ruff/mypy/bandit配置，没有可安装项目的 `[project]` 和build-system。

本次在内存中添加import阻断器，让所有 `api` 导入失败，未修改磁盘：

| 导入探针 | 实际结果 |
| --- | --- |
| `src.wafer_sched` | 成功 |
| `src.wafer_sched.metrics` | 成功 |
| `src.wafer_sched.policies.rules` | 成功 |
| `src.wafer_sched.artifacts` | `ModuleNotFoundError`，阻断在 `api` |

这是依赖隔离诊断，不是已经建立新仓库或完成了迁移后的全部运行验收。demo、实验导出、PPO训练和研究agent通过artifacts/atomic_record依赖平台模块。

### 零代码改动迁移需要的最小平台闭包

保持当前目录和 `src.wafer_sched` 命名空间时，研究默认执行链需要以下 **11个现有文件**，不需要整套铁路API：

```text
api/__init__.py
api/workspaces.py
api/contracts/__init__.py
api/contracts/optimization.py
api/persistence/__init__.py
api/persistence/annotations.py
api/persistence/local_runtime.py
api/services/__init__.py
api/services/run_artifacts.py
api/services/run_journal.py
api/services/run_scheduler.py
```

启用可选LLM时另需 `api/services/model_transport.py`、`model_endpoint.py`、`model_http_worker.py` 三个文件；transport通过子进程模块名启动worker，不能只迁移两个直接import。默认研究不需要LLM密钥、铁路服务、数据库或原 `.venv/vendor`，因为Semantica子集已经保存于研究源目录。

完整研究还需要以下内容：

- `configs/wafer_sched/` 全部套件和设备声明；`experiments/wafer_sched/` 复现入口；第一阶段测试还依赖 `scripts/63_audit_wafer_workspace.py`。
- `agent/_semantica/` 及其LICENSE、PROVENANCE；外部数值依赖。实际环境是Python3.13.13、numpy2.5.3、PyYAML6.0.3、OR-Tools9.14.6206、CPU Torch2.8.0、Gymnasium1.2.1、SB3/sb3-contrib2.7.1。以研究专用lock文件为准，不需要完整铁路环境依赖。
- 第六阶段现有study要求第五阶段medium的3个 `best.zip` 及相邻 `metadata.json`；第五阶段evaluation的历史CP参考要求第四阶段相关结果。仅拷贝权重但漏metadata，会在 `rl/policy.py:27` 或 `agent/skills.py:136` 失败。
- 保持目录深度：`artifacts.py:20` 使用 `Path(__file__).resolve().parents[2]` 计算项目根，多个入口从这里解析configs/results，worker在该root启动。如果把 `wafer_sched/` 直接移到根或改为新的包安装方式，需要后续修改路径与import设计。

当前不是“少一个铁路数据文件就不能跑”，而是“缺少通用I/O、任务执行模块及研究资源/包路径就不能跑”。更彻底的独立包可把这些通用能力收口到 `wafer_sched.infrastructure`，但这是后续迁移开发，本次未实施。

## 7. 是否有非晶圆代码参与指标计算

设备指标的唯一主计算位置是 [`metrics.py:6`](../src/wafer_sched/metrics.py#L6) 的 `calculate_metrics(trace)`，该文件只导入标准库math。输入为实际事件的 `state_after` 和相邻时间差：

- Makespan来自最后晶圆完成时间，整批未完成时为null。
- WPH为观测窗完成数×3600/窗口秒数，是有限窗口吞吐量；不是稳态产能估计。
- 腔室利用率只积分processing，不把blocked和停机算进加工分子；阻塞单独积分。
- 机器人利用率积分真实取片、空移、载片移动和放片时间；等待指标积分已释放、未完成、非加工、非该晶圆主动传输时间。

CP验证和RL评估均回到相同Simulator事件。`stage4_metrics.py` 额外用晶圆CP求解的bound/incumbent计算最优性差距，`rl/reward.py` 根据同类真实事件积分形成训练奖励，均没有调用铁路指标模块。OR-Tools、Torch、numpy、SB3等通用数学库参与求解/训练，不属于铁路业务模型。

**不能把这一结论扩展成“所有评价字段都不受任何平台代码影响”。** `agent/experiment_runner.py:140–166` 的 `wall_seconds` 包含平台队列、worker启动、计算及产物I/O；`FeedbackEvaluator` 在Makespan相同时按wall成本择优。平台调度、系统负载和文件I/O可影响墙钟成本、预算准入、停止轮次，进而间接影响被选策略或有限时限CP搜索；不会把这些墙钟秒数直接当成设备加工秒数。

窗口定义也必须保持。真实例子：第二阶段3片示例Makespan47秒、窗口47秒，WPH=229.787234；第三阶段A_demo/FIFO仍为47秒完成，但按共同80秒窗口保存，`comparison.csv` 的wph=135，同时另列 `completion_batch_wph`。这是分母定义不同，不能当成性能退化、提升或数据污染。第六阶段verification的主metrics也由真实保存事件窗口计算。

### 本次从保存事件独立重算的结果

遍历 `results/wafer_sched/` 的 `metrics.json`，仅在同目录实际存在 `events.json` 或 `events.json.gz` 时调用现有纯指标函数；逐字典对比，不启动Simulator/求解器、不写回结果：

| 产物范围 | 本次重算数量 | 与已保存metrics不一致数量 |
| --- | ---: | ---: |
| stage2-single-wafer | 1 | 0 |
| stage2-verified | 1 | 0 |
| stage3 | 50 | 0 |
| stage4（含retry） | 72 | 0 |
| stage5（包括有完整事件的历史尝试） | 104 | 0 |
| stage6（含smoke和metadata-extension验证） | 150 | 0 |
| 合计 | **378** | **0** |

该检查证明这些保存指标可由同目录事件重算；不是全部CSV字段、全部训练奖励、所有约束或新仓库运行的重新验收。无事件的失败尝试保留其失败状态，不能算作有效完成实验。

## 8. 历史结果和模型能否完整迁移

### 文件资产完整性

目前 `results/wafer_sched/` 共 **4,631个文件、119,470,912字节（约113.94MiB）**：

| 目录 | 文件数 | 字节数 |
| --- | ---: | ---: |
| stage2-single-wafer | 7 | 148,663 |
| stage2-verified | 9 | 816,829 |
| stage3 | 460 | 12,649,425 |
| stage4 | 722 | 21,539,999 |
| stage5 | 1,092 | 48,991,912 |
| stage6 | 2,341 | 35,324,084 |

这些文件是普通JSON/JSONL、CSV、压缩事件、文本、图片、XML和模型ZIP，不依赖铁路数据库解释。

第五阶段有 **12个正式PPO模型**：`training/{small,medium}/seed-{0,7,13}/models/{best,final}.zip`，另有 `smoke/seed-0/models/{best,final}.zip` 两个冒烟模型。本次12个正式ZIP的SHA256全部匹配 `stage5/verification.json` 中的 `model_sha256`；14个ZIP均通过逐成员CRC检查。压缩包实际包含 `data`、`policy.pth`、`policy.optimizer.pth`、`pytorch_variables.pth`、SB3版本及系统信息。CRC/哈希检查没有反序列化或执行模型。

第六阶段没有新增训练模型：`stage6_study.json` 注册第五阶段medium best权重；`agent/experiment_runner.py:88` 和正式 `stage6/verification.json` 明确new training=false。其记忆和图是研究记录，不能称为第六阶段重新训练的PPO模型。

本次还复查三个历史保护清单：第四阶段468份、第五阶段1,233份、第六阶段2,474份文件全部存在且哈希匹配。旧结果未被本次审计覆盖。

### 应一起保存的历史证据

迁移不能只挑成功结果或最佳模型，需要保留完整结果树以及以下记录：

- `stage4/large_retry/`、UNKNOWN/失败记录、CP schedule/solver日志与验证输出。
- `stage5/evaluation-attempt-1/` 和 `evaluation_repair.json`：训练后修复G_dual历史目录别名，不改变训练环境、奖励或模型；`stage5/verification.json` 已明确训练时完整源码与当前源码并非完全相同。
- `stage6/validation-attempt-1/`：保存失败测试输出；它们不应混同后来的通过结果。
- `stage6/metadata-extension/provenance.json`、`skills_before.py.txt` 与额外验证结果：原skills文本SHA为 `e93d4ae4759c7620ce714bd7c3f94a436d59806798c4a966818c3f63c17710d4`，本次与before_sha匹配，正式实验及后续说明扩展要区分。
- `stage6/protocol_before_development.json`、`frozen_method.json`、`holdout_protocol_at_start.json`、`holdout_labels.json`；`configs/wafer_sched/agent/holdout_seal.json`；每个研究会话的manifest、逐轮record、JSONL、decisions、context_graph、semantica_memory。
- 阶段保护清单、source_sha256、依赖lock、模型metadata和来源许可证。

**完整保存结果和模型是可行的；完整重建所有历史源码并未被证明。** 第五阶段训练前evaluation源码目前保存的是哈希和修复说明，未发现对应完整旧文本快照；哈希不能恢复源码内容。迁移时应保留这一限制，不能宣称旧版本代码已齐全。

### 跨目录运行和恢复的具体障碍

1. **绝对路径。** `stage6/development/F_competition/deterministic-seed-0/manifest.json` 的config_path和模型path为 `...`；同会话 `round-001/worker_result.json` 的artifact_directory也是绝对路径。保存文件可以读，但 `verify_stage6.py` 用这些路径读取原产物和模型，搬家后会失败。应将原JSON保持不变，后续增加旧根到新根的只读解析映射。
2. **恢复身份检查。** `agent/research_memory.py:18–21` 要求新manifest与原manifest完全相等；`experiment_runner.py:82–88` manifest包含绝对config/model路径、源码哈希、候选集、预算。换根或修改源码会被拒绝。恢复只支持完整提交的实验边界，不支持任意worker中断位置；不能仅复制semantica_memory便保证恢复。
3. **历史平台保护验收。** `verify_stage5.py`、`verify_stage6.py:25–27` 校验旧保护清单里所有原路径。独立仓库不含57份原API及铁路ontology/queries等全部旧文件时，这项“原铁路项目未变”的检查自然无法原样通过。应保留原工程保护证据，并另外建立迁移验收；不要把缺失文件改成历史检查通过，也不要为迁移省略物理约束检查。
4. **模型运行版本和编码。** `rl/policy.py:20` 检查模型动作/观测空间，load同时要求metadata；现有schema是max_wafers=8、max_chambers=4、max_stages=3、version=1。新环境应按lock重新安装，不能直接拷贝Windows虚拟环境。跨操作系统、CPU和库版本的推理/训练位级一致性未在本次验证。
5. **有限时间CP与研究预算。** 相同seed和设备不会保证不同机器的有限秒数CP状态、选中解、实际墙钟预算轮次完全相同。既有事件/计划可重算不等于重新求解必得相同日志。
6. **旧审计指向旧工程。** `workspace_inventory.json` 是旧铁路工作区的来源快照；它的文件数量和保护目标不适用于新的独立仓库。应作为历史来源证据保留，而不是当作新仓库清单。

因此，文件层面可以全量迁移；未来独立运行需要最小基础设施闭包及资源路径；历史跨路径恢复/完整验收需专门适配。上述适配本次均未实施。

## 独立GitHub仓库推荐目录结构

建议第一步采用**保留当前命名空间的兼容结构**，减少迁移时数值行为变更。`api/`只纳入前述11个通用闭包文件；可选LLM的3个文件按是否保留该能力决定，不复制铁路应用、solver或数据库。

```text
WaferSched-Agent/
├── README.md                         # 面向晶圆研究重写的说明（后续工作）
├── LICENSE                           # 新增代码许可证需项目所有者确定
├── pyproject.toml                    # 可先保留质量工具配置；当前尚无安装包定义
├── requirements-wafer.txt
├── requirements-wafer.lock.txt
├── requirements-wafer-agent.txt
├── requirements-wafer-agent.lock.txt
├── src/
│   └── wafer_sched/                  # 59个现有Python文件及来源文件
│       ├── policies/
│       ├── rl/
│       └── agent/
│           └── _semantica/            # 保留LICENSE、PROVENANCE、README
├── api/                              # 仅通用兼容闭包，具体文件见上文
│   ├── contracts/
│   ├── persistence/
│   ├── services/
│   └── workspaces.py
├── configs/wafer_sched/               # 设备、套件、rl、agent、holdout seal
├── experiments/wafer_sched/           # 已有复现和验证入口
├── scripts/
│   └── 63_audit_wafer_workspace.py
├── tests/
│   ├── wafer_sched/                  # 保留自身conftest；不携带铁路fixtures
│   └── test_local_runtime_compatibility.py  # 可选通用基础设施回归
├── results/wafer_sched/               # 全量历史文件，包括失败、重试和模型
│   ├── stage2-single-wafer/
│   ├── stage2-verified/
│   ├── stage3/
│   ├── stage4/
│   ├── stage5/
│   └── stage6/
└── docs/                             # 六阶段研究说明、审计、保护清单、来源盘点
    └── wafer_sched_independence_audit.md
```

这是建议结构，本次没有创建独立目录或仓库。原 `data/`、`storage/`、`metadata/`、根 `models/`、铁路solver、frontend和原虚拟环境都不是晶圆默认执行必需项。旧保护清单涉及的原工程文件可继续在原项目留存，独立仓库保留清单与原验收证据；后续迁移验收需要区分“旧工程保护”与“晶圆数据重放”。

再进行标准包整理时，可将通用兼容文件改为 `src/wafer_sched/infrastructure/` 的run_id、atomic_io、task_queue、model_transport适配器，补可安装pyproject，将 `src.wafer_sched` 改为 `wafer_sched`、明确资源根并实现历史路径解析。那是单独的后续开发任务，应该在数值回归与迁移验收后进行，不能把本报告当作这些修改已完成的证据。

上游MIT许可证已有明确证据；工作区根目录没有 `LICENSE`/`LICENSE.md`，不能自动宣称所有新增研究代码、原平台兼容代码及数据都已获得同一许可证。独立仓库的新增代码许可须明确，原平台代码来源也应在README/NOTICE列出。

## 本次实际检查与历史验证的区分

本次实际完成：AST/import与读取入口审查、20份设备配置盘点、研究依赖版本读取、Semantica12模块SHA和vendor字节比对、14个模型ZIP CRC、12个正式模型历史SHA、378份事件指标重算、3份保护清单全部复核、禁止api导入的核心/产物模块隔离探针。没有执行Git远程命令、模型加载、求解训练或新实验。

历史JUnit证据如下，不是本次重新测试：

| 结果文件位置 | 当时晶圆测试通过 / 跳过 | 当时平台通用回归 |
| --- | ---: | ---: |
| `stage2-verified/wafer_tests.xml` | 48 / 1 | 4通过 |
| `stage3/wafer_tests.xml` | 107 / 1 | 4通过 |
| `stage4/wafer_tests.xml` | 150 / 1 | 4通过 |
| `stage5/wafer_tests.xml` | 184 / 1 | 4通过 |
| `stage6/wafer_tests.xml` | 212 / 1 | 4通过 |

本次审计开始时Git已有 `.gitignore`、`README.md`、`tests/conftest.py` 修改及研究文件未跟踪状态；这些不是本次审计的修改。对研究src/configs/experiments/tests/results/docs、api、阶段一脚本、研究requirements和上述三个既有修改文件建立了4,867文件的只读内容指纹，排除缓存与本报告；开始指纹为 `e92d5acfed0004bdb059318c4474faa6ddb13ef5fc6b9010245b2ace92538b9c`。报告生成后，同一范围仍为4,867文件，指纹完全一致，既有文件内容未变；报告内4个源码链接也均指向存在的文件。
