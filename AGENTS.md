# AGENTS.md

This file is the Codex/GPT-agent compatibility mirror of `CLAUDE.md`.
It exists so Codex-style agents receive the same project rules that Claude
Code receives from `CLAUDE.md`.

When changing project-agent rules, update both `CLAUDE.md` and `AGENTS.md`
with explicit user approval. If the two files ever disagree, stop and ask
the user which rule should be authoritative.

`genesis_scinet` — **SciNet 方向的系统研究**:为 AI 驱动的自主科学实验闭环,做支撑它的网络与数据传输基础设施(GPU-to-GPU 传输、science-aware 自适应路由、可靠性与韧性、跨机构 workflow 协调),先在合作方已有的网络 digital twin 上做原型与验证。**不做**具体领域的科学 AI 模型(蛋白质/材料等),那是上层的事。

隶属美国能源部 Genesis Mission 计划下的 SciNet 项目(Science-Aware Network Operations for Research Networks),当前是**六个月 Phase 1 加速阶段**,目标是做出 proof of concept 与若干 demo,支撑 12 月的 Phase 2 proposal。

**当前处于方向收敛期**:proposal 仍很 high-level,digital twin 的具体形态、本组负责的模块、第一个可测的系统问题都**尚未确定**,会随合作方会议在数周内演进。因此现阶段的首要任务不是跑实验,而是把"要解决什么问题"收敛成一个可测的假设。背景见 `resources/meetings/20260727.md`(注:该记录源自语音转写 + AI 整理,人名与推断处已标注,引用前须核对)。

记录系统的可靠性建立在**结构强制**,而非执行者记忆。项目记忆属于 Git 仓库,不属于任何一台 server。换机器 = `git clone`。

## 1. 实验执行铁律

- 所有实验必须通过 `python scripts/run_experiment.py <config>` 启动。
- 禁止绕过入口直接运行实验脚本。
- 实验入口会自动 `commit` + `push`,无需手动 push。
- 新参数:先在 `configs/` 建 yaml,再启动。
- 复现历史实验时(checkout 到旧 hash / detached HEAD),入口脚本会自动跳过 commit/push,复现结果仅本地落盘、不进 git 历史。
- 核心系统文件(`CLAUDE.md`、`AGENTS.md`、`scripts/run_experiment.py`、`.gitignore`、`configs/defaults.yaml`)是项目骨架,其修改必须经用户明确同意,不得在执行其他任务时附带改动。如发现这些文件存在问题,应指出并提议修改,由用户决定,而不是直接改或默不作声。

## 2. 结论验证习惯

- 关键结论在标记为 ✅有效 之前,应至少重复运行一次确认,排除环境抖动、测量噪声或偶然因素导致的假结果。
- 对结果稳定性存疑时,可用不同 seed 重跑,观察结果对随机性的敏感度。
- 失败的实验同样有价值,应如实登记(Verdict 标 ❌),不要删除或隐藏。

## 3. 项目记忆地图

