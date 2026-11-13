# Adapter Experiment Report

四个 benchmark、八个 Agent 架构的适配器契约层与真实接入

> 当前里程碑：**适配器能正常执行**。要求 loader → host → agent → grader 链路跑通；复现 benchmark 自身的测试/成绩不在本阶段要求内。
> 真实 smoke 的 0/1、0/3 是执行与预算描述，不作方法结论。

## 1 本轮范围与结论

在原有“统一 host 契约 + mock benchmark”之上，本轮完成了四件事：

1. **真实 benchmark 接入**：Terminal-Bench 2.1（89 题）和 LHTB 2.0（46 道原题 + 31 道新题）共用一套 Harbor 格式 loader、Docker host 和官方 `tests/test.sh` 评分。
2. **真实官方评分链路**：评分阶段才把官方 `tests/` 复制进容器，运行 `test.sh`，读取 `/logs/verifier/reward.txt`；reward 缺失时记 invalid，不伪造通过。
3. **CORE-Bench 接入**：公开 train split 45 题，支持 easy/medium/hard 提示模板；easy 级别已用 Docker host + 官方 `report.json` 容差评分跑通。
4. **四个原生 loop**：Base、Sentry、Recuris、RRSI 接到公共契约；Spine、openJiuwen、LHH、Opera 仍只有契约适配器。

本轮**没有**跑 9B 模型，因此没有方法完成率、token 成本或机制收益结论。CORE-Bench 使用公开 train split，留出 test split 仍为 GPG 加密；MLE-bench 数据不在本机，报告为缺失数据集，不用 mock 冒充。

## 2 新增实现

| 文件 | 作用 |
| --- | --- |
| `experiments/adapters/benchmarks/harbor.py` | 通用 Harbor loader、Docker host、`OfficialTestVerifier` |
| `experiments/adapters/benchmarks/tb.py` | Terminal-Bench 2.1 adapter |
| `experiments/adapters/benchmarks/lhtb.py` | LHTB 2.0 adapter（`tasks` / `tasks-2.0`） |
| `experiments/adapters/benchmarks/core.py` | CORE-Bench 真实 adapter（train split，easy/medium/hard） |
| `experiments/adapters/benchmarks/core_grading.py` | 官方 `eval_result_json` 的无 numpy/scipy 等价实现 |
| `experiments/adapters/benchmarks/mle.py` | MLE-bench loader/host/medal adapter（low split，Kaggle 数据条件式） |
| `experiments/adapters/benchmarks/mle_grading.py` | 官方 medal 阈值 + 合成 accuracy 指标 |
| `experiments/adapters/tests/test_core.py` | CORE-Bench loader、容差评分、Docker host 测试 |
| `experiments/adapters/tests/test_mle.py` | MLE-bench loader、medal 阈值、合成提交评分测试 |
| `experiments/adapters/agents/sentry.py` | 官方 `SentryRunner` 原生 loop |
| `experiments/adapters/agents/recuris.py` | Recuris Skill Memory + completion gate |
| `experiments/adapters/agents/rrsi.py` | RRSI prompt-only candidate（Evaluate 半） |
| `experiments/adapters/agents/spine.py` | Spine 子任务树的 Python 重实现（非官方 Pi/Node 插件） |
| `experiments/adapters/hosts/docker.py` | 容器资源参数、`copy_in`、`exec`、`read_container_file` |
| `experiments/adapters/tests/test_harbor.py` | 真实 loader + 官方评分测试 |
| `experiments/adapters/tests/test_native_loops.py` | 三个原生 loop 的离线 smoke |

## 3 真实 benchmark 接入

两个数据集都采用 Harbor 布局：`task.toml`、`instruction.md`、`environment/`、`tests/`。

| Benchmark | 上游 @ commit | 许可证 | 题数 | 官方测试可用 |
| --- | --- | --- | ---: | ---: |
| Terminal-Bench 2.1 | `harbor-framework/terminal-bench-2-1` @ `12b75656` | Apache-2.0 | 89 | 89 |
| LHTB 2.0 原题 | `zli12321/LHTB` @ `e037434a` | Apache-2.0 | 46 | 46 |
| LHTB 2.0 新题 | 同上，`tasks-2.0` | Apache-2.0 | 31 | 31 |
| CORE-Bench | `siegelz/core-bench` @ `e32a2980` | MIT | 45（train） | 45 |
| MLE-bench | `openai/mle-bench` @ `507f92e1` | MIT | 22（low split） | 条件式 |

