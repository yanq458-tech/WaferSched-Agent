# WaferSched-Agent 第五阶段：事件驱动MDP与MaskablePPO

本阶段在原设备仿真器上新增强化学习封装，遵循[编码前MDP审计](wafer_sched_stage5_mdp_audit.md)。铁路业务、原Simulator、规则策略、CP-SAT及第三/四阶段历史实验不改写。正式训练前通过34项新增测试和256步短训练门禁；实际完成六次正式训练、36,864步、3311个完整回合及72次最终评价。24次RL评价均完成任务，所有评价零违反、零死锁；结果同时包含改进、持平和退步。

## 1. 实现与文件

| 文件/目录 | 功能 |
| --- | --- |
| `src/wafer_sched/rl/encoding.py` | EncodingSchema、ObservationEncoder、ActionEncoder；固定槽位及完整合法目录 |
| `src/wafer_sched/rl/environment.py` | WaferSchedulingEnv、当前任务观测适配器、原事件推进、终止/截断 |
| `src/wafer_sched/rl/reward.py` | RewardWeights、RewardCalculator；真实区间积分及分量记录 |
| `src/wafer_sched/rl/policy.py` | TrainedPolicyAdapter；独立加载和第三阶段select_action接口 |
| `src/wafer_sched/rl/training.py` | RLTrainingRunner；真实MaskablePPO、CSV、验证集选模、硬件信息 |
| `src/wafer_sched/rl/evaluation.py` | RLEvaluationRunner；七方法对照、历史CP重放、双执行路径核对及独立掩码审计 |
| `src/wafer_sched/rl/reporting.py`、`__init__.py` | 真实数据图表及可选RL导出；原核心导入不要求torch |
| `experiments/wafer_sched/run_stage5.py` | smoke→train→evaluate→plots阶段入口，复现必须使用新目录 |
| `experiments/wafer_sched/verify_stage5.py` | 独立重算、加载重放、历史保护、训练/测试隔离及依赖验收 |
| `configs/wafer_sched/rl/` | 3份训练配置、1份预先声明测试清单、4个验证与3个保留测试设备配置 |
| `tests/wafer_sched/test_rl_environment.py`、`test_rl_training.py` | 34个新增测试实例 |
| `docs/wafer_sched_stage5_mdp_audit.md`、`wafer_sched_stage5_preservation.json` | 事前审计；1233个原文件hash保护 |
| `requirements-wafer.txt`、`requirements-wafer.lock.txt`、`README.md` | 修改：真实研究环境依赖、CPU索引、第五阶段入口和结果 |
| `results/wafer_sched/stage5/` | 实际训练模型、日志、独立评价、图表和验收记录 |

原第二至四阶段核心文件、测试和配置保持hash一致。工作区已有未提交文件不全部归为本阶段新增；没有提交或推送GitHub。

## 2. 数学定义与Markov范围

定义 `M=(S,A,P,R,gamma)`。S为当前设备与任务信息：时钟、机器人位置/忙闲/携片/当前任务phase、源/目的/活动晶圆/剩余动作时间、腔室状态/可用性/占片/预留/加工剩余、各片工序/位置/状态/完整剩余路线、等待就绪年龄及完成数；同时包含设备已知运输矩阵和工艺耗时。实际历史加工/阻塞/空闲年龄/机器人活动比例是额外可观察统计。

首版只接受空设备初始化、全部0秒释放、无downtime、正取放时间的确定性批次。对于这一范围，剩余工序、选腔兼容性、剩余加工和已知动作时长足以确定下一状态；不需要读取未来队列。未来故障和未宣布到达会破坏这一完全可观察Markov假设，因此明确拒绝，没有静默移除它们。

原ObservationBuilder不变。新CurrentObservationBuilder只补充当前机器人任务字段，尤其用于时间限制发生在取片/运输途中时的截断观测和价值bootstrap。任务剩余从当前phase_end计算，未读取未来事件数组；控制执行器内部可读取最早事件时间用于预算保护，但这些内部数据不会进入策略输入。

P由原validate_action→submit→事件队列实现。RL不修改状态、时钟或容量，不产生独立提前定位或缓冲动作。

## 3. 状态与动作编码

