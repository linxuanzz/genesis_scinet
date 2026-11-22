# Experiments


<!--
本表由 scripts/run_experiment.py 自动追加,一行一个 run,手工只做勘误与归档。
Verdict: ✅ 有效 / ❌ 无效 / 🔍 待查
超过 100 行就归档到 EXPERIMENTS_archive.md。
-->

| Date | Tag | Hypothesis | Key Result | Verdict | Dir |
|------|-----|------------|------------|---------|-----|
| 2026-11-22 | exp_wftrace_1000genome_x2 | H1 预约传输全部按期完成且巡检无偏离;H2 后到的 WF-B 受 WF-A 已占容量限制;H3 09:00 对 WF-B 传输的需求预报字节量一致、请求时间误差可量化。 | H1 不成立:12 个预约传输,截止时间满足 9,巡检偏离 5;H2 成立:数据准备 WF-A 21.9 min / WF-B 29.3 min;H3 有预报:首次预报的请求时间误差 {'mean': 154.3, 'max': 754.7} | 🔍 | 20261122_133802_exp_wftrace_1000genome_x2_32b4bf0 |