LHTB `tasks-2.0` 的 `tests/private` 实际在公开快照中；适配器只在方法停止后复制 `tests/`，所以方法运行期间看不到私有 judge。此前报告写“官方 verifier 未接”是指未接入，不是文件不存在。

CORE-Bench 的官方 test split 是 GPG 加密的，本轮使用公开的 `core_train.json`（45 题）做开发验证；capsule 代码按需从 `corebench.cs.princeton.edu` 下载，不把 13 GB 数据放进仓库。

MLE-bench 加载 22 个 low-split competition 和官方描述；真实 Kaggle 数据需要凭据和 `mlebench prepare`，官方 metric 需要 `mlebench`/pandas。本轮用合成 competition + 无依赖 accuracy 指标验证 Docker host 和 medal 阈值路径，没有真实 Kaggle 分数。

## 4 官方评分链路

`OfficialTestVerifier` 的流程：

1. 方法停止后先 `rm -rf /tests /logs/verifier`，再 `mkdir -p /tests /logs/verifier`；方法预写的 reward 不会保留；
2. 把任务的官方 `tests/` 暂存并归一化为 LF 行尾，再 `docker cp` 到 `/tests`；
3. 在任务容器内运行 `bash /tests/test.sh`（没有 bash 的最小镜像回退到 `sh`）；
4. 读 `/logs/verifier/reward.txt`；有 CTRF 报告时同时记录 `passed/total`；
5. reward ≥ 1.0 记通过，reward 缺失记 `valid=false`。

已验证以下路径：

| 验证 | 结果 |
| --- | --- |
| 合成 Harbor 任务（alpine，写对/写错） | 写对：valid=true，passed=true；写错：valid=true，passed=false |
| TB 2.1 `regex-log` oracle | solve exit=0；官方测试 `1 passed`；valid=true，passed=true，checks=1/1，reward=1.0，80.6 s |
| LHTB 2.0 `2048` 空提交 | 官方测试 `1 failed`；valid=true，passed=false，checks=0/1，reward=0.0；验证失败路径 |
| CORE-Bench 合成 easy capsule | 写对 `report.json`：valid=true，passed=true，checks=1/1；缺失：valid=true，passed=false |
| CORE-Bench 真实 easy capsule（`capsule-1854976`） | 写入 oracle `report.json`；valid=true，passed=true，checks=3/3 |
| MLE-bench 合成 competition | 完美提交：score=1.0、gold medal、passed=true；错误提交：score=0.0、无 medal、passed=false |

`regex-log` 使用镜像 `alexgshaw/regex-log:20251031`，`2048` 使用 `zli12321/lhtb-2048:20260615`；完整日志在 `.cache/adapters/oracle-regex-log.log` 与 `.cache/adapters/lhtb-2048-smoke.log`（不入库）。

CORE-Bench 的评分是 `report.json` 对三道 gold run 的比较：数值答案要求落在 95% t 预测区间内，字符串按大小写不敏感比较，列表要求完全相等；一题全部问题答对才算通过。`benchmarks/core_grading.py` 是官方 `benchmark/evaluations.py::eval_result_json` 的无 numpy/scipy 等价实现（t 分位数表覆盖 df ≤ 30）。

MLE-bench 的评分按官方 Kaggle leaderboard 阈值：读取 `score` 列，按队伍数计算 gold/silver/bronze/median 阈值，提交分数达到任一奖牌线即 `passed=true`。`benchmarks/mle_grading.py` 复现了 `mlebench.grade_helpers.Grader.rank_score` 的阈值逻辑；真实 competition 的 metric 仍由官方 `mlebench` 提供。

**评分口径差异**：Harbor 对 `environment_mode="shared"` 的任务使用独立 verifier 容器；本轮在同一任务容器内复制 `tests/` 后运行，`/app` 文件系统与官方一致，但不构造独立 verifier 镜像。这是单容器近似。其次，对 `allow_internet=false` 的任务，评分阶段沿用无网络容器；如果官方 `test.sh` 需要联网安装依赖，会记环境失败。Harbor 的独立 verifier 容器路径未复现。

