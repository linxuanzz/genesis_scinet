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