- `EXPERIMENTS.md` — 实验索引(表格,一行一个实验)。
- `docs/findings_{YYYYMMDD}.md` — **结论性发现**,每条带 `runs/` 证据链接。**按日期分卷**:文件名日期 = 该卷起始日期,由用户决定何时新建下一卷,agent 不新建;**最新卷 = 日期最大的那个**。旧卷原地保留即是归档,`docs/archive/` 下不设 findings 归档。agent 可写已有 findings 卷。
- `docs/knowledge_{YYYYMMDD}.md` — **通用知识点**(工具行为/系统特性/领域事实),不随实验过期;**纯人工维护,agent 不写、不新建**(可读可引用)。**按日期分卷**防止单文件过大:文件名日期 = 该卷起始日期,由用户看情况手动新建下一卷,**最新卷 = 日期最大的那个**;旧卷原地保留即是归档,故 `docs/archive/` 下**不设** knowledge 归档。查全部知识:`ls docs/knowledge_*.md`。
- `docs/_index_findings.md` / `docs/_index_knowledge.md` — 对应分卷的目录索引,只收录一级至三级标题。新增卷或相关标题变化时同步更新;agent 可维护索引,但不能借此新建 findings/knowledge 卷。
- `docs/ideas.md` — **项目思考与点子**(假设、待办、推测,**允许过期**);**纯人工维护,agent 不写、不改**(可读可引用)。过期内容由用户手动剪切进 `docs/archive/ideas.md`(同为纯人工维护,agent 不写)。
- `docs/current_experiment_plan.md` — 当前实验的计划稿(**覆写式**,只反映当前实验;假设/步骤/待决项,对齐用);**末尾 `## 实验历史`** 记历次实验简介,换实验时由 AI carry-forward 进新 plan。
- `docs/current_log.md` — 当前实验**运行流水账**(**append-only**)。**由用户(人)手写维护,agent 不写入、不修改其内容**;用户据此慢慢读、再**手动** distill 进最新一卷 `findings_{YYYYMMDD}.md` / `knowledge_{YYYYMMDD}.md`。agent 对本文件的职责仅限于:换实验起稿时**创建**空文件、换实验时连同 plan 一并**归档**为 `{YYYYMMDD}_{tag}_log.md`。
- `docs/_plan_template.md` — 计划稿模板。新实验 `cp docs/_plan_template.md docs/current_experiment_plan.md` 起稿;TBD/TODO 约定、对齐/执行两阶段、覆写式纪律、实验历史 carry-forward 都写在模板抬头。
- `docs/archive/` — 历史计划稿归档({YYYYMMDD}_{tag}.md)+ 对应运行流水账({YYYYMMDD}_{tag}_log.md),换实验时把 current plan / current_log 一并挪入;另有 `ideas.md` 作为 ideas 的溢出归档。**findings 和 knowledge 都不在此归档**——它们按日期分卷,旧卷留在 `docs/` 下。
- `configs/` — 实验配置 yaml。
- `runs/` — 本地原始数据,**大件不进 git**(仅 `description.txt` / `config.yaml` / `metrics.json` / `env_snapshot.txt` 小文件入库)。
- `env/` — 外部依赖重建配方;凡 env 中出现 git 之外、复现要依赖的 artifact(包、源码、模型/数据、系统工具,含工具自动拉取的)即同步登记,细则见 `env/README.md`。
- `tools/` — 辅助工具(脚本 + 说明 md),**按用途分子目录**,每个子目录自带同名说明 md,固定操作写成其中的脚本。当前有两个同步工具,命令相同(setup/check/sync [--force|--dry-run]/begin/finish/status),公共逻辑在 `tools/common/repo_sync.sh`:`tools/manage_kklab_scinet_agents/kklab.sh`——与 telemetry agent 同事的共享仓库 `kklab_scinet_agents`(submodule `external/kklab_scinet_agents`,目标目录 `network_agent/`);`tools/manage_scinet_repo/scinet.sh`——项目共享仓库 SciNetGenesis(submodule `external/SciNetGenesis`,目标目录 `ucr/network_agent/`,只能改 `ucr/`)。**`src/lib/network_agent` 是 network agent 的唯一源头**,两个 submodule 里的副本只由 `sync` 写入,不得直接改;其实现计划在 `resources/other/network_agent/PLAN.md`,不放进代码目录。**推到这两个仓库的提交说明和代码注释里不能有中文、个人信息或私人仓库信息**,由脚本审查,规则在 `tools/common/private_patterns.txt`。**agent 不得自行推送 SciNetGenesis**,由用户亲自运行 `scinet.sh sync` / `finish`。其余注意事项(detached HEAD、两次提交、两份 `network_agent` 与 pytest 收集、测试须用包内相对导入)见各子目录说明 md。
- `resources/` — **外部资料**(论文 PDF、外部文档、摘来的笔记 md),与 `docs/`(本项目产出的记忆)相对,是外部输入的原材料。**子目录按类别划分(新资料放进对应子目录,不在根目录平铺)**:`meetings/`(会议记录,`{YYYYMMDD}[_{tag}].md`,含原始会议材料)、`notes/`(笔记与资料整理 md:邮件、slides 解读、设计讨论等,`{YYYYMMDD}_{tag}.md`)、`slides/`(外部 slides,pptx 等大件不进 git)、`imgs/`(md 引用的图片,见下条)、`other/`(不属上述类别的杂项:链接清单、原型/可视化 html 等);根目录只放 `README.md`。**默认纯人工维护,agent 只读不写**:可读取并引用其内容,但不主动写入/重命名/整理/删除,需要往里放东西时提议由用户来放。**例外:用户明确指定允许修改 `resources/` 中的具体文件或范围时,agent 可在该次授权范围内操作;授权不自动延续到其他文件或后续任务。**小文本(md/txt/bib)进 git 随仓库迁移;大件(pdf 等)不进 git,须在 `resources/README.md` 的清单里登记出处,细则见该文件。
- **md 图片规则(每次 commit 前结构强制)**:md 中的图片一律用**地址引用**(`![](相对路径)`),不得内嵌 base64(`data:image/...;base64,<巨长字符串>`)。图片统一放 `resources/imgs/`,命名 `{YYYYMMDD}_{tag}.{ext}`(日期与 tag 取自所在 md 的文件名;无 tag 用所在目录名,无日期用当天;重名递增 `_2`、`_3`,内容相同则复用)。由版本化 pre-commit hook(`scripts/git-hooks/pre-commit` → `scripts/extract_md_images.py`)在**每次 commit 前**(含入口脚本的自动 commit)检查暂存的 md,自动抽出 base64 图片、改写为相对路径并一并暂存;抽取失败即阻断提交。hook 经 `bash env/setup.sh` 激活(`core.hooksPath`),**新 clone 后须先跑一次**。手动全量检查:`python3 scripts/extract_md_images.py --all`。本规则是对 `resources/` 只读纪律的**常设授权例外**:仅限往 `resources/imgs/` 写图、把 md 中的 base64 图片改写为引用,不得借此改动其他内容。
- `weekly_report/` — **组会周报**,一次组会一个 md,文件名 `{YYYYMMDD}.md`(组会当天日期,排序即时间顺序);模板 `_report_template.md`。**人机协作**(区别于下面几处的人工独占):**AI 起草**——依据 `EXPERIMENTS.md` / `runs/*/metrics.json` / 最新一卷 `docs/findings_{YYYYMMDD}.md` 汇总本周客观结果,每条结论带证据链接,口径沿用 §7(观察与解释分开、推测须标注、负结果照实写);**用户定稿**——补判断、提问与下周打算。周报是汇报快照而非记忆本身,结论最终沉淀进最新 findings 卷,周报只引用不复制。

