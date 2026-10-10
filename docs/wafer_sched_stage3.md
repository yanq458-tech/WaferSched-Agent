# WaferSched-Agent 第三阶段：规则基准与自适应启发式

本阶段在第二阶段代码上增量完成，遵循已有架构文档。新增研究代码位于 `src/wafer_sched/`，没有改变铁路业务、仿真状态转移、事件优先级或第二阶段的指标公式。实际执行五个场景、五种策略、种子0及7，共50次完整运行。没有实现CP-SAT、强化学习、LLM或跨实验自主迭代。

## 1. 检查结论与实施顺序

开发前阅读 `architecture_analysis.md`、`wafer_sched_stage2.md`、设备配置、仿真器、验证器、指标、产物和测试。现有模型已经支持同一工序多个候选腔室，因此并行场景不需要修改物理模型。两份历史文档保留原内容。

`Simulator.submit()`及`advance_next()`会处理完当前时刻的全部事件，包括零时长后继事件，才返回。机器人忙碌期间由运行器继续执行事件，机器人空闲时产生策略决策；无法传输但有事件时显式选择 `wait`。原始 `snapshot()`包含未来队列与未释放晶圆，是审计接口，不能直接用于在线策略。

实际按只读观测→策略与解释→受约束运行器→真实场景→测试→完整对照→图表与总结的顺序完成。保留原验证驱动器，第三阶段使用新的策略运行器。

## 2. 文件清单

| 文件 | 操作与用途 |
| --- | --- |
| `src/wafer_sched/observation.py` | 新增：白名单观测、递归只读值、已发生事件的历史积分 |
| `src/wafer_sched/policies/__init__.py` | 新增：规则策略接口导出 |
| `src/wafer_sched/policies/rules.py` | 新增：Policy、四种规则、自适应阈值、评分解释和策略工厂 |
| `src/wafer_sched/policy_runner.py` | 新增：决策边界、动作验证、事件推进、预算、决策日志 |
| `src/wafer_sched/scenarios.py` | 新增：加载研究场景清单和物理配置 |
| `src/wafer_sched/experiments.py` | 新增：50次对照、共同窗口、重放校验、CSV与产物CLI |
| `src/wafer_sched/reporting.py` | 新增：真实状态区间甘特图、持久CSV指标图、压缩日志读取 |
| `src/wafer_sched/artifacts.py` | 修改：可选无损压缩事件JSON、递归记录策略源码hash；默认第二阶段JSON输出保持兼容 |
| `configs/wafer_sched/B_batch.json`、`C_bottleneck.json`、`D_parallel.json`、`E_long_robot.json` | 新增：四个设备与任务案例；A复用原始配置 |
| `configs/wafer_sched/stage3_suite.json` | 新增：五场景路径、预先声明窗口、种子 |
| `tests/wafer_sched/test_policies.py` | 新增59个参数化测试实例 |
| `requirements-wafer.txt`、`requirements-wafer.lock.txt` | 修改：加入实际安装的绘图依赖；独立环境完整版本锁 |
| `README.md` | 修改：真实阶段状态、结果入口与复现命令 |
| `docs/wafer_sched_stage3.md` | 新增：本验收报告 |
| `results/wafer_sched/stage3/` | 生成：50组真实产物、比较CSV、决策CSV、图表、测试XML |

本轮未修改 `simulator.py`、`verification.py`、`metrics.py`、铁路API、RDF、数据库或业务脚本。工作区已有第一、二阶段未提交变更保持原样，不能将整个 `git diff` 都归为本阶段修改。

## 3. 统一策略接口与信息边界

```python
from src.wafer_sched import Simulator, load_config
from src.wafer_sched.policies import FIFOPolicy
from src.wafer_sched.policy_runner import run_policy

sim = Simulator(load_config("configs/wafer_sched/minimal_demo.json"), seed=0)
run = run_policy(sim, FIFOPolicy())
assert run.outcome["status"] == "completed"

# 所有新策略实现相同契约：
# select_action(observation: Observation, legal_actions: tuple[Action, ...]) -> Action
```

