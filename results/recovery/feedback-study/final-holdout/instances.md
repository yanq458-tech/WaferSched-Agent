# 新快照逐例对照

编号中的 m、h 表示中、高竞争，t、f、b 表示紧期限、临界期限、可绕行设计。编号末位区分独立种子。输入分组仅表示生成条件。

表中 ✓ 表示按时证明；? 表示 UNKNOWN。各组顺序为 fixed / plain / agent。墙钟超预算按 UNKNOWN 计。配对增退以首轮为主。

## 1 秒

| 快照 | 首轮 | 反序 | Agent 首轮相对固定组合 | Agent 首轮 UNKNOWN 的实测情况 |
|---|---|---|---|---|
| blind-16-m-f1 | ? / ✓ / ✓ | ? / ✓ / ? | 新增证明 | — |
| blind-16-m-f2 | ✓ / ✓ / ✓ | ✓ / ✓ / ✓ | 均证明 | — |
| blind-16-m-f3 | ? / ✓ / ✓ | ? / ? / ✓ | 新增证明 | — |
| blind-16-h-f1 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.374s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN/UNKNOWN；分支 1133；未得到可重放见证或不可行证明 |
| blind-16-h-f2 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.340s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN/UNKNOWN；分支 833；未得到可重放见证或不可行证明 |
| blind-16-h-f3 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.353s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN/UNKNOWN；分支 701；未得到可重放见证或不可行证明 |
| blind-20-m-f1 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 1.496s；整次返回 1.651s 超时，原始状态 FINITE |
| blind-20-m-f2 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 1.301s；整次返回 1.478s 超时，原始状态 FINITE |
| blind-20-m-f3 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 1.110s；整次返回 1.264s 超时，原始状态 FINITE |
| blind-20-h-f1 | ✓ / ✓ / ✓ | ✓ / ✓ / ✓ | 均证明 | — |
| blind-20-h-f2 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.323s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN/UNKNOWN；分支 500；未得到可重放见证或不可行证明 |
| blind-20-h-f3 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.339s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN/UNKNOWN；分支 1027；未得到可重放见证或不可行证明 |
| blind-24-m-f1 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 1.870s；整次返回 2.153s 超时，原始状态 FINITE |
| blind-24-m-f2 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 1.654s；整次返回 1.862s 超时，原始状态 FINITE |
| blind-24-m-f3 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.319s；求解回执 UNKNOWN/UNKNOWN/UNKNOWN；分支 303；未得到可重放见证或不可行证明 |
| blind-24-h-f1 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.305s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN；分支 307；未得到可重放见证或不可行证明 |
| blind-24-h-f2 | ? / ? / ? | ? / ? / ? | 均未知 | 其余流程占时最多 0.320s；求解回执 INFEASIBLE/UNKNOWN/UNKNOWN；分支 115；未得到可重放见证或不可行证明 |
| blind-24-h-f3 | ✓ / ✓ / ✓ | ✓ / ✓ / ✓ | 均证明 | — |

## 30 秒

| 快照 | 首轮 | 反序 | Agent 首轮相对固定组合 | Agent 首轮 UNKNOWN 的实测情况 |
|---|---|---|---|---|
| blind-16-m-f1 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-16-m-f2 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-16-m-f3 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-16-h-f1 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.043s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 97116；未得到可重放见证或不可行证明 |
| blind-16-h-f2 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.168s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 90554；未得到可重放见证或不可行证明 |
| blind-16-h-f3 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 18.501s；求解回执 UNKNOWN/OPTIMAL/OPTIMAL/UNKNOWN/UNKNOWN；分支 102693；已有可行方案，上界未闭合 |
| blind-20-m-f1 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-20-m-f2 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-20-m-f3 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-20-h-f1 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-20-h-f2 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.096s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 95175；未得到可重放见证或不可行证明 |
| blind-20-h-f3 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.115s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 79741；未得到可重放见证或不可行证明 |
| blind-24-m-f1 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-24-m-f2 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-24-m-f3 | ✓ / ✓ / ✓ | — | 均证明 | — |
| blind-24-h-f1 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.048s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 78621；未得到可重放见证或不可行证明 |
| blind-24-h-f2 | ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.015s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 47879；未得到可重放见证或不可行证明 |
| blind-24-h-f3 | ✓ / ✓ / ✓ | — | 均证明 | — |