共同schema：`Nmax=8,Cmax=4,Kmax=3`，时长尺度100秒。观测为**588维float32**，Box范围[0,1]：存在位、位置/状态one-hot、stage/Kmax、route_length/Kmax、完成/等待队列、剩余时间、每片每阶段每腔的兼容标志与名义工时、完整有向travel矩阵、真实取放时间、历史积分和时钟。不存在的槽填0；兼容位区分0秒加工与不允许加工。

非负时长x编码 `x/(x+100)`，它在精确实数意义下可逆，不裁剪，不按每场景最大值变换尺度。float32仍有有限精度，这是数值实现的普通近似，极大值可能饱和。ID排序建立稳定槽位，输入JSON重排不会改变编码；不同规模下槽位对应关系可改变，普通MLP没有置换等变保证。

动作空间为Discrete(41)：

```text
0 = 原wait
1 + w*(Cmax+1) + d = 晶圆槽w到目的槽d的完整传输
d=0..Cmax-1: 当前腔室槽；d=Cmax: OUT卸载
```

来源和工序由当前状态确定，不增加原子取片/提前移动。每个合法操作与一个索引对应；所有空槽及非法工艺/占用组合为false，不截断候选列表。Action Mask来自原Simulator.legal_actions；decode只允许目录成员，再调用原validate_action。非法索引抛明确ValueError，物理状态、队列、日志及决策计数都不变。

最多8片、4腔、每片3工序，超限明确拒绝。原B/C/D/E及大型L不全部进入RL对照；本阶段不宣称任意规模迁移。模型保存schema，加载时核对action/observation空间。

## 4. 事件时长、等待和终止

机器人空闲、当前时刻事件全部处理完后选择动作。step执行完整传输微事件；若空闲却没有非wait操作，自动执行原wait，直到新的可决策时刻。主动wait只推进至下一真实事件，它仍可能在有传输可选时被选择，并承担完整时间成本。零移动/零加工仍由原有限事件链处理。

不同step真实时长不同，因此物理过程是半马尔可夫过程。本轮MaskablePPO使用**gamma=1**有限回合无折扣，与连续时间rho=0时的 `exp(-rho*Δt)=1`一致；没有自定义SMDP优化器。若改gamma<1，SB3按决策次数递推，而不是按秒折扣，必须标为近似。GAE lambda=0.95仍按决策步递推。

全部完成和真实死锁是terminated；最大仿真秒数或最大决策数是truncated。时间边界由原run_until处理全部更早事件，不跳过正在执行的取放；恰好在边界完成时优先判完成。SB3的时间限制价值bootstrap沿用标准实现，不把截断当自然完成。死锁保留原PotentialDeadlock记录，不修复成虚构合法状态。

CP与RL物理模型相同，但CP可以通过原run_until计划任意离线等待时间，RL只可等待至下一真实事件。因此不能声称两者决策时刻空间完全相同。CP参考是宏动作静态问题的最优值/界，RL性能差距同时可能包含决策时刻限制与策略学习不足。

## 5. 奖励、指标与防止收益重复

每一步遍历从上一个已结算端点至本次端点的真实事件区间，记录完成片增量q、elapsed秒D、waiting晶圆秒W、blocking腔室秒B、有效机器人秒U；原定义与第二阶段calculate_metrics一致。令实际批次片数N、腔数C、t_ref=100秒：

```text
r = 10*q/N - 0.5*W/(N*100) - 0.1*B/(C*100)
    - 0.1*U/100 - 2*D/100
死锁另减 10*(未完成片数/N)
```

完成奖励每片仅一次；不奖励放片/每道工序以避免重复完成收益。elapsed项明确对应Makespan；等待、阻塞、运输是另外成本，同一时间可能同时涉及多个目标，不称独立互斥成本。全批完成的总完成收益为10，其余项为真实时间积分罚项，因此主动等待没有正收益。没有把缩短评价窗口作为训练奖励。

奖励是多项成本目标，不等于只最小化Makespan；不能因奖励增加就宣称WPH提高。主评价按每个场景预先声明的共同[0,T]窗口，WPH=完成数*3600/T，加工利用率只把实际processing秒计分子，机器人利用率包含空载定位/取片/载片移动/放片。另列完成窗口批次WPH=完成数*3600/Makespan，非稳态产能。平均等待及阻塞沿用原事件积分；未完成Makespan为null。

