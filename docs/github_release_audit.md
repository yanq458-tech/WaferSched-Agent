# WaferSched-Agent 独立仓库与 GitHub 发布审计

审计及中断恢复日期：2026-10-10。独立仓库实际路径：`D:\SemanticaProject\WaferSched-Agent`。原项目：`D:\SemanticaProject\railway_project`。本报告依据真实文件、import、哈希、已保存运行日志和 Git 索引；没有创建公开仓库，没有配置远程仓库，没有执行 git push。

## 1. 当前结论与恢复范围

独立迁移及发布前验收已完成，具备提交到独立 GitHub 仓库的技术条件，等待用户确认发布。本地 main 仓库已初始化并暂存发布文件，但尚无提交，也没有 remote。此次恢复没有重复迁移、重新训练原 PPO 或重跑已通过的耗时实验；只补充文件完整性、原项目保护、发布清单与敏感检查，并修复新发布 README、NOTICE 和模型说明中因 PowerShell 管道编码造成的中文问号。历史源码、数据和模型没有因恢复而覆盖。

最终待提交文件数为 **5044**。逐文件列表见 [github_upload_files.txt](../provenance/github_upload_files.txt)，含大小和 SHA256 的清单见 [release_inventory.csv](../provenance/release_inventory.csv)。后者为避免自引用哈希，明确排除清单自身；待上传文本列表包含它。

## 2. 真实目录与迁移文件

```text
WaferSched-Agent/
├─ README.md / LICENSE / NOTICE.md
├─ pyproject.toml / requirements.txt / requirements-wafer*.txt
├─ .gitignore / .gitattributes
├─ configs/wafer_sched/                 # 29 个 JSON 配置
├─ src/wafer_sched/                     # 67 个 Python 文件
│  ├─ simulator.py / metrics.py / observation.py / policy_runner.py
│  ├─ policies/ / cpsat_*.py / rl/
│  ├─ agent/                           # 七个 Skill 与 CFAR
│  │  └─ _semantica/                   # 保留许可证的上下文与记忆子集
│  └─ infrastructure/                  # 独立路径、IO、任务和可选 HTTP 适配
├─ tests/wafer_sched/
├─ experiments/wafer_sched/
├─ scripts/                            # 独立 worker、历史复核与发布验收
├─ docs/                               # 原阶段记录、来源审计与本报告
├─ provenance/                         # 来源、迁移哈希、路径变更和上传清单
└─ results/
   ├─ wafer_sched/                     # 原第一至第六阶段可公开研究产物
   └─ release_validation/              # 本次独立验收与中断恢复证据
```

`.venv/`、`.migration-private/`、pytest/ruff 缓存及 `results/local/` 仅在本地，均不纳入 Git。原平台的 api、铁路 models、data、storage、数据库、前端和原虚拟环境没有迁移。`docs/workspace_inventory.json` 及历史保护清单中出现的铁路路径是审计元数据，不能把这些路径记录解释为已复制了对应业务文件。

| 对象 | 数量与一致性 | 直接证据 |
| --- | --- | --- |
| 原研究文件来源哈希 | 4,742 个 | `provenance/original_research_sha256.json` |
| 历史结果与模型产物 | 4,631 个，全部迁移 | `provenance/migration_manifest.json` |
| 历史产物字节不变 | 4,227 个 | 同上及 `results/release_validation/history.json` |
| 历史产物路径规范化 | 404 个：346 JSON、46 JSONL、8 XML、4 TXT | `provenance/path_normalization.json` |
| 原研究代码等迁移文件 | 111 个逐文件原始/发布哈希 | `provenance/source_migration.json` |
| 迁移后 Python 实现 | 67 个，包含 8 个新适配模块 | `results/release_validation/release_resume_check.json` |
| 配置 | 29 个 JSON | `configs/wafer_sched/` 及恢复检查 |
| 模型 ZIP | 14 个，原始和发布 SHA 完全一致 | `history.json`、迁移清单 |

