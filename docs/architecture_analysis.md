# WaferSched-Agent：工作区架构分析与增量开发方案

审查日期：2026-10-09（Asia/Shanghai）。审查基线：`4529b3bc8afcf890cc2c5b5291846a2b3cc56ff7`，当前分支 `feature/railway-v1.1`。

## 1. 本阶段范围与结论

本次落实用户要求的第一阶段：扫描现有工作区、核实智能体与工具能力、形成具体二次开发方案，并提供可以重复运行的源码审计。后续八阶段是开发计划，不能理解为已经实现；本阶段没有晶圆实验、PPO训练、五轮反馈结果或PDF研究报告。

**建议增量扩展现有 Semantica / COE 项目，暂不引入 LangGraph。** 已有图上下文、领域注册、数值求解工具、任务日志及决策追溯；缺少的是晶圆设备领域模型、真实仿真、调度器和实验反馈控制器。先实现独立Python研究入口，再接入已有智能体上下文，不建设工业监控界面。

这不是对“现成自主智能体”的直接换场景：当前助手是检索与受限查询助手，不能启动求解，自主迭代需要新增。最终必须在运行记录中证明调用了 Semantica 的上下文/记忆/决策能力，不能只把使用OR-Tools的独立程序称为已有开源智能体二次开发。课程对原项目是否符合“开源智能体”定义，应以这些真实能力和最终调用证据说明。

## 2. 扫描方法与证据边界

- 枚举第一方工作区文件，审查全部Python源码的语法树、导入与顶层定义；前端、配置、RDF、数据、文档进行目录与文件清单审计。
- 重点阅读入口、助手、LLM传输、领域协议、CP-SAT求解、运行持久化、测试隔离和CI；另外读取本机 Semantica 的上下文、记忆、决策与编排源码。
- 排除 `.git` 对象、虚拟环境、`node_modules`、构建产物、缓存、运行数据库与历史产物；不读取密钥文件内容，不打开实时Oxigraph库，不运行会写业务数据的初始化脚本。
- 可重复命令：`python scripts/63_audit_wafer_workspace.py`。清单写入 `docs/workspace_inventory.json`，包含相对路径、文件大小、SHA-256、Python导入/定义、静态证据与解释器依赖探测。
- 清单中的 `source_present` / `symbol_present` 是静态证据；`discoverable` 仅说明当前解释器能发现模块，均不能代替真实导入、工具调用或算法验收。审计不执行被扫描源码。
- 不是对所有代码逐行进行安全审计；未对前端做TypeScript类型验收，也未对RDF做新的SHACL校验。

## 3. 当前结构与入口

| 路径 | 当前用途 | WaferSched处理方式 |
| --- | --- | --- |
| `scripts/01_build_opening_case.py` | 创建铁路实体、规则、候选与分配边，保存演示图；模块顶层会写文件 | 保留；不能导入作为晶圆模型构建器 |
| `scripts/18_run_optimization_api.py` → `api/app.py` | 启动FastAPI、Semantica Explorer及Platform领域接口 | 后续可选集成，不作为研究运行必需服务 |
| `api/domains/registry.py` | `DomainRegistry`注册领域适配器 | 有真实领域注册；不等同于Skill注册 |
| `api/adapters/base.py`、`domain_types.py` | 图投影、会话、领域描述协议 | 需要图展示时再新增晶圆适配器；最小仿真不依赖它 |
| `api/services/assistant.py` | 固定意图表，平台事实检索；明确只读 | 保留检索层；另加研究反馈决策工具 |
| `assistant_graph_planner.py`、`assistant_graph_query.py` | LLM提议受限查询计划，程序验证并执行 | 复用“结构化候选→验证→工具执行”模式 |
| `assistant_llm.py`、`model_transport.py` | 可选答案润色、OpenAI兼容HTTP接口、限流与超时 | 后期研究建议适配器可调用传输层；不复用答案润色作为调度器 |
| `api/services/railway_solver.py` | 铁路车型/可用性/冲突的二元分配可行性模型，`minimize(0)` | 复用OR-Tools依赖与结果状态规范；不能复用数学模型 |
| `optimization_service.py`、`run_scheduler.py` | 铁路流水线编排、有限队列、后台执行与取消 | 调度器可以复用；铁路流水线须通过新工具适配，不能直接套用 |
| `run_journal.py`、`run_artifacts.py` | 原子JSON任务记录、独占租约、按run_id隔离产物 | 复用原子记录/任务调度；研究日志放到独立目录，避免抢占在线平台租约 |
| `api/persistence/local_runtime.py` | Windows/POSIX租约与持久文件替换 | 保留当前跨平台实现 |
| `report_analysis_service.py` | 已有事实的报告与只读agent预览 | 预览明确没有自主决策/动作执行；不等同于反馈控制器 |
| `ontology/`、`queries/`、`scripts/scenario_engine.py` | 铁路RDF、SHACL、场景变更 | 铁路语义不可复用；物理约束应由仿真状态不变量验证 |
| `tests/`、`.github/workflows/ci.yml`、`scripts/62_check_platform.py` | 现有回归、临时工作区与CI | 保留，并新增独立晶圆阶段测试 |
| `frontend/` | 迁移自Semantica Explorer的React界面 | 此课题无须扩展业务界面 |

