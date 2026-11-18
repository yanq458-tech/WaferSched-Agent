# v1.3.0 故障时钟与不可取消动作

在仓库根目录使用安装了 `requirements-recovery.txt` 的环境。此目录已有的 Python 环境可直接运行：

```powershell
.\.venv-langgraph\Scripts\python.exe -m wafer_sched.recovery.study
```

默认运行离线 LangGraph，输入是一件正在执行取片动作的两片晶圆实例。命令打印新建的结果目录，输入保存为 `input.json`，结果保存为 `result.json`。复现固定对照及图表使用 `python -m wafer_sched.recovery.study study`。每次创建独立输出目录。自定义输入示例：

```powershell
python -m wafer_sched.recovery.study solve --input results/recovery/v1.3.0-acceptance/mid_pick/input.json --repair 11.5
python -m wafer_sched.recovery.study boundary --input results/recovery/v1.3.0-acceptance/sealed/input.json
python -m wafer_sched.recovery.study agent --elapsed 0
python -m pytest tests/wafer_sched/test_continuation.py tests/wafer_sched/test_recovery.py
```

**输入与质量合同。** Schema 2 保存设备配置、故障时刻的完整快照、从初始化到故障的带时间戳动作日志、故障腔、逐片逐工序驻留和持片期限、工艺策略及调度延迟。以实际文件 `mid_pick/input.json` 为模板。Python 调用 `Continuation.capture(sim, failed_chamber, residency, holding, policy=..., dispatch_lag=...)`。使用 `Continuation.from_dict` 反序列化。动作日志必须能从原始配置重建给定快照，时间戳相同的已发生事件按 Simulator 顺序结算。复核待处理事件的物理属性与顺序，观察操作占用的事件流水号允许不同。模型承认原配置的有效晶圆，不允许报废或重新投片。原 schema 1 和旧命令仍可用。

| 故障腔内情况 | 配置与语义 |
|---|---|
| 空腔 | 默认 empty_only。修复后允许开始放片，机械臂可以提前移动或持片等待。 |
| 已加工完成，允许留片与卸片 | evacuate_finished 要求工艺方确认质量、允许停留和取出；原驻留时钟继续走。 |
| 已加工完成，维修期间封闭 | sealed_finished 要求工艺方确认封闭等待的质量条件；取片开始必须在修复时刻或之后，取完仍须满足原期限。 |
| 腔内加工中、放入故障腔途中、封闭时正从该腔取片 | 返回 UNSUPPORTED。缺少工艺授权时不能推断中断后的成品质量。 |

**固定前缀与单调性。** 故障时刻记作零。令 h 为已提交原语动作的剩余时间和 dispatch_lag 两者的最大值。在 h 以前没有新的机械臂决策，健康腔加工继续，原 Simulator 结算取移放、资源占用、加工和质量时钟。前缀违反质量期限即给出事件证据。动作完成后已出片的晶圆保留在原始历史及全程验证中，后续 CP 只安排未完成晶圆。对于准入策略，已开始动作的完成时刻和前缀中的工艺进度与维修时刻无关。未完成的后缀采用修复延迟 max(0,r−h)。因此有限维修边界为 h 加上后缀边界，完工时间相应平移。若全部晶圆在固定前缀中完成，按实际最后出片时刻计算完工，维修容忍度无穷。模型接受正取放时长和符合有向三角不等式的移动时长。

早修仅放宽放片或封闭腔取片的最早开始约束，旧计划可等待至原时刻。固定腔分配和机器人顺序后，新增封闭条件仍是一条由修复时刻给出的事件时间下界，沿用原差分约束有限上界及精确整数刻度。工艺策略在进入边界搜索前校验。若维修改变加工时长、恢复瞬间强制取片或质量状态依赖维修时长，本版本不接收该策略。

