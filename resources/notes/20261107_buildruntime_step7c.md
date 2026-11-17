# C 部分：本地修复（2026-11-07）

## 一、改了哪些文件


| 文件                                          | 写了什么                                                                                                                                                                                                                                     |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `operations.py`（新）                          | 从图 A 提炼出来的改动操作，图 A 与图 B 共用： - **modify**：`change_booking`、`change_circuit`、`restore_booking`、`record_change`，组合成 `modify_held`； - **新建 circuit**：`propagate_intents`、`undo_holds`、`commit_instance`、`make_commitment`，组合成 `open_circuit` |
| `graphs/modify.py`、`reserve.py`、`commit.py` | 节点改为调用上面的函数，图的形状没变                                                                                                                                                                                                                       |
| `repair.py`                                 | `RulePolicy.plan_local_repair`、`plan_all`、`execute`、四步修法 `extend` / `raise_rate` / `reroute` / `borrow`                                                                                                                                               |
| `ledger.py`                                 | `replace(booking_id, profile, now)`：只检查新 profile 增加的部分；已过去的槽保持原值                                                                                                                                                                         |
| `sense.py`                                  | `added_spans()`；`MockSense` 的准入只看从 now 起，modify 只看增加的部分                                                                                                                                                                                  |
| `sim.py`                                    | 预留的历史版本（`_history`、`reservation_at`）；`switch_flow`（WMS 跟着换路径）；`headroom(exclude=)`                                                                                                                                                       |
| `tests/test_step7_repair.py`（新）             | 19 个，见第六节                                                                                                                                                                                                                                |




## 二、四步修法

目标都是同一个：为剩余字节找一份在 deadline（`latest_finish`，最多到 ledger horizon）之前传完的预留，按预测判断。


| 顺序  | 修法         | 怎么做                                                                                                                                                                                           | 失败时                                                                      |
| --- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1   | extend     | 同一 circuit、同速率，结束时间推到预测传完的时刻（取整到秒）                                                                                                                                                            | 账本或 SENSE 拒绝 → 原样恢复，试下一步                                                 |
| 2   | raise_rate | 同一 circuit，从高一档的速率往上试，选第一个能在 deadline 前传完、账本也接受的；结束时间不提前                                                                                                                                      | 账本拒绝就试再高一档；SENSE 拒绝则这一步结束                                                |
| 3   | reroute    | 其他候选路径上，用 `placement.search` 为剩余字节找放置，选最早完成的（同样早时选早开始的）。先 hold、propagate、commit 新 circuit，成功后再 cancel 旧的、退还旧 booking（make-before-break）。commitment_id 不变，circuit_id 和 VLAN 换新，预订项里的请求字节改为剩余字节 | 新 circuit 任何一步失败都撤销；旧 circuit cancel 失败就记成 orphan，由 expiry sweep 稍后取消并退还 |
| 4   | borrow     | 找 priority 更低、与本路径共用某一跳、且在 [now, deadline) 内有预订的 commitment，从最低 priority 开始，每次降一档速率（只要它仍能赶上自己的 `latest_finish`），每降一档就重试 extend 和 raise_rate                                                   | 都不行就把借过的全部改回原样                                                           |


`RulePolicy.plan_local_repair` 的规则：


| 情况                                                   | 试哪些步                                                      |
| ---------------------------------------------------- | --------------------------------------------------------- |
| deadline 已过，或者剩余字节按最好的候选路径满速（unlocated 时还要受上限限制）都传不完 | 不试，直接 unresolved                                          |
| unlocated 且仍慢                                        | 只试 extend：提速、换路径都解决不了链路以外的瓶颈                              |
| late_start                                           | extend、raise_rate、reroute，不借：晚开始不该让别人付代价                  |
| link_down / congestion                               | 四步都可以；已经满速的不试 raise_rate，没有其他路径的不试 reroute，没有可借的不试 borrow |




## 三、priority

- 按 priority 从高到低修，同 priority 按 commitment 顺序，所以高的先拿到容量。测试中两个都需要 10:00 之后 L2 上同一段容量：高的 extend，低的只能 reroute；把 priority 对调，结果也对调。
- 只借不抢：被借的仍须赶上它自己的 `latest_finish`，并收到 `DeviationReport(outcome=repaired, action=lend, lent_to=…)`。
- 同一次运行里正在修的、以及正等 scheduler 决定的（`reported_unresolved`），都不出借。



## 四、为修复配套的三处改动（共用代码，影响图 A）

1. `ledger.replace` **只检查增加的部分、已过去的槽不动**。原来 replace 会把新 profile 的每个槽都重新检查一遍：
  - 运行中出过中断或拥塞的槽，observed 已经小于我们订的量，同速率延长也会被拒；
  - 已经过去的槽也会被检查。  现在只有新 profile 要得比原来多的槽才检查；已过去的槽保持原值，那是实际用过的。对图 A 的 modify：没有受损槽、也没有已过去的槽时，结果和原来完全一样；272 个测试里原有的 172 个都没改。