`Observation`是冻结且带slots的数据类，内部字典转换为只读Mapping，列表转换为元组。没有Simulator引用、内部队列、事件序号、未来维修开始/恢复时间、未来释放时间或未释放晶圆。设备的名义工艺耗时、方向性运输耗时、当前加工剩余时间已知；当前故障可用性可见，预计恢复时间不可见。已释放晶圆的完整工艺路线可见。这沿用第二阶段的剩余时间可观测假设。

历史只从已执行日志逐段积分，包含各腔室加工/阻塞秒、历史阻塞率、机器人活动比例；还维护当前工序传输任务的就绪时刻和连续空闲年龄。适配器内部读取审计日志，但仅发布白名单值，策略不能获得适配器对象。它属于单次运行，不能复用到另一个仿真器。

合法动作由原 `Simulator.legal_actions()`生成。规则只比较完整 `transfer/unload`，有可执行传输时不主动等待；无传输时选择目录内的 `wait`。wait掩码会表明系统可以通过事件继续推进，但不暴露事件时间或内容。诊断用手动取放动作不混入规则基准；输入原子动作会明确报错。

运行器再次校验选择是否在目录中且合法，拒绝时保留状态并报告 `invalid_policy`与一次真实拒绝；不会换动作掩盖错误。事件后物理状态验证仍由原仿真器执行，验证失败直接报错。无动作无事件报告死锁；步数或时间预算超限报告截断。默认总步骤预算100000，包括忙碌机器人微事件，保证等待策略不会无限循环。策略仅获得数值接口；该隔离不是针对任意恶意Python代码的进程安全沙箱。

## 4. 五种策略的数学定义

设合法任务a传输晶圆w，来源s，目的d；决策时间t。`u(a)=1`表示卸片，`b(a)=1`表示来源腔室当前阻塞。当前任务就绪时刻为首次释放或上一工序实际完成时刻，等待年龄 `A(a)=t-ready_since(w)`。它是本次传输的排队年龄，区别于评价指标中的晶圆全程累计等待；同晶圆的不同候选目的地共享年龄。

名义机器人耗时（秒）为

```text
D(a) = travel(robot_position,s) + pick + travel(s,d) + place
P(a) = 当前晶圆下一工序在目的腔室的名义加工秒数；卸片取0
E(a) = t + D(a) + P(a)
```

合法目录保证目标当前可放片，不需要虚构一个未来资源释放时刻。所有规则按下面的键取字典序最小值，最终统一用晶圆ID、目的ID消除并列，不依赖集合遍历顺序：

| 策略 | 优先级键 | 解释 |
| --- | --- | --- |
| FIFO | `(-A, -u, wafer_id, destination)` | 最大任务等待年龄；并列先卸片，传输和卸片用相同秒数比较 |
| SPT | `(-u, P, -A, wafer_id, destination)` | 先卸片释放末端资源，再优先短下一工序，最后按年龄 |
| ECT | `(E, -A, -u, wafer_id, destination)` | 最早下一工序完成/卸载时刻，包含空载定位；不是整片所有后续工序完成时间 |
| Bottleneck-Aware | `(-Score, -A, wafer_id, destination)` | 综合释放阻塞、供给剩余负荷大的腔室、饥饿、年龄、卸片及运输代价 |

ECT不读取预排未来事件；未来未宣布故障可能使实际完成时刻不同于估计值。

瓶颈评分先计算已释放未完成晶圆的剩余服务负荷 `L_c`：将未开始工序的名义耗时平均分摊给合法候选腔室；已在加工/暂停的当前工序只加入所在腔室的已知剩余秒数。它是负荷代理，不是精确最优分配，也不保证识别全局瓶颈。令 `ell_c=L_c/max(1,max L)`，不存在的LOAD/OUT位置取0；`r=max(1,设备最大名义工艺秒数)`；`I_d`为目的腔室连续可用、无占用无预留的空闲秒数。

默认评分全部无量纲：

