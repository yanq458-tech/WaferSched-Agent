# WaferSched-Agent 第二阶段：离散事件仿真器验收

日期：2026-10-10（Asia/Shanghai）。本阶段在现有工作区增量实现，开发前读取并遵循 `architecture_analysis.md`；没有重新扫描覆盖第一阶段清单，没有修改铁路求解模型或实时业务数据。

## 1. 已完成范围与模型约定

实现确定性设备模型、JSON配置、事件队列、单片机器人、工艺路线、资源预约、独立约束验证、验证用驱动器、日志产物及日志积分指标。支持2或3腔室案例，配置可扩展更多腔室。工序指定recipe和合法腔室集合；不同工序不能无条件互换腔室，同一工序的不同候选腔室可具有不同加工时间。

沿用架构中首版物理假设：机器人容量严格为1，每腔室容量严格为1，无中间缓冲；JSON中的容量字段会被校验，其他容量明确拒绝，不能仅修改字段获得多片设备。

高层 `transfer/unload`从接受动作到放片完成一直独占机器人。为验证非法取放片和位置约束，另外提供诊断用 `pick/move/place`原子动作；它们不插入正在执行的高层传输。下一阶段的策略候选集合默认使用完整传输，避免把不同动作粒度混在算法比较中。

本阶段没有规则优化基准、CP-SAT、强化学习、Skill注册器或LLM决策，也未宣称实现自主优化。Semantica上下文/记忆集成依旧按原方案留到第六阶段；设备数学核心无需启动Semantica或业务数据库。

## 2. 文件清单

本阶段新增研究实现全部位于 `src/wafer_sched/`：

| 文件 | 主要功能 |
| --- | --- |
| `__init__.py` | 导出Simulator、Action、配置和独立验证接口 |
| `config.py` | RobotConfig、ChamberConfig、RouteStep、WaferConfig、Downtime、EquipmentConfig；JSON读写及耗时/路线/容量校验 |
| `equipment.py` | RobotState、ChamberState、WaferState、EquipmentState与深拷贝快照 |
| `actions.py` | 完整传输、卸载、等待及诊断取片/移动/放片动作 |
| `events.py` | 按时间、优先级、稳定sequence排序的Event |
| `simulator.py` | Simulator事件推进、动作执行、占用语义、暂停恢复与潜在死锁诊断 |
| `verification.py` | 不修改状态的validate_action、validate_state和带原因的ValidationResult |
| `metrics.py` | 从事件快照积分重算指标 |
| `driver.py` | 只用于验证的合法动作驱动器与时间/决策预算 |
| `artifacts.py` | 复用平台原子写入、持久替换和run_id，发布不可覆盖的研究产物 |
| `demo.py` | 仓库内真实演示CLI |

其他新增文件：

- `configs/wafer_sched/minimal_demo.json`：两阶段、两腔室、三晶圆配置。
- `tests/wafer_sched/conftest.py`、`test_simulator.py`、`test_artifacts.py`：研究测试。
- `requirements-wafer.txt`：直接测试依赖；`requirements-wafer.lock.txt`：本轮真实环境的完整依赖版本。
- 本文与下方列出的两组真实运行产物。

修改文件：`README.md`更新阶段状态和命令；`.gitignore`排除独立环境；`tests/conftest.py`把铁路数据库/应用导入移到实际使用它们的fixture中，保持fixture逻辑不变。这样研究测试和平台纯文件回归可以独立收集，不要求安装整个平台。

第一阶段的架构分析、清单、审计脚本和审计测试保持原内容。没有改动任何 `api/`、铁路脚本、RDF或前端实现。

## 3. 主要接口

```python
from src.wafer_sched import Action, Simulator, load_config
from src.wafer_sched.metrics import calculate_metrics

sim = Simulator(load_config("configs/wafer_sched/minimal_demo.json"), seed=0)
result = sim.validate_action(Action.transfer("W1", "CLEAN"))
assert result.valid
sim.submit(Action.transfer("W1", "CLEAN"))
sim.advance_next()  # 到最早事件时间，并处理该时刻的所有事件
assert sim.validate_state().valid
```

