# WaferSched-Agent 第四阶段：CP-SAT基准与原仿真交叉验证

日期：2026-10-10（Asia/Shanghai）。先完成[编码前模型审计](wafer_sched_stage4_model_audit.md)，再实现模型、通过小规模回放门禁、增加统一对照和规模实验，最后完成回归。本阶段没有改写Simulator或铁路业务，没有覆盖第三阶段历史结果，没有引入强化学习。

## 1. 验收结论与适用范围

CP-SAT准确表示本轮**静态确定性、空设备初始化、单夹爪单容量、无缓冲、完整transfer/unload宏动作**的问题：包含实际取放耗时、顺序相关空载定位、合法选腔、工序顺序、接受动作时的目标预留、加工结束后的阻塞及取片完成释放。连续同腔工序和一般重入路线均可建模。

这是与第三阶段相同宏动作空间的最优性范围，不包含独立提前定位/原子动作优化、动态故障恢复、任意中途状态、多片夹爪或缓冲。Downtime、零取/放、不能精确量化的时间会明确拒绝。中途仿真器不能用空设备计划回放。模型可接受显式已知释放表，但公平对照全为0秒释放，不向在线规则公开未来事件。所有尚未支持项见审计表及 `model_inconsistencies.json`。

主实验11实例×6算法=66次尝试，另对最大实例追加30秒限时的6算法对照，总计72次。70次完成任务，完成的调度均零约束违反、零死锁；另外2次为CP搜索UNKNOWN，没有CP调度方案。主实验2个实例OPTIMAL、8个FEASIBLE、1个UNKNOWN；追加实验仍UNKNOWN。10份真实CP方案全部通过原Simulator，并从保存计划重新回放，与保存事件逐条一致。

## 2. 新增和修改文件

| 文件 | 内容 |
| --- | --- |
| `src/wafer_sched/cpsat_model.py` | 新增：整数时间域、选腔、工序与占用、机器人Circuit、完整定位耗时、Makespan和验证提示 |
| `src/wafer_sched/cpsat_solver.py` | 新增：SolverOptions、求解状态/上下界、计划提取、日志和运行成本 |
| `src/wafer_sched/schedule_adapter.py` | 新增：受控定时等待和原Simulator逐动作回放，不修改状态/时钟 |
| `src/wafer_sched/cpsat_validator.py` | 新增：模型预测与实际取片、传输、加工、完工时间逐项比较 |
| `src/wafer_sched/stage4_metrics.py` | 新增：已证明最优差距、可行CP方案差值及下界差值，区分证明口径 |
| `src/wafer_sched/stage4_scenarios.py` | 新增：统一场景清单加载及路径/窗口检查 |
| `src/wafer_sched/stage4_experiments.py` | 新增：六算法重新运行、保存计划/求解证明/回放报告、负例及图表 |
| `tests/wafer_sched/test_cpsat.py` | 新增23个测试实例，含大型提示约束兼容性检查 |
| `tests/wafer_sched/test_stage4_experiments.py` | 新增20个测试实例，含真实多决策序列及历史保护 |
| `configs/wafer_sched/F_competition.json`、`G_dual_bottleneck.json`、`H_heterogeneous.json` | 新增三类高区分度场景 |
| `configs/wafer_sched/S_small.json`、`M_medium.json`、`L_large.json` | 新增三个多维规模层次 |
| `configs/wafer_sched/stage4_suite.json`、`stage4_large_retry.json` | 新增主实验和限时追加实验清单 |
| `docs/wafer_sched_stage4_model_audit.md`、`wafer_sched_stage4_preservation.json` | 新增：事前语义审计和468个历史/核心文件hash |
| `docs/wafer_sched_stage4.md` | 新增：本研究总结 |
| `requirements-wafer.txt`、`requirements-wafer.lock.txt`、`README.md` | 修改：独立研究依赖、实际版本锁、当前阶段和复现入口 |
| `results/wafer_sched/stage4/` | 生成：主66行CSV、追加6行CSV、72组审计产物、70张真实甘特图、求解日志/证明、图表和测试记录 |