404 个历史文件仅规范化路径或机器相关文字；数值没有改写。历史 CSV、PNG、ZIP 和压缩事件文件保持字节不变。另一个规范化文件是迁移副本中的来源审计文档，因此总路径变更记录可能显示 405 个文件，而历史结果计数仍是 404。不得声称迁移所有文件的原始字节均未变。

中断恢复时再次核对所有 4,631 个历史产物、111 个迁移代码及配置等文件和 12 个上游实现文件，哈希失配为 0；2,878 个历史 JSON/JSONL 均完整解析。没有发现未完成复制或截断写入。历史失败实验保留其失败状态，不因为文件完整就算作成功。

## 3. 原项目保护

`results/release_validation/original_preservation.json` 对原项目的 87,462 个非符号链接文件逐一比较大小及纳秒修改时间：新增、缺失、变化均为 0；再对 4,742 个原研究文件进行 SHA256 检查，失配为 0。原始元数据基线留在新目录的私有迁移目录，不公开原工作区全部文件列表。

这是对文件元数据及选定研究内容的保护验证，不声称为原项目全部 87,462 个文件进行了内容哈希。整个迁移及恢复没有向原 railway_project 写入、删除或移动文件。

## 4. 来源、许可证与依赖解耦

新研究代码与独立适配层使用根目录 MIT LICENSE。Semantica 必要子集保留目录内原 MIT LICENSE、版权和 PROVENANCE.json；12 个上游实现文件 SHA 与迁移前一致，3 个最小包初始化文件是原晶圆研究已有的包装。上游地址为 https://github.com/semantica-agi/semantica ，原 vendor 副本报告版本 0.7.0，但未独立核验对应 Git commit。具体说明见 [NOTICE](../NOTICE.md)。

原铁路平台的通用模块依赖已替换为 `wafer_sched.infrastructure`：

- `paths.py` 定位发布根目录，配置、模型、结果和研究记忆以根目录相对路径加载与存储。
- `io.py` 提供运行 ID 和原子持久化写入；没有引入业务服务。
- `scheduler.py` 提供有界任务执行、同工作区串行和关闭行为，按本项目单 worker 配置验收。
- 可选模型 HTTP 适配使用独立 worker；默认禁止 LLM 网络出口，没有把接口存在当作已验证 LLM 规划。
- `scripts/run_worker.py` 与 `run_model_worker.py` 从所在新仓库启动，跨目录恢复不依靠指向旧项目的 PYTHONPATH。

所有研究 import 统一为 `wafer_sched`。AST 检查没有 `api`、`api.*` 或遗留 `src.wafer_sched` 导入。`results/release_validation/numerical/acceptance.json` 对应的实际运行安装了禁止铁路 API 导入的拦截器，并拒绝访问 railway_project 文件；演示、CP 和全部原模型推理通过。Semantica 子集仍是项目明确保留的开源依赖，但运行不需要原铁路平台、数据库或它的日志服务。

仿真、事件、动作、约束、指标、策略运行、CP 数学模型/求解/验证、RL 环境/编码/奖励等 14 个数值核心文件保持原字节；此检查在 `tests/wafer_sched/test_release.py` 中执行。`metrics.py` 和 `simulator.py` 没有被独立适配层替换，实验指标没有引入铁路算法。

## 5. 独立验收结果与运行证据

独立环境位于新仓库 `.venv/`，基于 CPython 3.13.13，不启用 system site-packages。原 39 个锁定依赖版本一致；使用本仓库的可编辑安装。没有设置 PYTHONPATH 或 WAFER_SCHED_ROOT 来引用原项目。

