# 2026-11-09 检查共享仓库最新 Telemetry Agent

## 一 检查版本与结论

本次检查了 `external/kklab_scinet_agents` 对应远端 `origin/main` 的最新代码，先执行 fetch 确认版本，再读取代码并在临时快照中验证，**没有修改同事的实现、没有同步 Network Agent、没有提交或推送**。


| 项目                    | 版本/状态                                                                                 |
| --------------------- | ------------------------------------------------------------------------------------- |
| 检查日期                  | 2026-11-09                                                                            |
| 本地 submodule checkout | `35d4cc313002c8aea5a4a46522d5ff8e28bc75c2`，仍保留原位                                      |
| fetch 后远端最新版本、本次审查对象  | `1e805628fde566fe996532085f302234d7216996`                                            |
| 最新提交时间                | 2026-11-05 19:11:26，America/Los_Angeles                                               |
| 最近三次更新                | `25fda14` 换成 Telegraf southbound；`d8b55b5` 增加 LangGraph northbound；`1e80562` 增加设计图与说明 |


注意：本地 checkout 中看到的旧 README 仍是 10 月的 mock Prometheus 原型。本记录讲的是 **fetch 后的远端新版本**，所以代码证据链接固定到该 commit，不能用当前本地旧文件来判断新版本能力。

**总体结论**：这版已经搭出“真实 Prometheus 指标采集 → 单位转换 → InfluxDB 历史存储/Last Value Cache → Python LangGraph 查询 → `LinkSample`”的链路。它目前是**一个真实网卡的观测与容量估计原型**，不是完整拓扑 telemetry，也还不是 runtime 所需的 flow progress / subscription / alert 服务。

对接的主要限制是：

1. 只绑定一个 demo 有向链路到一个实际接口，没有真实 topology discovery。
2. `available_gbps` 仍为“标称容量 − 全部实测流量”，没有排除我们自己的传输，与 Network Agent 的扣账契约不一致。
3. 所有返回值都假定 `up=True`，也把一次观测当成整个请求时间窗的常量，不是未来容量/预约信息。
4. NB 保存了原始采样时间元数据，但目前只按查询记录的 `time` 判断新鲜度。
5. 共享版使用旧模块路径；与本地已重构的 Network Agent 直接组合时，当前会导入失败。



## 二 与旧版本相比，具体做了什么

旧版是请求驱动的 `NB → SB → normalize → NB`，由 Python 向受控 mock Prometheus 查询，支持针对模拟网络的 foreign-only schedule 语义。

新版把职责重新分开：

```text
独立后台采集（不等 Network Agent 请求）
NRP Prometheus
  → Telegraf HTTP input
  → XPath JSON 解析
  → scale / rename processors
  → InfluxDB interface_metrics 历史表
  → InfluxDB 自动维护 interface_latest LVC

按需查询（只读存储，不启动采集）
Network Agent.link_samples(...)
  → TelemetryAgent 的 LangGraph
  → 先读 LVC，检查可用性
  → 必要时读历史表
  → 返回 LinkSample，或抛 TelemetryError
```

因此旧的 `southbound.py`、`normalizer.py`、`mock_prometheus.py`、`context.py`、独立 `graphs/protocol.py` 和旧 demo 等已被删除。SB 与单位转换改由 Telegraf 插件执行；新的查询图直接定义在 `northbound.py`。

**这个变化同时带来语义变化**：旧 mock 的 foreign-only/future interval 断言，不能当成新版真实网卡指标也已提供的能力；新版 README 明确把容量规划口径列为待完善项。

## 三 Southbound：真正采集什么

依据：[telegraf.conf](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/telegraf.conf)。

### 3.1 当前数据源固定为一个接口

- Prometheus 默认地址：`https://prometheus.nrp-nautilus.io`，可以通过 Compose 环境变量 `PROMETHEUS_URL` 改 base URL。
- 机器/instance：`amd-halo.ucsd.edu`。
- 网卡/device：`enp191s0`。
- 采集间隔 **15 秒**，flush 间隔 **5 秒**。
- 实际 source/instance/device 选择与 PromQL 仍写在配置中，尚无多服务器/多接口配置生成器。



### 3.2 查询六组结果