原 `config.py`、`simulator.py`、`verification.py`、`events.py`、`observation.py`、`policy_runner.py`、规则策略与指标模块不变。已有第一至三阶段工作区未提交变更保持原样；不能将所有未跟踪文件归为本阶段新增。

## 3. 数学模型

所有时间先换算为整数tick。自动scale为配置十进制时间分母的最小公倍数，上限10000；用户可指定能精确表示输入的scale。不能表示时拒绝，不做隐含取整。此次统一案例均为整数秒，测试另验证0.25秒粒度及6.25秒完工。

晶圆w有固定必需工序 `k=0..K_w-1`，传输任务 `j=(w,k)`共 `K_w+1`次，包含入首腔、工序间转移和最终卸片。变量：

- `q_wk`及 `x_wkc`：工序腔室与对应布尔选择，恰好一个兼容候选；没有跳过必需工序的变量。
- `s_j,e_j,h_j`：传输接受、放片完成和取片完成时刻。
- `v_j`：机器人前一任务终点；首任务取配置initial_position。
- `b_wk,f_wk`：工序加工开始/完成；加工必须在放片完成立即开始。
- `a_ij`：机器人相邻任务选择，所有传输任务和虚拟节点0形成一条Circuit；节点0只是首尾连接，不消耗时间。
- `g_wk`：逻辑占腔区间末端；`Cmax`为所有最终卸片完成时刻的最大值。

令来源 `src_j=LOAD`（首次）或上一工序的选定腔；目的 `dst_j=q_wk`或OUT。T为原 `RobotConfig.travel`有向矩阵，取片p、放片l：

```text
empty_j = T(v_j, src_j)
loaded_j = T(src_j, dst_j)
h_j = s_j + empty_j + p
e_j = h_j + loaded_j + l
b_wk = e_(w,k)
f_wk = b_wk + process_time(q_wk, recipe_wk)
s_(w,k+1) >= f_wk
s_(w,0) >= release_w
a_ij = 1 => s_j >= e_i, v_j = dst_i
Cmax = max_w e_(w,K_w)
minimize Cmax
```

机器人对 `[s_j,e_j)`执行NoOverlap，整段定位/取/运/放均占用。不能在工序完成之前先接受转移再等待取片，也不能在任务之间偷加独立提前移动。

腔室的可选资源区间从入腔传输接受 `s_(w,k)`开始，涵盖预留、加工和阻塞，通常结束于下一传输取片完成 `h_(w,k+1)`。对选中腔室使用OptionalInterval+NoOverlap。

同片下一工序仍选同一腔室时，原验证器允许own_source取放，前后资源区间会在下一传输接受处逻辑交接：`g_wk=s_(w,k+1)`。否则 `g_wk=h_(w,k+1)`。两段的并集连续占用该腔，其他晶圆仍不能插入；并未把来源物理释放时刻提前。加工区间是这个连续资源占用的子区间，因此不会出现同腔同时加工两片的问题。单独对加工区间NoOverlap不能表达这些语义，本实现没有省略保留和阻塞区间。

所有动作有正取/放时间，机器人任务严格有正时长；零移动和零加工允许。半开区间可端点相接，原Simulator在同刻排空事件后接受新动作，回放再检查这一约定。

默认时间域H使用“所有晶圆完全串行、各工序最大兼容耗时、每传输最多两次最大移动、最大释放时间”的保守可行界。该串行方案不会资源死锁，H不会排除更好的方案。用户设置更窄horizon或额外目标界时标为restricted，不冒称完整问题不可行或全局最优。

给定任务顺序和选腔，以上时间关系是具有整数常数的差分约束；可行排程能按约束最长路径前移至整数tick。因此在本静态宏动作范围内，精确整数化不会排除连续时间下更优的Makespan。无故障场景不涉及暂停后重新估计的非整数随机时间。

## 4. 求解与独立回放接口