极小单片验证：输入3秒+加工5秒+输出3秒=11秒，机器人6秒、等待0、阻塞1腔秒（使用两个腔中的一个）；两步真实间隔8和3秒，总奖励 `10-0.22-0.006-0.0005=9.7735`。测试逐项断言，不使用配置假指标。

## 6. 训练/验证/最终测试划分

| 组 | 训练 | 选checkpoint的验证集 | 最终评价 |
| --- | --- | --- | --- |
| small | S_small两片单阶段；A_demo三片两阶段 | V_small改工时6/11；V_demo改清洗/漂洗5/7 | S/A独立加载的**已训练实例**评价，不能称环境泛化 |
| medium | F_competition四片竞争选腔；G_dual四片三阶段双瓶颈 | V_competition改工时；V_dual改各阶段工时 | F/G为已训练实例；H、T_count、T_noalt、T_transport为保留测试 |

H六片/三腔/两阶段及不同混合工时未用于训练/选模。T_count由F增加到五片；T_noalt从五片案例移除ALT并同步修正工艺候选；T_transport在五片三腔下改取/运/放为2/4/2秒。所有配置经原EquipmentConfig校验，没有表面可替代但实际上不支持recipe的腔室。

测试清单在拟合前已保存到配置，并在每组训练开始归档；评价必须与归档清单一致。每个种子单独按验证集完成率优先、再按平均Makespan选择checkpoint，分数相同保留较早模型。测试不用于选择种子、训练步数或checkpoint；报告三个种子全部结果。

共同网络为独立actor/critic各[64,64]，CPU1线程；learning_rate=0.0003、n_steps=128、batch_size=64、n_epochs=5、gamma=1、GAE=0.95、ent_coef=0.01。small=4096步、medium=8192步，各seed0/7/13；每run最大墙钟600秒、最大仿真1000秒、最大决策512。smoke=256步、rollout64、batch32、最大墙钟60秒。

训练随机性来自场景抽样、网络初始化与动作采样，三个训练种子可用于检查算法稳定性；仿真器仍完全确定，没有三份独立随机工况。独立加载评价采用deterministic=True和显式action_masks，环境seed=0。训练选择器为自定义掩码验证循环，未使用不支持掩码的SB3基础EvalCallback。

## 7. 真实训练和最终对照

短训练实际256步、29完整回合、4.907596秒；保存后加载并完成验收。正式训练的每个run都达到预定步数，未触发600秒上限。下面为真实模型metadata/episode CSV，时间包含模型初始化、训练、验证与模型保存，不含导入模块和最后写metadata的时间：

| 组/seed | 实际步数 | 完整回合数 | 墙钟秒 | 验证选中步数 | 验证平均Makespan秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| small/0 | 4096 | 538 | 43.663947 | 4096 | 35.5 |
| small/7 | 4096 | 543 | 44.682982 | 3072 | 36.5 |
| small/13 | 4096 | 568 | 42.218148 | 2048 | 35.5 |
| medium/0 | 8192 | 547 | 95.874024 | 6144 | 125.0 |
| medium/7 | 8192 | 560 | 96.271195 | 8192 | 125.0 |
| medium/13 | 8192 | 555 | 98.095092 | 6144 | 129.0 |

正式训练累计420.805390秒，3311个已结束回合全部完成、全部掩码合法。每次learn最后可能还保留一个未结束回合，未把它伪造为完成回合；transition_rewards.csv记录全部36,864次真实转移。small有32个完整rollout、medium有64个，SB3更新日志包含真实loss、entropy、KL及更新数。完成率证据覆盖运行稳定性，效率仍须独立比较。

训练奖励前20/后20个回合的实测均值依次为：small seed0=9.015392/9.226650，7=9.071883/9.136425，13=8.998833/9.298250；medium seed0=5.678525/7.693092，7=6.303758/7.123729，13=5.653375/7.409442。各组混合两个训练实例，样本组成可能改变均值，不能据此直接声称产能改善。Makespan图按实例分开，使用真实20回合滑动均值。

最终对照使用五条原规则、CP-SAT、三个独立训练的MaskablePPO模型。八场景每场景9行，总计72行：40条规则、8条CP、24条RL。全部完成同批任务。S/A/F/G/H的5份第四阶段CP参考核对完整配置后重新回放，原结果不写入；T三个变体在3秒限时、单线程seed0下重新求解并独立验证。CP状态为2个OPTIMAL、6个FEASIBLE，未把FEASIBLE参考当最优。