| 结果           | Prometheus 表达式的核心                              |
| ------------ | ---------------------------------------------- |
| 接口标称容量       | `node_network_speed_bytes`                     |
| TX 速率        | `rate(node_network_transmit_bytes_total[1m])`  |
| RX 速率        | `rate(node_network_receive_bytes_total[1m])`   |
| 容量原始采样时间     | `timestamp(node_network_speed_bytes)`          |
| TX 原始计数器采样时间 | `timestamp(node_network_transmit_bytes_total)` |
| RX 原始计数器采样时间 | `timestamp(node_network_receive_bytes_total)`  |


六组结果通过同一次 POST `/api/v1/query` 获取，`label_replace` 增加 `scinet_field` 标签区分字段。PromQL 本身不做单位转换。

XPath JSON parser 要求这一接口有六组结果，把它们组合成**一条完整记录**。其后：

1. `processors.scale` 将容量、TX、RX 乘 `8e-9`，从 bytes/s 转 Gbps；时间字段不缩放。
2. `processors.rename` 改为 `max_capacity_gbps`、`tx_gbps`、`rx_gbps`。
3. `outputs.influxdb_v3` 写入数据库。

TX/RX 是**过去 60 秒的平均速率**，每 15 秒取一次，窗口会重叠；不是瞬时速率，也不是针对单个 transfer 的进度。

## 四 存储与启动

依据：[compose.yaml](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/compose.yaml)、[scripts/store.py](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/scripts/store.py)。

- Docker Compose 两个独立容器：`influxdb:3.12.2-core`、`telegraf:1.40.2`。
- InfluxDB 在宿主机暴露 `127.0.0.1:8181`；Telegraf 在 Compose 网络内连接 `influxdb:8181`。
- 数据库：`telemetry`；历史表：`interface_metrics`；LVC：`interface_latest`。
- tags：`source / instance / device`；fields 包括容量、TX/RX、60 秒统计窗口及三种原始采样时间。
- 记录 `time` 为 Prometheus 查询评估时间，保留毫秒精度。
- LVC 按接口标识保存最新一条完整记录，TTL 为 **1 小时**；这与 NB 的 15 秒数据有效期是两个概念。
- 历史数据放在 Docker named volume；配置未指定历史表过期时间。

启动脚本顺序：启动 InfluxDB 并等待 health check → 初始化 operator token、数据库、空表和 LVC → 启动 Telegraf。初始化不写假指标；token 存入忽略跟踪的 `.env`，权限设置为 `0600`。初始化有重复执行复用逻辑。

另提供 `scripts/store.py query` 作为手动 SQL 查看工具，它不是 NB 服务。停止 Telegraf 后仍可以查询已有存储；Compose down 不主动删除 named volume。

## 五 Northbound：LangGraph 怎样提供查询

依据：[northbound.py](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/northbound.py)、[store.py](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/store.py)。

### 5.1 对外入口与 link/interface 映射

```python
from telemetry_agent.northbound import TelemetryAgent, TelemetryError

nb = TelemetryAgent()
samples = nb.link_samples(link_ids, start, end, now)
```

它返回共享仓库中实际的 `network_agent.schemas.LinkSample`，满足旧版 `TelemetrySource.link_samples()` 的调用形式。NB 在应用进程内运行，不是新增一个 HTTP server，也没有单独 NB 容器；另有 `python -m telemetry_agent` CLI 输出 JSON。

`bindings.json` 目前只有：

```text
demo:amd-halo>peer
  → source=nrp
  → instance=amd-halo.ucsd.edu
  → device=enp191s0
  → direction=tx
```

换成 `direction=rx` 则选择 RX 使用量。这里的 link ID 是手动提供的 demo ID，`peer` 不代表已发现的真实对端。没有把我们 mock 拓扑的 `L0/L1/L2/...` 自动映射到真实网卡。

### 5.2 六节点执行图

```text
validate_request
  ├─ 参数错误 / 未知 binding / 空批次 → respond
  └─ read_cache → assess_cache
                     ├─ 全部可用 → respond
                     └─ 缺失/无效/过期 → read_store
                                           ├─ 查询异常 → respond
                                           └─ assess_store → respond
```