## 5 原生方法 loop

| 方法 | 原生 loop | 本轮实际执行 | 未执行 |
| --- | --- | --- | --- |
| Base | `BaseReactAgent` | 终端动作 + submit | — |
| Sentry | 官方 `SentryRunner` | detector 被调用；动作进入 Sentry 窗口；finalize 后 drain 事件 | verifier/updater 的完整软恢复 H=10 路径 |
| Recuris | `TerminalSkillBridge` | m0（固定记忆）和 m0-gate（`check_completion`）都能跑完并评分 | tta meta-agent patch loop |
| RRSI | prompt-only candidate | 候选 system prompt 加载、SHA-256 记录、官方评分 | proposer/analyst/critic 搜索环（需 Vertex） |
| Spine（重实现） | Python 子任务树 | `spine_open/close/next` 与完成分支折叠为 memory；4 项离线测试 | 官方 Pi/Node 插件桥接；`spine_spawn` 执行 |
| Spine（官方） | — | 契约适配器 | Pi + `spine_*` 原生 loop |
| openJiuwen / LHH / Opera | — | 契约适配器 | 原生 loop |

三个离线 smoke 都在 `ManifestBenchmarkAdapter` + `LocalHost` 上完成，每个方法跑 2 个 manifest 任务（写 `answer.txt`、写 `result.txt`）：方法只通过 `Host` 动作，评分由 benchmark 侧独立执行，`grade_calls_during_run=0`。

## 6 测试结果

命令：

```bash
.cache/venv/Scripts/python.exe -m unittest discover \
  -s experiments/adapters/tests -t experiments/adapters -v
```

结果：**43 项测试全部通过**（`Ran 43 tests, OK`）。其中新增 8 项适配器测试（下表）、10 项 CORE-Bench 测试、4 项 Spine 重实现测试和 7 项 MLE-bench 测试。

| 测试 | 验证内容 |
| --- | --- |
| `test_tb21_loads_official_tasks` | TB 2.1 加载 89 题，89 题官方测试可用 |
| `test_lhtb_public_and_private_task_sets` | LHTB 46 + 31 题，官方测试均可用 |
| `test_official_reward_is_read_from_test_sh` | 官方 `test.sh` 的通过/失败两条路径 |
| `test_planted_reward_is_removed_before_grading` | 方法预写 reward 会被评分前清除 |
| `test_recuris_m0_runs_and_grades` | Recuris m0 跑完并评分 |
| `test_recuris_completion_gate_runs` | m0-gate 的 bounce 上限与评分 |
| `test_sentry_detector_runs_and_grades` | Sentry detector 被调用并评分 |
| `test_rrsi_candidate_prompt_runs_and_grades` | RRSI 候选 prompt 加载并评分 |

CORE-Bench 新增 10 项：

| 测试 | 验证内容 |
| --- | --- |
| `test_train_split_loads` | 加载 45 道 train 题；gold 结果不在方法可见的 `TaskSpec.metadata` 中 |
| `test_numeric_prediction_interval` | 数值落在 95% 预测区间内才算对 |
| `test_numeric_outside_interval_fails` | 数值超出区间判错 |
| `test_string_and_list` | 字符串大小写不敏感、列表精确比较 |
| `test_all_correct_passes` | 全部问题正确才通过 |
| `test_missing_answer_does_not_pass` | 缺答案不通过 |
| `test_report_round_trip` | Docker host + 合成 capsule + `report.json` 通过 |
| `test_missing_report_is_a_valid_failure` | 缺 `report.json` 记 valid=true/passed=false |
| `test_medium_environment_keeps_reproducing_files` | medium 保留 `REPRODUCING.md`/`environment`/`code/run.sh`，清空 `results` |
| `test_hard_environment_removes_hints_and_results` | hard 删除提示文件并清空 `results` |

Spine 重实现新增 4 项（明确标注为非官方插件）：