| 场景 | FIFO | SPT | ECT | 瓶颈 | 自适应 | CP Makespan/状态/下界 | RL seed0/7/13 | RL均值±样本标准差 |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| S_small（已训练） | 19 | 23 | 23 | 19 | 19 | 19/OPTIMAL/19 | 19/23/19 | 20.333±2.309 |
| A_demo（已训练） | 47 | 47 | 47 | 47 | 47 | 47/OPTIMAL/47 | 47/47/47 | 47±0 |
| F_competition（已训练） | 74 | 65 | 65 | 74 | 65 | 63/FEASIBLE/51 | 65/65/65 | 65±0 |
| G_dual（已训练） | 185 | 194 | 194 | 199 | 185 | 183/FEASIBLE/142 | 183/183/189 | 185±3.464 |
| H_heterogeneous（保留） | 139 | 141 | 141 | 137 | 137 | 137/FEASIBLE/91 | 133/133/137 | 134.333±2.309 |
| T_count（保留） | 89 | 80 | 80 | 89 | 80 | 78/FEASIBLE/62 | 80/80/80 | 80±0 |
| T_noalt（保留） | 90 | 90 | 90 | 90 | 90 | 90/FEASIBLE/68 | 95/95/95 | 95±0 |
| T_transport（保留） | 183 | 182 | 182 | 183 | 182 | 180/FEASIBLE/101 | 182/182/182 | 182±0 |

所有Makespan为秒，标准差是3个**训练算法种子**间的样本标准差，不是随机工况置信区间，也不把确定性环境重放当独立样本。S中2/3模型达到已证明19秒，seed7多4秒（21.0526%）；A三个模型达到已证明47秒。F三个模型与最好规则同65秒，比CP可行参考多2秒，不能称最优性差距。G两个达到183秒，一个189秒；均值185秒与最好规则持平，不能只挑最好的两个宣称总体超越。

H三个保留测试均值134.333秒，比最好规则及旧CP可行参考137秒少2.667秒；seed0/7各少4秒，seed13持平。参考仍为FEASIBLE，下界91；这是一份更好的原引擎合法方案，**不是证明全局最优133秒**。T_count/T_transport与最好规则持平、比CP可行参考各多2秒；T_noalt全部多5秒。泛化结果并不一致，没有根据这些最终测试再调参或选择另一个checkpoint。

### 7.1 实际动作差异与退步原因

S seed0先将W02送ALT（3–15加工），再将W01送CLEAN（7–12加工），19秒完工；seed7先CLEAN（3–8）再ALT（7–19），23秒完工。相同合法空间内，慢工序先并行启动对最后完工有利；这是实际选腔/顺序差异，不仅是策略标签。

H seed0的RINSE顺序为W03、W02、W01、W05、W06、W04，对应加工区间16–31、43–45、61–76、88–103、115–117、127–129；最后卸片133秒。旧CP参考顺序W01、W02、W03、W04、W05、W06，最后两道RINSE为106–121和131–133，卸片137秒。RL把长漂洗W05提前，虽将W04分配到16秒CLEAN而非3秒ALT，最终仍提前结束。它不是简单按全部阶段最短耗时选腔。

T_noalt seed0装载顺序W02、W01、W03、W05、W04，首先加工13秒的W02；FIFO依次W01至W05，先加工2秒W01。最后RINSE在RL为85–92、FIFO为80–87，分别95/90秒卸完。记录中H和T_noalt所有RL模型均没有“存在传输仍主动wait”的选择，不能把这次退步归因于无效等待；排序/分配和槽位迁移是需后续消融检验的原因，不能在本轮断言单一因果。

### 7.2 独立指标与计算成本

下表为三个RL模型的实测算术均值；详细规则和CP指标均在[72行CSV](../results/wafer_sched/stage5/evaluation/comparison.csv)，不使用累计奖励代替：