- `validate_action(state, config, action)`和`validate_state(state, config)`也可独立调用。
- `submit(action)`返回ValidationResult；非法动作给出例如`robot_busy`、`empty_chamber`、`robot_not_carrying`、`chamber_full`、`process_unfinished`、`route_order`原因，状态、事件队列与日志不变。
- `legal_actions()`提供经过相同验证器筛选的完整传输/卸载及必要等待。
- `advance_next()`只推进到事件队列的最早时间，处理全部同时刻事件；无事件时不修改时间。
- `run_until(T)`添加真实观测边界事件，先处理所有不晚于T的操作，不会跳过取放片或加工。
- `snapshot()`返回与内部状态分离的审计快照，包含机器人、晶圆、腔室、历史记录和完整事件队列。
- `detect_deadlock()`在未完成批次、没有可行完整传输且没有未来事件时记录潜在死锁及等待资源/拒绝原因；加工或恢复事件尚存在时应等待。它是本模型下的诊断，非任意制造系统的完备死锁证明。
- `calculate_metrics(trace)`只依赖事件日志，可以读取已保存JSON后重算，不读取配置中的理论统计值。

每个处理过的事件后执行状态验证；状态验证失败会明确抛出错误，不自动修补状态。

## 4. 事件与资源占用语义

时间单位为秒；队列键为 `(time, priority, sequence)`。同一时间优先序：故障开始 → 恢复 → 加工完成 → 晶圆释放 → 机器人操作完成 → 新机器人操作开始 → 加工开始 → 晶圆完成。相同优先级按插入sequence处理，所有同时刻事件处理完才返回决策点。

机器人位置表示最近抵达的位置，移动过程中由phase、目的地和剩余动作时间共同表示在途状态。

| 操作/事件 | 开始时 | 完成时 |
| --- | --- | --- |
| 完整传输接受 | 机器人置忙，预约合法目的腔室；需要时先空载定位 | 直到最终放片完成才解除整段占用 |
| RobotPick | 晶圆仍占来源腔室/装载位置，机器人正在取片 | 从来源移除，机器人真实携片；此时释放来源容量 |
| RobotMove | 占用机器人；空载定位和携片移动均耗时 | 更新抵达位置；携片晶圆一直在ROBOT位置 |
| RobotPlace | 晶圆仍由机器人携带，目的容量处于预约状态 | 移入目的腔室/输出，释放夹爪与预约 |
| ChamberProcess | 放片完成后开始，占用本腔室；其他腔室可并行加工 | 工艺stage增加，晶圆仍在腔室，状态blocked |
| WaferCompleted | 仅在完整工艺和最终输出放片之后排队 | 记录完成时间，增量完成数量恰好一次 |

支持一般路线、重复访问同一腔室、并行候选腔室、方向性旅行时间、配置中的延迟释放及停机窗口。两个装载端口LOAD/OUT表示同一装载单元的输入/输出位置，不是两个机器人或额外中间缓冲。

故障采用暂停恢复：停机时保留加工剩余时间；恢复后继续，不重复计工艺阶段。目的腔室在携片途中或放片途中停机时，保留夹爪晶圆及目的预约，冻结未完成放片耗时直到恢复。首版停机禁止新放片，但不禁止从已完成加工的腔室取片，这是设备可访问性的明确简化假设。

故障开始与加工完成同一时刻时，故障先处理：即使剩余加工时间为0，阶段完成通知也延至恢复，活动加工积分不增加。相邻停机窗口不会短暂误恢复。

开始事件的`end_time`是计划结束；完成事件的`end_time`是真实结束，日志中用`interval_semantics`区分。暂停可能取消原计划完成事件；故障事件的前后状态和恢复后的新开始事件会保留真实过程。指标依据实际状态区间，不按被取消的计划结束时间统计。

## 5. 指标严格定义

由相邻日志时间`t_i`到`t_{i+1}`的`state_after`状态积分，默认观测窗口`[0,T]`，T是最后一个日志时间。通常演示在最后一片完成时停止，也允许显式观测至更晚的T。

| 指标 | 定义与单位 |
| --- | --- |
| Makespan | 全批次完成时最后卸载完成时间减0，秒；未完成批次为null，不以截止时间冒充makespan |
| 有限批次WPH | `completed * 3600 / T`，片/小时；不是稳态WPH |
| 单腔室利用率 | 实际处于processing的秒数/T；阻塞和停机不进分子，停机保留在观测分母 |
| 平均腔室利用率 | 各腔室利用率的算术平均 |
| 机器人利用率 | 取片、空载定位、携片移动、实际放片秒数/T；等维修时不进入分子，另报recovery wait |
| 晶圆等待 | 已释放、未完成，既不在实际加工、也不在本片取片/携片移动/放片操作中的时间积分，秒 |
| 平均等待 | 完成晶圆的累计等待之和/完成数；另报全体已释放晶圆的平均及未完成数，避免截断偏差 |
| Blocking Time | 各腔室从加工完成到取片完成的占腔秒数之和，包括取片耗时 |
| Blocking Rate | 总阻塞腔室秒/(腔室数*T) |