```text
Score = 4*b*(1 + ell_s + min(A/r,2))
      + 3*ell_d
      + ell_d*min(I_d/r,2)
      + 0.5*min(A/r,4)
      + u
      - D/r
```

当前等待队列通过年龄和剩余任务负荷影响评分。记录每个候选的六项带符号贡献、总分、时间参考量、来源/目的负荷比例和最终排序键；没有只返回一个不可解释动作。

自适应启发式每次决策从以下有序反馈条件选择规则，阈值由冻结的 `AdaptiveThresholds`明确提供：

1. 当前至少一腔阻塞，且阻塞腔比例≥0.5 **或** 历史阻塞腔秒/(腔数*t)≥0.12：使用瓶颈评分，释放阻塞权重由4增至8。
2. 否则，最大剩余负荷腔室具有合法供片动作，且空闲年龄/r≥0.25：使用瓶颈评分，供片权重由3增至8。
3. 否则，当前waiting晶圆数≥4：历史机器人活动秒/t≥0.65时用ECT，低于该值时用SPT。
4. 其余使用FIFO。

t=0时历史比例为0。waiting数量包含已加工待传输晶圆及装载区待加工晶圆，不含加工中/运输中晶圆。每次记录规则、触发条件、上一规则、是否切换、阈值、当次权重及实际证据。切换来自实际设备反馈，不按预设轮次或时间表切换。本阶段没有学习阈值，也没有跨实验调整下一轮策略。

## 5. 实际配置与评价口径

每片路线均为清洗→漂洗→OUT，0秒释放，单机器人单夹爪、腔室容量1、无缓冲。同一场景所有方法使用同一JSON任务和设备。B/E用两类晶圆形成真实可区别的下一工序耗时；D只在清洗阶段具有替代资源，漂洗不能由清洗腔代做。

| 场景 | 晶圆数 | 清洗秒 | 漂洗秒 | 取/默认移动/放秒 | 腔室数 | 固定窗口T秒 |
| --- | ---: | --- | --- | --- | ---: | ---: |
| A_demo | 3 | 4 | 6 | 1/1/1 | 2 | 80 |
| B_batch | 12 | 奇数ID为4、偶数为7 | 奇数6、偶数9 | 1/1/1 | 2 | 400 |
| C_bottleneck | 12 | 3 | 24 | 1/1/1 | 2 | 600 |
| D_parallel | 12 | CLEAN=5、CLEAN_ALT=9，可替代 | RINSE=8 | 1/1/1 | 3 | 400 |
| E_long_robot | 10 | 奇数4、偶数7 | 奇数6、偶数9 | 3/6/3 | 2 | 1000 |

窗口在 `stage3_suite.json`中预先声明，非根据最佳结果修改。全部完成后通过原 `run_until(T)`加入观测边界事件，继续处理已有事件，不直接改时钟。主指标与第二阶段完全相同：

- Makespan：最后一片实际卸载时刻；不会因观测到更晚T而改变。
- 主WPH：`完成数*3600/T`；腔室利用率为实际processing秒/T，均值为各腔算术均值；机器人利用率为实际取、空载/载片运输、放片秒/T。
- 辅助 `completion_batch_wph`：`完成数*3600/Makespan`，明确以各自批次完成时刻为分母，不能与共同窗口主WPH混用。
- 平均等待与总阻塞沿用真实状态积分定义，阻塞包括加工结束至取片完成的占腔时间。完整任务完成后不再增加等待和阻塞。
- 约束违反次数：记录策略边界实际拒绝；物理状态验证错误会使运行失败，不会被记成成功的零违反。此次全部运行通过逐事件验证且无动作拒绝。
- 策略执行秒：`perf_counter`累计 `select_action`墙钟耗时，包含评分和解释生成，不含仿真、适配器、写盘、绘图；不同机器和重放可能改变该列。

两组seed仅检查确定性重放。设备没有随机采样，两组完全相同的事件/决策不构成50个独立随机样本；不计算虚假的置信区间，不将不同规模场景的WPH直接作算法改进证据。

## 6. 真实对照数据

