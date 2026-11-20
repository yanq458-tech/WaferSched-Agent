# 1 秒配对结果

首轮覆盖全部 120 个输入。总体数字只计首轮，每个输入权重相同。反序重复用于判断单例变化能否复现。编号与 inputs 中的 JSON 文件同名。

旧策略准时证明 101 个，新策略准时证明 112 个。本组归档方案另行重放 387 份。

## 两次均由新策略独自证明（10 个）

- terminal-06-01　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-06-02　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- terminal-06-04　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- terminal-06-07　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-08-01　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-08-07　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-08-08　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- terminal-12-01　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-12-06　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）
- terminal-12-07　UNKNOWN/INFEASIBLE_AT_ZERO | UNKNOWN/INFEASIBLE_AT_ZERO（每对为旧 / 新）

## 两次均由旧策略独自证明（0 个）

无。

## 出现证明得失，但未在两次中稳定复现（2 个）

- terminal-06-10　UNKNOWN/FINITE | UNKNOWN/UNKNOWN（每对为旧 / 新）
- terminal-08-02　UNKNOWN/UNKNOWN | UNKNOWN/FINITE（每对为旧 / 新）

## 都未证明边界时，返回的区间是否变化

下界越大、上界越小越好。以下为首轮观察，逐次复核见 instances.csv。

新策略区间更强（5 个）：terminal-08-10、terminal-12-02、terminal-12-04、terminal-12-10、kim-04。

新策略区间更弱（2 个）：terminal-08-02、terminal-08-04。

上下界各有得失（0 个）：无。

[全部实例及用时](instances.csv) · [每次运行记录](runs.csv)