当前业务数据在 `storage/oxigraph/`；`models/railway_opening_poc.json` 是旧演示产物。第一阶段不修改业务数据库、铁路场景或上游源码。

## 4. Agent框架、LLM、Skill与状态能力

### 4.1 现有框架与开源来源

项目沿用 Semantica 的 `ContextGraph` 和Explorer，并包含平台自主扩展。锁文件 `requirements-client-demo.lock.txt`固定上游提交 `7996d1ab4bd0c96ea7e3d91a4ce70fe5881d224b`；包元数据 `0.7.0` 不等于正式发布版本证明。

本机 `.venv/Lib/site-packages/semantica-0.7.0.dist-info/direct_url.json` 指向本地vendor安装，并非远程Git安装证明。最终复现必须使用固定提交安装且核实真实导入，不依赖本机vendor路径。

上游源码有 `context/agent_memory.py`、`agent_context.py`、`decision_recorder.py` 与 `core/orchestrator.py`：

- `AgentMemory`支持 `store/retrieve/save/load`，源码中向量存储可选；内存对象不会自动成为耐久实验日志。
- `AgentContext`构造要求向量存储，不宜为了数值实验先引入嵌入服务。
- `DecisionRecorder`需要图存储等适配，不能宣称无适配即可调用。
- `Semantica`主编排器偏知识处理流水线，不能替代设备事件引擎。

第六阶段优先实际调用 `AgentMemory`存取上一轮结构化摘要，用 `ContextGraph`记录设备、实验、策略及反馈选择关系；CSV/JSON仍为实验指标与恢复的权威记录。通过集成测试证明这些上游能力被执行。若精简依赖无法导入，先定位依赖问题，不能静默退化后宣称复用了智能体。

### 4.2 LLM与工具执行

LLM配置来自 `ASSISTANT_LLM_BASE_URL/API_KEY/MODEL`，当前查询和润色路径受工作区外发配置约束。`model_transport.py`发送兼容chat completions的结构化请求，包含并发、调用次数、输出大小和独立HTTP子进程超时控制。

没有发现项目已有的通用LLM `tool_calls`执行循环。当前机制是固定意图或校验过的查询计划→本地处理函数。新增研究工具将使用有类型的输入/输出和明确的Skill注册表；LLM只能建议白名单候选算法/参数，不能生成数值状态转移、任意代码或伪造结果。默认规则反馈模式不需要模型密钥。

### 4.3 Skill缺口

没有发现本项目的五类Skill或通用Skill调用注册器。`DomainRegistry`注册领域图适配器；上游 `PluginRegistry`注册知识处理组件，均不能直接视为本课题Skill实现。