**质量与时间。** 驻留截至取片完成，持片截至放片完成。输出的顶层 makespan_seconds 和维修时刻都从故障计时。prefix 记录故障和可调度的绝对设备时刻及必做事件。best 和 suffix_search 内层保留后缀求解器的原始相对刻度。求解器区分 OPTIMAL、FEASIBLE、INFEASIBLE 和 UNKNOWN，通过整机原语重放再交付见证。进行可行性查询时 OPTIMAL 只代表该次调用成功，剩余完工最优性读取 makespan_optimal。有限边界见证、无穷界见证和求解预算耗尽时的可行下界分别记录。输入历史不一致报错，与模型外的 UNSUPPORTED 分开。

dispatch_lag 是从故障起到允许发送首个新动作的时间，可按实测或预留的计算时间设置。使用 --elapsed 时，由调用者提供开始求解时距故障的设备秒数，程序加上本次实际计算耗时，在 result.json 的 dispatch_check 中标记 ON_TIME 或 STALE_PLAN。该检查要求设备时钟与墙钟等速、期间仅发生输入中已建模的事件。如首动作时刻已经过去，应读取新快照或用更新后的派发延迟重新求解。实现覆盖快照延迟与时钟检查，现场指令发送、设备状态订阅和滚动控制仍需外部系统。

**算法与核验。** 健康腔或故障腔中已有晶圆的取完截止时间可排序。前 k 片要在第 k 个截止时刻前取完，即使忽略移动和准备，也至少需要 k 次取片、k−1 次放片；若起初持片还需要先放一次。仅当这个工作量严格超过期限才剪枝。沿用 v1.2 的末工序联合上界作为二分搜索上探点；边界优化前独立重放同一查询的已验证调度，加作时间变量提示。提示不限制可行域。Agent 按未完成晶圆数设置首次预算，之后由实际求解状态改变查询值、预算或目标。预算用尽可返回合格见证与 UNKNOWN 边界。

primitive_oracle.py 独立实现离散时间的最短路，枚举等待、空移、持片移动、取片和放片。它与求解器共用配置、Simulator 历史和不可取消前缀语义；后缀状态、约束更新、搜索及目标计算独立于 CP-SAT、剪枝和 LangGraph。触及时间截断或状态预算而未举证时返回 UNKNOWN。它用于很小的精确刻度实例。数值一致性是实现核验。

**对照结果。** 见 [实验摘要](../results/recovery/v1.3.0-acceptance/summary.json)、[逐方法数据](../results/recovery/v1.3.0-acceptance/comparison.csv)、[图表](../results/recovery/v1.3.0-acceptance/comparison.png) 和 [独立枚举记录](../results/recovery/v1.3.0-acceptance/enumeration.json)。每个实例目录含相同输入、三方法输出、求解状态、参数、全程重放或不支持原因。FINITE 在边界处比较最短完工时间，UNBOUNDED 在 r=0 比较。各方法均为单线程、种子0、总预算30秒、每次CP最多2秒，单独的固定维修时刻复核另有2秒。wall_seconds 包括编排和验证，cp_seconds 和 branches 统计边界流程各CP调用，后置复核单列。CP分支数是可获取的搜索规模指标。总时限控制分配给求解器的预算，建模、验证和图初始化有额外开销。

14个场景各运行3种方法，包含3个应拒绝的输入。三种方法结论一致，30次可行结果后置检查通过，27次原语枚举一致。287次边界流程调用中 UNKNOWN 为0。另存零预算和一轮耗尽的压力轨迹。三片对称例中，增强算法将查询数从15降至7，但分支数从1265增至1337。mid_pick 的两种精确方法同为14次调用、47个分支。一次共享机器实测只反映给定实例，不支持普遍加速结论。

同一已加工完成的 S2 晶圆在允许撤离时边界无穷，封闭等待时边界为3秒。封闭案例 Agent 在4秒查询得到不可行，在2秒和3秒得到可行，随后在3秒切换为最短完工优化并采用已验证提示，得到17秒。见 [实际决策轨迹](../results/recovery/v1.3.0-acceptance/sealed/agent.json)。

当前还限制为单设备、单故障、确定时间、完整可重放历史；动作中途只接受已提交的单个原语，尚未拆解不可中断的高层 transfer/unload。实验是合成设备实例，工艺授权和现场设备有效性须由部署方提供。