- 参数包含 link IDs 与 `start / end / now`；时间规范到 UTC，要求带时区，且 `start < end`。
- IDs 去重；空批次返回空列表；任何 ID 无 binding 都在读库前报错。
- `_read()` 按每个 link 顺序查库；当前不是并发批量 SQL。
- 先读 InfluxDB LVC；LVC 不可用也视为 miss。
- 只要一个 link 的缓存不合格，就对整个请求批次重新读历史表，既不拼出部分成功，也不触发重新采集。
- 历史表仍缺失/无效/过期，返回错误。

查询 SQL 的核心条件：对应 source/instance/device，`time <= now`，再按 `time DESC LIMIT 1`。没有读取 `now` 之后的观测；历史 `now` 可以回查表中的旧记录。

### 5.3 `LinkSample` 实际代表什么

每个 link 返回一个 sample，覆盖调用方整个 `[start, end)`：


| 字段               | 新版实现                                                   |
| ---------------- | ------------------------------------------------------ |
| `available_gbps` | `max(0, max_capacity_gbps - tx_gbps)`；RX binding 则减 RX |
| `up`             | 固定 `True`，不是实测 operational state                       |
| `sampled_at`     | 数据记录的 `time`                                           |
| `valid_until`    | `sampled_at + 15 秒`                                    |
| `source`         | `nrp:measured_headroom`                                |
| `start / end`    | 原样采用请求窗口，假设观测容量在整个窗口内不变                                |


检查边界为 `sampled_at <= now < valid_until`，到期时刻本身不再有效；读库不会延长原记录有效期。

即使请求未来几分钟的时间窗，也只是把当前 headroom 作为常量估计铺到未来，**没有未来预约或预测的证据**。这个政策已在 README 明确标为 prototype assumption。

### 5.4 错误处理

Python 方法抛 `TelemetryError`，不在应返回 list 的位置塞一个错误字典：

- `invalid_request`：请求格式或时间无效。
- `not_found`：未知 link，或任意 link 没有有效、新鲜的证据。
- `store_error`：历史表查询失败，包括连接/认证类错误。

CLI 再将异常转换为错误 JSON、退出码 1。Network Agent 如何把该异常转换为 scheduler 可识别的错误响应，仍未完成。

## 六 对我们当前 Network Agent 的实际意义与缺口



### 6.1 已具备：只读 link capacity 查询路径

成功路径已经有测试：真实 `refresh_stale()` 调用 NB，NB 返回实际 `LinkSample`，再写入 ledger。适合演示“从存储读指标、形成链路容量观测、交给 Network Agent”。

但该测试基于**共享仓库里的旧版 Network Agent**，并且数据库由 FakeStore 替代；不等于真实数据源、整套 topology 和当前 runtime 已全部集成。

### 6.2 重要：自身流量会重复扣减

本地最新 [LinkSample 契约](../../src/lib/network_agent/src/models/schemas.py) 要求：`available_gbps` 尚未扣除本 agent 自己的 bookings，因为 ledger 还会扣一次 `own`。

新版 NB 的计算却是：

```text
capacity − total measured traffic
```

如果 total traffic 包含我们自己的传输，再由 ledger 扣自己的预留，就会把同一部分资源算两次。示例，仅说明计算关系：

```text
容量 100，其他流量 20，我们正在使用/预留 30
NB 返回 100 − (20 + 30) = 50
ledger 再扣 own 30 → 20
在此例中真实剩余为 50，而不是 20
```

README 已承认 foreign-only accounting 未解决；当前测试验证 schema/调用和简单数值转换，不证明这个扣账口径正确。需共同确定怎样区分自己的用量、预留与其他流量，不能机械地假定“加回全部 booking”在所有测量条件下都成立。

### 6.3 Runtime 尚缺 flow progress、订阅和告警

目录内尚无下列服务：

- `FlowSource.progress(instance_id, now)` / 单条 transfer 的已传字节与开始时间。
- 订阅注册、阈值监控、push notification。
- link down/up、flow stalled、flow below rate 等告警及其去重。
- NDT/VIT 的 metrics adapter。
- RTT/loss 等更广泛指标接口。

因此 11 月 9 日组会讨论的 subscription + periodic query 两条 runtime 入口，目前这个版本只为其中的 **link_samples 主动查询**提供了基础；还不足以替换 runtime 中的全部 mock。

### 6.4 原始源时间没有参与 NB 新鲜度检查

