# 数学特例：冻结实验设计

> 状态：2026-11-15 冻结提案。适配器、数据与 5090 环境已完成；正式跑之前只需确认第 13 节的三个决策。
> 本文件是 `docs/plan/Motivation-and-Experimental-Design.docx` 的数学面板细化版；不改变论文主框架（AIGC 文本+图像内容生成/编辑，数学沟通是其中一个可内核验证的特例）。

## 0. 一句话

冻结 9B 权重，只放开 token/时间预算，用 4 个 Agent 架构在 MATH-500/AIME/miniF2F/PutnamBench/ProofNet 上检验：SLM 能否在长时程数学任务上持续推进，并保持可验证的正确性。

## 1. 动机与定位

- **问题**：本地小模型被认为只能做短任务。若冻结权重、只增加预算并配 Agent 架构，SLM 在长时程任务上的完成度能到什么程度？
- **为什么数学**：数学是 AIGC 内容生成/编辑的特例，但它是唯一有**内核验证器**（Lean）的 slice：不依赖 VLM judge，评分可复现、可审计；形式化证明的状态维护、错误恢复和长时程推进，正好检验 L2 的核心能力。
- **两级**：
  - **L1 gate**：MATH-500/AIME（非形式，答案匹配）+ miniF2F（短形式化证明）。用于排除低级失败、确认工具/接口可用；结果只作 gate 表，不参与主排名。
  - **L2 主表**：PutnamBench（长形式化证明）+ ProofNet（逐定理形式化）。主结论看 L2；数学面板与 AIGC 内容面板**分开报表**，不混分。
- **不是**：不做 GUI computer use；不把 VLM 用于数学评分；不把旗舰模型/专用 prover 的公开数字当作同条件基线；不在看到结果后调任务/预算/提示。

## 2. 研究问题与假设

- **RQ-M1（预算）**：固定 9B，只增加 E 预算，L1/L2 数学完成度是否单调上升？在哪个预算饱和？
- **RQ-M2（架构）**：同一预算下，Sentry / Recuris / RRSI 相对 Base 是否提高长时程完成度与 E-to-success？
- **RQ-M3（上下文）**：共享 context policy 是部署条件还是方法增益？去掉它是否显著伤害长时程任务？
- **RQ-M4（形式/非形式）**：非形式数学（答案匹配）与形式化（内核）的结论是否一致？形式化是否更能暴露状态维护失败？
- **RQ-M5（接口）**：把“写 Lean 文件”的接口从 heredoc 命令换成统一 `write` action，能解释多少失败？剩余失败中有多少是数学能力而非格式？

假设：
- H1：L1 在 5k→30k E 上有明显提升；L2 在 25k→100k E 上仍有提升，但边际递减。
- H2：Recuris completion gate 降低过早提交；Sentry 的 detector/verifier 降低重复/无效动作；RRSI 的提示候选在 L1 有增益，在 L2 形式化上增益有限。
- H3：去掉 context policy 后，L2 的上下文丢失/重复动作显著上升，E-to-success 变差。
- H4：形式化任务的失败更集中在 Lean 错误/状态丢失，非形式更集中在答案格式/计算；两者不能互相替代。
- H5：统一 `write` action 显著降低 invalid-JSON/格式失败；在控制格式后，方法差异才是数学能力差异。

## 3. 任务集（冻结）

### 3.1 L1 gate（130 题）

| Benchmark | 数量 | 采样 | 评分 |
| --- | ---: | --- | --- |
| MATH-500 | 50 | 按 subject（7 类）× level（1–5）分层；`sha1(seed|task_id)` 排序，分层轮转取满 50 | 答案匹配（`answer.txt`） |
| AIME 2024 | 30 | 全量 | 整数 0–999 精确匹配 |
| miniF2F Test | 50 | 按题目前缀（aime/amc/algebra/imo/numbertheory/mathd）分层，哈希轮转 | Lean 内核，无 `sorry`/`admit`/新公理 |

- L1 主预算：**30k E**（raw cap 100k，max_steps 60，wall 1800s）。
- L1 可靠性：miniF2F Valid 50 题作为 held-out，只在最终可靠性检查中跑，不参与 gate 排名。
- Gate 判据（预注册）：至少一个方法在 MATH-500 ≥20%、AIME ≥1 题、miniF2F ≥3 题；且所有方法 valid grade ≥95%。未过 gate 先修 harness，不进入 L2。

### 3.2 L2 主表（166 题）

