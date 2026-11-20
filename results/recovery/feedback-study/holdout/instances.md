# 新快照逐例对照

编号中的 m、h 表示中、高竞争，t、f、b 表示紧期限、临界期限、可绕行设计。编号末位区分独立种子。输入分组仅表示生成条件。

表中 ✓ 表示按时证明；? 表示 UNKNOWN。各组顺序为 legacy / fixed / plain / agent。墙钟超预算按 UNKNOWN 计。配对增退以首轮为主。

## 1 秒

| 快照 | 首轮 | 反序 | Agent 首轮相对固定组合 | Agent 首轮 UNKNOWN 的实测情况 |
|---|---|---|---|---|
| new-16-m-f1 | ? / ✓ / ? / ? | ? / ✓ / ? / ? | 丢证明 | 其余流程占时最多 0.657s；求解回执 UNKNOWN/UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-16-m-f2 | ? / ✓ / ? / ? | ? / ✓ / ? / ? | 丢证明 | 其余流程占时最多 1.181s；整次返回 1.363s 超时，原始状态 FINITE；求解回执 UNKNOWN/OPTIMAL；分支 712 |
| new-16-m-f3 | ? / ✓ / ? / ? | ? / ✓ / ? / ? | 丢证明 | 其余流程占时最多 1.171s；整次返回 1.295s 超时，原始状态 FINITE；求解回执 UNKNOWN/OPTIMAL；分支 349 |
| new-16-h-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-16-h-f2 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 精确搜索占时最多 0.396s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/UNKNOWN；分支 5637；未得到可重放见证或不可行证明 |
| new-16-h-f3 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 0.650s；求解回执 UNKNOWN/FEASIBLE/INFEASIBLE/UNKNOWN；分支 3433；已有可行方案，上界未闭合 |
| new-20-m-f1 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 0.811s；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-20-m-f2 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 0.795s；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-20-m-f3 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 1.211s；整次返回 1.349s 超时，原始状态 UNKNOWN；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-20-h-f1 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 精确搜索占时最多 0.349s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE；分支 3065；未得到可重放见证或不可行证明 |
| new-20-h-f2 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 精确搜索占时最多 0.402s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/UNKNOWN；分支 5845；未得到可重放见证或不可行证明 |
| new-20-h-f3 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 精确搜索占时最多 0.395s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/UNKNOWN；分支 5608；未得到可重放见证或不可行证明 |
| new-24-m-f1 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 1.543s；整次返回 1.741s 超时，原始状态 UNKNOWN；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-24-m-f2 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 1.797s；整次返回 1.976s 超时，原始状态 UNKNOWN；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-24-m-f3 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 1.524s；整次返回 1.679s 超时，原始状态 UNKNOWN；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |
| new-24-h-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-24-h-f2 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 精确搜索占时最多 0.356s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/UNKNOWN；分支 5577；未得到可重放见证或不可行证明 |
| new-24-h-f3 | ? / ? / ? / ? | ? / ? / ? / ? | 均未知 | 其余流程占时最多 1.274s；整次返回 1.402s 超时，原始状态 UNKNOWN；求解回执 UNKNOWN；分支 0；已有可行方案，上界未闭合 |

## 30 秒

| 快照 | 首轮 | 反序 | Agent 首轮相对固定组合 | Agent 首轮 UNKNOWN 的实测情况 |
|---|---|---|---|---|
| new-16-m-f1 | ✓ / ✓ / ✓ / ✓ | — | 均证明 | — |
| new-16-m-f2 | ✓ / ✓ / ✓ / ✓ | — | 均证明 | — |
| new-16-m-f3 | ✓ / ✓ / ✓ / ✓ | — | 均证明 | — |
| new-16-h-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-16-h-f2 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 20.450s；求解回执 UNKNOWN/UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 219333；未得到可重放见证或不可行证明 |
| new-16-h-f3 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 21.628s；求解回执 UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 205520；已有可行方案，上界未闭合 |
| new-20-m-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-20-m-f2 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.288s；求解回执 FEASIBLE/OPTIMAL/UNKNOWN/OPTIMAL/OPTIMAL；分支 107357；已有可行方案，上界未闭合 |
| new-20-m-f3 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-20-h-f1 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.109s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 123894；未得到可重放见证或不可行证明 |
| new-20-h-f2 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.077s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 155503；未得到可重放见证或不可行证明 |
| new-20-h-f3 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 20.174s；求解回执 UNKNOWN/UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 143806；未得到可重放见证或不可行证明 |
| new-24-m-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-24-m-f2 | ✓ / ✓ / ✓ / ✓ | — | 均证明 | — |
| new-24-m-f3 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-24-h-f1 | ? / ✓ / ✓ / ✓ | ? / ✓ / ✓ / ✓ | 均证明 | — |
| new-24-h-f2 | ? / ? / ? / ? | — | 均未知 | 精确搜索占时最多 16.017s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 150127；未得到可重放见证或不可行证明 |
| new-24-h-f3 | ? / ? / ? / ? | — | 均未知 | 其余流程占时最多 15.092s；求解回执 UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 63273；已有可行方案，上界未闭合 |

## 未闭合边界的进展

同一快照上两档预算分别运行。区间单位为秒，问号表示该端没有在预算内获得证据。下界来自合法方案；有限上界来自数学约束或求解器。