SB 已保留 `capacity_sampled_at_unix / tx_sampled_at_unix / rx_sampled_at_unix`，但 `_sample()` 不读取它们，只看行 `time`。

这意味着：如果 Prometheus 查询时间很新、底层样本却较旧，只要行时间仍在 15 秒内，NB 也可能接受。已有 `test_original_source_metadata_does_not_override_row_time` 甚至明确让很旧的 TX 元数据不影响通过。这是当前原型的已知政策，不应把“保存源时间”写成“已经校验源证据新鲜度”。

此外 15 秒采集与严格 15 秒过期，加上 flush/查询延迟，可能短暂没有可接受的新记录；README 也说明了这一点。本次没有测量该空档频率。

### 6.5 `up=True` 与常量时间窗限制

返回零 headroom 仍然 `up=True`；不能用它区分故障与饱和。对于需要逐槽容量、未来已知中断/预约变化的 scheduler/ledger，整个窗口使用一个常量只是一种简化估计，不是等价实现。

### 6.6 与本地新目录布局不兼容

新版同事代码仍导入：

```python
from network_agent.schemas import LinkSample
```

而我们本地已重构到 `network_agent/src/models/schemas.py`。这次把 NB 快照与本地当前 package 放在同一隔离进程，导入得到：

```text
ModuleNotFoundError: No module named 'network_agent.schemas'
```

共享仓库的兼容性测试也仍使用旧 `config / ledger / telemetry / topology` 路径及 `quote_ttl_seconds`。因此“接口形式不需要改 Network Agent”只适用于它当前测试的共享旧版本；下一次同步本地结构时需要提前通知同事，并共同调整 imports/测试。此次未替任何一方改代码。

## 七 本次实际验证与证据边界



### 7.1 已实际执行：51 项检查通过

在远端最新 commit 的独立临时快照中，使用本仓库现有 `.venv` 执行：

```sh
python -m pytest \
  telemetry_agent/tests/test_northbound.py \
  telemetry_agent/tests/test_store.py \
  network_agent/tests/test_step3a_telemetry.py \
  -q -p no:cacheprovider
```

结果：**51 passed in 0.28s**，没有失败或 skip。这些检查主要验证：

- LangGraph 缓存命中与历史表回退路径。
- 全批次成功/失败、空请求、ID 去重、身份与时间校验。
- 过期边界、TX/RX 选择、负值/非法值拒绝、零 headroom。
- Store HTTP 请求参数及错误转换（HTTP 被 mock，不访问实际数据库）。
- 共享版 Network Agent 的 `refresh_stale()` 消费 NB 的 samples。

另单独复现了上一节的本地新 package 导入失败。这不影响上述 51 项共享旧版本测试通过，两者检查的版本组合不同。

### 7.2 未在本次重跑的部分

当前执行环境没有找到 Docker CLI，因此没有启动容器、没有运行 `test_pipeline.py`，也没有访问 NRP 实测或创建 InfluxDB/token/数据卷。

新版 README 报告，作者在 11 月 5 日已验证固定输入的 Telegraf parser/processors、真实 NRP 查询、约 15 秒历史写入、LVC、重复初始化和重启持久化；本次检查确认有对应实现/测试代码，**没有独立复现这些部署结果**。

## 八 最值得先对齐的一件事

先与同事确认 `LinkSample.available_gbps` **到底表示什么**：是当前总流量扣除后的 headroom，还是符合 Network Agent 账本要求、尚未扣除自身预订的容量。这个口径决定接入后 ledger 是否能正确工作，比直接把返回值接进去更优先。

## 九 阅读入口


| 文件                                         | 本次确认的用途                                         |
| ------------------------------------------ | ----------------------------------------------- |
| `telegraf.conf`                            | 真正的采集、解析、单位转换与写入配置                              |
| `compose.yaml`                             | 两个容器与持久化存储                                      |
| `scripts/start.sh`、`scripts/store.py`      | 启动/初始化、人工 SQL 查看                                |
| `northbound.py`                            | 对 Network Agent 的 API、六节点 LangGraph、容量转换及错误     |
| `store.py`                                 | NB 专用的只读 InfluxDB HTTP SQL client               |
| `bindings.json`                            | 有向 link → 接口/方向映射，目前只有一个 demo binding           |
| `__main__.py`                              | 单次查询 CLI                                        |
| `tests/test_northbound.py`、`test_store.py` | 无服务依赖的查询与兼容性测试                                  |
| `tests/test_pipeline.py`                   | 需要 Docker 的生产 Telegraf parser/processors 固定输入测试 |
| `docs/code-flow.html`                      | startup、SB、NB 的代码流程图                            |