[comparison.csv](../results/wafer_sched/stage3/comparison.csv)保留50行完整精度数据，包含执行耗时与全部验收列。下表列seed0；seed7的仿真指标、事件及决策完全一致，仅墙钟耗时变化。

| 场景 | FIFO Makespan | SPT | ECT | 瓶颈评分 | 自适应 | 完成数（各策略） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 47 | 47 | 47 | 47 | 47 | 3 |
| B | 197 | 192 | 192 | 197 | 192 | 12 |
| C | 388 | 388 | 388 | 388 | 388 | 12 |
| D | 198 | 198 | 198 | 202 | 198 | 12 |
| E | 535 | 535 | 535 | 535 | 535 | 10 |

所有时间为秒；所有50行的约束违反次数均为0。共同窗口指标如下，在本次每个场景内均对所有策略相同：

| 场景 | 主WPH片/小时 | 平均腔室利用率 | 机器人利用率 |
| --- | ---: | ---: | ---: |
| A | 135 | 18.75% | 41.25% |
| B | 108 | 19.50% | 35.25% |
| C | 72 | 27.00% | 23.50% |
| D | 108 | 15.00% | 35.25% |
| E | 36 | 6.50% | 52.20% |

有限批次全部完成时，共同窗口WPH相同是公式的必然结果；总加工秒、总机器人活动秒在本次配置及实际分配下也相同。不能据此宣称算法提升了主WPH或利用率。批次完成更早体现在Makespan、完成窗口WPH和等待上。

| 场景/方法 | 完成窗口WPH | 平均等待秒 | 总阻塞腔秒 |
| --- | ---: | ---: | ---: |
| A/全部 | 229.787 | 14.667 | 14 |
| B/FIFO、瓶颈评分 | 219.289 | 86.917 | 71 |
| B/SPT、ECT、自适应 | 225.000 | 80.667 | 66 |
| C/全部 | 111.340 | 176.917 | 277 |
| D/FIFO、SPT、ECT、自适应 | 218.182 | 87.750 | 223 |
| D/瓶颈评分 | 213.861 | 91.750 | 231 |
| E/全部 | 67.290 | 256.500 | 375 |

50次运行的策略累计墙钟耗时约0.103–11.878毫秒，原始秒数在CSV。运行过程中有测试和绘图负载，该单次耗时用于透明记录开销，不能作为稳定的算法性能排名。

## 7. 自适应实际触发与动作变化

[adaptive_decisions.csv](../results/wafer_sched/stage3/adaptive_decisions.csv)包含两组种子的每次自适应决策，包括显式等待。初始化规则选择单独记录，下面的切换数不包含初始化：

| 场景(seed0) | FIFO次数 | SPT次数 | ECT次数 | 瓶颈评分次数 | 后续规则切换数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 7 | 0 | 0 | 6 | 7 |
| B | 8 | 2 | 16 | 24 | 30 |
| C | 8 | 14 | 3 | 35 | 27 |
| D | 1 | 1 | 4 | 43 | 6 |
| E | 4 | 1 | 7 | 20 | 22 |

B的实际决策片段：

| 决策序号/秒 | 实际证据 | 选择 |
| --- | --- | --- |
| 0/0 | waiting=12，机器人历史比例0 | queue_pressure→SPT，供W01到CLEAN |
| 1/3 | waiting=11，历史机器人比例1 | queue_and_robot_pressure→ECT；无传输则等待 |
| 2/7 | 当前阻塞腔比例0.5 | blocking_pressure→瓶颈评分，W01转RINSE |
| 3/10 | waiting=11，历史机器人比例0.6 | queue_pressure→SPT，W03转CLEAN |
| 4/14 | waiting=10，历史机器人比例约0.7143 | queue_and_robot_pressure→ECT |
| 33/116 | waiting=3，当前没有阻塞 | normal_state→FIFO |

在t=10的同一观测和合法目录上，固定FIFO会选W02，实际自适应选择加工4秒的W03。此比较由保存的决策观测重新调用FIFO得到，证明实际动作发生变化，不只是修改策略名称。

