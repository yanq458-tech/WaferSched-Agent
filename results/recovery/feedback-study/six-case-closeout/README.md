# B 批六个高竞争快照结项复测

在此前两种策略 30 秒首轮均为 UNKNOWN 的六例上，使用同一套求解工具各跑 1 秒、30 秒，再交换顺序。48 次均在预算内返回，新增精确边界或立即不可行证明为 0。保留历史和本次两种策略取得的最佳上下界后，六例均未进一步收紧。

|快照|结项保留区间（秒）|1 秒智能体比人工多压低的上界（首轮 / 反序，秒）|30 秒观察|
|---|---|---:|---|
|16-h-1|? ～ 41.875|+0.25 / +0.25|两轮均同上界。仍缺立即修复的方案或无解证据。|
|16-h-2|? ～ 51.625|−7.75 / +0.375|两轮均同上界。1 秒首轮智能体查零返回 UNKNOWN，容量松弛给到 676 刻度，人工为 610；反序时两者均到 610。|
|20-h-3|4.75 ～ 104|+0.25 / +0.375|首轮智能体得到可重放至 4.75 秒的方案，人工此次未找到；两轮人工上界均为 104，智能体均为 104.125。反序时下界相同，智能体区间宽 0.125 秒。|
|24-h-1|1.375 ～ 73.25|0 / +0.25|两轮、两种策略均得到相同上下界。|
|24-h-2|? ～ 119.125|+0.25 / 0|首轮相同；反序智能体上界 123.625，宽 4.5。该轮容量松弛给到 994 刻度，人工为 958，两者后续各排除 5 个高端刻度。|
|24-h-3|? ～ 106|+0.25 / +0.25|两轮均同上界，仍缺立即修复的方案或无解证据。|

问号表示缺全批合法方案。本轮 1 秒档均无可行下界，只能比较上界。表内保留区间汇总跨策略证据，不计作某一次运行成绩。与历史相同条件比较，20-h-3 的人工策略在 30 秒首轮丢掉原有见证，反序找回；24-h-2 的智能体在 30 秒反序上界退步 4.5 秒。

[24 组同轮配对与耗时](paired.csv) · [48 次与历史同策略对比](historical.csv) · [逐例最终保留区间](retained.csv) · [原始日志与方案](runs/) · [学习策略实际决策与回执](decisions.json)

## 快照来源与证据核验

B 批是项目设备模型生成的合成故障快照。16、20、24 片各设中、高两档竞争，每档 3 例。生成器从可达在制状态出发，用种子配置末道路线和期限，入组前重放历史。24 片中竞争有 5 个健康末道腔加 F，高竞争有 2 个健康末道腔加 F，并偏向 H1。本次属于历史难例复测。人工是手写查询策略，智能体是离线学习选择器。两者共用 LangGraph 与单线程求解工具，未训练或调用外部 API。

[种子与输入哈希](../value-agent-002/manifest.json) · [18 个输入](../value-agent-002/inputs/) · [批次生成程序](../../../../src/wafer_sched/recovery/feedback/learned_study.py) · [路线和期限生成规则](../../../../src/wafer_sched/recovery/holdout.py) · [本轮协议](protocol.json)

计时使用 B 批原提交，源码、模型、输入均通过封存哈希校验。每例沿用历史绑定核心，三例先人工、三例先智能体，次轮对调。计时包含读入输入和模型、预测、图编排、求解和运行内验证，磁盘日志及事后审计另计。测试在共享桌面上运行，部分 30 秒运行与 PPT 文件处理重叠；绑核和反序不能消除系统负载差异。7 条带方案的记录对应 2 份去重方案，均通过发布版模拟器重放。6 份不同初始数学证书通过复核，48 次最终端点与求解回执一致。用求解器收紧的上界保留求解回执，未另行生成形式化证明。115 次学习策略决策中，两个不同端点均可选的有 34 次，选找方案 26 次、查上界 8 次。[审计结果](audit.json)

## 离线复现

在仓库根目录使用项目研究环境，需可绑定的核心 2、4、6、8。输出目录必须是新目录；墙钟预算下的端点和用时可能波动。

```powershell
$timing = Join-Path $env:TEMP ('wafer-six-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $timing | Out-Null
git archive --format=zip --output "$timing/src.zip" 0cd54f4cbf4879b065c6b2fd36739840fd5b5076 src
Expand-Archive -LiteralPath "$timing/src.zip" -DestinationPath $timing
$env:PYTHONHASHSEED = '0'
$env:OPENBLAS_NUM_THREADS = '1'
$env:PYTHONPATH = Join-Path $timing 'src'
$out = 'results/local/six-case-reproduction'
.\.venv-langgraph\Scripts\python.exe scripts/retest_six_recovery.py --out $out
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv-langgraph\Scripts\python.exe scripts/review_six_recovery.py $out
```

只核验本次封存证据时，将最后一条命令的目录改为 `results/recovery/feedback-study/six-case-closeout`。相关反馈、学习查询和智能体回归测试合计 13 项通过。