版本化证据总入口：[本次检查的 Telemetry Agent 目录](https://github.com/ShiningChuang/kklab_scinet_agents/tree/1e805628fde566fe996532085f302234d7216996/telemetry_agent)、[对应 README](https://github.com/ShiningChuang/kklab_scinet_agents/blob/1e805628fde566fe996532085f302234d7216996/telemetry_agent/README.md)。

---

> - “只绑定一个 demo 有向链路到一个实际接口”，用的是ucsd的机器的某个interface吗？如果只有一台机器，一个接口，那怎么得到link信息的？
> - “`available_gbps` 仍为“标称容量 − 全部实测流量”，没有排除我们自己的传输，与 Network Agent 的扣账契约不一致”，这里能否不让tele agent变动，而是在network agent这边，通过不排除自己的传输来对齐？
> - “把一次观测当成整个请求时间窗的常量，不是未来容量/预约信息”是啥意思？
> - “目前只按查询记录的 `time` 判断新鲜度”是啥意思？

**1. 是 UCSD 主机的一个接口，但没有真正发现一条完整网络链路。**

配置选的是：

```
主机：amd-halo.ucsd.edu
接口：enp191s0
方向：TX
```

它知道这个接口的标称速率和发送流量，就能计算这个接口当前的 headroom：

```
接口标称容量 − 接口发送速率
```

随后，代码**人为把这个接口映射成** `demo:amd-halo>peer` 这条有向链路。`peer` 是占位名称，没有从指标中发现真实对端。

一个接口的观测可以用于描述其本地出口，但不能据此知道中间路径、其他链路或端到端瓶颈。因此目前验证的是“接口指标如何返回给 Network Agent”，还没有完成真实拓扑的链路监控。

**2. 可以在 Network Agent 侧适配，但不能简单停止扣除自己的预留。**

如果你的意思是“telemetry 已扣了自己的流量，Network Agent 就不再扣 `own`”，问题在于：

**实际流量与预留资源不是同一个量。** 自己尚未开始的传输、已 reserve 但未 commit 的资源，以及未来时段的预留，都不会出现在当前流量中。

例如：

```
链路容量 100 Gbps，当前没有流量
已经给明天的任务 A 预留 60 Gbps
```

Telemetry 仍会返回当前 headroom 为 100。如果 Network Agent 不扣自己的预留，就可能再给明天的任务 B 分配 60，造成超额承诺。

**你可以保持 Telemetry Agent 不动，把口径转换放在 Network Agent 的 adapter 中。但需要知道同一接口、方向和统计窗口内，我们自己的实际用量**：

```
其他流量 = 总实测流量 − 我们的实际流量
可分配容量 = 容量 − 其他流量估计 − 我们的预留
```

不能直接把全部预留当成实际流量加回去。目前 Telemetry Agent 没有提供自身 flow 的实际用量，所以仅靠现有返回值，还不足以准确完成这个转换。

**3. “整个请求时间窗的常量”意味着：把现在的估计铺到你请求的所有时间。**

例如，现在 12:00，观测到：

```
容量 1 Gbps，发送流量 0.2 Gbps → headroom 0.8 Gbps
```

你问：

```
今天 15:00–16:00 有多少可用容量？
```

当前实现会直接返回：

```
15:00–16:00：0.8 Gbps
```

它没有查询那一小时的预约，也没有预测流量变化，只是假设当前状态保持不变。

**15 秒有效期只表示“这个估计多久后需要刷新”，不表示它对几小时后的容量有保证。**

**4. “只按记录的 time 判断新鲜度”意味着：判断的是这次 Prometheus 查询有多新，尚未检查底层指标有多新。**

这里有两个不同时间：


| 时间                  | 含义                   |
| ------------------- | -------------------- |
| 记录的 `time`          | Prometheus 执行这次查询的时间 |
| `*_sampled_at_unix` | 底层容量或流量计数器实际采样的时间    |


假设：

```
底层指标最后采样：11:59:00
Prometheus 查询：12:00:00
Network Agent 请求：12:00:05
```

目前 NB 看记录时间是 12:00:00，距现在只有 5 秒，就会接受；即使底层数据实际上已有 65 秒没更新。

代码虽然保存了底层采样时间，**但尚未用它们做新鲜度检查**。另外，反复读取同一条数据库记录不会刷新它的 `time`；问题在于新执行的 Prometheus 查询可能仍返回旧的底层证据。

---

> 第二点关于扣账的问题我没理解。请你按照问题是什么、我的实现、telemetry agent的实现来解释，并用简单的例子帮我理解。

**问题是什么？**

双方对 `available_gbps` 的理解不同，接起来之后，**我们自己的传输会被扣两次**。

用同一个例子：

- 链路总容量：**100 Gbps**
- 别人的传输占用：**20 Gbps**
- 我们给任务 A 预留了 **30 Gbps**，它也正在使用 **30 Gbps**
- 所以还能给新任务分配：**50 Gbps**

这里特意假设“预留量＝实际使用量”，方便先理解。

**你的实现**

你的账本分两步算：

```
Telemetry 告诉我：扣掉别人的占用后，还剩多少？
100 − 20 = 80

我自己知道：已经给任务 A 预留了 30。
80 − 30 = 50
```

所以你期待 Telemetry 返回的 `available_gbps` 是 **80**。这 80 包括“已经给我们任务 A 的 30”和“尚未分配的 50”。

你的 ledger 再扣自己的预留，得到能分给新任务的 **50**。

**Telemetry Agent 的实现**

它读的是网卡的总流量，里面包括别人的流量和我们的流量：

```
网卡总流量：20 + 30 = 50

Telemetry 返回：
available_gbps = 100 − 50 = 50
```

这个 **50 已经是扣掉双方实际流量后的剩余量**。

但你的账本仍按照原来的约定继续算：

```
Telemetry 返回 50
再扣任务 A 的预留 30
最终得到 20
```

于是，本来剩余 **50**，你的系统却认为只剩 **20**。


| 计算步骤           | 你的接口预期    | 目前实际组合      |
| -------------- | --------- | ----------- |
| Telemetry 返回   | 80：仅扣别人   | 50：别人和自己都扣了 |
| Ledger 再扣自己的预留 | −30       | −30         |
| 最终可分配          | **50，正确** | **20，重复扣减** |


所以，**问题就发生在 Telemetry 已经扣过自己的实际流量，ledger 又扣自己的预留。**

你可能接着想：“那 ledger 别再扣 30，不就好了？”在这个例子里确实可以。但如果任务 A **还没开始传输**，网卡看不到这 30，Telemetry 就不会扣它；此时 ledger 仍必须扣掉这份预留，否则会把已经答应给 A 的资源再次分出去。

因此，需要区分清楚两个数：**自己实际用了多少**，以及**自己已经预留了多少**。它们有时相等，有时不相等。

---

> - 独立后台采集是定时的吗？15秒？5秒的flush是啥？
> - 简单告诉我InfluxDB是存在磁盘里吗
> - 简单告诉我Telegraf是用来干啥的
> - [nb.link](http://nb.link)_samples(link_ids, start, end, now)中的link_ids是通过node+interface的格式来定位一个directed link吗？所以当前demo中只有一条link？
> - [amd-halo.ucsd.edu](http://amd-halo.ucsd.edu)是随便取的名字吗，还是真有这台机器？
> - “原始源时间没有参与 NB 新鲜度检查”请指出对应的代码。

**1. 是每 15 秒定时采集。Flush 是把已采集的数据发送到数据库。**

两者分开：

- `interval = "15s"`：每 15 秒向 Prometheus 查询一次。
- `flush_interval = "5s"`：每 5 秒尝试把缓冲区里的数据写入 InfluxDB；没有新数据就没有新内容可写。

所以不是每 5 秒重新采集。[配置代码 (line 12)](/Users/lxzhong/Documents/GitHub/genesis_scinet/external/kklab_scinet_agents/telemetry_agent/telegraf.conf:12)

**2. 是，InfluxDB 的历史数据保存在磁盘。**

当前通过 Docker volume 持久化。最新值缓存 LVC 在内存中。

**3. Telegraf 用来自动采集、处理和发送指标。**

这里就是：**定时查询 Prometheus → 转换单位 → 写入 InfluxDB**。

**4.** `link_ids` **不要求采用** `node+interface` **格式，而是通过配置表映射到接口。**

当前配置为：

```
link_id: demo:amd-halo>peer
    ↓ bindings.json
主机: amd-halo.ucsd.edu
接口: enp191s0
方向: tx
```

所以**当前只有一条已配置的 demo 有向 link**。它不是从真实拓扑中发现的链路，`peer` 也是占位名称。[映射配置 (line 2)](/Users/lxzhong/Documents/GitHub/genesis_scinet/external/kklab_scinet_agents/telemetry_agent/bindings.json:2)

**5. 它是真实的监控实例名称，不是随便取的 demo 名字。**

我刚查询 NRP Prometheus，确实返回了：

```
instance = amd-halo.ucsd.edu
device = enp191s0
node_network_speed_bytes = 125000000，即 1 Gbps
```

[查询证据](https://prometheus.nrp-nautilus.io/api/v1/query?query=node_network_speed_bytes%7Binstance%3D%22amd-halo.ucsd.edu%22%2Cdevice%3D%22enp191s0%22%7D)

不过，这个名称在当前本机 DNS 查询中无法解析；它作为监控实例标识存在，不代表能直接当网站打开。

**6. 对应代码在** `_sample()` **的第 165–168 行：**

```
observed_at = utc_time(row["time"], database=True)
valid_until = observed_at + SAMPLE_VALIDITY
if not observed_at <= state["now"] < valid_until:
    return None
```

它只用 `row["time"]` 判断新鲜度，**没有检查**：

```
capacity_sampled_at_unix
tx_sampled_at_unix
rx_sampled_at_unix
```

[检查代码 (line 165)](/Users/lxzhong/Documents/GitHub/genesis_scinet/external/kklab_scinet_agents/telemetry_agent/northbound.py:165)

还有一个明确的测试：把 `tx_sampled_at_unix` 设为 **0**，返回值仍被接受，证明底层 TX 采样时间没有参与检查。[对应测试 (line 144)](/Users/lxzhong/Documents/GitHub/genesis_scinet/external/kklab_scinet_agents/telemetry_agent/tests/test_northbound.py:144)

---

> “不能直接把全部预留当成实际流量加回去。目前 Telemetry Agent 没有提供自身 flow 的实际用量，所以仅靠现有返回值，还不足以准确完成这个转换。”  所以无论如何，谁来做这个转换，telemetry agent都必须区分背景流量和scinet流量？

**基本是，但要求可以再窄一点：telemetry 不需要给"背景流量"分类，只需要能识别出"我们自己的流量"。** 背景流量 = 总实测流量 − 我们的实际流量，减法谁来做都行；做不了的是"我们的实际流量"这一项，它只能来自测量。

**为什么绕不开测量**：转换要用的是**我们在这个接口、这个方向、同一个统计窗口里实际用了多少**。预留量不等于实际用量（传输可能还没开始、可能比预留慢、已 reserve 未 commit 的根本没有流量），所以 network agent 只看自己的账本算不出来。

**两种做法，都依赖 telemetry 能识别我们的流量：**

1. **telemetry 按链路给出"我们的用量"或直接给"不含我们的可用容量"**（推荐）。我们的每条 circuit 都有 SENSE 分配的 VLAN（`ReservedOffer.vlan`），network agent 可以把"哪条链路上有哪些 VLAN 是我们的"交给 telemetry，由它按 VLAN 过滤计数后相减。最准确，口径也最清楚：`LinkSample.available_gbps` 就是现在契约里的"不含我们"。
2. **network agent 用 flow 进度自己估算**。`FlowProgress` 本来就要 telemetry 提供，而能提供它，本身就说明 telemetry 能识别我们的 flow。我们知道每个 flow 走哪些 hop，那么某条链路上我们的用量 ≈ 经过它的我们的 flow 的最近速率之和，再用总流量减掉。缺点：
  - flow 进度是端到端送达的数据量，接口计数还包括包头和重传，两者口径不同；
  - 两边的统计窗口要对齐；
  - 误差会直接进入容量估计。

**所以结论是**：无论哪种做法，telemetry 都必须能识别我们自己的流量（按 VLAN、instance 或五元组），区别只是在链路层面识别（做法 1）还是在 flow 层面识别（做法 2）。

**如果短期内谁都做不到**：只能退而求其次——把总实测流量全部当作"别人的"，再扣一次我们的预留。这样我们的流量会被扣两次，可用容量**偏低**。结果是浪费一些容量，但不会超额承诺，属于安全的一侧。相反，"把全部预留当作实际流量加回去"会让可用容量**偏高**，可能超额承诺，所以不能这么做。

**另外**：这些都只解决"现在"的容量。未来时段的容量，实测流量本来就给不出，应该来自预约信息（例如 SENSE 已登记的预留），这是另一个需要对齐的问题（见同一笔记中"整个请求时间窗的常量"）。

---

> SB:  
> [2026/11/9, 22:17:04] Sourabha: 1.⁠ ⁠For “Foreign-only accounting remains unresolved” -- I agree. The current available cap that I return doesn't depend on background traffic, because, there's no way I can measure it as per my exploration. I will check more how to identify background traffic, although I don't know if it's direct/easy.
>
> [2026/11/9, 22:17:08] Sourabha: 2.⁠ ⁠That's true because underlying Prometheus only samples at 15s interval. So, I can't query faster than that. One thing is, I can compare tx_sampled_at_unix with requested time and query the sample, instead of "time" field. Let me fix that.
>
> [2026/11/9, 22:17:10] Sourabha: 3.⁠ ⁠Right, for now, it is just 1 link's interface. I got the [amd-halo.ucsd.edu](http://amd-halo.ucsd.edu) instance from some random exploring the NRP API. In fact I searched for ANL/ORNL sites but couldn't find any instances on NRP Prometheus API -- maybe they are internal clusters. But yes -- any new link we add, we can just write another config file to sync the metrics.

Sourabha 这两条分别回复了我们指出的两个问题：第 2 条是新鲜度检查（[20261109_checktelemetryagent.md](../../resources/notes/20261109_checktelemetryagent.md) 第 6.4 节），第 3 条是目前只接了一条 demo 链路。

**第 2 条：新鲜度检查**

- **前半句**：他承认问题存在。底层 Prometheus 每 15 秒才采样一次，数据最多可能旧 15 秒，他没法查得比这更细。这回应的是 6.4 节说的"15 秒采样、严格 15 秒过期，再加上写库和查询的延迟，可能有一小段时间拿不到有效记录"。
- **后半句**：他打算改为用底层指标的真实采样时间 `tx_sampled_at_unix` 和请求时间比较，不再用查询记录的 `time` 字段。这正是我们指出的问题。改完后，`sampled_at` 和 `valid_until` 就能反映真实的测量时间。

可以提醒他两点：

1. **不能只看 TX 的时间。** 容量也有自己的采样时间 `capacity_sampled_at_unix`，RX 方向则要看 `rx_sampled_at_unix`。应该取用到的几个时间里最旧的那个。
2. **改完后，"拿不到有效记录"的空档会更常见。** 底层采样时间比查询时间更早，如果有效期还是严格的 15 秒，很容易出现旧样本刚过期、新样本还没到的情况。建议有效期取采样间隔再加一点余量，比如 2 × 15 秒，并放进 config。

**第 3 条：只有一条链路**

- 他确认目前只接了一个接口。`amd-halo.ucsd.edu` 是他浏览 NRP 的 Prometheus API 时随手找到的一台真实机器。
- 他也找过 ANL、ORNL（两个能源部国家实验室）的机器，但在 NRP 的 Prometheus 里没找到。他猜这些实验室的集群是内部的，不对 NRP 公开。
- 以后每加一条链路，只要再写一个配置文件，把这条有向链路映射到某台机器的某个接口和方向，就能同步它的指标。

对我们有三点影响：

- **加链路仍要手工写映射**，不是自动发现拓扑。每条链路都得有人知道它对应哪台机器的哪个接口。
- **测到的是端主机网卡的情况**，不是路径中间路由器的端口，所以反映不了整条路径的瓶颈。
- **ANL / ORNL 相关的链路可能没有数据源。** 如果这些站点在 NRP 上确实看不到，我们拓扑里涉及它们的链路就要另找来源，比如 ESnet 自己的监控或 digital twin。这只是推测，需要和合作方确认。

