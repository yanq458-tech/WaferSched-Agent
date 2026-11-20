# 30 秒配对结果

首轮覆盖全部 120 个输入。总体数字只计首轮，每个输入权重相同。反序重复用于判断单例变化能否复现。编号与 inputs 中的 JSON 文件同名。

旧策略准时证明 101 个，新策略准时证明 110 个。本组归档方案另行重放 208 份。

## 两次均由新策略独自证明（9 个）

- terminal-04-05　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-04-09　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-04-11　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-08-03　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-08-09　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-12-03　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-12-05　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-12-09　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-12-11　UNKNOWN/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）

## 两次均由旧策略独自证明（0 个）

无。

## 出现证明得失，但未在两次中稳定复现（0 个）

无。

## 都未证明边界时，返回的区间是否变化

下界越大、上界越小越好。以下为首轮观察，逐次复核见 instances.csv。

新策略区间更强（1 个）：terminal-08-04。

新策略区间更弱（0 个）：无。

上下界各有得失（0 个）：无。

[全部实例及用时](instances.csv) · [每次运行记录](runs.csv)
