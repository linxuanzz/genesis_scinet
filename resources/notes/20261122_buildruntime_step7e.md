# 第 7e 步:运行期重构(预报 → 检测 → 修复)

设计来源:`resources/notes/20261121_rethink_detectinruntime.md`。2026-11-22 一次改完,342 个测试通过。

## 模块关系

```
                 telemetry(当前/过去时段测量)   ForecastInputs(停机日历、已登记预约、统计基线)
                        │                                   │
                        ▼                                   ▼
 图 A query/reserve/modify ──► forecast.refresh ◄── forecast.update_forecast ◄── 图 B 第一步
                        │            │ 写账本 observed(p50 / p95)
                        │            ▼
                        │      CapacityLedger(observed、own)
                        │            │ 读
                        ▼            ▼
                     规划(按 p95)   detection.detect_deviations ──► assessment.assess ──► repair(triage → plan → execute → report)
                                       ▲ short_slots(新变得不够用的已订时段)
                                       └── 由 update_forecast 给出
```

## 文件与重点函数

| 文件 | 角色 | 重点函数 |
|---|---|---|
| `runtime/forecast.py`(新) | 网络预报:让账本在被读之前有效;过去/当前时段用 telemetry 测量,未来时段自己算 | `refresh`(任何读账本前调用,图 A、图 B 共用)、`update_forecast`(图 B 第一步)、`forecast_link`(单条链路未来时段的公式)、`measure`(拉 telemetry、记录计划外停机) |
| `adapters/forecast_inputs.py`(新) | 预报的三类输入接口 + mock | `planned_outages`、`registered_reservations`、`baseline` |
| `adapters/scheduling_agent.py` | 新增 `SciNetDemandSource`:预报模块 B 的占位接口,尚无调用 | `future_demand` |
| `runtime/detection.py`(原 deviation.py) | 检测:flow 分支 a(slow)/ b(overrun)、link 分支 | `detect_deviations`(按事件选 commitment 和分支)、`check_commitment`(单个 commitment 三个分支 + 定位) |
| `runtime/assessment.py`(原 forecast.py) | 完工时间评估:按账本 p50 / p95 分别推算 | `finish_of`、`assess` |
| `runtime/repair.py` | 修复规则按新树调整,其余不变 | `RulePolicy.plan_local_repair`、`_lenders` |
| `state/ledger.py` | 每时段存 p95(`gbps`)和 p50(`p50_gbps`) | `Observation.capacity`、`put`、`current_slot` |
| `graphs/runtime/runtime.py` | 图 B:deduplicate_event → update_forecast → detect_deviations → scan_path → triage → … | — |

## 串起来的方式(三种事件)

- **tick**:`update_forecast` 重算过期的预报值 → `detect_deviations` 对所有 commitment 跑 slow、overrun、link 三个分支。
- **flow 告警**:预报不动 → 只对该 flow 跑 slow,吞吐用告警里的测量值。
- **link 告警**:`update_forecast` 记下停机开始/结束,立即重新测量该链路、重算预报,得出“够用→不够用”的已订时段 → `detect_deviations` 只对在这些时段有预约的 commitment 跑 link 分支。

检测到的 deviation 之后照旧:`scan_path`(扩展到受损链路上的其他 commitment + 评估)→ `triage`(来不来得及)→ `plan_local_repair` → `execute_repair` → `report_deviation`。

## 与设计稿不同、需要知道的地方

1. **第一次读进度时不判 slow**:没有“最近速率”,用“开始以来的平均速率”会把已经结束的停机算成“现在很慢”。损失的字节由 overrun(b)负责。flow 告警自带测量值,可直接判 slow。
2. **link 告警只复查“新变得不够用”的预约**:链路恢复(link_up)不会触发复查,失败修复的记录要等下一次 tick 全量检查时才清除。
3. **当前时段的测量只取“从现在起”**:时段里已经过去的部分不算,否则 link_up 之后,本时段仍会显示 down。
4. **telemetry 发现链路 down、日历里又没有**,也记为计划外停机(不必等 link_down 告警)。
5. **p95 下 down 的时段不能续订**:计划外停机按 p95 预计 3 小时修好,extend 要在这些时段续订会被账本拒绝,于是改走 reroute。
6. 修复后传输回到满速、延长后的预约装得下,就不再被检出;之前“每次 tick 都重复检出、再由 triage 判为来得及”的问题随之消失。

---

### Demo

## 怎么运行

```bash
cd src/lib
python -m network_agent.tests.test_step7e_demo        # 全部 6 个场景
python -m network_agent.tests.test_step7e_demo 3      # 只跑第 3 个

```

每个场景都从同一张网络出发：几条传输已经通过 graph A 订好，然后网络里发生一件事。每次 graph B 运行，都按阶段各打印一行：

```
10:00  EVENT  telemetry alert: link_down on L2
  [forecast]   our booked slots that became short: L2 10:00–12:00
  [detection]  cmt-1: link (damage ahead) → cause link_down at L2
  [assess]     cmt-1: 32 TB left, not through before its reservation ends → needs a repair
  [plan]       cmt-1: try extend → increase → reroute
  [report]     → scheduling agent: cmt-1 [link_down] repaired by reroute; p95 11:46, deadline 15:00

```

有的场景还会打印出预报视图：某条链路每个时段是测量值还是预报值，以及 p50/p95。每个场景结束时给出模拟出来的实际完成时间。

## 6 个场景

| #   | 场景            | 展示什么                                                                         | 结果                    |
| --- | ------------- | ---------------------------------------------------------------------------- | --------------------- |
| 1   | 计划维护在前面       | 日历里的停机 → link 分支，传输开始前两小时就修好                                                 | extend，13:36 完成       |
| 2   | 未登记的拥塞现在发生    | link 告警 → 预报从当前测量值逐渐过渡到平时水平 → 12:00 的传输在 10:00 就修好；预报低估了拥塞，传输开始后 flow 分支再补一次 | extend 两次，13:12 完成    |
| 3   | 光纤中断          | 计划外停机的 p50/p95 窗口 → 先建新电路、切换传输、再拆旧电路                                         | reroute，11:46 完成      |
| 4   | 端主机慢、网络正常     | flow 告警 → 定位不到网络原因 → 只延长，不动网络                                                | extend，13:37 完成       |
| 5   | 两条传输共享一段拥塞的链路 | 低优先级的传输借速率给高优先级的，自己仍然按时完成                                                    | extend + lend         |
| 6   | 本地怎么修都来不及     | 报告“未解决”，只报一次 → scheduling agent 决定放宽截止时间 → agent 恢复安静                        | unresolved → 12:46 完成 |

## 顺带修的一个 bug

写场景 2 时发现，reroute 给还没开始的传输重新安排时，新电路从“现在”开始，没有等到传输本来的开始时间。结果新电路在传输开始前就已经结束了。已修复：新电路不早于原预约的开始时间。

## 其他

- 每个场景都配了 pytest 检查，保证演示的结论和代码行为一致。现在共 348 个测试，全部通过。
- 打印器 `PipelineSession` 加在 [tests/printing.py](../../src/lib/network_agent/tests/printing.py)；demo 在 [tests/test_step7e_demo.py](../../src/lib/network_agent/tests/test_step7e_demo.py)。[PLAN.md](http://PLAN.md) 的 7e 那一行也记上了 demo 和这个修复。
- 场景 2 为了效果明显，把预报的过渡时间设成了 2 小时（默认是 30 分钟），打印的场景说明里写了这一点。
