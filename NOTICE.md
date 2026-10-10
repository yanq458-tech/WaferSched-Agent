# 代码来源与版权说明

WaferSched-Agent 是在 Semantica 平台工作区内增量开发的数学研究项目。本发布目录只迁移晶圆研究代码，并将原平台的通用接口替换为独立适配层。新研究代码及适配层按根目录 MIT 许可证发布。

`src/wafer_sched/agent/_semantica/` 保留 Semantica 0.7.0 的必要上下文、研究记忆和日志工具子集。来源为 https://github.com/semantica-agi/semantica ，本次迁移的实际来源是原工作区已有的 vendor 副本。12 个上游实现文件保持字节不变，另有 3 个最小包初始化文件。该目录保留原 MIT LICENSE、`Copyright (c) 2026 Semantica` 和 PROVENANCE.json。原副本对应的上游 Git commit 尚未独立核验，不能声称来自已确认的特定提交。

`wafer_sched.infrastructure` 是针对独立运行接口新写的 Python 标准库适配层，提供根目录相对路径、原子 JSON 写入、运行 ID、有限队列任务执行和可选 HTTP 模型接口。它没有复制铁路 API、数据库或铁路求解器。线程适配层在本项目单 worker、单 pending 配置下验收，不宣称具备原平台所有多工作区公平性功能。

OR-Tools、Gymnasium、Stable-Baselines3、sb3-contrib、PyTorch、NumPy、Matplotlib、PyYAML 等依赖按各自许可证分发；锁文件只记录版本，本仓库不提交虚拟环境或第三方 wheel。

历史实验产物来自原工作区的真实晶圆研究运行。迁移副本中的路径与机器相关文字规范化记录于 `provenance/path_normalization.json`；数值未改写，CSV、模型 ZIP 和图表保持原字节。原文件与发布副本的 SHA256 分别保存在迁移清单中。