规划 `SkillRegistry.invoke(name, request)`：验证输入→调用确定性工具→校验结果→记录输入摘要、输出产物和失败状态。五类Skill逐阶段增加实际可用实现，不提前注册空函数。工具共享唯一设备/任务数据契约，反馈控制器只能调用已实现且通过验收的工具。

### 4.4 状态与多轮运行

已有任务journal、解产物、RDF版本与决策来源；队列支持多个任务。**多任务记录不等于读取指标后改变下一轮策略。** 新增结构化实验历史、反馈状态及恢复游标，保存选择前所见指标和决策原因，并测试历史变化会改变下一轮选择。

### 4.5 本机运行环境

已现场确认系统 `python` 可运行（Python 3.13.13）。现有 `.venv` 与 `.venv_optimization` 的 `pyvenv.cfg`指定Python 3.11.9，但启动器引用的用户目录路径已经失效；现有 `.venv/Scripts/python.exe`无法启动。系统Python未发现pytest、OR-Tools、Semantica、Gymnasium、SB3、sb3-contrib、ruff。

因此本阶段用标准库 `unittest`完成新增审计工具测试；未运行原平台完整依赖测试。后续建立独立Python 3.11环境，验证固定Semantica依赖、OR-Tools及Torch/SB3兼容性后生成研究锁文件；不覆盖现有两个环境。

README中仍有“原生Windows不支持”的历史说明，但HEAD的 `local_runtime.py`已经增加Windows路径。此次只核实源码分支存在，不能据此声称原平台在本机已经重新运行验收。

## 5. 增量目标结构与首批文件

本阶段实际首批文件如下，先提交本架构文档，再增加审计代码：

| 文件 | 操作 | 内容 |
| --- | --- | --- |
| `docs/architecture_analysis.md` | 新增 | 当前证据、复用结论、数学与实验方案、九阶段验收 |
| `scripts/63_audit_wafer_workspace.py` | 新增 | 标准库源码清单、AST审计、静态能力证据、解释器探测CLI |
| `tests/wafer_sched/test_workspace_audit.py` | 新增 | 审计不执行源码、排除运行/密钥目录、语法错误与目录边界测试 |
| `docs/workspace_inventory.json` | 生成 | 本轮真实扫描结果，包含自身之外的第一方文件清单 |
| `README.md` | 增量修改 | WaferSched入口、阶段状态、复现审计命令 |

后续逐阶段创建以下文件，不提前生成无实现的目录/函数：

```text
requirements.txt                     # 独立研究依赖；验证后固定版本
configs/wafer_sched/                  # 静态、动态、训练、评价配置
src/wafer_sched/
  equipment.py, config.py             # Equipment Modeling
  simulator.py, events.py, actions.py  # Simulation，唯一状态转移与Action Mask
  metrics.py, verification.py          # 指标积分、守恒与轨迹复核
  policies/rules.py, cpsat.py          # 规则与有限时域优化
  rl/env.py, train.py                  # Gymnasium与MaskablePPO
  skills/registry.py, tools.py         # 可执行Skill与工具契约
  agent/feedback.py, memory.py         # 反馈选择及Semantica适配
  reporting.py                        # 图表与报告数据
tests/wafer_sched/                    # 各阶段测试与属性/集成验证
experiments/wafer_sched/              # 对照、动态、反馈、消融入口
results/wafer_sched/<experiment_id>/  # 配置、CSV/JSON、轨迹、训练记录
reports/report.md, report.pdf         # 中文研究报告与渲染验收
```

研究目录 `configs/` 与已有平台 `config/` 分开；已有铁路 `scripts/01_*`、API、RDF及前端不改名、不重构。

## 6. 数学模型与仿真实现约定（设计，尚未实现）

### 6.1 事件驱动半马尔可夫过程

定义 `M=(S,A,P,R,gamma)`。决策点为机器人空闲或相关设备事件发生后；状态包含物理时间、机器人位置/负载/动作剩余时间、每腔室占用与加工剩余时间、每晶圆所在位置/工艺序号、释放队列、完成数及当前可观察故障状态。仿真内部事件队列也属于可恢复状态。

