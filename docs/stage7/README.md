# 第七阶段真实研究成果

v1.1.0 成果提交至 `feature/langgraph-research-agent` 开发分支；暂不合并 main、不创建新标签或远程 Release，v1.0.0 保持原样。

## 数据目录与方法映射

保留已有 `results/stage7_langgraph/`，避免改写检查点和日志中的真实产物路径。`live-study-002/A` 是原确定性 CFAR，`B` 是 LangGraph + DeepSeek，`C` 是固定流程。课程报告使用方法名称；按课程任务字母顺序，固定流程 A 对应保存字段 C，CFAR B 对应保存字段 A，LLM Agent C 对应保存字段 B。原始 CSV 的 arm 字段不修改。

正式对照 16/12/16 轮，44 个候选方案全部通过原 Simulator 独立验证。LLM 12 轮均为真实 API 规划、8 轮有效反思；25 条调用记录中 21 次实际 API 请求，4 条预算阻止未发出。F/G 最佳解为 63/183 秒。所有方法最终解质量相同；LLM 总活动时间 134.137 秒，高于 CFAR 55.419 秒和固定流程 28.005 秒。

`live-study-001/B` 保留参数与证据格式错误后的确定性回退，不能计为真实自主研究轮次。`preflight-006` 是唯一成功的最小认证请求。早期认证诊断和旧试跑仍保留在本机，但不纳入本次提交清单。

## 离线复核与复现

先按 [复现说明](reproducibility.md) 安装；无 API Key 也可复核保存的数据：

```powershell
.\.venv-langgraph\Scripts\python.exe experiments/wafer_sched/stage7/reproduce_saved.py --output results/stage7_langgraph/v1.1.0-audit/saved_evidence.json
```

该命令重放 44 条保存决策，核对原始事件指标、LLM 来源和反馈记忆；不发 API、不求解新调度、不训练模型。付费重新实验必须选择新目录，遵守配置预算，本轮没有开展。

## 文档

- [二次开发架构](architecture.md)
- [真实研究验收](research_acceptance.md)
- [发布审计](github_release_audit.md)
- [课程研究报告 Word](WaferSched-Agent_课程研究报告_v1.1.0.docx)
- [课程研究报告 PDF](WaferSched-Agent_课程研究报告_v1.1.0.pdf)

LangGraph 1.2.15 为 MIT，完整版权与许可文本位于 `provenance/langgraph/LICENSE`。上游 commit 尚未独立核验，记录为 null。公开课程报告已隐藏个人姓名、学号与作者元数据；原本机报告不改写。