```python
from src.wafer_sched import load_config
from src.wafer_sched.cpsat_solver import SolverOptions, solve_schedule
from src.wafer_sched.cpsat_validator import validate_solution

config = load_config("configs/wafer_sched/minimal_demo.json")
result = solve_schedule(config, SolverOptions(max_seconds=3, seed=0, workers=1))
replay, validation = validate_solution(config, result)
assert validation["valid"]
```

SolverOptions支持时间限制、seed、线程数、tickscale、horizon、目标下/上界及搜索日志开关。统一实验的 `solver_seconds`和可选 `solver_options`来自suite，每次保存实际选项；CLI可覆盖时间、seed、workers。

主实验先重新执行五个未改变的规则，选取实际完成、同配置、原引擎状态验证通过的最好方案作提示和有效上界。提示不会固定任务顺序/选腔，求解器仍可改进；F从最好规则65秒改进到63秒，G从185改进到183秒。提示来自同实例的已验证输入，不是假指标。CP总算法时间包含建模和求解；五个规则产生初始提示的成本分别已列CSV，但未计入CP运行时间，因此应把此方法理解为带规则初始化的CP-SAT，不据这些单次墙钟值宣称纯CP算法速度优势。

回放只调用原Simulator：用 `run_until(s_j)`插入真实观测边界，先处理全部更早事件，然后 `validate_action/submit`；完成传输微事件后核对实际终点。没有直接改时钟、占腔状态或加工记录。定时等待是既有run_until能力，不为CP增加独立提前移动。规则为在线贪心、CP为已知静态批次离线规划，区别是决策方法和计算成本，物理约束相同。CP适配器是计划回放接口，目前不是动态在线select_action策略。

验证器进一步从原日志核对每次取片完成、传输来源/目的/开始/结束、每道工序腔室/开始/结束及Makespan。任何不一致保留原状态、报告失败，不修复计划，也不将求解成功当作调度可行。UNKNOWN/INFEASIBLE无计划时不回放、不用规则方案冒充CP解。

## 5. 实验设计与实际实例

种子0、单线程；没有随机设备扰动，seed仅用于求解搜索，不构成独立随机环境样本。所有方法使用同一设备和批次。A至E直接复用第三阶段配置，25个规则指标行与历史CSV逐项一致。其他配置如下，全部0秒释放、路线严格按表中顺序：

| 实例 | 晶圆/腔室/总工序数 | 配置要点 | 固定T秒 | 求解预算秒 |
| --- | --- | --- | ---: | ---: |
| A_demo | 3/2/6 | 原clean4→rinse6，机器人1/1/1 | 80 | 3 |
| B_batch | 12/2/24 | 两类clean4或7、rinse6或9 | 400 | 3 |
| C_bottleneck | 12/2/24 | clean3→rinse24 | 600 | 3 |
| D_parallel | 12/3/24 | CLEAN5或ALT9→RINSE8 | 400 | 3 |
| E_long_robot | 10/2/20 | 两类工艺、机器人3/6/3 | 1000 | 3 |
| F_competition | 4/3/8 | x在CLEAN2/ALT13，y在CLEAN13/ALT2；漂洗7；机器人1/1/1 | 250 | 4 |
| G_dual_bottleneck | 4/3/12 | 两类清洗10/18→漂洗20/8→干燥4/14；机器人2/3/2 | 400 | 4 |
| H_heterogeneous | 6/3/12 | CLEAN对x/y为5/16，ALT为8/3；漂洗15/2；机器人1/2/1 | 400 | 4 |
| S_small | 2/2/2 | 一工序可用CLEAN5或ALT12；机器人1/1/1 | 100 | 3 |
| M_medium | 8/4/24 | 清洗两候选、漂洗、干燥三阶段；机器人1/2/1 | 600 | 5 |
| L_large | 20/6/80 | 清洗/漂洗均两候选，干燥及终处理共四阶段；机器人2/3/2 | 2500 | 8 |

F/G/H测试分别执行FIFO及反向合法目录策略，两者都完整完成且动作序列确实不同；没有凭相同Makespan推断相同决策。规模层次同时增加晶圆、腔数、工序数和传输竞争，非仅改批次数量。追加实验只改变L的求解预算至30秒，保留原8秒实验及输入，单独写入 `large_retry/`。

