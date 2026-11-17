# 管理共享仓库 kklab_scinet_agents

与 telemetry agent 同事共享代码和图表的仓库：<https://github.com/ShiningChuang/kklab_scinet_agents>（私有，同事为 collaborator）。
在本仓库里以 submodule 接入，位置是 `external/kklab_scinet_agents`。固定操作都写成了 [kklab.sh](kklab.sh)，公共逻辑在 [tools/common/repo_sync.sh](../common/repo_sync.sh)（和推项目仓库 SciNetGenesis 的 [scinet.sh](../manage_scinet_repo/scinet.sh) 共用）。

```bash
bash tools/manage_kklab_scinet_agents/kklab.sh setup                 # 一次性：加入 submodule
bash tools/manage_kklab_scinet_agents/kklab.sh check                 # 只审查，不碰任何仓库
bash tools/manage_kklab_scinet_agents/kklab.sh sync --dry-run        # 预览会推什么，然后还原，不提交不推送
bash tools/manage_kklab_scinet_agents/kklab.sh sync [--force]        # network agent 有新提交后：同步到共享仓库
bash tools/manage_kklab_scinet_agents/kklab.sh begin                 # 改共享文件前
bash tools/manage_kklab_scinet_agents/kklab.sh finish "<English message>"   # 改共享文件后
bash tools/manage_kklab_scinet_agents/kklab.sh status                # 随时查看状态
```

> **规则：推到 kklab 的提交说明和代码注释里不能有中文，也不能有个人信息和私人仓库信息。** `sync` 和 `finish` 都会审查，违反就拒绝推送，详见 §4 第 1 条。

## 1. 三处代码的关系

```
genesis_scinet（本仓库，私有，不分享）
├── src/lib/network_agent/          ← network agent 唯一的源头，日常开发都在这里
│         │
│         │  kklab.sh sync（单向复制已提交的内容，英文提交说明；不带 genesis 的提交历史）
│         ▼
└── external/kklab_scinet_agents/   ← submodule = 共享仓库
    ├── network_agent/              ← 同步过来的副本，只由 sync 写入
    ├── telemetry_agent/            ← 同事负责
    ├── resources/                  ← 两人共享的图表、笔记
    └── README.md                   ← 归属规则、接口说明
```

## 2. 哪些文件能在 submodule 里改

| 位置 | 能否在 submodule 里改 | 说明 |
|---|---|---|
| `resources/`、顶层 `README.md`、`requirements.txt` | ✅ 用 `begin` / `finish` | 两人共用 |
| `telemetry_agent/` | 按与同事的约定 | 归同事；小修改先打招呼 |
| **`network_agent/`** | ❌ | 源头在 `src/lib/network_agent`。在这里改，改动回不到源头，下次 `sync` 还会冲突。要改就在 `src/lib/network_agent` 改、commit、再 `sync`。`finish` 会检查这一条，发现改动就拒绝提交 |

## 3. 日常操作

### 同步 network agent

```bash
git commit ...                    # 先在 src/lib/network_agent 里提交
bash tools/manage_kklab_scinet_agents/kklab.sh sync
git push                          # 推本仓库（sync 只在本地提交了 gitlink）
```

`sync` 先做三项检查，任何一项不通过就停下：
- `src/lib/network_agent` 下没有未提交的改动；
- `src/lib/network_agent` 里已提交的代码文件（`.md` 以外）不含中文；
- 共享仓库当前的 `network_agent/` 等于本仓库某一次提交的版本，也就是没有人在那边直接改过（否则复制会把那些改动覆盖掉）。

然后依次：
1. 把 submodule 切到 `main` 并拉到最新；
2. 用 `git archive` 取出 `src/lib/network_agent` **已提交**的内容，用 `rsync --delete` 覆盖 `network_agent/`（未跟踪文件、`__pycache__` 不会带过去）；
3. 有变化就在共享仓库提交 `Sync network_agent from genesis_scinet@<hash>` 并推送；
4. 在本仓库**只**提交 submodule 指针（gitlink），不带上其他改动。