| Benchmark | 数量 | 采样 | 评分 |
| --- | ---: | --- | --- |
| PutnamBench | 100 | 按年代（1962–1979/1980–1999/2000–2019/2020–2025）× 题号 a/b 分层，哈希轮转 | Lean 内核；单文件单定理，pass/fail |
| ProofNet | 66 | 全部可用定理（5 个文件；6 个文件因 v4.20 API 被 precheck 排除） | 逐定理：目标定理无 `sorry` 且文件编译；其他定理的 `sorry` 不计 |

- L2 主预算：**100k E**（raw cap 500k，max_steps 200，wall 7200s）。先用 20 Putnam + 20 ProofNet、50k E 做校准；若命中率 <2%，只在 50 题子集上把预算升到 200k，不把 1M 套到全部 166 题。
- Putnam 选中的 100 题在冻结协议生成时用 Lean 预编译一次（带 `sorry`）；2026-11-15 在 5090 上 **100/100 rc=0**，没有剔除；不因模型结果改题。
- ProofNet 已全量 precheck（493/499 OK；miniF2F 488/488；ProofNet 66）。

### 3.3 L2 stress（10 题，10h）

- 10 个 Putnam 题（按年代/难度分层），方法：Base + 表现最好的非 Base 方法。
- 预算：**2M E**、raw cap 2M、wall **36,000s（10h）**、max_steps 2000。用于验证“10+ 小时持续推理”的条件；结果单独报告，不混入 L2 主表。
- 1M cumulative-token 是评测条件之一；stress 记录实际 E/P/G 与 wall，报告是否到达 10h 或 token cap。

### 3.4 采样、污染与排除

- 冻结种子：`20261115`；脚本：`experiments/adapters/freeze_math_protocol.py`，输出显式 task id 列表。
- 污染：MATH-500/AIME/Putnam/miniF2F 都是公开题；9B 的训练截止未知。主表优先 AIME 2024、Putnam 2020–2025；对 20 条模型输出做记忆审计（是否逐字复述题解），报告 caveat，不把“数学 SOTA”作为主张。
- 排除：6 个 ProofNet 文件（Artin/Axler/Dummit-Foote/Herstein/Munkres/Rudin，v4.33 API 不兼容）；Putnam 预编译失败的选中题；miniF2F 全量通过。排除原因与数量写进结果。
- 所有任务/预算/协议在正式跑前 commit 冻结；结果出来后不回溯改题。

## 4. 方法与基线

### 4.1 同条件主表

- **Base**、**Sentry**、**Recuris m0-gate**、**RRSI**（4 个）；**Recuris m0** 作为 completion-gate 消融，不进主表。
- Spine reimpl 单独报告（非官方 Pi/Node 插件），不进主表。
- 同一 9B（Qwen3.5-9B Q4_K_M）、同一 host、同一预算、同一工具权限、同一隐藏评分；方法增益 = 方法+adapter − Base+adapter。

### 4.2 任务专用基线（单独表，非同条件）

- 可跑候选：Leanabell-Prover-V2-7B、OProver-8B、Goedel-Prover-V2-32B（量化）、LeanDojo/ReProver、COPRA。
- 这些方法的模型/训练/搜索预算不同，不能与 9B+Agent 直接同条件比较；只按各自官方设置跑 1 次，报官方 pass@1/pass@k 与成本，作为参考。
- 若 12-01 前权重/代码不可用，则只引用公开结果，不阻塞主表。

### 4.3 旗舰/上界（只引用）

Aleph、Goedel-Architect、HILBERT、AlphaProof、Seed-Prover、DeepSeek-Prover-V2 671B、Kimina 72B：只作上界与相关工作，不跑、不混表。

## 5. Harness v2：统一 write action（冻结）

- **决策（已实现 2026-11-15）**：主实验使用 **Harness v2**，动作 schema 为：
  - `{"command": "..."}`
  - 写文件（多行首选）：一行 JSON header `{"path": "..."}`，随后一个 fenced block 包含文件内容（无需 JSON 转义，可带 `lean` 语言标记）
  - 单行 JSON `{"path": "...", "content": "..."}` 作为 fallback
  - `{"final": "..."}`