评价窗口与第三阶段一致：各实例预先声明共同 `[0,T]`，Makespan独立为最后卸片时间，主WPH=N*3600/T。加工利用率只计实际processing，机器人只计实际定位/取/运/放；阻塞及等待沿用原日志积分。另列 `completion_batch_wph=N*3600/Makespan`，明确不同分母，不当作稳态WPH。无CP方案的性能列留空；其目录中的初始状态日志只用于审计，不能视为一次完整CP调度的指标。

## 6. 真实Makespan与最优性状态

数据来自[主比较CSV](../results/wafer_sched/stage4/comparison.csv)，单位秒。O=OPTIMAL，F=FEASIBLE，U=UNKNOWN。

| 实例 | FIFO | SPT | ECT | 瓶颈 | 自适应 | CP-SAT | 状态 | CP下界 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| A | 47 | 47 | 47 | 47 | 47 | 47 | O | 47 |
| B | 197 | 192 | 192 | 197 | 192 | 192 | F | 147 |
| C | 388 | 388 | 388 | 388 | 388 | 388 | F | 344 |
| D | 198 | 198 | 198 | 202 | 198 | 198 | F | 154 |
| E | 535 | 535 | 535 | 535 | 535 | 535 | F | 414 |
| F | 74 | 65 | 65 | 74 | 65 | 63 | F | 51 |
| G | 185 | 194 | 194 | 199 | 185 | 183 | F | 142 |
| H | 139 | 141 | 141 | 137 | 137 | 137 | F | 91 |
| S | 19 | 23 | 23 | 19 | 19 | 19 | O | 19 |
| M | 216 | 204 | 204 | 211 | 210 | 204 | F | 132 |
| L(8秒) | 1010 | 999 | 999 | 1016 | 1013 | 无方案 | U | 0 |

只有A、S的表内数值可称本静态宏动作实例的全局最优：A五规则与最优差值均0；S的FIFO/瓶颈/自适应差值0，SPT/ECT差值4秒，即相对19秒最优值约21.05%。S中优先在慢腔启动一片并在快腔并行加工另一片，使后续卸片匹配更好；局部SPT不能保证全批最优。

B至M的FEASIBLE只能给出下界L和已验证上界U，不能回答精确的“离最优差多少”。CP报告差距为 `(U-L)/U`，是上下界相对差距；CSV另有对可行CP方案的差值，不标作最优差值。

| 实例 | 已知CP区间[L,U]秒 | CP相对差距 |
| --- | --- | ---: |
| B | [147,192] | 23.4375% |
| C | [344,388] | 11.3402% |
| D | [154,198] | 22.2222% |
| E | [414,535] | 22.6168% |
| F | [51,63] | 19.0476% |
| G | [142,183] | 22.4044% |
| H | [91,137] | 33.5766% |
| M | [132,204] | 35.2941% |

第三阶段五案例在本次限时下未出现CP严格优于最好规则的结果，不能夸大优化效果。F和G有真实2秒改进，但并未证明全局最优。H自适应与瓶颈、CP同为137秒，却有不同的加工分配、利用率及等待，不能将数值相同当成同一决策。

## 7. 指标与目标取舍

CSV包含Makespan、两种WPH、加工/机器人利用率、平均等待、阻塞、完成数、约束拒绝、死锁、算法/建模/求解/回放时间、状态、下界及差距。所有数值从真实事件计算；下表选取实际有区分度的结果：

| 实例/方法 | 主WPH | 平均腔利用率 | 机器人利用率 | 平均等待秒 | 阻塞腔秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| F/FIFO | 57.6 | 10.6667% | 18.0% | 23.75 | 42 |
| F/SPT | 57.6 | 4.8% | 18.0% | 25.75 | 68 |
| F/CP | 57.6 | 4.8% | 18.0% | 23.25 | 29 |
| G/FIFO | 36 | 12.3333% | 37.75% | 71.75 | 110 |
| G/SPT | 36 | 12.3333% | 37.0% | 69.0 | 78 |
| G/CP | 36 | 12.3333% | 37.75% | 71.0 | 103 |
| H/自适应 | 54 | 8.9167% | 25.5% | 58.0 | 147 |
| H/CP | 54 | 6.25% | 25.5% | 64.8333 | 179 |