| 场景/T秒 | 共同窗口WPH | 腔平均利用率 | 机器人利用率 | 平均等待秒 | 阻塞腔秒 | 单批累计推理毫秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S/100 | 72 | 8.5% | 14.3333% | 2.6667 | 3.3333 | 3.4258 |
| A/80 | 135 | 18.75% | 41.25% | 14.6667 | 14 | 9.7216 |
| F/250 | 57.6 | 6.2667% | 18.0% | 23.0 | 57 | 43.8325 |
| G/400 | 36 | 12.3333% | 37.25% | 68.6667 | 90.3333 | 76.0612 |
| H/400 | 54 | 7.8611% | 25.5% | 61.7222 | 160.3333 | 19.1623 |
| T_count/400 | 45 | 4.6667% | 14.25% | 31.2 | 81 | 81.3849 |
| T_noalt/400 | 45 | 8.375% | 14.25% | 38.6 | 33 | 121.5662 |
| T_transport/600 | 30 | 3.1111% | 28.0% | 87.4 | 229 | 84.6576 |

各场景全部完成同批任务，因此同场景的共同窗口WPH均相同，H的Makespan改善没有带来主WPH变化；辅助完成窗口WPH另列，不宣传为稳态WPH提升。H的RL均值与CP的等待/利用率/阻塞也不同，不能把较短Makespan当所有指标更优。

推理列为原Policy接口内状态编码、mask构造、模型predict及动作转换的累计perf_counter墙钟，包含仅wait的统一策略调用；不含仿真、写盘、加载和训练，不是每次决策平均。CPU调度/缓存造成单次波动，不能由此排序算法普遍速度。历史CP求解时间来自第四阶段原metadata，CSV显式cp_reference_reused，未冒充本轮新求解时间；新T场景保存实际建模/求解日志。约420.8秒训练成本单独报告，不能与一次推理或CP求解混算。

## 8. 回归、产物及复现

独立环境Windows/CPython3.13.13：torch2.8.0+cpu、gymnasium1.2.1、stable-baselines3/sb3-contrib2.7.1；CPU20逻辑核，本轮torch1线程，无CUDA。原平台环境不变，锁文件来自实际pip freeze，CPUwheel索引保留。未在Python3.11/Linux重验完整锁。

实际研究测试185项：184通过、1项原符号链接权限测试跳过；其中34项新增均通过，原150项全部通过。4项平台非破坏性回归通过；不称整个平台/RDF/API/前端全部验收。

Gymnasium官方check_env本身不使用mask，并在确定性检查中先采样再reset。本测试只让checker的Discrete.sample使用初始合法掩码，不改变生产step语义；其他测试独立遍历所有动作索引、原约束检查、非法拒绝及具体时间/状态。没有绕过物理约束来训练。

```powershell
.venv_wafer\Scripts\python.exe -m pip install -r requirements-wafer.lock.txt
.venv_wafer\Scripts\python.exe -m pytest tests/wafer_sched -v
.venv_wafer\Scripts\python.exe -m pytest tests/test_local_runtime_compatibility.py -v
.venv_wafer\Scripts\python.exe -m ruff check src/wafer_sched tests/wafer_sched tests/conftest.py experiments/wafer_sched
.venv_wafer\Scripts\python.exe -m pip check
.venv_wafer\Scripts\python.exe -m experiments.wafer_sched.run_stage5 --output results/wafer_sched/stage5-replay
.venv_wafer\Scripts\python.exe -m experiments.wafer_sched.verify_stage5 --output results/wafer_sched/stage5-replay
```

最后一条独立验收还读取测试XML；在新复现目录保存XML：`pytest tests/wafer_sched -v --junitxml=results/wafer_sched/stage5-replay/wafer_tests.xml`及相应平台XML，待实验目录创建后运行。这两个测试文件名与主产物一致，不覆盖历史结果。入口支持--phase smoke/train/evaluate/plots继续完成阶段，已存在的训练/评价目录拒绝覆盖。

训练每seed保存episodes.csv、transition_rewards.csv（逐步真实时间/奖励分量/动作/掩码）、episode_summaries.json、monitor.csv、updates/progress.csv、validation.json、best/final.zip及metadata.json。模型metadata记录真实步数、用时、硬件/软件、选模位置和设备；模型独立加载不依赖训练环境对象。

接入原第三阶段执行接口的独立加载示例：

```python
from src.wafer_sched import Simulator, load_config
from src.wafer_sched.policy_runner import run_policy
from src.wafer_sched.rl.policy import TrainedPolicyAdapter

policy = TrainedPolicyAdapter.load(
    "results/wafer_sched/stage5/training/medium/seed-0/models/best.zip")
simulator = Simulator(load_config("configs/wafer_sched/H_heterogeneous.json"))
run = run_policy(simulator, policy, max_time=400)
assert run.outcome["status"] == "completed"
```