## 未闭合边界的进展

同一快照上两档预算分别运行。区间单位为秒，问号表示该端没有在预算内获得证据。下界来自合法方案；有限上界来自数学约束或求解器。

| 快照 | 1 秒 Agent 区间 | 30 秒 Agent 区间 | 30 秒首轮求解情况 |
|---|---|---|---|
| blind-16-h-f1 | [?, 88.25] | [?, 77.125] | 精确搜索占时最多 16.043s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 97116；未得到可重放见证或不可行证明 |
| blind-16-h-f2 | [?, 88.125] | [?, 87.625] | 精确搜索占时最多 16.168s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 90554；未得到可重放见证或不可行证明 |
| blind-16-h-f3 | [?, 87.875] | [4.625, 42.25] | 精确搜索占时最多 18.501s；求解回执 UNKNOWN/OPTIMAL/OPTIMAL/UNKNOWN/UNKNOWN；分支 102693；已有可行方案，上界未闭合 |
| blind-20-m-f1 | [?, ?] | FINITE | FINITE |
| blind-20-m-f2 | [?, ?] | FINITE | FINITE |
| blind-20-m-f3 | [?, ?] | FINITE | FINITE |
| blind-20-h-f2 | [?, 103.625] | [?, 103.125] | 精确搜索占时最多 16.096s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 95175；未得到可重放见证或不可行证明 |
| blind-20-h-f3 | [?, 104] | [?, 90.125] | 精确搜索占时最多 16.115s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 79741；未得到可重放见证或不可行证明 |
| blind-24-m-f1 | [?, ?] | FINITE | FINITE |
| blind-24-m-f2 | [?, ?] | FINITE | FINITE |
| blind-24-m-f3 | [?, 121.25] | FINITE | FINITE |
| blind-24-h-f1 | [?, 123.75] | [?, 123.25] | 精确搜索占时最多 16.048s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 78621；未得到可重放见证或不可行证明 |
| blind-24-h-f2 | [?, 121] | [?, 120.5] | 精确搜索占时最多 16.015s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 47879；未得到可重放见证或不可行证明 |

## 逐例配对得失

相对各直接调用对照列出首轮分类增退和未证区间变化。同一输入反序运行的结果单列在 paired.csv。

### 1 秒相对 fixed

- 新增边界证明：blind-16-m-f1、blind-16-m-f3。
- 丢失边界证明：无。
- 均未知时区间更强：无。
- 均未知时区间更弱：blind-16-h-f1、blind-16-h-f2、blind-16-h-f3、blind-20-h-f2、blind-20-h-f3、blind-24-m-f1、blind-24-m-f2、blind-24-h-f1、blind-24-h-f2。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：无。
- 同一有限边界处完工时间变长：无。

### 1 秒相对 plain

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：无。
- 均未知时区间更弱：blind-20-m-f1。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：无。
- 同一有限边界处完工时间变长：无。

### 30 秒相对 fixed

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：blind-16-h-f3。
- 均未知时区间更弱：blind-16-h-f1、blind-16-h-f2、blind-20-h-f2、blind-20-h-f3、blind-24-h-f1、blind-24-h-f2。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：blind-24-m-f3、blind-24-h-f3。
- 同一有限边界处完工时间变长：无。

### 30 秒相对 plain

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：无。
- 均未知时区间更弱：无。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：blind-16-m-f1、blind-24-h-f3。
- 同一有限边界处完工时间变长：无。