| 测试 | 验证内容 |
| --- | --- |
| `test_open_command_close_final` | `spine_open` → terminal → `spine_close` → final；关闭分支的 memory 进入树 |
| `test_next_closes_and_opens_sibling` | `spine_next` 关闭当前分支并进入兄弟分支 |
| `test_root_cannot_close` | root 不能 close，失败后仍可继续 |
| `test_spawn_is_recognized_but_not_executed` | `spine_spawn` 被识别和计数，但本重实现不执行并发子 agent |

MLE-bench 新增 7 项：

| 测试 | 验证内容 |
| --- | --- |
| `test_thresholds_and_medals` | gold/silver/bronze/median 阈值与 above_median |
| `test_lower_is_better` | lower-is-better 排行榜方向 |
| `test_leaderboard_csv` | 读取 leaderboard `score` 列 |
| `test_low_split_loads` | 加载 22 个 low-split competition |
| `test_perfect_submission_earns_medal` | Docker host + 合成提交 + medal |
| `test_wrong_submission_has_no_medal` | 错误提交无 medal |
| `test_missing_submission_is_a_valid_failure` | 缺 submission 记 valid=true/passed=false |

原有 14 项契约/公平性/LocalHost/DockerHost 测试全部保留并通过。完整输出在 `.cache/adapters/test-output.txt`（不入库）。

### 6.1 真实 9B smoke（2026-11-13）

条件：Qwen3.5-9B Q4_K_M，llama.cpp Vulkan，`-ngl 26`，16384 ctx，temperature 0.2，`--reasoning off`；每步 `max_tokens=512`，最多 6 步。这是接线 smoke，不是正式预算。

| 方法 | Benchmark | 任务 | Agent 秒 | tokens | 动作 | 官方评分 | 观察 |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Base | TB 2.1 | `regex-log` | 60.4 | 4524 | 6 | valid=true, passed=false, 0/1 | 5 次重复写同一个错误正则，随后提交 |
| Base | LHTB 2.0 | `2048` | 15.0 | 12568 | 6 | valid=true, passed=false, 0/1 | 5 步 move；band 0、最大 tile 8、dense reward 0.0908 |
| Sentry | LHTB 2.0 | `2048` | 203.5 | 33639 | 6 | valid=true, passed=false, 0/1 | 5 步 move；band 0；detector 触发 6 次 |
| Recuris m0 | LHTB 2.0 | `2048` | 17.9 | 13488 | 6 | valid=true, passed=false, 0/1 | 5 步 move；band 0 |
| RRSI | LHTB 2.0 | `2048` | 14.2 | 13024 | 6 | valid=true, passed=false, 0/1 | 5 步 move；band 0 |
| Base | CORE easy | `capsule-1854976` | 20.2 | 4365 | 5 | valid=true, passed=false, 0/3 | 读了 `results/output`，但直接 submit，未写 `report.json` |
| Base + submit guard | CORE easy | `capsule-1854976` | 33.4 | 9909 | 8 | valid=true, passed=true, 3/3 | 首次 submit 被拒（缺 `report.json`），随后补写正确 report |
| Sentry | CORE easy | `capsule-1854976` | 158.5 | 21223 | 6 | valid=true, passed=true, 3/3 | detector 触发 6 次；读 output 后写入正确 `report.json` |
| Recuris m0 | CORE easy | `capsule-1854976` | 20.2 | 4745 | 5 | valid=true, passed=false, 0/3 | 读了 output，直接 submit，未写 `report.json`；completion gate 关闭 |
| Recuris m0 + submit guard | CORE easy | `capsule-1854976` | 35.6 | 10413 | 8 | valid=true, passed=true, 3/3 | 首次 submit 被拒后补写 report，再次 submit 通过 |
| Recuris m0-gate | CORE easy | `capsule-1854976` | 19.2 | 4745 | 5 | valid=true, passed=false, 0/3 | 与 m0 相同；completion gate 未触发 bounce |
| Recuris m0-gate + submit guard | CORE easy | `capsule-1854976` | 44.7 | 12242 | 7 | valid=true, passed=true, 3/3 | 首次 submit 被拒后补写 report |
| RRSI | CORE easy | `capsule-1854976` | 24.5 | 7171 | 6 | valid=true, passed=true, 3/3 | 读 output 后写入正确 `report.json` |