**为什么不用 git subtree 了：** subtree 会把 genesis 里每个提交的原始说明（大多是中文）原样带进共享仓库，违反上面的规则。现在改成复制，代价是共享仓库里只能看到一串 `Sync network_agent ...` 提交，看不到 genesis 里的逐条历史；要看细节，用提交说明里的 `<hash>` 回 genesis 查。

### 修改共享文件（resources/、README 等）

```bash
bash tools/manage_kklab_scinet_agents/kklab.sh begin
# 编辑 external/kklab_scinet_agents/resources/... 等文件
bash tools/manage_kklab_scinet_agents/kklab.sh finish "resources: add topology diagram"
git push                          # 推本仓库
```

`finish` 依次：检查 submodule 在 `main` 上、`network_agent/` 没被改、提交说明（含尚未推送的提交）没有中文、新增的代码行（`.md` 以外）没有中文 → 提交 → `pull --rebase`（同事可能刚推过）→ 推送共享仓库 → 在本仓库提交 gitlink。

### 新机器 / 新 clone

```bash
git submodule update --init external/kklab_scinet_agents
bash tools/manage_kklab_scinet_agents/kklab.sh begin         # 切到 main（submodule 初始化后处于 detached HEAD）
```

## 4. 注意事项

1. **推送前的两项审查：不能有中文，不能有个人信息和私人仓库信息。**
   - **[中文]**：中文字符和中文标点（`，。（）：；` 等全角字符）都不行。
   - **[私人信息]**：规则见 [tools/common/private_patterns.txt](../common/private_patterns.txt)，包括私人仓库的路径（`resources/`、`runs/`、`docs/`、`CLAUDE.md`、`PLAN.md`、`src.lib.` …）、私人仓库名、本机路径、账号、邮箱、人名、会议（`meeting`、`10/15 design` 这类写法）、内部实验编号。有新的要拦就加一行正则，误报就把规则改窄；kklab 和 SciNetGenesis 共用这一份。
   - 审查范围：**提交说明**（`finish` 的参数，以及尚未推送的提交；`sync` 的提交说明由脚本生成，不审查）；**代码文件**（`.md` 以外的所有文件）里的注释、docstring 和字符串。
   - 不审查的：`.md` 文档的正文（比如共享仓库 README 里的归属表写了人名，这是有意的）。
   - 什么时候审查：`sync` 审查 HEAD 中 `src/lib/network_agent` 下的代码文件；`finish` 审查暂存区里新增的代码行；`check` 随时可以单独跑。命中会打印文件和行号。
   - 本仓库（genesis_scinet）不受这条限制：这边的提交说明、gitlink 提交、脚本注释照常可以用中文。
   - 审查在本地完成，所以**只拦得住通过脚本推送的内容**。同事那边需要自觉遵守，"English only" 已写进共享仓库 README。

2. **submodule 默认处于 detached HEAD。** `git submodule update` 之后，submodule 停在某个 commit 上，不在任何分支。这时直接 commit，提交不属于任何分支，很容易丢。所以改之前一律先运行 `begin`（`sync` 内部也会自动切到 `main`）。

3. **每次修改都要提交两次。** 一次在 submodule 里（提交并推送共享仓库），一次在本仓库（提交新的 gitlink）。脚本两步都会做，但**本仓库的 push 需要你自己执行**。`scripts/run_experiment.py` 的自动提交只会 `git add EXPERIMENTS.md configs runs`，**不会**带上 gitlink。

4. **本地有两份 `network_agent`。** 一份在 `src/lib/network_agent`（源头），一份在 `external/kklab_scinet_agents/network_agent`（副本）。
   - 不要把 `external/kklab_scinet_agents` 加进 `PYTHONPATH` / `sys.path`，否则可能 import 到副本。
   - 在本仓库根目录直接运行 `pytest`，可能把副本的测试也收集进来，两份模块名相同，会报 `import file mismatch`。根目录的 `pytest.ini` 已经限定 `testpaths = src`、`norecursedirs = external ...`；显式写路径（`pytest src/lib/network_agent/tests`）也没问题，**不要写成 `pytest external/...` 或 `pytest .`**。

5. **`sync` 只同步已 commit 的内容。** `src/lib/network_agent` 下有未提交的改动时，脚本会直接停下。