每个评价保存原事件JSON.gz/CSV/TXT、真实配置/指标/最终状态/sourcehash；RL另存原Policy决策、Gym决策/分量、episode_summary与独立掩码审计。原Policy与Gym两条执行路径逐条物理事件一致；保存计划的CP重新原引擎回放。主CSV包括全部独立指标、推理墙钟、完成率/违反数及证明口径。

独立验收重新读取72份完整事件并重算指标，独立加载24个模型/场景组合重放，8份CP计划再回放；核对1233个原文件不变、4个保留测试与训练/验证物理配置不同、奖励分量与原指标一致及依赖锁。原Policy决策共431个，独立枚举检查17,671个动作索引，false-positive/false-negative/选中masked动作均0。

第一次最终评价在G的历史参考读取处因简称G_dual与目录G_dual_bottleneck不一致中断；未完成产物保留在 `evaluation-attempt-1/`。修复只在找不到历史目录时按原config.name定位，然后仍核对完整配置；重新执行最终72行评价。模型、训练/奖励/编码/策略模块未变，未根据已测结果选模。`evaluation_repair.json`保留评价器修复前后hash；训练时的source_sha256原记录未重写，verification显式报告一处评价器hash差异，不能称所有新RL源码在训练后均未变化。第三/四阶段和原核心1233文件不变。

图表使用实际日志/CSV，已检查训练Makespan、七方法对照、CP差值和H甘特图的布局与数据口径：

- [奖励曲线](../results/wafer_sched/stage5/figures/training_reward.png)、[分实例训练Makespan](../results/wafer_sched/stage5/figures/training_makespan.png)、[训练完成率](../results/wafer_sched/stage5/figures/training_completion.png)
- [七方法Makespan](../results/wafer_sched/stage5/figures/makespan_comparison.png)、[WPH](../results/wafer_sched/stage5/figures/wph_comparison.png)、[腔利用率](../results/wafer_sched/stage5/figures/utilization_comparison.png)、[评价完成率](../results/wafer_sched/stage5/figures/completion_comparison.png)
- [RL与CP差值图](../results/wafer_sched/stage5/figures/rl_cp_difference.png)：左图为已证明最优差距，右图为FEASIBLE参考差值，可出现负值，不称最优性差距
- [H seed0真实甘特图](../results/wafer_sched/stage5/evaluation/H_heterogeneous-maskable_ppo-s0/gantt.png)、[动作轨迹](../results/wafer_sched/stage5/evaluation/H_heterogeneous-maskable_ppo-s0/decisions.json.gz)
- [独立掩码统计](../results/wafer_sched/stage5/evaluation/mask_statistics.json)、[完整验收](../results/wafer_sched/stage5/verification.json)、[真实训练清单](../results/wafer_sched/stage5/training/medium/manifest.json)
- [研究测试XML](../results/wafer_sched/stage5/wafer_tests.xml)、[平台回归XML](../results/wafer_sched/stage5/platform_regression.xml)

## 9. 局限与后续研究

仅验证静态兼容槽位组，未支持动态故障/释放、暖启动、超过8片/4腔/3工序、缓冲或多片夹爪；未保证MLP置换等变或任意跨规模泛化。没有自定义连续时间PPO折扣，所有奖励和评价定义明确区分。

短训练不保证最优；验证表现可波动，最终测试可低于规则。CP的FEASIBLE仅为已知可行参考，静态CP含已知全批与不同等待时刻，不称在线动态最优策略。推理耗时与CP求解耗时性质不同，训练成本另计；单机单次墙钟不作普遍速度结论。

后续先定义动态故障/到达过程及其可观察信息，必要时将问题视为POMDP或增加当前故障年龄/事件机制状态；不把未来恢复或未宣布加工抽样暴露给模型。再开展配对扰动轨迹、训练/验证/测试分离、固定规则与RL对照、奖励消融和反馈关闭消融。第六阶段才接入Semantica记忆及跨实验反馈；本阶段的PPO训练与验证选模不冒称已实现五轮自主研究智能体。

工具接口参考官方[MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)、[Gymnasium Env](https://gymnasium.farama.org/v1.0.0/api/env/)、[时间限制](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)。本报告数值证据均来自本仓库实际运行，非文献性能。
