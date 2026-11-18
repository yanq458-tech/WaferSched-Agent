# v1.2.0 中文项目研究汇报材料

正式汇报使用 `WaferSched-Agent_v1.2.0_项目研究汇报.pptx`，共18页，按逐页讲稿建议用时合计20分钟。`WaferSched-Agent_v1.2.0_逐页汇报讲稿.docx` 共9个打印页面，每页对应两张PPT，含讲解提示和原始证据定位。PowerPoint备注也保存逐页讲稿。

发布整理说明：main现已整合v1.2.0代码及本目录材料。PPT、Word和事实清单保留制作时的历史快照；其中“main尚未合并”的讲述指材料制作时，不是本次整合后的状态。原始PPT与Word文件未改写，历史版本标签未移动。

本次合并后的离线回归：264项通过、1项跳过，另排除1项实际PPO训练测试；其中26项故障恢复测试全部通过。测试进程禁用网络连接。详见[本地整合验收](qa/main-integration.json)及[JUnit记录](qa/main-integration-tests.xml)。该记录与原始v1.2.0验收分开保存。

## 文件索引

| 文件或目录 | 用途 |
|---|---|
| `项目技术摘要.md` | 数学问题、方法、保证、结果、绝对路径和后续三项优先方向 |
| `项目事实清单.md` | 本轮读取的项目事实与版本状态 |
| `charts/汇报图表_可编辑.pptx` | 三张原生可编辑统计图；在PowerPoint中右键图表“编辑数据” |
| `charts/*.csv`、`charts/chart_data.json` | 静态基线、阶段七活动时间、恢复分支数和默认调度时间数据 |
| `data/slide_content.json` | 18页标题、结论、讲稿、用时和证据索引 |
| `data/facts.json`、`data/source_index.json` | 重新核算的事实、原始文件绝对路径及SHA256 |
| `data/github_releases.json` | 只读获取的GitHub Release核验结果，不含认证信息 |
| `data/*.csv` | 保存的原始对照表副本 |
| `scripts/` | 内容、PPT、Word、图表数据生成及质量检查脚本 |
| `qa/slides/`、`qa/word/` | PowerPoint逐页PNG、Word原生导出PDF及逐页PNG |
| `qa/materials-check.json` | 最终材料一致性与源文件完整性检查 |
| `qa/presentation-validation.json` | PPT包、字体、原生图表、表格和版式校验 |
| `build/` | 可重新生成的编辑模型与构建中间文件，不作为正式汇报文件 |

设备图、资源冲突时间轴、边界搜索、Agent流程图和默认调度甘特图均由PowerPoint原生形状与文字构成，可逐项编辑。统计图为3个原生图表，分别附带可编辑Excel工作簿；6张表格也是原生表格。

构建中间文件、临时图表工作簿目录和内部校验收据不纳入Git。上述 `build/` 与 `qa/presentation-validation*.json` 可通过生成脚本重建；原生Office检查记录、最终渲染图片和材料校验结果随本目录保存。

## 数据解释

- 第13页为历史静态F/G场景的Makespan；第15—16页为故障后的修复延迟与剩余完工时间，不跨场景比较大小。
- 第14页活动总时间图显示到小数点后3位。`charts/stage7_active_time.csv` 保留读取值。原始comparison.csv每组在F/G各行重复组总时间，汇总时按组去重，不能累加两次。
- 第16页CP分支数来自9类实例的保存记录，按方法累加：基础4718、安全判据3625、离线Agent5119。它是这些运行的求解器搜索统计，不是一般复杂度或普遍加速比。
- `charts/default_schedule.csv` 采用真实保存方案；甘特图的腔室条只画加工区间，实际容量占用延续至取片完成，机器人条包含持片等待。
- 第3页是解释资源竞争的数学构造，明确不当作新增实验。
- 265项通过/1项跳过、独立环境26项通过，均从原有JUnit与验收文件核对。本轮没有重跑测试或求解实验。
- 对称解析式仅用于严格子类；一般恢复问题依赖精确模型。核验不代替一般证明，不宣称全球首次。

## 修改与重新生成

当前正式材料可以直接用PowerPoint和Word打开修改，无需运行脚本。若需要从数据重新生成，在本目录运行：

```powershell
$runtimeRoot = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime'
& "$runtimeRoot/dependencies/python/python.exe" scripts/content.py
& "$runtimeRoot/dependencies/python/python.exe" scripts/build_documents.py
& "$runtimeRoot/dependencies/node/bin/node.exe" scripts/build_deck.mjs
& ./scripts/render_materials.ps1
& "$runtimeRoot/dependencies/python/python.exe" scripts/verify_materials.py
```

`content.py` 是讲稿内容的编辑源；`build_deck.mjs` 是图形版式与公式的编辑源。同步修改这两处，避免PPT与Word不一致。`build_documents.py` 会同时更新技术摘要和绘图数据。

脚本依赖本机Codex捆绑的ArtifactTool、python-docx与Poppler，PPT校验使用已安装的Presentations技能辅助程序；渲染需要Windows桌面版PowerPoint和Word。Node脚本允许用 `CODEX_RUNTIME`、`PRESENTATIONS_SKILL` 环境变量指定路径。换机时直接编辑成品最方便，重新生成需配置这些依赖。

`collect_facts.py` 仅在需要重新审计项目状态时手动运行：会读取本地Git和已保存数据，并只读请求GitHub API，不进行提交、推送、训练或求解。日常改版不必重复运行它。

## 实际检查与范围

18页PPT与9页Word均使用本机Microsoft Office成功打开并渲染，已逐页目视检查文字、公式、图表和分页。PPT文本框未发现尺寸溢出；6张表格亦完成目视检查。Word没有空白尾页或标题单独落页。图表有嵌入数据，未使用图表截图替代。

本机捆绑环境未提供LibreOffice，因此Word采用原生Word导出PDF，再由捆绑Poppler转PNG。Poppler日志有本机中文路径下辅助nameToUnicode文件警告，但9页均成功输出并逐页检查，无可见缺字。

制作时的Git核验快照：分支 `codex/fault-recovery-boundary`；v1.2.0与当时HEAD均为 `7812cc93ea7a860e83b1a534ba669ba4387cbc75`。v1.0.0标签存在，未查询到同名GitHub Release对象；v1.1.0、v1.2.0有正式Release。当时远程main停在v1.1.0对应提交；本次已将故障恢复及汇报材料整合至main。精确复现原始验收仍应选择v1.2.0标签。

汇报制作轮只新增本目录材料，当时未提交或推送GitHub。本次发布整理按用户授权整合至main，原始求解源码、模型权重、历史实验和Git标签仍保持不变，没有调用付费API。

[GitHub仓库](https://github.com/yanq458-tech/WaferSched-Agent) · [v1.2.0 Release](https://github.com/yanq458-tech/WaferSched-Agent/releases/tag/v1.2.0)