D的序号3、t=8秒实际触发 `bottleneck_starvation`：RINSE为最大剩余负荷腔、存在合法供片，空闲比例8/9≈0.8889，当前阻塞比例1/3、历史阻塞率0未达到阻塞阈值，因此选择供片权重8并将W01转入RINSE。D中其余42次瓶颈选择来自阻塞压力。所有五类触发条件均有单元测试，其中饥饿触发还在真实实验中发生。

这些切换不证明其额外收益来自反馈。B的自适应结果与固定SPT/ECT相同；本阶段没有按计算预算匹配的跨实验反馈消融，因果改进仍待后续验证。

## 8. 优劣分析与已知问题

FIFO透明且稳定，但B中等待年龄优先使短工序晶圆不能提前处理，实测完成时间和平均等待略高。SPT与ECT在B均提前5秒完成，其他多数案例持平；不能据此认定二者普遍等价。SPT不考虑运输代价，ECT只估计下一工序，不优化整批完工时间，两者均可能使长工序等待。

瓶颈评分可解释且响应阻塞，但对替代腔室采用等比例负荷分摊，较慢腔室可能得到更大负荷权重。D中它首先把W01送到9秒的CLEAN_ALT，普通规则首先选5秒的CLEAN；实测Makespan增加4秒、总阻塞增加8腔秒。这是被保留的负结果，提示服务能力估计和供片/释放权重存在改进空间。

自适应依据当前与历史指标实际切换，B与SPT/ECT同为192秒，D避免了默认瓶颈评分的退步，但没有超越最佳固定规则。C的慢漂洗和E的长机器人动作主导排程，所测规则均持平，没有最优性证明。E机器人实际活动522秒，批次535秒；主窗口T=1000下利用率52.2%，不能将这个带完工后空闲的数值直接解读为机器人资源宽裕。

继承第二阶段的单夹爪、单腔容量、无缓冲限制。存在循环路线时，合法贪心规则仍可能走入物理死锁，运行器会记录原因，不具有死锁避免保证。观测隔离保障本项目正常策略的数据访问边界，不是恶意代码安全沙箱。加工时间确定、剩余时间已知，未实现随机扰动、多轮研究反馈、阈值训练或稳态长时间评价。

Matplotlib图使用英文资源/指标标签避免本机中文字体缺失，中文说明在本文。观察适配器本轮以历史累计积分支持规则，未来强化学习若要求严格Markov状态，还需审核这些累计统计的充分性和固定槽位编码。

## 9. 真实产物与复现

实验入口：

```powershell
.venv_wafer\Scripts\python.exe -m pip install -r requirements-wafer.lock.txt
.venv_wafer\Scripts\python.exe -m src.wafer_sched.experiments --output results/wafer_sched/stage3-replay --seeds 0 7
```

输出目录必须不存在；已存在则明确拒绝覆盖。改变场景需编辑对应JSON及清单，但应创建新的输出目录，不能改历史产物。`manifest.json`保存实际输入配置、T、seed、策略、运行状态、50次计数及重放校验结果。每个run另存实际config及SHA-256、所有研究Python源码hash、Python版本和约束结果。

每个运行目录含 `events.json.gz`（完整前后状态及未来审计队列）、`events.csv`、`events.txt`、`decisions.json.gz`（只读观测、合法目录、候选评分和解释）、`config.json`、`metrics.json`、`final_state.json`、`state.json`及 `gantt.png`。未来队列只出现在审计产物，未传递给策略。完整产物约12MB，无需保存虚拟环境。

JSON读取和重算示例：

```python
import gzip, json
from pathlib import Path
from src.wafer_sched.metrics import calculate_metrics
from src.wafer_sched.reporting import read_events

directory = Path("results/wafer_sched/stage3/B_batch-adaptive-s0")
assert calculate_metrics(read_events(directory)) == json.loads(
    (directory / "metrics.json").read_text(encoding="utf-8"))
with gzip.open(directory / "decisions.json.gz", "rt", encoding="utf-8") as stream:
    decisions = json.load(stream)
```