加工完成到取片开始之间属于晶圆等待；取片操作本身不属于等待，但来源腔室尚未释放，因此仍属于阻塞。这两个物理定义不同，不应直接把阻塞秒数作为平均等待。

晶圆在装载区等待机器人的空载定位、加工暂停、携片等待恢复均计等待；尚未释放的时间不计等待。诊断模式中的空闲持片也计等待，不算机器人有效运行时间。

零时长配置在有限事件链内可完成，makespan为0；由于分母为0，WPH和利用率为null，不输出虚构无穷大。负数、NaN、无穷大和布尔耗时均被配置验证拒绝。

## 6. 三片晶圆真实演示

配置：1机器人；CLEAN与RINSE各容量1；W1、W2、W3全部在0秒释放。每片路线严格为`clean@CLEAN → rinse@RINSE → OUT`。取片、移动、放片各1秒；加工clean=4秒、rinse=6秒；同位置移动为0秒。

驱动器仅在合法动作中先卸载、再推进已加工晶圆、再装载输入晶圆，并使用固定ID顺序消除并列；没有搜索、学习或收益反馈。不能把它作为最终优化算法。

| 晶圆 | CLEAN加工区间 | RINSE加工区间 | 卸载完成 | 累计等待 |
| --- | --- | --- | --- | --- |
| W1 | 3–7秒 | 10–16秒 | 20秒 | 1秒 |
| W2 | 14–18秒 | 24–30秒 | 34秒 | 15秒 |
| W3 | 28–32秒 | 38–44秒 | 47秒 | 28秒 |

真实指标：

| 指标 | 实测结果 |
| --- | --- |
| 完成晶圆 | 3/3 |
| Makespan | 47秒 |
| 有限批次WPH | 229.787234片/小时 |
| CLEAN加工秒/利用率 | 12秒 / 25.531915% |
| RINSE加工秒/利用率 | 18秒 / 38.297872% |
| 平均腔室利用率 | 31.914894% |
| 机器人运行秒/利用率 | 33秒 / 70.212766% |
| 平均晶圆等待 | 14.666667秒 |
| 总阻塞 | 14腔室秒：CLEAN=9，RINSE=5 |
| Blocking Rate | 14.893617% |

机器人33秒包括9次取运放的27秒及6秒空载定位；不是只统计携片移动。所有结果来自真实日志积分，没有产能改善百分比或最优性声明。

完整演示保存91条事件/控制记录（含初始化与动作接受）：

- [可读事件序列](../results/wafer_sched/stage2-verified/events.txt)
- [CSV事件日志](../results/wafer_sched/stage2-verified/events.csv)
- [含前后完整状态的JSON事件日志](../results/wafer_sched/stage2-verified/events.json)
- [指标JSON](../results/wafer_sched/stage2-verified/metrics.json)
- [可重新加载的配置](../results/wafer_sched/stage2-verified/config.json)
- [最终状态及工艺/传输记录](../results/wafer_sched/stage2-verified/final_state.json)
- [运行状态、seed、配置及核心源码hash](../results/wafer_sched/stage2-verified/state.json)

日志以原平台`atomic_record`和`durable_replace`发布；run_id复用平台工具。每个目录只创建一次，不覆盖既有运行；全部产物写完才发布最终`state.json`。模拟磁盘写入失败的测试证实不会提前发布“completed”摘要。不创建RunJournal对象、不取得在线平台调度租约。

## 7. 无资源竞争的手算对照

同一设备只放W1：

```text
0–1取片，1–2移动，2–3放入CLEAN
3–7清洗
7–8取片，8–9移动，9–10放入RINSE
10–16漂洗
16–17取片，17–18移动，18–19放入OUT并完成
理论T = 3*(1+1+1) + 4 + 6 = 19秒
```

程序真实完成时间为19秒，断言精确相等。机器人活动9秒、CLEAN加工4秒、RINSE加工6秒、晶圆等待0秒，腔室阻塞共2秒（每腔室完成后的1秒取片占用）。对应27条日志见 [单片真实事件序列](../results/wafer_sched/stage2-single-wafer/events.txt) 与 [单片指标](../results/wafer_sched/stage2-single-wafer/metrics.json)。

额外手算测试：单片三阶段、加工2/3/4秒，需要4次3秒传输，完成时间21秒；两片分别在A/B加工10秒，实际加工区间3–13与7–17，重叠6秒，完成批次时间21秒。