| 检查 | 实测结果 | 文件证据 |
| --- | --- | --- |
| 全部 WaferSched 测试 | 216 项：215 通过、1 跳过、0 失败、0 错误 | `results/release_validation/wafer_tests.xml`、`wafer_tests.txt` |
| 从真实 Git 索引导出后独立测试 | 同样 215 通过、1 跳过 | `git_snapshot_tests.xml`、`git_snapshot_tests.txt` |
| 最小仿真案例 | 3 片晶圆完成，Makespan 47 秒 | `numerical/demo/`、`numerical/acceptance.json` |
| CP-SAT 最小案例 | OPTIMAL，目标 47 秒，原 Simulator 验证通过 | `numerical/cpsat/` |
| 原 PPO 独立推理 | 14 个模型成功加载、合法完成；6 个正式 best 模型事件逐条符合旧评价轨迹 | `numerical/acceptance.json`、`numerical/ppo-*/` |
| 模型完整性 | 14 个 ZIP CRC 通过，12 个正式模型符合历史验证 SHA | `history.json` |
| 历史指标重算 | 378 组，数值失配为 0 | `history.json` |
| 已完成历史决策独立重放 | 148 组通过；另 2 个未完成案例未算作通过 | `history.json` |
| 五轮真实 CFAR | 5 轮均完成 4 片，约束通过率 1.0 | `cfar/decisions.csv`、`cfar/summary.json` |
| 换根目录会话恢复 | 新版本暂停第 3 轮，另一个根目录真实执行至第 5 轮，manifest 和源哈希一致 | `relocation.json`、`cfar_checkpoint_before_relocation/` |
| 静态与依赖 | Ruff、pip check 通过，39 个锁定版本相符 | `static_checks.json`、`ruff.txt`、`pip_check.txt` |
| 本次恢复轻量复核 | 文件哈希、模型身份、import 和结构化历史文件均通过 | `release_resume_check.json` |

跳过项需要 Windows 创建符号链接权限；不是失败后跳过数学验证。首次独立测试曾有 2 个历史原始字节保护断言失败，其证据保留为 `wafer_tests_attempt1.xml`；原因是 XML 中路径已按迁移要求规范化。两个测试改为同时核验原始身份和显式迁移哈希，未修改物理约束、原始历史保护清单或结果数字，随后两处完整测试均通过。

Git 导出测试执行于 `.migration-private/git-snapshot/`，从暂存的真实 Git 索引导出源码和数据；依赖仍为新建独立虚拟环境，源码导入来自导出根目录。不是仅复制测试结果，也不引用铁路项目。最终补充内容仅为 Markdown、文件清单和恢复证据，没有改变已验收的研究实现，所以没有重跑整套耗时流程。

### 本次五轮反馈的实际轨迹

场景为 G_dual_bottleneck，seed=0，固定评价窗口 400 秒，最大 5 轮、总预算 120 秒。该窗口中所有轮均完成 4 片，因此窗口 WPH 均为 36，平均腔室利用率均为 0.123333，机器人利用率均为 0.3775；不能把相同指标人为放大为改进。完成时长不同，故以完整批次 Makespan 为主目标。

| 轮次 | 实际方法与参数 | Makespan（秒） | 单轮实际墙钟时间（秒） | 反馈依据/接受情况 |
| --- | --- | ---: | ---: | --- |
| 1 | FIFO | 185 | 0.238440 | 无历史时建立合法基准；接受 |
| 2 | Bottleneck | 199 | 0.237483 | FIFO 的阻塞/加工=0.743243；检验瓶颈规则，未改善，不接受 |
| 3 | 原 PPO medium-seed-0 | 183 | 4.833460 | 已验证规则仍阻塞，选择兼容已有模型；接受，无重训 |
| 4 | CP 搜索 1 秒 | 183 | 1.847119 | 使用合法 incumbent 作 hint；同 Makespan、较低成本，接受 |
| 5 | CP 搜索 3 秒 | 183 | 4.380798 | 上一轮 FEASIBLE、下界 142、gap 0.224044，增加搜索预算；未改善，不接受 |

第 3 轮首次得到最终最佳完成时长，累计约 5.580495 秒；最终反馈累计耗时 12.820519 秒，全会话墙钟 12.972052 秒，以 max_rounds 停止。第 4、5 轮的 CP 均为 FEASIBLE，不是本场景全局最优证明。触发原因和历史证据在 decisions.csv/experiments.jsonl 中保存。该五轮是迁移验收，不替代历史多种子对照研究。