- 所有方法（Base/Sentry/Recuris/RRSI/Spine）使用同一 schema；这是**接口扩展**，不改变规划、记忆、恢复、提示策略。host 已支持 `Action("write")`；各方法的 parser/prompt 已统一，`tests/test_write_action.py` 4 项在本机和 5090 均通过。
- **每次调用 `max_tokens_per_step=4096`**：v2b smoke 里 512 会在 Lean 文件写到一半时截断（completion_tokens=512，fenced block 没有闭合），所以 512 只保留给早期 answer-only pilot；正式写入协议全部 4096。
- 理由：预实验（command-only）里 9B 多次生成未转义的 heredoc JSON，4 步只有 1–3 个有效 action，解答文件未变；v2 的纯 JSON `content` 仍会被多行内容截断/转义失败，fenced block 是主路径。
- v2 smoke（4 题）：512-token 的 v2b 把 fenced block 截断（无闭合 fence，没有 write action）；4096-token 的 v2c 在 Putnam a2 / ProofNet 上真实触发 write action。4 题仍 0/1，说明接口已通，证明内容质量是下一层问题。
- **消融**：同一 30 题子集跑 command-only（v1），报告 invalid-JSON/格式失败率与 pass 差异；v1 数据只作诊断，不进主表。
- host 侧：`LocalContentHost` 已实现 write；Lean host 通过 `lake env lean` 提供编译反馈（5090 上 server 与 Lean 共存，agent 可在 episode 内编译）。

## 6. 预算与 E

- 5090 实测（153 个 timing 样本）：prefill median **7053 t/s**，decode median **197 t/s**，**ρ_5090 = 36**（median；mean 28，报告两者）。E = P/36 + G。
- 3050 的 ρ=65 只用于本机 smoke；正式数字全部按 5090 ρ=36 重算并记录原始 P/G/E。
- L1：E_question = **30k E**（raw 100k）；L2 主：**100k E**（raw 500k）；L2 stress：**2M E**（raw 2M，wall 10h）。
- 每次调用 `max_tokens_per_step=4096`（见第 5 节；512 会截断多行 Lean 文件）。
- Token 口径：一次任务所有模型调用的 prompt + completion；缓存 tokens 单列；工具输出进入 prompt 的按实际计；Lean/编译时间不计入 E，但记 wall。
- 终止：submitted / max_steps / timeout_equivalent / timeout_tokens / timeout_wall / loop / crash / model_error / context_overflow；E 与 raw 同时记录。

## 7. 指标

| 指标 | 定义 | 用途 |
| --- | --- | --- |
| **pass@1（主）** | L1：答案匹配；L2：Lean 内核验证的完整证明（无 `sorry`/`admit`/新公理） | 主表 |
| pass@E | 在 E_budget 内达到 pass@1 | gate/主表 |
| E-to-success | 第一次成功时的 E；失败记 ≥E_budget | 主表 |
| E_used / E_budget | 实际 E 使用率；raw P/G 附录 | 成本 |
| 可靠性 | 30 题子集 3 次独立运行的完成率均值/范围 | 第二张表 |
| 过程失败 | premature submit / loop / context loss / invalid JSON / Lean 错误 / 预算耗尽 | 诊断表 |
| ProofNet 诊断 | 目标定理 pass；同文件其他 `sorry` 数；文件编译 | 诊断 |
| miniF2F 诊断 | 文件 pass；编译错误类型；剩余 `sorry` | 诊断 |

- **不声称 goal-level partial credit**：当前 adapter 只暴露 Lean 编译输出，不提供 goal state；Putnam 是单定理 pass/fail，ProofNet 是逐定理 pass/fail。部分进度只报告“剩余 `sorry` 数/编译错误类别”，不换算成官方部分分。
- 主表只放 pass@1 与成本；可靠性/自主性/失败表放第二张表，不参与主排名。
- 自主性：全部无人介入；记录零介入完成率（按构造为 100%）与提前终止原因。

## 8. 运行次数与统计

- L1 gate：每方法 1 次全量（130 题）；30 题可靠性子集 3 次（Base/Recuris-gate/RRSI）。
- L2 主表：每方法 1 次全量（166 题）；30 题可靠性子集（10 Putnam + 10 ProofNet + 10 L1）3 次。
- 总运行量：约 130×4 + 166×4 + 30×3×3 + stress 10×2 ≈ 1,400 次；按 L1 30k E、L2 100k E 估算，5090 上约 3–6 天 GPU 时间（不含 Lean 编译），在 12 月窗口内可行。
- 统计：
  - 任务级配对比较；bootstrap 10k 次重采样，报 95% CI；
  - 方法两两 McNemar（pass/fail）；Holm–Bonferroni 校正；
  - 混合效应 logistic：`success ~ method * benchmark + level + (1|task)`，报 odds ratio；
  - 3 次可靠性子集报均值±范围/标准差；
  - 预注册 gate 判据与主表指标；不做事后挑题/挑预算。

## 9. 消融

| 消融 | 子集 | 对照 |
| --- | --- | --- |
| 接口 v1（command-only） vs v2（write） | 30 题 | 格式失败率、pass、E-to-success |
| context policy on/off | 30 题 | 重复动作、上下文丢失、E-to-success |
| submit guard off/on（host 级） | 30 题 | 过早提交率、最终 pass |
| Recuris m0 vs m0-gate | 30 题 | gate 触发、过早提交、pass |
| 预算 5k/15k/30k E（L1）；25k/50k/100k E（L2） | 50 题 / 40 题 | pass@E、E-to-success 饱和点 |
| episode 内 Lean 反馈 on/off | 30 题 | 编译错误恢复、pass、E-to-success |