F的FIFO利用率更高是选择了更多慢加工，并未带来更短Makespan；利用率不等价于Makespan。G的SPT平均等待低于CP，但Makespan更长；H的CP与自适应同Makespan却有不同等待和阻塞。第一版只最小化Makespan，没有声称其他指标同时最优。主WPH在同实例全部完成时相同，这是共同固定窗口的定义，不伪造主WPH提升。

## 8. 规模与失败案例

| 层次 | N/腔/工序/传输 | 建模秒 | 实际求解秒 | 结果 |
| --- | --- | ---: | ---: | --- |
| S | 2/2/2/4 | 0.013917 | 0.022112 | OPTIMAL19秒 |
| M | 8/4/24/32 | 0.195467 | 5.005616 | FEASIBLE204秒，下界132 |
| L首次 | 20/6/80/100 | 1.564048 | 8.092097 | UNKNOWN，没有方案 |
| L追加 | 同上 | 1.839439 | 30.020191 | UNKNOWN，没有方案，下界454 |

L产生9740个序列弧、11181个变量、21270条约束。首次限时在预处理阶段停止；30秒追加完成预处理并搜索，但仍无返回的可行解。原日志显示提示不完整、预处理约14.85秒，30秒时已有23423次分支。限时包含预处理，实际返回可能稍超配置时间。该一次运行说明具体计算瓶颈，不是渐近复杂度或跨机器统计结论。

追加结果保存在[追加CSV](../results/wafer_sched/stage4/large_retry/comparison.csv)。454是有用的模型下界；999是已验证SPT/ECT的实例上界，**不是CP搜索解**。可讨论实例范围[454,999]，但不把其差值填写为CP incumbent gap，CP性能仍留空。

为排除提示不兼容，另用同一个大型模型固定已验证规则提示：求解约0.053839秒完成，所有工序和传输变量与原Simulator记录一致。[诊断JSON](../results/wafer_sched/stage4/diagnostic_large_hint_feasibility.json)中的OPTIMAL仅针对固定提示子问题，`global_optimum_claim=false`。这说明999秒方案与模型相容，但不证明自由搜索最优，也不替换两次UNKNOWN。该检查已加入可重复执行的单元测试。

其他真实负例：5秒horizon使单片案例INFEASIBLE，这是人为限域不可行，不是物理设备本身不可行；0秒求解为UNKNOWN；篡改加工结束预测被原回放验证拒绝。非法选腔、机器人重叠、缺少卸片及中途初始化在测试中被拒绝。主实验 `model_inconsistencies.json`的回放不一致列表为空，测试篡改负例单独存档，不能说是求解器产生了错误解。

## 9. 测试、产物与复现

实际环境仍为独立 `.venv_wafer`、Windows/CPython3.13.13，新增OR-Tools9.14.6206及真实依赖，旧平台环境未修改。完整依赖锁来自本机实际安装，未在Python3.11或其他系统验证整套锁文件。

```powershell
.venv_wafer\Scripts\python.exe -m pip install -r requirements-wafer.lock.txt
.venv_wafer\Scripts\python.exe -m src.wafer_sched.stage4_experiments --output results/wafer_sched/stage4-replay
.venv_wafer\Scripts\python.exe -m src.wafer_sched.stage4_experiments --suite configs/wafer_sched/stage4_large_retry.json --output results/wafer_sched/stage4-replay/large_retry
.venv_wafer\Scripts\python.exe -m pytest tests/wafer_sched -v
.venv_wafer\Scripts\python.exe -m pytest tests/test_local_runtime_compatibility.py -v
.venv_wafer\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched tests/conftest.py
.venv_wafer\Scripts\python.exe -m pip check
```