**人工独占清单(agent 默认只读不写,一律不新建/不改名/不整理/不删除)**:`docs/knowledge_{YYYYMMDD}.md`(全部分卷)、`docs/ideas.md`、`docs/archive/ideas.md`、`docs/current_log.md`(仅换实验时创建空文件与归档)、`resources/`。这几处是用户的思考缓冲区,agent 扫到问题可在对话里指出并提议,由用户来动手;其中仅 `resources/` 可在用户明确指定具体文件或范围时按上述例外授权修改。**agent 可写**的记忆文件是:`EXPERIMENTS.md`(入口自动)、已有的 `docs/findings_{YYYYMMDD}.md`、两个 `_index_*.md`、`docs/current_experiment_plan.md`、`docs/archive/` 下的计划稿/流水账归档、`weekly_report/{YYYYMMDD}.md`(起草);findings 新卷仍只由用户创建。

## 4. 新接手阅读顺序

1. 本文件 `AGENTS.md`,并同时检查 `CLAUDE.md` 是否有更新。
2. `docs/current_experiment_plan.md` —— 末尾「实验历史」看历次实验脉络,顶部看当前实验在做什么。
3. `docs/_index_findings.md` —— 从目录定位相关 `findings_{YYYYMMDD}.md` 卷中的已确立结论。
4. `EXPERIMENTS.md` 最近若干行。
5. (方向收敛期额外)`resources/meetings/20260727.md` —— 项目背景问答:项目定位、Genesis Mission 与 SciNet 是什么、digital twin 指什么、候选研究方向。**是背景材料不是结论**:其中含语音转写误识别与 AI 推断,标注了置信度的地方须回原始出处核对。

## 5. Tag 命名约定

项目长期规范,与具体研究内容无关,适用于本项目未来任何方向的实验。

- **格式**:`{kind}_{prefix}_{variant}`,小写 + 下划线分隔,尽量简短。
- **kind(类别)**:`exp_` = 正式实验(产出可登记结论);`probe_` = 中间表征/探路(为定参数、探可行性)。两类都进 `runs/` 平铺,靠前缀筛(`ls runs/ | grep exp_`)。中间结果也走入口落 `runs/`,不留 `/tmp`、不堆进计划稿。
- **prefix** 表示一个探索方向,用于把相关实验聚合在一起(可通过 `ls runs/ | grep <prefix>` 或在 `EXPERIMENTS.md` 中筛选)。prefix 由实验者在做实验时自取,无需预先定义或登记;同一探索方向复用同一 prefix,转入新方向时起一个新 prefix。
- **variant** 描述本次实验的具体配置或变体,用于区分同一 prefix 下的不同尝试。
- **核心原则**:主题靠 tag 前缀**软聚合**,不靠文件夹区分。`runs/` 始终平铺,目录结构不随研究主题变化。

## 6. 代码复用与一致性铁律