| 快照 | 1 秒 Agent 区间 | 30 秒 Agent 区间 | 30 秒首轮求解情况 |
|---|---|---|---|
| new-16-m-f1 | [7.75, 89.375] | FINITE | FINITE |
| new-16-m-f2 | [?, ?] | FINITE | FINITE |
| new-16-m-f3 | [?, ?] | FINITE | FINITE |
| new-16-h-f2 | [?, 82.125] | [?, 30.375] | 精确搜索占时最多 20.450s；求解回执 UNKNOWN/UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 219333；未得到可重放见证或不可行证明 |
| new-16-h-f3 | [3.75, 86.625] | [3.75, 51.875] | 精确搜索占时最多 21.628s；求解回执 UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 205520；已有可行方案，上界未闭合 |
| new-20-m-f1 | [3.625, 104.75] | FINITE | FINITE |
| new-20-m-f2 | [1.375, 104.375] | [91.625, 104.375] | 精确搜索占时最多 16.288s；求解回执 FEASIBLE/OPTIMAL/UNKNOWN/OPTIMAL/OPTIMAL；分支 107357；已有可行方案，上界未闭合 |
| new-20-m-f3 | [?, ?] | FINITE | FINITE |
| new-20-h-f1 | [?, 103.25] | [?, 102.875] | 精确搜索占时最多 16.109s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 123894；未得到可重放见证或不可行证明 |
| new-20-h-f2 | [?, 105.125] | [?, 104.75] | 精确搜索占时最多 16.077s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 155503；未得到可重放见证或不可行证明 |
| new-20-h-f3 | [?, 88.125] | [?, 55.375] | 精确搜索占时最多 20.174s；求解回执 UNKNOWN/UNKNOWN/OPTIMAL/UNKNOWN/UNKNOWN；分支 143806；未得到可重放见证或不可行证明 |
| new-24-m-f1 | [?, ?] | FINITE | FINITE |
| new-24-m-f2 | [?, ?] | FINITE | FINITE |
| new-24-m-f3 | [?, ?] | FINITE | FINITE |
| new-24-h-f2 | [?, 122.125] | [?, 121.75] | 精确搜索占时最多 16.017s；求解回执 UNKNOWN/UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 150127；未得到可重放见证或不可行证明 |
| new-24-h-f3 | [?, ?] | [6.125, 123] | 其余流程占时最多 15.092s；求解回执 UNKNOWN/FEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE/INFEASIBLE；分支 63273；已有可行方案，上界未闭合 |

## 逐例配对得失

相对三套直接调用对照列出首轮分类增退和未证区间变化。同一输入反序运行的结果单列在 paired.csv。

### 1 秒相对 legacy

- 新增边界证明：new-16-h-f1、new-24-h-f1。
- 丢失边界证明：无。
- 均未知时区间更强：new-16-m-f1、new-16-h-f2、new-16-h-f3、new-20-m-f1、new-20-m-f2、new-20-h-f1、new-20-h-f2、new-20-h-f3、new-24-h-f2。
- 均未知时区间更弱：new-20-m-f3、new-24-m-f2、new-24-h-f3。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：无。
- 同一有限边界处完工时间变长：无。

### 1 秒相对 fixed

- 新增边界证明：无。
- 丢失边界证明：new-16-m-f1、new-16-m-f2、new-16-m-f3。
- 均未知时区间更强：new-20-m-f1、new-20-m-f2、new-20-h-f3。
- 均未知时区间更弱：new-16-h-f2、new-20-h-f1、new-20-h-f2、new-24-h-f2、new-24-h-f3。
- 区间各有得失：new-16-h-f3。
- 同证用时增加至少 20% 且至少 50 毫秒：new-16-h-f1、new-24-h-f1。
- 同一有限边界处完工时间变长：无。

### 1 秒相对 plain

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：new-16-m-f1。
- 均未知时区间更弱：new-16-h-f3、new-24-h-f3。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：new-24-h-f1。
- 同一有限边界处完工时间变长：无。

### 30 秒相对 legacy

- 新增边界证明：new-16-h-f1、new-20-m-f1、new-20-m-f3、new-24-m-f1、new-24-m-f3、new-24-h-f1。
- 丢失边界证明：无。
- 均未知时区间更强：new-16-h-f2、new-20-m-f2、new-20-h-f1、new-20-h-f2、new-20-h-f3、new-24-h-f2、new-24-h-f3。
- 均未知时区间更弱：无。
- 区间各有得失：new-16-h-f3。
- 同证用时增加至少 20% 且至少 50 毫秒：无。
- 同一有限边界处完工时间变长：无。

### 30 秒相对 fixed

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：无。
- 均未知时区间更弱：new-20-h-f1、new-20-h-f2、new-24-h-f2。
- 区间各有得失：new-24-h-f3。
- 同证用时增加至少 20% 且至少 50 毫秒：new-16-h-f1、new-24-h-f1。
- 同一有限边界处完工时间变长：无。

### 30 秒相对 plain

- 新增边界证明：无。
- 丢失边界证明：无。
- 均未知时区间更强：无。
- 均未知时区间更弱：无。
- 区间各有得失：无。
- 同证用时增加至少 20% 且至少 50 毫秒：无。
- 同一有限边界处完工时间变长：无。
