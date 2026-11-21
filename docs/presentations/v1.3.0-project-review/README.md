# WaferSched-Agent 故障恢复研究汇报

[20 页可编辑研究汇报 PPT](WaferSched-Agent_v1.3.0_研究汇报.pptx) · [逐页 Word 讲稿](WaferSched-Agent_v1.3.0_逐页讲稿.docx)

材料以本地 17 页演示稿和约 20 分钟的扩展讲稿为底稿。在原“当前支持范围”与“后续研究方向”之间插入三页，原末页顺延至第 20 页。完整讲稿建议用时 23 分 08 秒；若限时 20 分钟，可将第 2、7、13 页的详述留到答疑。

| 页码 | 内容 | 核对材料 |
|---|---|---|
| 1–16 | 数学问题、模型、Agent 流程及 v1.3.0 发布验收 | [历史验收目录](../../../results/recovery/v1.3.0-acceptance/) |
| 17 | 30 秒内得到 9 个有限精确边界，另有 2 个即刻维修也无解的快照 | [盲测汇总](../../../results/recovery/feedback-study/final-holdout/summary.json) |
| 18 | 7 个高竞争 UNKNOWN 快照的编号及 Agent 的已验下界与已证上界 | [逐例结果](../../../results/recovery/feedback-study/final-holdout/instances.md) |
| 19 | 固定工具组合、同策略普通函数、离线 LangGraph Agent 的首轮结果及反序复测 | [配对记录](../../../results/recovery/feedback-study/final-holdout/paired.csv) |
| 20 | 工艺规则、算法规模与在线接续的后续研究方向 | [适用范围](../../recovery-v1.3.md) |

新增表格均可在 PowerPoint 中编辑；原时间轴、图表和内嵌工作簿沿用本地底稿。两档预算下，普通函数与 Agent 在首轮证明了相同的实例。[实验协议与复现命令](../../recovery-closeout.md)

## 汇报材料源文件

[底稿提交](https://github.com/yanq458-tech/WaferSched-Agent/commit/6c9eeb49e118360fd7885e3f08040cc90c2729da)保留本地修改后的原稿与长讲稿。[新增三页的文字与讲稿](sources/blind_review.json)与[版式](sources/blind_slides.mjs)配套使用。[更新脚本](sources/update_blind_review.py)读取原始逐次记录生成表格，导入底稿后仅移入新增幻灯片，再向长讲稿插入对应段落。历史生成器和 content.json 对应原 17 页的短版材料。

在含完整 Git 历史、项目所用 Codex 运行时（Artifact Tool、python-docx、lxml）的环境中，于仓库根目录执行：

```powershell
$python = Join-Path $env:USERPROFILE ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
& $python docs/presentations/v1.3.0-project-review/sources/update_blind_review.py
& ./docs/presentations/v1.3.0-project-review/sources/render_materials.ps1
```

第二条命令在装有 PowerPoint 和 Word 的 Windows 环境中逐页渲染，预览和版面检查结果写入本目录的 build 子目录。