输出目录必须不存在，防止覆盖。可用 `--max-seconds`、`--workers`、`--seed`覆盖搜索选项。单线程固定seed尽量使搜索可复现，但墙钟限时会随机器/版本/负载改变方案或证明进度，不能保证重新求解逐条相同；保存的计划可以精确回放。没有重复环境seed的统计或挑选最优随机单次结果。

151项研究测试：**150通过、1跳过**。第四阶段43个实例全部通过，第三阶段及更早的107个实例全部通过。跳过的是原Windows符号链接权限测试。新增覆盖单腔11秒、双片同腔23秒、三片原例47秒、连续同腔13/27秒、长传输29秒、方向性运输和6.25秒小数、已知释放16秒、互斥/兼容、horizon不可行、限时UNKNOWN、提示验证、计划损坏/不完整、原Simulator穷举对照、真实多个可行行为、规模及468文件保护。

平台非破坏性回归4项全部通过，覆盖跨进程租约、退出释放、中文日志写入失败保护和Windows替换失败保护；ruff、pip check、git diff --check通过。未运行完整Semantica/RDF/API/前端套件，不把这4项称作全平台验收。

主/追加每个run均保存配置、完整压缩事件、CSV/TXT事件、决策、日志积分指标、最终状态、核心源码hash。CP另存 `schedule.json`、`solver.json`、`solver.txt`、`validation.json`；无解的schedule为null。每个完成run都有基于真实状态区间的甘特图。72组产物约20.54MB，不包含环境。

最终核验实际重新读取72组日志积分、逐列核对完成运行的CSV、重新回放10份CP计划、检查源码hash/依赖锁、对比第三阶段25行基准及468个受保护文件，全部通过，见[verification.json](../results/wafer_sched/stage4/verification.json)。原始pytest证据见[研究XML](../results/wafer_sched/stage4/wafer_tests.xml)及[平台XML](../results/wafer_sched/stage4/platform_regression.xml)。

- [六算法Makespan图](../results/wafer_sched/stage4/makespan_comparison.png)
- [规模求解时间图](../results/wafer_sched/stage4/scale_runtime.png)
- [竞争分配CP甘特图](../results/wafer_sched/stage4/F_competition-cpsat-s0/gantt.png)
- [竞争分配独立验证报告](../results/wafer_sched/stage4/F_competition-cpsat-s0/validation.json)
- [所有求解证明状态/下界](../results/wafer_sched/stage4/solver_proofs.json)
- [模型不一致/未支持项](../results/wafer_sched/stage4/model_inconsistencies.json)
- [真实负例](../results/wafer_sched/stage4/negative_cases.json)

已查看Makespan与规模图，图中UNKNOWN未绘制虚假的CP柱。指标数据链接和计划回放是研究证据，图表本身不替代约束验证。

## 10. 未解决问题与MDP/RL建议

动态暂停恢复及暖启动仍未建模；静态最优不能冒称动态在线最优。大型序列弧数量近二次增长，部分提示和预处理成本阻碍限时获得可行方案。下一步可补全辅助变量提示、剪除不可能弧、对相同任务作有证明的对称破除、采用滚动时域，但每项均需保留原回放验收。未实现这些优化，不把它们写成现有能力。

进入MDP/RL时保留原Simulator、只读Observation及合法动作目录。先定义事件步长和积分奖励，再建Gymnasium包装；区分终止/截断，明确等待动作能否选择定时边界，避免与CP宏动作范围混淆。动态研究只暴露已发生扰动，静态CP仅作已知批次参考；不把有未来信息的离线解当作在线公平对照。

优先将S等已证明小例用于策略校验，将F/G/H用作任务排序/分配训练与保留测试，训练、反馈验证与最终测试分开。Makespan、固定窗口WPH、利用率、等待和阻塞继续独立记录；本轮已观察到多指标取舍，不能用一个奖励值代替全部指标。RL、自主多轮研究反馈、Semantica记忆集成仍属后续阶段。

本模型使用的整数接口和状态含义依据官方[CP-SAT说明](https://developers.google.com/optimization/cp/cp_solver)与[Python参考](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model)；本报告性能结论全部依据本仓库实际运行。