TB `regex-log` 第一次尝试的官方评分阶段卡在 `apt-get update`，按 D-apt 记为环境失败；上表是重跑后官方测试完整执行的 valid 评分。CORE 批次已完成：Sentry 和 RRSI 在 `capsule-1854976` 上 3/3，Base、Recuris m0、Recuris m0-gate 都是 0/3（读了 `results/output` 但未写 `report.json`）。LHTB `2048` 的评分是 dense reward：Base 5 步后 band 0、最大 tile 8、reward 0.0908，低于 band≥1，因此 valid 但 passed=false。LHTB `2048` 的 Base/Sentry/Recuris/RRSI 四个方法都停在 band 0、0/1；6 步预算远不足以到 band 1（64 tile），不能据此比较方法。

**读法**：这里证明的是“真实 9B → 公共 Host → 官方评分”链路可执行；6 步/512 token 远低于正式预算，失败不能当方法上限或收益结论。Base 的重复写和“读了结果但不写 report”是模型行为信号，不是适配器 bug。

**提交门**：CORE/MLE host 在 `submit` 时检查任务要求的产物（`report.json` / `submission.csv`）；缺失时返回普通环境错误，agent 继续。它不暴露 hidden tests 或答案，且对所有方法一致。Base、Recuris m0、Recuris m0-gate 的 0/3 → 3/3 对照说明这是 host-level 提交校验 + agent 继续逻辑的作用，不是模型突然变强；Sentry/RRSI 本来就会写 report，guard 未改变它们的结果。

## 7 就绪度

`adapter-readiness.json` 仍为 4 benchmark × 8 method = 32 行。两层含义：

- **contract-ready 32/32**：动作/观察映射、预算、hidden test 隔离、工作流不变；
- **real-ready 0/32**：本轮没有配置 model endpoint（离线），所以没有任何组合达到真实端到端。

按缺口拆开：

| Benchmark | 真实数据/host/官方评分 | 缺口 |
| --- | --- | --- |
| TB 2.1 | 已接（89 题） | Base/Sentry/Recuris/RRSI 只差 model endpoint；Spine/openJiuwen/LHH/Opera 还差原生 loop |
| LHTB 2.0 | 已接（46 + 31 题） | 同上 |
| CORE-Bench | 已接（train 45 题；easy 真实 capsule，medium/hard 合成环境） | test split 加密；真实 medium/hard 复现未跑；Base/Sentry/Recuris/RRSI 只差 model endpoint |
| MLE-bench | loader/host/medal 已接（low 22 题） | Kaggle 数据/凭据缺失；官方 metric 需 `mlebench`/pandas，未跑真实分数 |

所以现在可以说“TB 2.1、LHTB 2.0 和 CORE-Bench train split 的执行+官方评分链路已接；MLE-bench 的 loader/host/medal 结构已接，真实 Kaggle 分数未跑”，不能说“所有方法 × 四个 benchmark 都能正常跑”。

## 8 与上一版报告的差异

| 项 | 上一版 | 本轮 |
| --- | --- | --- |
| 真实 benchmark 数据 | 0/4 | 3/4（TB 2.1、LHTB 2.0、CORE-Bench train） |
| 真实 host | 0/4 | 3/4，另有 MLE-bench host 路径在合成数据下验证 |
| 官方评分 | 0/4 | 3/4，且 TB 2.1 真实 oracle 通过、LHTB 2048 真实失败路径正确、CORE-Bench 真实 capsule 通过；MLE-bench 只有合成 metric |
| 原生方法 loop | 0/8 | 4/8（Base、Sentry、Recuris、RRSI）；另有 Spine 重实现，不计入官方 8 方法 |
| 测试数 | 14 | 43 |
| 真实 9B smoke | 未跑 | TB Base 0/1；LHTB 四方法 0/1（band 0）；CORE Sentry/RRSI 3/3；Base/Recuris 0/3 → 3/3（加提交门） |
| 方法分数 | 无 | 仍无正式预算/收益结论 |

## 9 边界与未做