动态释放、故障、加工扰动由带seed的外生过程生成。预先生成的未来随机事件不暴露给动态策略；残余加工时间默认已知，这一观测假设必须写入报告。若残余时间不可观测，应改称部分可观测模型。非无记忆故障过程需包含已运行时间等充分状态；未来计划维修只能在声明已知的场景中提供。

最小模型采用单机器人单夹爪、腔室容量1、输入/输出装载区、无额外中间缓冲；阶段可以包含多个可选并行腔室。明确取片、空载/负载行驶、放片耗时。

首版高层动作是完整的 `transfer(wafer, destination)` 或 `unload(wafer)`；执行轨迹展开为定位、取片、运输、放片，机器人负载在各子事件中真实更新。高层动作约定不可插入其他机器人任务，是对底层动作空间的明确限制。`wait`推进到下一个实际事件，没有零时间等待。

若放片途中目的腔室故障，机器人保持负载与目的保留状态，等待恢复；故障模式首版为加工暂停并在恢复后继续，不引入报废/重做。维修和加工完成事件必须处理同一时刻的确定性顺序。动作持续期间腔室加工及动态事件照常发生，不能在每次传输后再一次性虚构完成。

每次动作前应用同一合法性检查；各事件后检查晶圆守恒、唯一占用、工艺顺序和加工次数。终止状态不提供新动作。无合法传输但存在加工完成/恢复/未来释放事件属于等待；存在未完成晶圆且无可能改变阻塞状态的未来事件才判死锁，并记录等待资源关系。主动等待不等于物理死锁，额外事件/时间预算超限要记录为截断。

### 6.2 独立指标与奖励

时间单位秒，统计窗口 `[0,T]`：

- `WPH = 3600 * completed / T`，单位片/小时；同时报告完成数、释放数及未完成数。
- `chamber_utilization_j = processing_seconds_j / T`；平均利用率是各腔室的算术平均。故障时间保留在分母，另报可用时间分母版本以解释故障影响。
- `robot_utilization = robot_action_seconds / T`；包含定位、取片、运输、放片；持片等待维修另计，不算有效传输利用率。
- 等待为已释放晶圆处于非加工、非机器人动作状态的积分，按完成晶圆报告平均累计等待秒；另报全体释放晶圆的等待累计/数量和未完成数，防止截断选择偏差。
- `blocking_rate = sum(blocked_seconds_j)/(chamber_count*T)`；阻塞仅指加工完成但尚未取走的占腔时间，不能将加工或维修暂停混计为阻塞。
- `makespan`为指定批次全部完成时的最后卸载时间减批次窗口起点；未全完成时为null，报告截止时间及失败/截断原因。

令初始目标批次规模 `N_ref>0`、参考时间 `t_ref>0`、腔室数 `C`固定，则单步奖励：

```text
r = alpha * delta_completed / N_ref
  - beta * integral(unblocked_waiting_wafers dt) / (N_ref*t_ref)
  - eta * integral(blocked_chambers dt) / (C*t_ref)
  - delta * robot_action_seconds / t_ref
```

完成收益只在卸载时给一次；阻塞晶圆不再计入奖励的普通等待项。评价指标的总等待可以包括阻塞，但须区别于奖励项定义。不额外把WPH和累计完成奖励相加；保存每项原始积分、归一化基准及权重。

严格连续时间折扣为 `gamma ** (action_duration/t_ref)`；标准SB3默认按决策次数折扣，不能冒称实现了时间折扣。首版有限批次PPO拟用 `gamma=1.0`、`gae_lambda=1.0`及持续时间积分奖励，避免可变动作时长的折扣偏差，记录算法稳定性与截断bootstrap处理；若采用`gamma<1`，必须改造回报计算或明确为决策步近似。

### 6.3 三类算法共享约束

