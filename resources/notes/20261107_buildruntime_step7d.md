# D 部分：demo 与收尾（2026-11-07）

## 一、demo（`tests/test_step7_demo.py`，5 个场景）

运行：在 `src/lib` 下 `python -m network_agent.tests.test_step7_demo`。每个场景打印网络、commitments、图 B 每次运行走过的节点、偏差、预测、plan、DeviationReport，最后是模拟的实际完成时间。


| 场景         | 设置                                                                                 | 图 B 的结果                                                                                          | 实际完成              |
| ---------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------- |
| outage     | L2 09:30–09:45 中断，T1 50 TB @ 40，latest_finish 15:00                                | 10:00 link_down → extend 到 12:01:40；10:15 再检查：covered，不报                                         | 12:01:40          |
| congestion | L2 09:30–10:30 多 20 Gbps 背景，latest_finish 12:10                                    | 10:00 congestion → extend 要到 12:16:40，太晚；MAIN 12:00 前不能提速 → reroute 到 ALT，si-2 / VLAN 3002       | 12:01:40          |
| unlocated  | 源端 09:00 起只有 60%，11:00 起完全停住                                                       | 10:00 unlocated → 按 24 Gbps extend 到 13:37:47；11:30 最近速率 16 → 传不完，直接 unresolved；11:45 已报过，不再报    | 不会完成              |
| priority   | TH（priority 2，9 TB，10:10 前）09:10–09:30 被挤到 20；09:30 之后 L2 全归 TL（priority 1）；ALT 已满 | TH extend 到 09:40；TL 从 80 降到 40，结束改到 11:30，收到 lend 报告                                            | TH 09:40，TL 11:30 |
| decision   | L2 09:30–10:30 中断，latest_finish 11:50                                              | 10:00 三步都失败 → unresolved，记下每步的原因；10:05 不重复报；scheduler 通过图 A modify 让 T1 跑到 14:00 → 10:10 covered | 12:46:40          |




## 二、html 与 PLAN

- **图 B html**（两个文件同步，`runtime_graph_b.html` 的 srcdoc 整段替换）：节点和边都没变。
  - 节点说明按代码更新：classify_event 补上 overrun 与 late_start；scan_path 补上逐槽预测；triage 补上"已报过、没变"；plan 补上每次降一档、unlocated 只延长、晚开始不借；
  - triage → END 的边标签改为 "Covered / reported"；
  - 标题注明 2026-11-07 已实现。
- **PLAN**：
  - 第 7 步那一行补上 B–D 的产出，标 ✅；
  - A 部分记下的空白 ②③ 标为已解决；
  - 新增一条"第 7 步 B–D 留下的空白"；
  - "跨 workflow 按 priority 预留"一条补上第 7 步已做和未做的部分。



## 三、留下的空白（已记进 PLAN 待决）

1. 只有一次进度读数时，unlocated 用开始以来的平均速率做预测，停滞刚发生时会偏乐观。
2. 修好之后，传输仍落后于新 profile，之后每次 tick 都会检出、判为 covered 后结束：多算一遍，但不会重复上报。
3. 借用是贪心的：按 priority 从低到高、每次降一档，不求全局最优；被借的只保证赶上自己的 `latest_finish`，不留余量。
4. 换路径时旧 circuit 立即取消；新放置如果晚于 now 才开始，中间会停顿。
5. 只做单路径修复，多路径是第 8 步；真正的抢占、query / reserve 读 priority 也没做；`Subscribe` 仍未接通。



## 四、测试结果

`.venv/bin/python -m pytest src/lib/network_agent/tests`：**272 passed**。原有 172 个没改；第 7 步共 100 个：flows 28、classify 21、scan 27、repair 19、demo 5。

- 代码中没有未使用的 import，没有中文；
- 私有信息检查（`tools/common/private_patterns.txt`）无命中；
- 没有 commit / push，没有动 SciNetGenesis

