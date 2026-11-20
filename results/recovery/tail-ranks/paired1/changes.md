# 1 秒配对结果

首轮覆盖全部 120 个输入。总体数字只计首轮，每个输入权重相同。反序重复用于判断单例变化能否复现。编号与 inputs 中的 JSON 文件同名。

旧策略准时证明 92 个，新策略准时证明 104 个。本组归档方案另行重放 374 份。

## 两次均由新策略独自证明（8 个）

- kim-04　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-09　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-10　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-16　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-18　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-34　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-40　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-46　UNKNOWN/FINITE | UNKNOWN/FINITE（每对为旧 / 新）

## 两次均由旧策略独自证明（0 个）

无。

## 出现证明得失，但未在两次中稳定复现（18 个）

- terminal-06-10　UNKNOWN/FINITE | UNKNOWN/UNKNOWN（每对为旧 / 新）
- terminal-06-11　UNBOUNDED/UNBOUNDED | UNKNOWN/UNBOUNDED（每对为旧 / 新）
- terminal-08-03　UNKNOWN/UNBOUNDED | UNKNOWN/UNKNOWN（每对为旧 / 新）
- terminal-08-09　UNKNOWN/UNBOUNDED | UNBOUNDED/UNBOUNDED（每对为旧 / 新）
- terminal-08-11　UNBOUNDED/UNKNOWN | UNKNOWN/UNKNOWN（每对为旧 / 新）
- kim-00　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-02　FINITE/UNKNOWN | FINITE/FINITE（每对为旧 / 新）
- kim-06　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-11　FINITE/FINITE | FINITE/UNKNOWN（每对为旧 / 新）
- kim-14　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-15　UNKNOWN/FINITE | FINITE/FINITE（每对为旧 / 新）
- kim-22　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-23　FINITE/UNKNOWN | FINITE/FINITE（每对为旧 / 新）
- kim-28　UNKNOWN/FINITE | FINITE/FINITE（每对为旧 / 新）
- kim-29　UNKNOWN/FINITE | FINITE/FINITE（每对为旧 / 新）
- kim-30　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）
- kim-39　UNKNOWN/FINITE | FINITE/FINITE（每对为旧 / 新）
- kim-42　FINITE/FINITE | UNKNOWN/FINITE（每对为旧 / 新）

## 都未证明边界时，返回的区间是否变化

下界越大、上界越小越好。以下为首轮观察，逐次复核见 instances.csv。

新策略区间更强（4 个）：terminal-06-04、terminal-08-04、terminal-12-02、terminal-12-08。

新策略区间更弱（0 个）：无。

上下界各有得失（0 个）：无。

[全部实例及用时](instances.csv) · [每次运行记录](runs.csv)