图表全部从保存的日志或CSV生成，甘特图积分实际状态区间，不读取开始事件中的预计结束值。已查看并行案例甘特图及Makespan图，资源、工序、阻塞与坐标正常。

- [主窗口WPH图](../results/wafer_sched/stage3/wph.png)
- [腔室利用率图](../results/wafer_sched/stage3/chamber_utilization.png)
- [Makespan图](../results/wafer_sched/stage3/makespan.png)
- [辅助完成窗口批次WPH图](../results/wafer_sched/stage3/completion_batch_wph.png)
- [自适应批量甘特图](../results/wafer_sched/stage3/B_batch-adaptive-s0/gantt.png)
- [并行瓶颈评分甘特图](../results/wafer_sched/stage3/D_parallel-bottleneck-s0/gantt.png)
- [可直接阅读的真实事件序列](../results/wafer_sched/stage3/B_batch-adaptive-s0/events.txt)

完成后实际读取全部50组压缩事件和决策，重新计算metrics，逐列核对比较CSV、动作目录、重放hash、当前源码hash和甘特图存在性，全部一致；结果见 [最终核验JSON](../results/wafer_sched/stage3/verification.json)。两seed相同场景/策略的事件和决策hash一致，墙钟耗时不纳入确定性hash。

## 10. 测试、环境与平台回归

继续使用第二阶段独立 `.venv_wafer`，原 `.venv`及 `.venv_optimization`未改。真实环境Windows、CPython3.13.13；新增Matplotlib3.10.8及其绘图依赖，完整版本来自实际 `pip freeze`。源码目标3.11+，完整依赖锁只在3.13验收；不能保证将该锁直接装到3.11。

实际执行：

```powershell
.venv_wafer\Scripts\python.exe -m pytest tests/wafer_sched -v --junitxml=results/wafer_sched/stage3/wafer_tests.xml
.venv_wafer\Scripts\python.exe -m pytest tests/test_local_runtime_compatibility.py -v --junitxml=results/wafer_sched/stage3/platform_regression.xml
.venv_wafer\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched tests/conftest.py
.venv_wafer\Scripts\python.exe -m pip check
```

研究测试108项：**107通过、1跳过**，包括本轮59个实例全部通过，第二阶段41个实例全部通过。跳过项是第一阶段Windows符号链接创建权限测试，与策略功能无关。新增测试检查合法动作、深层只读与状态不变、未来配置变化不影响观测、五策略完整路线、并行分配、预算退出、精确单片19秒/指标、确定性日志、FIFO/SPT/ECT排名、评分加和、五类自适应阈值、历史压力、真实多规则切换、9秒循环死锁、28秒故障/延迟释放流程、压缩指标重算及甘特区间。没有为了通过测试改变原数学约束。

原平台非破坏性回归4项全部通过，覆盖跨进程租约、进程退出释放、中文日志写入失败保护和Windows文件替换失败保护。使用临时目录，没有访问业务库。ruff通过；pip check无冲突。未安装和运行完整Semantica/RDF/API/前端测试，不能称为全平台完整验收。

原始记录：[研究测试XML](../results/wafer_sched/stage3/wafer_tests.xml)、[平台回归XML](../results/wafer_sched/stage3/platform_regression.xml)。

## 11. 下一阶段CP-SAT建议（尚未实现）

保留相同Policy接口、观测适配器、合法目录和运行器。CP-SAT适配器只能依据已释放任务、已知路线、当前占用/剩余耗时生成有限时域计划；输出当前目录内的首个动作，后续计划由同一仿真器逐步重放。等待仍通过当前合法wait执行，重新规划不可直接写时钟或设备状态。

必须显式建模加工至取片完成的占腔区间、单机器人互斥、路线顺序、空载定位和卸载时间；如果简化定位或阻塞，应给出适用范围，并用匹配设备假设比较。新增求解状态、墙钟预算、目标、下界/gap与计划可执行性验证，不把有限时域或简化模型的最优解称为完整设备全局最优。本阶段仅提供这套可复用接口和真实规则基准，没有求解器实现。