规则策略只从合法动作集合选取；比较FIFO、最早可执行、卸片/阻塞优先。CP-SAT根据当前快照输出可执行计划，由仿真重放验证；遇到新故障立即重规划，不可继续执行过时计划。

CP-SAT首版范围：固定路线、确定整数加工/传输时间、有限批次、静态单夹爪模型。变量包括加工与传输区间、机器互斥、工序先后、**加工开始至实际取片结束的占腔区间**，以体现无缓冲阻塞。机器人空载定位必须建模；如果暂时改为统一固定传输代价，文档和输出要明确是简化设备假设，并让所有方法在该假设下比较。输出求解状态、时间限额、可行目标、下界和gap；`FEASIBLE`不写成最优，滚动时域最优不写成全局最优。

Gymnasium包装同一仿真器，固定最大任务/腔室槽位并给未释放、完成或不适用槽位加mask；容量不足明确报错，不截掉任务。环境区分批次完成与时间/事件预算截断，显式seed，并通过环境检查及非法动作测试。训练/评估都使用mask；使用MaskablePPO专用评估工具。官方接口依据：[Gymnasium环境接口](https://gymnasium.farama.org/api/env/)、[MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)、[OR-Tools时序模型](https://developers.google.com/optimization/scheduling/job_shop)。

## 7. 真正反馈迭代与实验设计（设计，尚未实现）

### 7.1 反馈选择，不预设五组运行参数

第一轮运行FIFO，随后每轮读取已完成的验证集结果和轨迹诊断：阻塞偏高→提高卸片优先级；机器人接近饱和→缩短转移/定位优先；腔室负载不均→负载均衡；规则收益停滞且小案例可求解→调用CP-SAT；已有合法训练工具时才选择PPO训练/调整。各阈值、白名单与计算预算来自配置。

决策记录包含上一轮来源、瓶颈证据、候选集合、实际选择、参数变化和原因；每轮重新调用实验工具。至少五轮后方可按耐心值/预算停止。保留最佳验证策略，但同时保留退步、死锁、训练失败等记录。日志应证明同轮次不同反馈可触发不同选择；不得保证五轮必然改进。

轮日志CSV和JSON包含轮次、算法、参数、理由、seed、完成数、WPH、腔室/机器人利用率、等待秒、阻塞率、makespan、合法性、相对上一轮/基准变化，以及配置hash、代码版本、策略模型hash、时间预算、失败原因和轨迹位置。上一轮不存在/基准为零时差值或比率明确为null。

### 7.2 数据划分与四组实验

- 训练seed `0..9`；反馈验证seed `100..104`；最终保留测试seed `200..209`。这些是起始计划，不是已有实验结果。
- 每个算法共享同seed的释放/故障时间表与按晶圆-阶段采样的加工时间，避免不同动作顺序改变随机数消耗造成不公平。
- 静态工况比较规则、限定适用规模CP-SAT、真实训练的PPO；另列求解/训练墙钟开销。
- 动态工况包含维修停机、随机加工时间、临时到达晶圆；在线策略只能看已发生事件和明确宣布的计划。
- 五轮自主反馈在验证集运行，选定策略冻结后在保留测试集评价。测试指标不得用于下一轮选择。
- 消融使用同一训练数据、候选工具、轮数和计算预算，关闭指标驱动选择并保持预先声明的固定策略/参数；完整与消融在同一保留测试集比较，报告预算差异。
- 报告所有seed的均值、标准差及配对差值/置信区间，而非只展示最佳一次。优于固定策略是待检验假设；负结果同样如实保留。

七类图从实际产物生成：设备图来自已校验配置；甘特图、故障前后图来自事件轨迹；WPH与腔室利用率图来自逐seed结果；反馈曲线来自迭代历史；训练奖励图来自真实Monitor/训练日志。未训练时不能生成假的训练曲线。

## 8. 严格九阶段实施与验收

| 顺序 | 实际工作 | 本阶段结束前必须验证 |
| --- | --- | --- |
| 1 当前分析 | 本文、可重复审计、首批清单、复用和许可证边界 | AST审计、目录/密钥边界与审计CLI测试；记录环境限制 |
| 2 最小仿真 | JSON设备/路线/耗时配置；事件引擎；单晶圆完整取运放/加工/卸载 | 手算时间线；事件同时发生；机器人/腔室唯一占用；守恒；故障暂停恢复 |
| 3 规则基准 | FIFO、最早可执行、阻塞优先；统一指标与验证 | 多晶圆并行加工；工艺顺序；非法动作拒绝；死锁与可恢复等待；可复现轨迹 |
| 4 CP-SAT | 有限批次静态模型及计划重放；动态滚动求解 | 极小实例穷举对照；求解状态/下界；所有计划经相同仿真合法性校验 |
| 5 MDP/RL | Gymnasium、mask、真实MaskablePPO训练与保存 | 环境接口；seed一致；合法动作；终止/截断；模型加载后真实评价；训练日志 |
| 6 自主反馈 | 实际Semantica记忆/图调用；五类已实现Skill；反馈选择与恢复 | 至少五轮真实CSV/JSON；历史变化改变策略；失败记录；测试集无反馈泄漏 |
| 7 对照与消融 | 四组实验、多个训练/测试seed、配对比较 | 训练/验证/测试隔离；共用扰动；约束全部复核；计算预算公开 |
| 8 图表与报告 | 七类真实图、中文报告、PDF | 数值与源CSV/JSON一致；PDF逐页渲染检查；来源引用及局限 |
| 9 GitHub复现 | 锁文件、运行命令、清洁检出、CI与许可证说明 | 新环境从配置重建结果；依赖检查；无数据库/密钥入库；完整阶段测试 |

第一阶段以后按表顺序推进，前一阶段的最小运行与必要测试通过后再接下一阶段；不能用测试替身的训练日志作为实验结果。

## 9. 来源、许可证与已知局限

- 当前Git远程：`yanq458-tech/complex-organization-platform`与`ProfGuan/complex-organization-platform`；本地基线以本文完整SHA为准，不声称远程已更新。
- Semantica来源由锁文件及 `frontend/UPSTREAM.md`记录：`https://github.com/semantica-agi/semantica`，MIT原文保留在 `frontend/LICENSE.semantica`。复用上游文件须保留版权/许可说明。
- 当前仓库未找到顶层LICENSE；不能将上游MIT自动当成整个平台的授权。最终研究代码的许可证须由权利人确定，同时保留上游通知。
- 本机Semantica来源与锁文件安装方式不同，现有Python 3.11环境失效；原平台完整回归和上游真实调用尚未在本轮验收。
- 最小设备限制单夹爪、单容量、无缓冲与暂停恢复故障，不代表完整工业设备。CP-SAT规模、动作层次、可观测性、PPO折扣约定都必须随实现与报告披露。
- 预期创新为阻塞/负载诊断驱动的策略与参数选择、事件持续时间积分奖励、合法动作共享验证及配对动态扰动实验；这些目前是研究假设，不能提前宣称产能提升。

## 10. 第一阶段实际验证记录

本轮生成清单枚举527个第一方文件，解析127个Python文件，未发现语法/编码错误或文件读取错误；九项已有平台能力均找到对应源码和顶层定义。这是静态源码验收，不代表127个模块已成功导入运行。

`python -m unittest discover -s tests/wafer_sched -p "test_*.py" -v`：运行8项测试，7项通过，1项因当前Windows不允许创建符号链接而跳过。覆盖扫描不执行源码、密钥/运行文件排除、语法与编码失败、静态能力判定、重复输出、非零失败退出和输出路径边界；符号链接边界测试在具备权限的环境中继续执行。

原平台完整测试未执行：系统解释器缺少平台依赖，旧Python3.11虚拟环境无法启动。本阶段没有修改原平台求解器、实时数据、运行journal或前端，也未创建实验指标、训练成功记录或PDF占位文件。
