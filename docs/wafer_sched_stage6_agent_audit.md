# 第六阶段开发前接口审计

审计日期：2026-10-10。本文件先于第六阶段实现写入；以下“计划”不代表运行成功。

## 已核实接口与复用边界

| 已有接口 | 源码证据 | 本阶段处理 |
| --- | --- | --- |
| 只读助手 | `api/services/assistant.py`、`assistant_llm.py` | 固定意图与事实润色，不具备通用Skill执行循环；新增研究注册器 |
| 结构化规划 | `assistant_graph_planner.py` | 复用候选计划→Schema/白名单验证→本地执行模式，不修改铁路查询器 |
| LLM通信 | `model_transport.model_completion` | 真实兼容chat接口：5秒HTTP子进程截止、2并发、60次/小时、512输出token；复用此函数 |
| 外发授权 | `assistant_llm.py`及平台项目授权检查 | 配置模型不等于研究数据外发授权；研究入口另要求显式`allow_llm_egress`，默认关闭，只检查环境变量是否齐全，不记录值 |
| 任务执行 | `run_scheduler.WorkspaceRunScheduler.submit` | 接受Python callable，确实是通用有限队列；研究使用独立实例/研究workspace标识，不调用铁路优化服务、不获取在线任务租约 |
| 原子持久化 | `run_journal.atomic_record`、`local_runtime.durable_replace` | 复用，逐实验独立目录；已保存研究产物继续由原`save_run`生成 |
| 规则、CP、RL | `policy_runner.run_policy`、`cpsat_solver.solve_schedule`、`cpsat_validator.validate_solution`、`rl.policy.TrainedPolicyAdapter` | 调用原实现。CP无解不以规则解冒充CP解；RL只加载已有模型 |
| 设备验证/指标 | `Simulator.validate_action/validate_state`、`metrics.calculate_metrics` | 原Simulator执行和事件积分；增加独立重放检查，不改变数学约束 |

## Semantica记忆与图上下文

研究环境尚未安装完整Semantica，旧`.venv`启动器失效。现存`.venv/vendor/semantica/semantica/`和旧site-packages提供实际Semantica 0.7.0源码：`context.agent_memory.AgentMemory`支持无向量库store/retrieve/save/load；`context.context_graph.ContextGraph`支持add_node/add_edge/get_neighbors/to_dict，关闭advanced_analytics即可避免KG计算依赖。

完整`semantica.context.__init__`会急切导入大量本研究不需要的检索/图分析模块，完整包依赖也会改变现有研究环境。计划将**真实、未修改的必要源码及相对导入闭包**以MIT许可放入`src/wafer_sched/agent/_semantica/`，添加轻量包初始化文件，使用其真实AgentMemory与ContextGraph方法。记录原路径、逐文件SHA-256、MIT许可证及来源说明，并用集成测试验证调用。该子集不是完整Semantica安装，不宣称具备向量RAG、DecisionRecorder或完整上游编排器。

锁文件记录上游提交`7996d1ab4bd0c96ea7e3d91a4ce70fe5881d224b`，旧安装direct_url指向本地vendor；vendor不含独立.git。不能据此证明现存源码与该提交逐字一致。交付子集以实际文件哈希固定版本，保留此溯源局限，复现无需依赖旧虚拟环境。

权威实验历史使用原子JSON记录，Semantica记忆存取结构化摘要，图记录场景→实验→方法及反馈依赖。恢复时从已提交实验重建上下文，防止缓存充当真实结果。

## 第六阶段实施计划

1. 保存前五阶段源码、配置、测试、报告与结果（含模型）的保护哈希；添加上述源码子集及PyYAML单独依赖，不更改原数值实现。
2. 新增严格ExperimentProposal、七个可运行Skill、约束优先接受器、确定性反馈规划、显式LLM回退、有预算的原平台任务执行、实验边界恢复。预训练RL兼容性先检查；本阶段不注册训练和跨场景调参操作。
3. 开发F/G每轮重新读取真实历史，按阻塞/利用率、规则退化、RL结果、CP状态和证明界选择下一候选；测试同一轮次不同反馈会改变选择。已证明最优/候选耗尽/预算截止均可停止，不人为保证提升。
4. 在相同候选集与总预算下对照固定顺序、反馈规划；另比较固定CP预算和状态驱动预算。无可用且授权的LLM时只做回退检验，不生成LLM性能曲线。
5. 新场景预先封存，开发完成后冻结最终方法与参数，再各运行一次最终评价。H及第五阶段旧测试明确属于已使用评估场景。
6. 保存每轮提案、实调用、结果、重放验证、接受/拒绝、下一提案与停止原因；生成真实图表及中文阶段总结，执行全部晶圆测试、必要平台回归、ruff和pip check。

## 指标与比较规则

同一配置哈希、批次与预声明窗口才能比较Makespan；先全完成、再合法无死锁、然后Makespan，数值相同时比较真实实验墙钟成本。WPH以共同观察窗口计算，另列有限批次完成时间吞吐率；不冒称稳态产能。CP状态与界单列，FEASIBLE不标最优。累计预算包含加载、求解、仿真、验证、保存及规划成本，硬限额在研究执行边界检查；数值工具内部仍遵守自身限额，记录可能的启动/收尾开销。

本阶段目标是实证CFAR反馈机制；best-so-far单调只来自接受器，不是收敛定理。既有静态研究范围与动态设备范围的差异继续保留。
