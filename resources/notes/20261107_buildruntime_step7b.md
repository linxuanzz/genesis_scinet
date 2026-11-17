# B 部分：scan_path、triage、report_deviation（2026-11-07）

## 一、改了哪些文件


| 文件                             | 写了什么                                                                                                                                                                        |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forecast.py`（新）               | scan_path 的预测：`expected_gbps`（某个 circuit 在某个槽预计拿到的速率）、`circuit_runs` / `held_runs`（从现在起逐槽的速率段）、`off_path_cap`（unlocated 时的速率上限）、`assess` / `assess_all`；结果放在 `Assessment` 里 |
| `estimate.py`                  | `RateModel` 加 `finish_along(runs, nbytes)`：速率随时间变化时的 p50 / p95。`IdealRateModel` 直接积分，p50 = p95。第 9 步校准仍从这里接入                                                                |
| `deviation.py`                 | 新增 overrun 信号与 cause `late_start`（见第三节）；`detect()` 拆出 `check()`，新增 `widen()`                                                                                                |
| `schemas.py`                   | `Cause` 移到这里（加了 `late_start`）；`RepairAction`；`DeviationReport`                                                                                                              |
| `repair.py`（新）                 | B 用到的部分：`RuntimePolicy` 接口与 `RulePolicy.triage`、`triage_all`、`unresolved`、`report`                                                                                          |
| `context.py`                   | `reported`：报过 unresolved 的 commitment → (cause, 当时的 commitment)                                                                                                             |
| `graphs/runtime.py`            | 图 B 全部节点，占位节点 `deviation_found` 删除；`build_runtime_graph(policy=None)` 可换策略                                                                                                  |
| `tests/helpers.py`             | `tr()` 可设 `priority`、`workflow_id`；新增 `book()`（单条传输 query → reserve 第 k 个 offer → commit）、`TICK`、`visited()`、`reports()`、`follow_reroutes()`                                |
| `tests/test_step7_scan.py`（新）  | 27 个，见第五节                                                                                                                                                                   |
| `tests/test_step7_classify.py` | 3 处随行为改动更新，见第三节                                                                                                                                                             |




## 二、规则

**scan_path**

1. **扩大范围**（`widen`）：事件没涉及、但路径经过某个已发现受损的跳的 commitment，也检查一遍。例：flow 告警只涉及 si-1，刷新后发现 L2 在 11:30 之后拥塞，那么 12:00 才开始、同样经过 L2 的 cmt-2 也要检查。
2. **刷新到 deadline**：每个偏差的路径从 now 刷新到 `latest_finish`（只刷过期的），因为修复可能要用到预留结束之后的时间。
3. **逐槽预测**（`expected_gbps`），从 now 开始：

  | 这一槽里路径上的某一跳                            | 预计速率                           |
  | -------------------------------------- | ------------------------------ |
  | down                                   | 0                              |
  | 我们在这跳上订的总量（本 circuit 按它的速率算）> observed | 按速率比例分到的份额：observed × 本速率 / 总量 |
  | 否则                                     | 本 circuit 的速率                  |

   取各跳中最小的。还没过去的损坏（计划中的中断、telemetry 认为会持续的拥塞）会压低预测，已经过去的不会。按槽读数（账本记的是槽内最小值），所以预测偏保守。
4. **链路以外的上限**（`off_path_cap`）：只用于 unlocated。最近速率（没有上一次读数时用开始以来的平均速率）比预留速率低超过容差，就用它封顶；否则认为已恢复，不封顶。
5. 用 `RateModel.finish_along` 算两个完成时间：
  - `finish`：只在现有预留内能否传完，传不完是 None；
  - `finish_if_kept`：假设 circuit 按原速率一直延长下去，什么时候传完（unresolved 报告里用）。

**triage**（`RulePolicy.triage`，可替换）


| 情况                                    | 结果                                   |
| ------------------------------------- | ------------------------------------ |
| `finish` 的 p95 ≤ 预留结束                 | covered：不动、不报，结束                     |
| 已报过 unresolved，cause 相同，commitment 没变 | reported：留给 scheduling agent，不再修、不再报 |
| 其他                                    | 去 plan_local_repair                  |


每次 triage 前先清理 `reported`：commitment 已被 release 或被改过（例如 scheduler 通过图 A modify）的，忘掉；判为 covered 的也忘掉。

**report_deviation**：每个 outcome 一条 `DeviationReport`，按 cause 分组输出到 state 的 `reports`；unresolved 的记进 `reported`。怎么送到 scheduling agent 仍由调用方负责。

`DeviationReport` 字段：`commitment_id`、`transfer_id`、`workflow_id`、`cause`、`links`、`outcome`（repaired / unresolved）、`action`（extend / raise_rate / reroute / lend，只有 repaired 有）、`lent_to`（只有 lend 有）、`predicted_finish_p50` / `p95`、`latest_finish`、`commitment`。预计完成时间：repaired 时按更新后的预留算；unresolved 时是 `finish_if_kept`，即"如果 circuit 按原速率延长下去"，到 ledger horizon 都传不完就是 None。

## 三、A 留下的空白：我的决定（可改）

A 部分记下的问题：晚开始的传输不算落后，但预留结束时传不完，剩下的字节没人管。我的处理是新增 **overrun 信号**：

- 已开始的传输，剩余字节 − 预留从 now 到结束还能运的字节 > 容差 × 剩余字节，就算偏差。
- 这个信号还覆盖了另一种情况：落后量小于容差、不算 behind，但积累到最后会让 circuit 在传完之前结束。例：09:00–09:02 停了 2 分钟，10:00 时落后 3.3%，不报；到 11:30 少的 0.6 TB 已超过剩余字节的 5%，报出，修法是延长 2 分钟。
- cause 新增 `late_start`：没有受损的跳，且传输晚于预留开始，说明是 WMS 自己晚了，不是网络的问题。顺序为 link_down > congestion > late_start > unlocated。
- 还没开始、但预留已经开始的 commitment 仍然不报：不知道它什么时候开始，这是 scheduler 的事。

A 的测试相应改了 3 处：

- `test_late_start_is_not_a_deviation` 改为 `test_late_start_is_not_behind_but_overruns`；
- 新增 `test_small_lag_that_still_overruns`；
- `test_outage` 不再依赖占位节点；告警刷新那条只断言 L2 在刷新列表里，因为 scan_path 还会多刷到 deadline。



## 四、与第九节的偏离与补充

- **偏离**：cause 多了 `late_start`（理由见第三节）。
- **补充**：
  - `DeviationReport` 多两个字段 `action`、`lent_to`，scheduler 由此知道改了什么、为谁让出；
  - unresolved 时的 p50 / p95 按上面的定义算。
- **去重放在 triage**：第九节写在上报那里。放到 triage 是因为报过 unresolved 的不应该每次 tick 再修一次（第九节："资源保持原样，等 scheduler 决定"）。
- **策略可换**：`build_runtime_graph(policy=...)`。



## 五、测试（`test_step7_scan.py`，27 个）

- **预测**：
  - 中断之后剩 36.5 TB、按原速率 12:01:40 传完；
  - 拥塞到 10:30 的那半小时只拿到 20；
  - 前方计划中断那段为 0；
  - 我们两个 circuit 在拥塞的跳上 30 / 10 按比例分；
  - unlocated 以 24 Gbps 封顶；
  - unlocated 已恢复时不封顶（第一次读数用平均 28 Gbps，第二次最近速率回到 40）；
  - 换一个更保守的 RateModel，图 B 就按它的 p95 订。
- **triage**：修好之后下一次 tick 仍检出偏差（落后补不回来），判为 covered 结束；flow 告警扩大到同一受损跳上的 cmt-2。
- **unresolved 与报告**：
  - 每一步都失败 → unresolved，记下每一步失败的原因；
  - 连 MAIN 满速都来不及 → 不试修，直接报；
  - 同一偏差只报一次；cause 变了再报；scheduler 通过图 A modify 之后忘掉；
  - 按 cause 分组；
  - 换掉的策略生效；
  - `DeviationReport` 的校验 9 种；
  - `finish_along`。

---






> What is forecast.py used for? introduce the class Assessment and the functions in it.

**用途**：在图 B 的 scan_path 里，回答一个问题：一个已经偏差的 commitment，**从现在起**还要传多少、在现有预留下何时能传完。classify_event（deviation.py）只说明"出了偏差、原因是什么"；forecast.py 把这个偏差算成数字，后面的 triage 和修复都按这些数字判断。

**位置**：

```
scan_path → assess_all → assess ─┬─ off_path_cap                 (unlocated 时的速率上限)
                                 └─ held_runs → circuit_runs → expected_gbps   (逐槽速率)
                                       └→ ctx.rate_model.finish_along          (→ p50 / p95)