- 真实 9B smoke 是 6 步 × 512 token 的接线 smoke，不是正式预算；CORE 只有 1 道 easy 任务，不能当完成率或方法收益结论。
- TB `regex-log` 第一次官方评分卡在 `apt-get update`，按 D-apt 环境失败处理；重跑后拿到 valid 0/1。
- CORE 上 Sentry/RRSI 3/3；Base/Recuris 在未加提交门时 0/3，加提交门后 3/3。这是 host-level 提交校验的作用，必须作为不同条件分别报告，不能把 0/3 → 3/3 当模型收益。
- LHTB `2048` 是长程游戏；6 步只能到 band 0，四个方法都是 0/1。这是预算描述，不是方法差异。
- 提交门是 benchmark-side 的通用产物校验（CORE `report.json`、MLE `submission.csv`），对所有方法一致；它改变了 host 的反馈，因此有/无 guard 的结果不能直接合并。Recuris m0-gate 在没有 guard 时没有触发 bounce。
- Sentry 在 CORE 上 detector 触发 6 次并 3/3；verifier/updater 的 H=10 软恢复仍未触发。
- Recuris 只跑 m0/m0-gate，没有 tta meta-agent patch loop；seed 记忆来自 TB2.1，不是 TB8 演化产物。
- RRSI 只跑 Evaluate 半，搜索环需要 Anthropic Vertex。
- Spine 的官方原生 loop 是 Pi/Node 插件，尚未桥接到 Python 公共契约；`agents/spine.py` 是明确标注的 Python 重实现，只验证 `spine_open/close/next` 协议和 memory 折叠，`spine_spawn` 未执行，上下文折叠是简化版，不能当官方插件成绩。
- openJiuwen、LongHorizon-Harness、Opera 的上游没有接入。
- CORE-Bench 本轮只用公开 train split（45 题），不是留出 test split；test split 需要 GPG 解密，未使用。
- CORE-Bench 真实 capsule 只跑 easy 级别（读 `results/`，不执行代码）；medium/hard 的环境准备（保留/删除哪些文件、清空 `results`）和 Docker host（`--privileged`）已用合成 capsule 验证，但没有真实 medium/hard 复现成绩。
- MLE-bench 真实 Kaggle 数据/凭据不在本机；loader/host/medal 用合成 competition 验证，官方 metric 需要 `mlebench`/pandas，未跑真实分数，不能当 MLE-bench 成绩。
- 官方评分是单容器近似；Harbor 的独立 verifier 容器路径未复现。
- 真实 benchmark 的正式跑还需要冻结 4 个 benchmark 的共同 token 预算、模型服务和 3 次独立运行。

## 10 证据入口

- 代码：`experiments/adapters/`
- 契约：`experiments/adapters/contract/types.py`
- 公平性：`experiments/adapters/contract/fairness.py`
- CORE-Bench loader：`experiments/adapters/benchmarks/core.py`
- CORE-Bench 官方评分等价实现：`experiments/adapters/benchmarks/core_grading.py`
- CORE-Bench 测试：`experiments/adapters/tests/test_core.py`
- Spine 重实现：`experiments/adapters/agents/spine.py`
- Spine 重实现测试：`experiments/adapters/tests/test_spine.py`
- MLE-bench loader/host/medal：`experiments/adapters/benchmarks/mle.py`
- MLE-bench medal 阈值：`experiments/adapters/benchmarks/mle_grading.py`
- MLE-bench 测试：`experiments/adapters/tests/test_mle.py`
- 9B 真实 smoke 汇总：`experiments/adapters/results/real-smoke-9b.json`
- 9B 逐次原始记录：`.cache/adapters/real-smoke/*.json`（本机，不入库）
- 模型启动记录：`.cache/server/launch-smoke.json`（本机，不入库）
- 契约矩阵：`experiments/adapters/results/adapter-matrix.json`（32 行）
- 就绪度：`experiments/adapters/results/adapter-readiness.json`（32 行）
- 数据集清单：`experiments/adapters/results/adapter-datasets.json`
- 真实接入汇总：`experiments/adapters/results/real-integration.json`
- 测试输出：`.cache/adapters/test-output.txt`（本机）
- TB 2.1 oracle 日志：`.cache/adapters/oracle-regex-log.log`（本机）
- LHTB 2048 空提交日志：`.cache/adapters/lhtb-2048-smoke.log`（本机）
- 设计文档：`docs/plan/Motivation-and-Experimental-Design.docx` 的 Appendix: Adapter Design