## 10. 流程与命令

1. **冻结协议**：`python experiments/adapters/freeze_math_protocol.py --seed 20261115` → `protocols/math-l1-informal.json`、`math-l1-formal.json`、`math-l1-valid.json`、`math-l2-calibration.json`、`math-l2.json`、`math-l2-stress.json`；scaling 为 `math-l1-scale-{informal,formal}-{5k,15k,30k}.json`、`math-l2-scale-{25k,50k,100k}.json`；reliability 为 `math-reliability-{informal,formal}.json`。commit。
2. **Harness v2（已实现）**：统一 fenced write（`{"path": ...}` + fenced content）到所有方法 parser/prompt；`max_tokens_per_step=4096`；`tests/test_write_action.py` 4 项通过；4 题 v2c smoke 已验证 write action，正式跑前补 10 题 smoke。
3. **5090 环境**：`bash experiments/adapters/start_llama_text.sh`；`export PUTNAM_LEAN_BIN=$PWD/.cache/tools/lean-wrapper/bin/lake`。
4. **L1 gate**：`repro_matrix.py protocols/math-l1-informal.json`（MATH/AIME）+ `repro_math_batch.py protocols/math-l1-formal.json --phase all`（miniF2F）。
5. **L2 校准**：`repro_math_batch.py protocols/math-l2-calibration.json --phase all`（20 Putnam + 20 ProofNet、50k E、Base/Recuris-gate）；确定主预算。
6. **L2 主表**：`repro_math_batch.py protocols/math-l2.json --phase all`（5090 上不需要 `--release-model`）。
7. **Stress**：`repro_math_batch.py protocols/math-l2-stress.json --phase all`（10h wall）。
8. **消融/可靠性/分析**：按第 8–9 节；生成 `results/` summary、图表、失败分类。
9. **归档**：协议 commit、模型/llama.cpp/Lean/Mathlib/commit、原始轨迹 `.cache`、summary 入库。

## 11. 威胁与边界

- **污染**：公开题可能被 9B 见过；优先新题 + 记忆审计；主张是长时程能力，不是数学 SOTA。
- **单模型/量化**：只报 Qwen3.5-9B Q4_K_M；不外推到其他规模。
- **接口**：v2 是本文的 harness 选择；v1 消融解释格式失败；不把 v2 当作方法增益。
- **Lean**：固定 4.33.1/Mathlib v4.33.1；ProofNet 6 文件排除；miniF2F 488/488；Putnam 选中题预编译；无 goal-level partial credit。
- **内存/硬件**：正式数学在 5090（62GB，server+Lean 共存）；本机 16GB 只做 smoke；5090 的 ρ=36 与 3050 的 65 不混用。
- **评分**：Lean 内核无 VLM；AIGC 内容面板另有 VLM judge 威胁，不与数学混表。
- **统计**：任务子集 frozen；3 次可靠性只覆盖子集；多重比较校正；不把 1 次全量结果过度解释为方法结论。

## 12. 产出与时间表

- 2026-11-15~11-18：冻结本设计/协议；实现 Harness v2；write-action 测试；10 题 smoke。
- 11-19~11-25：L1 gate（130 题）+ 预算 scaling（50 题）。
- 11-26~12-10：L2 校准（20+20）；L2 主表（100 Putnam + 66 ProofNet）。
- 12-11~12-20：L2 stress（10h，10 题）+ 30 题可靠性 3 seeds + 消融。
- 12-21~01-05：buffer/重跑/环境失败修复。
- 01-06~01-15：分析、图表、失败分类。
- 01-16~01-25：写作、内审、ICML 2027-01 投稿。

## 13. 需要确认的三个决策（当前按推荐值冻结）

1. **接口**：主实验用 Harness v2（fenced write + 4096 per-step），v1 只作消融。已按推荐实现（2026-11-15）。
2. **任务专用基线**：只跑权重/代码可用的 1–2 个（优先 Leanabell-Prover-V2-7B / OProver-8B），其余引用。推荐：是；不阻塞主表。
3. **L2 主预算**：100k E 为默认；校准后若 <2% 命中，只在 50 题子集升到 200k E，不把 1M 套到全部 166 题。推荐：是。

如果以上三项不改，按本文件冻结并开始实现 Harness v2 与协议生成；如果要改，只改这三项，其余任务集/指标/统计保持不变。