repair.py: triage 用 a.covered；修复用 a.deadline / a.cap_gbps / finish_under / circuit_runs
```

### `Assessment`：对一个偏差的判断结果（frozen dataclass）

| 字段 / 属性 | 含义 |
|---|---|
| `deviation` | 来自 deviation.py 的原始偏差（cause、受损链路、进度等） |
| `remaining_bytes` | 还剩多少字节 |
| `deadline` | `latest_finish`，但不超过账本的时间范围（账本之外无法预测） |
| `cap_gbps` | 链路以外的速率上限，只在 unlocated 时有值；None 表示只按链路预测 |
| `finish` | 在**现有预留内**的 (p50, p95)；预留结束前传不完则为 None |
| `finish_if_kept` | 假设 circuit 按最后一段速率一直延长下去，何时传完；写进 unresolved 报告，让 scheduler 知道"大概晚多少" |
| `committed` / `commitment_id` / `priority` | 便捷属性，从 deviation 里取 |
| `covered` | `finish` 的 p95 ≤ 预留结束时间，也就是现有预留仍然够用。triage 据此结束，不修复 |

### 函数（自底向上）

1. **`expected_gbps(ledger, path, i, gbps, booking_id)`**：在槽 i，一个速率为 gbps 的 circuit 预计实际能拿到多少。逐跳看：
   - 有一跳 down → 0；
   - 我们在这一跳上订的总量（自己按 gbps 算，并扣掉自己已有的预订 `held`，避免重复计算）> observed → 按速率比例分：observed × gbps / 总量；
   - 否则 → gbps。
   - 取各跳最小值。`booking_id=None` 用于"还没订"的假想 circuit（修复时评估新速率、新路径）。
   - 例：L2 只剩 40，我们订了 60 + 20 → 分别得到 30 / 10。
2. **`circuit_runs(ledger, path, gbps, start, end, booking_id, cap)`**：对 [start, end) 的每一槽调用 `expected_gbps`（有 cap 时再取 min），把相邻、速率相同的槽合并成 `(start, end, gbps)` 段。时间截在账本范围内。
3. **`held_runs(ledger, item, now, cap, until=None)`**：沿着一个已订 item 的 rate profile，从 now 起每一段都调用 `circuit_runs`，得到"按现有预留"的速率段。给了 `until`，就再把最后一段速率从预留结束延长到 until，用来算 `finish_if_kept`。
   - 例：L3 计划在 11:00–11:15 中断 → `[(10:00,11:00,40), (11:00,11:15,0), (11:15,end,40)]`。
4. **`off_path_cap(d, now, tolerance)`**：只用于 cause = unlocated（原因不在链路上，比如端主机磁盘慢，账本里看不到）。用最近速率（没有上一次读数时用开始以来的平均速率）；它比预留速率低超过容差，就作为上限；否则认为已恢复，返回 None。located 的偏差返回 None，因为账本已经反映了原因。
   - 例：源盘只有 0.6 倍速 → 上限 24 Gbps；只在 09:30 前慢，10:00 时最近速率回到 40 → 不设上限。
5. **`assess(ctx, d, now)`**：组装一个 Assessment：先算 cap，再分别用 `held_runs` 不带 until / 带 `until=horizon_end` 喂给 `rate_model.finish_along`，得到 `finish` / `finish_if_kept`，deadline 取 min(latest_finish, horizon_end)。
6. **`finish_under(ctx, item, nbytes, cap, now)`**：给定 item **当前**的预留，nbytes 的 (p50, p95)。修复改完预留之后，用它重新算完成时间（`_repaired` 判断修复是否成功；借出方也用它算自己让出速率之后的完成时间）。
7. **`assess_all(ctx, deviations, now)`**：scan_path 的入口。先把每个偏差的路径从 now 刷新到 `latest_finish`（只刷过期的；刷到 latest_finish 而不是预留结束，因为 extend 等修复要用到之后的时间），再逐个 `assess`。返回 (assessments, 刷新过的链路)。

### 一个完整例子（`test_outage_forecast`）

si-1 要传 50 TB，以 40 Gbps 预留 09:00–11:46:40，latest_finish = 15:00。L2 在 09:30–09:45 中断。10:00 时：
- 已传 45 min × 5 GB/s = 13.5 TB → `remaining_bytes` = 36.5 TB；
- 预留剩 10:00–11:46:40 = 6400 s × 5 GB/s = 32 TB < 36.5 → `finish` = None，`covered` = False；
- 一直按 40 延长：36.5 TB / 5 GB/s = 7300 s → `finish_if_kept` = 12:01:40；
- `deadline` = 15:00，`cap_gbps` = None（located）。
- 于是 triage 判为需要修复；extend 把预留结束时间延到 12:01:40 即可。

**为什么是 p50 / p95 而不是一个时间**：完成时间都经由 `RateModel.finish_along` 计算，以后在这里接入校准过的速率模型（第 9 步）。目前的 `IdealRateModel` 直接积分，p50 = p95。

**偏保守的地方**：账本每槽只记最小值，所以整槽都按最差值算，预测只会偏晚，不会偏早。

---

> 1. 没懂cap_gbps，finish，finish_in_kept，covered的含义？remaining_bytes不是可以直接从deviation里的进度里获得吗？
> 2. 为什么expected要-held+gbps？held和gbps是啥？
> 3. circuit_runs中的a、b、g是什么？用直观的标志符名，一看就懂那种。
> 4. "沿着一个已订 item 的 rate profile"请说人话。

**先说两类数据的区别**：`Deviation` 是**观察到的事实**（过去：已传多少、哪跳坏了、原因）；`Assessment` 是**对未来的预测**（还要传多少、什么时候能传完、现有预留够不够）。

**1. 四个字段**（用同一个例子：50 TB，40 Gbps 预留 09:00–11:46:40，latest_finish 15:00，此刻 10:00）

- **`finish`**："什么都不改，只靠**现有预留**，什么时候传完？"预留结束时还没传完就是 None。
  - 例：L2 在 09:30–09:45 断了 15 分钟，剩 36.5 TB，预留剩下的时间只够 32 TB → None。
- **`covered`**："现有预留还够不够？"就是 `finish` 不为 None 且 p95 ≤ 预留结束时间。够就什么都不做（triage → covered → END）。
  - 例：上面 → False，要修。如果只断了 1 分钟、偏差在容差之内也传得完 → True。
- **`finish_if_kept`**："如果**只是让 circuit 按原速率继续开下去**（不改路径、不提速），什么时候传完？"即需要的额外时间。
  - 例：36.5 TB ÷ 40 Gbps = 2:01:40 → 12:01:40。修不好时写进 unresolved 报告，告诉 scheduler"大约晚到 12:01:40"。
- **`cap_gbps`**：链路以外的速率上限。账本只知道链路；如果慢的原因不在链路上（例：源盘只有 0.6 倍速），账本里链路全都正常，`expected_gbps` 会预测满速 40，太乐观。所以 unlocated 时用实际看到的速率（24）封顶。原因在链路上时账本已经反映了，所以是 None。

**`remaining_bytes`**：对，它就是 `Deviation.remaining_bytes`（请求总字节 − 已传），之前在 Assessment 里又存了一份，是多余的。**已改**为属性，直接从 deviation 取，与 `committed` / `commitment_id` 一致。

**2. `expected_gbps` 里的 −held + gbps**（已改名：`held` → `booked_now`，`demand` → `ours`）

- `gbps`：要评估的速率（"假如这个 circuit 以 gbps 跑，能拿到多少"）。它不一定等于现在订的速率：提速（raise_rate）时评估 60；延长到预留之后时那段本来没订。
- `booked_now`：这个 circuit **现在**在槽 i 订了多少（预留之外为 0；还没订的 circuit 为 0）。
- `ledger.own(link, i)`：我们在这跳、这槽**所有**预订的总量，已经包含了 `booked_now`。
- 所以 `ours = own − booked_now + gbps`：把这个 circuit 现有的那份换成要评估的速率，得到"按 gbps 跑时，我们在这跳上的总需求"。不减就会把它算两次。
- 例：L2 上我们只剩 observed = 40 可用；本 circuit 订 40，另一个订 20，own = 60。
  - 按 40 评估：ours = 60 − 40 + 40 = 60 > 40 → 40 × 40 / 60 = 26.7；
  - 按 60 评估（提速）：ours = 60 − 40 + 60 = 80 → 40 × 60 / 80 = 30；
  - 不减 `booked_now`：60 + 60 = 120 → 20，偏低，是错的。

**3. a、b、g**（已改名）

- `a` → `run_start`、`b` → `run_end`：这一槽与 [start, end) 的交集的起止时间；
- `g` → `rate`：这一段预计拿到的速率；
- 和上一段首尾相接、速率相同就合并（加了注释）。
- `estimate.py` 的 `IdealRateModel.finish_along` 遍历的是同样的段，也一起改成了 `run_start, run_end, gbps`。

**4. "沿着 rate profile"**

rate profile 就是这条预留的**时间表**：几点到几点、按多少 Gbps。现在大多只有一段（09:00–11:46:40 @ 40），修改过后可能有几段（例：09:00–10:00 @ 40，10:00–11:30 @ 60）。

`held_runs` 做的事：拿着这张时间表，**从现在起**，对每一段逐槽问账本"这段时间实际能拿到多少"，拼成一串 (起, 止, 速率)。已经过去的部分跳过。给了 `until` 就再假设最后一段速率一直开到 until。
- 例：时间表 09:00–11:46:40 @ 40，L3 计划在 11:00–11:15 中断，现在 10:00 → `[(10:00, 11:00, 40), (11:00, 11:15, 0), (11:15, 11:46:40, 40)]`。

（以上改名与 `remaining_bytes` 改为属性后 272 个测试全过。）

---

> 来看off_path_cap。讲讲这个函数在干嘛


**它要解决的问题**：预测完全靠账本，而账本只知道**链路**。如果慢的原因不在链路上（源/目的端磁盘慢、主机忙、传输软件调参不当……），账本里每一跳都正常，`expected_gbps` 会预测"从现在起满速"，太乐观：
- triage 可能误判为 covered（"后面满速能追回来"），结果不修；
- extend 按满速算延长多少，延得不够，下一次 tick 又偏差。

所以：原因不在链路上时，**用实际看到的速率给预测封顶**，假设这个慢会一直持续。

**逐步**：

1. **只管 unlocated**。located（link_down / congestion）的原因已经在账本里（断开 → 0，拥塞 → 按比例分），再封顶就重复算了。late_start 也不管：它慢在"开始晚"，开始之后速率是正常的。
2. **还没开始**（`started_at is None`）→ 没有速率可参考 → None。
3. **看到的速率**：优先用 `recent_gbps`（距上一次读数的平均速率），它反映**现在**的状态，能看出已经恢复；第一次读数时没有上一次，退而用开始以来的平均速率。
4. **和预留速率比**：低于 (1 − 容差) × 预留速率 → 返回它作为上限；否则返回 None，认为已恢复（或只是测量抖动），不封顶。容差复用 `progress_lag_tolerance`。

**例子**（预留 40 Gbps，09:00 开始）：

| 情况 | 看到的速率 | 结果 |
|---|---|---|
| 源盘一直只有 0.6 倍速，10:00 第一次读数 | 开始以来平均 24 | 封顶 24：之后每一段都按 ≤ 24 预测，`finish_if_kept` 也按 24 算 |
| 只在 09:30 前慢（0.5 倍），09:50 第一次读数 | 平均 (30 min × 20 + 20 min × 40) / 50 min = 28 | 封顶 28（没有更近的读数，保守） |
| 同上，10:00 第二次读数 | 09:50–10:00 的最近速率 = 40 | 不低于 (1 − 容差) × 40 → None，不封顶 |
| L2 断开（located） | — | None，账本里那段已经是 0 |

**下游怎么用**：`circuit_runs` 每一段取 min(预计速率, cap)；repair 里 unlocated 只试 extend（瓶颈不在网络，提速、换路都没用），判断"值不值得试"时也把可达速率限制在 cap 以内。

**局限**：假设"现在多慢，之后就一直多慢"。端主机的慢如果是间歇性的，会偏保守；更准的模型属于第 9 步校准。

---

> Triage下的三个属性是啥意思？如果你觉得不清楚，请重改名字。

`Triage` 是 triage 节点的结果：把每个 `Assessment` 分进三组之一。

| 属性 | 内容 | 含义 | 之后 |
|---|---|---|---|
| `covered` | commitment id | 现有预留仍能按时传完剩下的字节（`Assessment.covered`，p95 ≤ 预留结束） | 什么都不做 |
| `already_reported`（原 `reported`） | commitment id | 之前已经报过 unresolved，而且原因相同、commitment 没被改过——在等 scheduler 决定 | 不重复修、不重复报 |
| `to_repair` | `Assessment` | 其余的 | 交给 plan_local_repair |

前两组只要 id（之后不再用），第三组要整个 Assessment（修复要用 deadline、cap 等）。

**改了的名字**（272 个测试全过）：
- `Triage.reported` → `already_reported`：原名分不清是"这次报了"还是"之前报过"；也和图 B state 里已有的键 `already_reported` 对齐；
- 策略的判定值 `"reported"` → `"already_reported"`；
- `ctx.reported` → `ctx.reported_unresolved`：记的是"报过 unresolved 的 commitment → (当时的 cause, 当时的 commitment)"；
- runtime.py 里的局部变量 `t` → `triaged`；`Triage` 加了 docstring，每个字段的注释写明内容和含义。
- `covered`、`to_repair` 没改：`covered` 与 `Assessment.covered` 同义，`to_repair` 已经直观。

**`already_reported` 什么时候失效**（`triage_all` 开头）：commitment 被 release 或被 scheduler 通过图 A modify 过（和记下的不一样了）就忘掉；之后又 covered 也忘掉。cause 变了则不算 already_reported，会重新修 / 报。
---

> RulePolicy下的triage和plan对应图b的triage和plan_local_repair吗

**对**，它们就是图 B 两个 ◇ 判断节点里"做判断"的那部分。每个节点分三层：

```
节点 triage            → triage_all(ctx, policy, assessments)   → policy.triage(ctx, a)        每个 Assessment 一次
节点 plan_local_repair → plan_all(ctx, policy, to_repair, now)  → policy.plan(ctx, a, now)     每个 Assessment 一次
```

| 层 | 做什么 |
|---|---|
| 节点（runtime.py） | 只编排：从 state 取输入、调函数、写回 state |
| `triage_all` / `plan_all`（repair.py） | 不随策略变的固定部分：triage_all 先忘掉已失效的 `reported_unresolved`，再按判定分组；plan_all 按 priority 从高到低排序，保证高优先级先修 |
| `policy.triage` / `policy.plan` | **判断本身**，只看一个 Assessment：triage 返回 covered / already_reported / repair；plan 返回要试的步骤列表（如 `["extend", "raise_rate", "reroute"]`），空列表 = 不值得试 |

**为什么单独拎出来**：判断规则以后会换（第 9 步按校准结果调，或换成 LLM 判断），所以放在 `RuntimePolicy` 接口后面，`build_runtime_graph(policy=...)` 传入另一个实现即可，图和固定部分不动。`RulePolicy` 是第一版、基于规则的实现。执行修复（execute_repair）不属于策略：怎么 extend、怎么回滚是固定的。