- 决定实验结果的参数(样本量、数据路径、超参、硬件/系统配置等)**只能来自 config 文件**,禁止在代码里硬编码魔法数字。
- 公共/可复用逻辑必须放入 `src/lib/` 并被复用;当一段逻辑**第二次**被用到时,必须提炼进 lib,禁止复制粘贴或重新实现。
- `src/experiments/{tag}/` 每个实验一个文件夹(按 tag 分类,入口拒绝裸露平铺),内部允许杂乱;`src/lib/` 放稳定复用代码,需保持整洁。
- **命名与注释**:标识符要一眼看懂是什么(如 `reserved_offer` 而非 `item`,`deviation` 而非 `d`),同一概念全项目只用一个名字;同一事物在不同层出现时(如图节点、它背后的函数 / 策略方法、state 键)名字一一对应,如节点 `plan_local_repair` ↔ 策略方法 `plan_local_repair`。注释只写代码本身看不出的东西(为什么这样做、单位、边界情况),言简意赅、直观,任何第一次接触的人都能读懂;不写复述代码的废话注释。
- 每次实验自动记录环境快照(`env_snapshot.txt`),用于事后 diff 排查"环境是否悄悄改变"。快照采什么(命令/库列表)由 `configs/defaults.yaml` 的 `env_snapshot` 段声明,随项目所用工具链维护。

## 7. 实验协作节奏

agent 帮用户做实验时的行为准则。

### 做实验前(防止无效实验)

- 任何实验在运行前,必须先用一两句话说明:**这个实验验证什么假设、预期看到什么、为什么值得做**。等用户认可后再跑。没有清晰假设的实验不要做。

### 节奏(防止信息过载)

- 一次只推进**一个任务**——即一个能独立得出结论的最小单元(一个假设 → 一个可登记的结果)。
- 跑完一个任务、给出结果后,**停下来**等用户消化和决定下一步,不要自作主张连续推进多个实验或多个方向。
- 可以建议下一步,但**只给一个最值得的**,不要罗列一堆选项让用户挑。

### 自主权的度(既不事事确认,也不擅自做主)

- **可自主进行(无需逐一确认)**:跑用户已认可假设的实验、读数据/log、做数据分析、实现用户已同意的改动、落盘登记 push。
- **必须停下等用户**:跑实验前(确认假设)、得出结论后(等用户决策)、要改变研究方向时、遇到意外结果时。
- **原则**:"想清楚做什么"和"决定下一步"是用户的职责;"把已想清楚的事做好"是 agent 的职责。停顿点设在决策关口,不是每个动作上。

### 汇报结论(简洁、不臆测)

- 实验汇报只说三点:① **客观结果**(数字/事实,先不解释);② **对照假设**(验证还是推翻,一句话);③ **一个**建议的下一步。
- 严禁对结果做无数据支撑的猜测性解释。若要推测原因,必须明确标注"这是推测,需 X 实验验证",不得把推测当结论——**观察(数据)与解释(原因)严格分开**。
- 不要重复用户已知的背景,不要在一次汇报里铺开多个方向。
- 汇报只发给用户(对话里),**不要写入 `docs/current_log.md`**——该流水账由用户手写维护,agent 不动其内容(见 §3、§8)。

## 8. 计划稿同步铁律(不允许任何实验游离于计划之外)

实验做到后期常常派生出分支实验或偏离原计划,导致这些实验没有被 `docs/current_experiment_plan.md` 记录。这是禁止的:**每一个实验(含临时起意的分支、探路、变体)都必须在 `current_experiment_plan.md` 里有其位置。**

- **跑实验前**:先回顾 `current_experiment_plan.md`,确认本次要跑的实验在「步骤与进度」里有对应条目。若没有(临时派生的分支/变体),**先把它补进计划**(新增子任务条目,或在现有条目下开分支),再跑。补计划这一步不需额外确认——它是执行动作的一部分。
- **跑完实验后**:立即更新计划——勾掉/标注刚完成的条目,更新「当前状态」;若结果使方向发生偏移,把偏移如实反映进计划(调整后续步骤、在「待办与决策」记下新决策点)。
- **发现偏离时**:一旦意识到实际在做的事已偏离计划所写,**立刻停下先同步计划**(而非跑完再补),必要时提示用户方向是否要正式调整(方向变更属 §7「必须停下等用户」)。
- **底线**:任何时刻 `current_experiment_plan.md` 都应能回答"现在在做什么、做过哪些分支、下一步是什么"。计划稿仍是**覆写式**(§3):它反映当前实验的当前全貌与分支结构,不堆历史试错细节(那些进 EXPERIMENTS.md / current_log.md)。