2. **MockSense 的准入只看从 now 起，modify 只看增加的部分**（`added_spans`）。理由同上：控制器不会收回已经批准的预留，过去的时间也不必再检查。
3. **sim 记录预留的历史版本**。每次 propagate / modify / cancel 都记下生效时间，流只从那一刻起按新预留走，过去不被改写（A 记下的已知空白 ②，已解决）。另加 `switch_flow`：换路径后 WMS 把剩下的字节移到新 circuit 上。



## 五、与第九节的偏离与补充

- **raise_rate**：第九节写的是"在未受损的时段提速"。一个 circuit 只有一个恒定速率，提速就是整段一起提，前面每个槽都要有余量。所以这一步只在损坏已经过去时才可能成功（测试场景就是这种）；损坏还在时由 reroute 或 borrow 接手。
- **borrow 每次降一档**：第九节只说"借用低 priority 的 slack"。我起初写成直接降到最低可行速率，demo 里 TL 从 80 被压到 20，其实降到 40 就够了。现在改成逐档下降，只借够用的那么多。
- **按 cause 收窄**：unlocated 只试 extend，late_start 不借。这是 plan 里的规则，第九节没有。
- **commitment_id 不变**：换路径后 commitment_id 保持不变，便于 scheduler 对应。
- **p95 重算**：修复后按新预留重新算 p95，放进报告。



## 六、测试（`test_step7_repair.py`，19 个）

模拟传输都跑到底，核对实际完成时间和图 B 报的 p95 一致。

- **extend**：
  - 中断之后，同一 circuit、同一 VLAN 延长到 12:01:40，账本、SENSE、reservation、commitment 都更新了；
  - 晚开始延长到 12:06:40；
  - unlocated 按 24 Gbps 延长；
  - 拥塞仍在的槽保持原值，只新增 12:00 之后的部分。
- **raise_rate**：落后 10.5 TB，40 Gbps 要到 10:15，提到 50 则 10:08 完成；已过去的槽保持 40，过去的字节不被改写。
- **reroute**：
  - 改走 ALT，si-2 / VLAN 3002，旧的 si-1 被取消、MAIN 上的 booking 被退还，WMS 切过去后 12:01:40 完成；
  - 旧 circuit cancel 失败 → orphan，由 sweep 回收；
  - 新 circuit 的 propagate 或 commit 失败 → 全部撤销，报 unresolved；
  - SENSE 拒绝 extend → 账本恢复，改走 reroute。
- **borrow 与 priority**：
  - 只借够用的：TL 降到 40，TH 09:40、TL 11:30 完成；
  - 借了也没用 → TL 改回 80；
  - 高 priority 先修，priority 对调后结果也对调；
  - 各 cause 的 plan。
- **底层改动**：
  - 账本只查增加的部分；
  - SENSE 只查从 now 起增加的部分；
  - sim 不改写过去；
  - `switch_flow`。
---

> _placement_through_by是啥

**一句话**：给一个已订的 offer 和一个速率 gbps，算出"改成这个速率之后，预留要开到几点才能把剩下的字节传完"，返回改好的新 placement；到 deadline 都传不完就返回 None。三种修法都用它算新预留，只是传的速率不同：

| 谁调用 | 传的速率 | 得到 |
|---|---|---|
| extend | 原速率 | `longer`：同速率，结束时间推后 |
| raise_rate | 逐个更高的速率档 | `faster`：提速后的 placement |
| borrow（借出方） | 逐个更低的速率档 | `slower`：借出方降速后，仍须在它自己的 deadline 前传完 |

**步骤**：
1. 从 `max(now, 原开始时间)` 到 deadline，按这个速率生成预计速率段（`expected_rates_on_circuit`：考虑中断、拥塞时的份额、unlocated 的上限 `cap`）；
2. `finish_at_expected_rates` 算出剩余字节的完成时间 (p50, p95)；传不完 → None；
3. 新结束时间 = p95 向上取整到秒，不超过 deadline，**也不早于原结束时间**；
4. 返回原 placement 只改两项：`gbps` 和 `end`（路径、开始时间不变）。

**两个细节**：
- **向上取整到秒**：完成时间常带小数秒，向下截会差一点传不完。
- **结束时间不提前**：提速后理论上可以早结束，但缩短预留没有好处，还可能因为预测偏差又传不完，所以保留原结束时间作为余量。

**例**（`test_outage_forecast` 的场景）：40 Gbps、10:00 剩 36.5 TB、deadline 15:00、路径之后正常 → 预计 12:01:40 传完 → 返回 09:00–12:01:40 @ 40 的 placement，extend 用它改预留。