6. **测试必须保持包内相对导入。** `src/lib/network_agent/tests/` 里用的是 `from ..src.models.schemas import ...`、`from .helpers import ...`，所以同一份代码在两个仓库里都能运行（这边是 `src.lib.network_agent`，那边是顶层 `network_agent`）。新写的测试不要再用 `from src.lib.network_agent...`，否则同步过去后会 import 失败。

7. **共享仓库里的稳定接口。** 共享仓库 README 写明 telemetry agent 可以依赖四个接口：`schemas.LinkSample`、`telemetry.TelemetrySource`、`topology.Topology` / `TopologySpec`、`sim.MockNetwork`。**改这几个之前先通知同事**；其余模块（ledger、placement、graphs …）属于内部实现，可以随时改。

8. **同步的是整个 `src/lib/network_agent` 目录**，凡是放在里面的文件都会进共享仓库。network agent 的实现计划（进度表、待决项，含私人仓库路径和会议信息）因此放在 `resources/other/network_agent/PLAN.md`，不在这个目录里。不想分享的内容都不要放进 `src/lib/network_agent`；注释里也不要写本仓库的私人路径（`resources/`、`runs/`、`docs/` 等）和会议信息。

9. **大文件不进共享仓库。** 共享仓库的 `.gitignore` 已经忽略 `*.pptx`、`*.pdf`；其他大文件（数据集等）也不要提交，在共享仓库的 `resources/README.md` 里登记来源。

10. **登记外部依赖。** 按 CLAUDE.md §3 的规定，这个 submodule 已登记在 `env/external_deps.md`。它是协作仓库，指针变化频繁，所以那里不写固定 hash，以 gitlink 为准。

## 5. 出问题时

### 找回 detached HEAD 上的提交

在 detached HEAD 上 commit 了，之后又切走：

```bash
git -C external/kklab_scinet_agents reflog -10          # 找到那次提交的 hash
git -C external/kklab_scinet_agents checkout main
git -C external/kklab_scinet_agents cherry-pick <hash>
bash tools/manage_kklab_scinet_agents/kklab.sh finish "<提交说明>"
```

### 有人直接改了共享仓库里的 `network_agent/`

`sync` 会停下并提示"与本仓库任何一次提交都不一致"。这时**不要强行同步**：复制会用 `src/lib/network_agent` 的内容整体覆盖 `network_agent/`，对方的改动就丢了。处理原则是**以 `src/lib/network_agent` 为准**：

1. 先看对方改了什么：`git -C external/kklab_scinet_agents log -p origin/main -- network_agent`；
2. 有价值的改动，手工搬进 `src/lib/network_agent` 并 commit（注释保持英文）；
3. 运行 `bash tools/manage_kklab_scinet_agents/kklab.sh sync --force`：跳过这项一致性检查，用 `src/lib/network_agent` 的内容覆盖共享仓库的 `network_agent/`。**只有确认对方的改动已经搬回本仓库（或者确定不要）之后才用 `--force`**；
4. 提醒对方：`network_agent/` 只由 sync 写入。

### 想换回独立 clone，或者不用 submodule 了

```bash
git submodule deinit -f external/kklab_scinet_agents
git rm -f external/kklab_scinet_agents
rm -rf .git/modules/external/kklab_scinet_agents
```

同时删掉 `env/external_deps.md` 里对应的一节。

## 6. 相关文件

| 文件 | 作用 |
|---|---|
| [tools/manage_kklab_scinet_agents/kklab.sh](kklab.sh) | kklab 的参数（仓库地址、目标目录、提交说明） |
| [tools/common/repo_sync.sh](../common/repo_sync.sh) | 和 SciNetGenesis 共用的同步、审查、提交逻辑 |
| [tools/common/private_patterns.txt](../common/private_patterns.txt) | 私人信息审查规则 |
| [pytest.ini](../../pytest.ini) | 防止收集到副本的测试 |
| [env/external_deps.md](../../env/external_deps.md) | submodule 登记 |
| `external/kklab_scinet_agents/README.md` | 共享仓库的归属规则与接口说明（给同事看） |