两组保存产物均已从配置重新执行，逐条事件与原JSON相等；已从保存JSON重算所有指标，并核对核心文件hash与当前代码相等。

## 8. 环境与真实测试记录

原 `.venv`、`.venv_optimization`的Python3.11启动路径仍失效；本机可用解释器为CPython3.13.13。创建独立 `.venv_wafer`，仅安装pytest、ruff及其测试依赖；旧环境没有被覆盖。`requirements-wafer.lock.txt`来自实际安装后的`pip freeze`。

在仓库根目录运行：

```powershell
python -m venv .venv_wafer
.venv_wafer\Scripts\python.exe -m pip install -r requirements-wafer.lock.txt
.venv_wafer\Scripts\python.exe -m pip check
.venv_wafer\Scripts\python.exe -m pytest tests/wafer_sched -v
.venv_wafer\Scripts\python.exe -m pytest tests/test_local_runtime_compatibility.py -v
.venv_wafer\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched tests/conftest.py
.venv_wafer\Scripts\python.exe -m src.wafer_sched.demo --print-events
```

已在独立环境实际执行用户要求的pytest检查；显式解释器路径确保不用失效旧环境。若该环境已创建，直接使用它，无须重复创建。默认演示生成新run_id；显式指定已有`stage2-verified`会拒绝覆盖。

结果：研究目录49项，**48通过、1跳过**；其中本阶段新增41项全部通过，第一阶段已有符号链接边界测试因Windows创建链接权限而跳过。原平台非破坏性回归4项全部通过；ruff通过；pip check无依赖冲突。

原始pytest XML记录：[研究测试](../results/wafer_sched/stage2-verified/wafer_tests.xml)、[原平台回归](../results/wafer_sched/stage2-verified/platform_regression.xml)。

测试断言覆盖用户要求的10类场景及具体数值：单片/多片顺序流程、腔室并行区间、机器人互斥、容量/预约、非法取放、工艺先后、相同seed日志一致、同时刻优先序、死锁与未来事件等待；还覆盖维修暂停、携片/放片中断、重复腔室路线、延迟到达、负耗时、零耗时、观测窗口、截断、状态损坏、日志重算、配置重放和写入失败。

四项原平台回归均使用pytest临时目录，检验跨进程租约、进程退出释放、中文日志原子写入失败保护、Windows文件替换失败保护。没有读取/写入实时Oxigraph或在线任务目录。未运行完整平台/RDF/前端测试，因为本阶段未安装完整业务依赖；不能把本轮4项回归称为整个平台验收。

## 9. 已知限制与第三阶段接口建议

- 首版只支持单夹爪、单容量、无缓冲；更复杂夹爪、批式腔室、报废/返工、机械避碰和驻留时间上界没有建模。
- 加工时间确定且残余加工时间可观测；seed仅记录，当前核心不采样随机数。故障与释放由配置预先给出，暂不支持在线追加设备/晶圆或随机扰动采样器。
- 停机暂停加工/放片；已加工晶圆仍可取片。这一可访问性假设需在更真实设备中单独配置和验证。
- 不可行循环保留原状态并诊断潜在死锁，不自动挪到虚构缓冲或修复工艺。保守诊断可能等未来事件处理完后才报告。
- 计时使用浮点秒；完全相同的时间戳按优先级处理，未将近似相等浮点值自动合并。后续高精度设备可用整数时间单位。
- 审计快照包含完整未来事件队列，适合验证/重放，不应直接作为在线策略输入；第三阶段需过滤未来故障/未宣布到达，仅保留当前可观测状态和已知操作完成事件。
- 保存日志可从配置确定性重放；尚未实现从任意中途快照直接恢复执行的公共API。
- 观测日志保存完整前后状态，利于手工检查但会随批次规模增长，后续可增加压缩或增量日志。
- 已验证Windows/Python3.13.13；源码目标Python3.11+，3.11和Linux尚未在本轮重新运行验收。

第三阶段建议统一策略契约为`select_action(observation, legal_actions) -> Action`：策略只选择动作，不改时钟、队列、晶圆或腔室；执行必须通过同一`submit`和验证器。FIFO、最早可执行、阻塞优先各实现独立策略，复用本仿真器、配置、日志与`calculate_metrics`。无动作时用事件等待，预算超限记录truncated；真正死锁保留原因。下一阶段还应建立过滤未来事件的只读策略观测接口，避免动态算法获取未来故障答案。
