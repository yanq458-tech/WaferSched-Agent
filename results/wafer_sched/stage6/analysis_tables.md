# 真实数据自动汇总

| 场景 | 规划器 | 最佳Makespan均值±样本标准差(s) | 找到最佳平均墙钟(s) | 完整研究平均墙钟(s) | 调用数 |
| --- | --- | --- | --- | --- | --- |
| F_competition | deterministic | 63.000 ± 0.000 | 6.464 | 19.068 | [8, 5, 6] |
| F_competition | fixed | 63.000 ± 0.000 | 7.503 | 11.747 | [8, 8, 8] |
| G_dual_bottleneck | deterministic | 183.000 ± 0.000 | 4.490 | 18.923 | [8, 8, 8] |
| G_dual_bottleneck | fixed | 183.000 ± 0.000 | 5.236 | 11.812 | [8, 8, 8] |

| 预算场景 | 模式 | CP实际尝试(限额/状态/目标/下界) | 最佳合法(s) | 全流程墙钟(s) | 停止原因 |
| --- | --- | --- | --- | --- | --- |
| F_competition | adaptive | 1/FEASIBLE/63.0/51.0; 3/OPTIMAL/63.0/63.0 | 63.0 | 6.645 | verified_supported_instance_optimum |
| F_competition | fixed-1 | 1/FEASIBLE/63.0/51.0 | 63.0 | 2.216 | max_rounds |
| F_competition | fixed-10 | 10/OPTIMAL/63.0/63.0 | 63.0 | 4.245 | max_rounds |
| F_competition | fixed-3 | 3/OPTIMAL/63.0/63.0 | 63.0 | 4.069 | max_rounds |
| F_competition | fixed-30 | 30/OPTIMAL/63.0/63.0 | 63.0 | 3.444 | max_rounds |
| G_dual_bottleneck | adaptive | 1/FEASIBLE/183.0/142.0; 3/FEASIBLE/183.0/142.0 | 183.0 | 6.063 | two_cp_budgets_no_incumbent_or_bound_gain |
| G_dual_bottleneck | fixed-1 | 1/FEASIBLE/183.0/142.0 | 183.0 | 2.192 | max_rounds |
| G_dual_bottleneck | fixed-10 | 10/OPTIMAL/183.0/183.0 | 183.0 | 10.123 | max_rounds |
| G_dual_bottleneck | fixed-3 | 3/FEASIBLE/183.0/142.0 | 183.0 | 4.286 | max_rounds |
| G_dual_bottleneck | fixed-30 | 30/OPTIMAL/183.0/183.0 | 183.0 | 10.934 | max_rounds |

| 封存测试场景 | 方法 | 参数 | Makespan(s) | 验证通过 | CP状态/下界 | 冻结CFAR选择 |
| --- | --- | --- | --- | --- | --- | --- |
| U_recipe_mix | rule | {'policy': 'adaptive'} | 108.0 | True | None/None | False |
| U_recipe_mix | rule | {'policy': 'bottleneck'} | 114.0 | True | None/None | False |
| U_recipe_mix | cpsat | {'max_seconds': 1} | 118.0 | True | FEASIBLE/77.0 | True |
| U_recipe_mix | cpsat | {'max_seconds': 3} | 110.0 | True | FEASIBLE/77.0 | False |
| U_recipe_mix | rule | {'policy': 'ect'} | 108.0 | True | None/None | False |
| U_recipe_mix | rule | {'policy': 'fifo'} | 114.0 | True | None/None | False |
| U_recipe_mix | rl | {'model_id': 'medium-seed-0'} | 108.0 | True | None/None | False |
| U_recipe_mix | rl | {'model_id': 'medium-seed-13'} | 108.0 | True | None/None | False |
| U_recipe_mix | rl | {'model_id': 'medium-seed-7'} | 108.0 | True | None/None | False |
| U_recipe_mix | rule | {'policy': 'spt'} | 108.0 | True | None/None | False |
| U_slow_transport | rule | {'policy': 'adaptive'} | 348.0 | True | None/None | False |
| U_slow_transport | rule | {'policy': 'bottleneck'} | 347.0 | True | None/None | False |
| U_slow_transport | cpsat | {'max_seconds': 1} | None | False | UNKNOWN/236.0 | True |
| U_slow_transport | cpsat | {'max_seconds': 3} | None | False | UNKNOWN/236.0 | False |
| U_slow_transport | rule | {'policy': 'ect'} | 348.0 | True | None/None | False |
| U_slow_transport | rule | {'policy': 'fifo'} | 331.0 | True | None/None | False |
| U_slow_transport | rl | {'model_id': 'medium-seed-0'} | 339.0 | True | None/None | False |
| U_slow_transport | rl | {'model_id': 'medium-seed-13'} | 345.0 | True | None/None | False |
| U_slow_transport | rl | {'model_id': 'medium-seed-7'} | 337.0 | True | None/None | False |
| U_slow_transport | rule | {'policy': 'spt'} | 348.0 | True | None/None | False |