## 6. 历史实验的一致性与研究结论

第五阶段的模型 ZIP、CSV 与图表原字节保持不变；路径规范化后的 JSON/JSONL 保留原数值。指标从真实事件重算而非引用文档结论。第二至第六阶段重算数量分别为 2、50、72、104、150，总计 378。

原第六阶段分析中，CFAR 在 F/G 开发场景较固定顺序更早找到同样最佳方案：F 为 6.464 对 7.503 秒，G 为 4.490 对 5.236 秒；总成本却更高：F 为 19.068 对 11.747 秒，G 为 18.923 对 11.812 秒。132 个合法与 2 个失败实验完整迁移。U_recipe_mix 和 U_slow_transport 的失败或退化表现没有隐去。当前仅完成静态工况研究，没有验证 LLM 自主规划、动态故障优化或自主修改 RL 代码。

所有原模型直接迁移；没有重新训练原模型来替代它们。单元测试在临时目录中进行新的 64 步训练只用于检验真实梯度/保存/加载，不替换原 PPO。此次断线恢复没有新增训练或数值实验。

## 7. Git、敏感文件与大文件

最终索引和工作树一致性、逐文件列表与字节核验记录于 `results/release_validation/release_git_state.json`。全部列出的文件均是本地待首次提交文件；没有历史提交、远程地址、公开仓库或 push 操作。

`results/release_validation/sensitive_and_size_check.json` 是对实际待提交清单的扫描：没有发现密钥格式、个人 home 目录路径、虚拟环境、私有迁移基线、数据库或无关铁路业务文件；运行代码、配置和启动脚本没有硬编码原项目绝对路径。审计文档中的项目路径、上游源码中的出处以及不参与执行的历史保护元数据保留其解释用途。扫描是路径与模式检查，不能声称穷尽一切秘密检测。

最大文件为 `results/wafer_sched/stage5/training/medium/seed-7/transition_rewards.csv`，3,186,653 字节；没有超过 50 MiB 或 100 MiB 的文件。14 个模型合计约 1.09 MB，全部纳入待上传清单，不需要删除或改为外部下载。后续大模型版本化方案见 [模型存储说明](model_storage.md)，GitHub 限制依据见其中官方链接。

`.gitattributes` 设置 `* -text`，保持源码、CSV 和日志的精确字节，防止 autocrlf 改写后破坏历史 SHA。Git 索引导出已实际验证。`.gitignore` 排除环境、缓存和私有目录，但不忽略原模型或研究结果。

## 8. 尚未解决的限制与待用户确认事项

- 上游 Semantica vendor 副本的确切 commit 未独立核验；许可证与 12 个实际文件哈希均保留。
- Windows 符号链接权限导致 1 项跳过；其他系统、Python 版本和只安装 wheel 的分发方式尚未完整验收。
- 完整旧版本源码快照并未逐阶段保存；训练前源码的部分原文只有历史哈希，不能声称可重建每个旧版本源码。
- 换根目录恢复验证针对新发布版本。旧会话仍保留原始身份记录，不能绕过源代码/配置/模型身份检查冒充可直接继续旧源码会话。
- 模型 ZIP 内可能保留 cloudpickle 的原调试文件名；禁止访问旧项目时已实际加载推理通过，不能把惰性调试字符串解释为运行依赖。
- LLM 网络规划、多工作区任务公平性、动态故障、自主改写 RL 和跨场景稳健提升属于未完成验证或后续研究，不是本次发布阻塞项。
- 尚未创建 GitHub 仓库、首个提交、tag 或 Release；需用户确认目标账号、仓库名称及可见性后才进入正式发布。本次停在上传前。

技术迁移、独立运行验收、来源说明、历史一致性、发布清单均已完成。下一步只在用户明确确认后安排实际 GitHub 发布；本报告不构成已上传证明。
