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
| `experiments/adapters/benchmarks/content.py` | PutnamBench / MATH-500 / AIME 与文本+图像内容 adapter |
| `experiments/adapters/benchmarks/formal_math.py` | miniF2F（文件级）与 ProofNet（逐定理） |
| `experiments/adapters/prepare_formal_math.py` | 复制 miniF2F/ProofNet 到统一 v4.33.1 工程 + 可选 precheck |
| `experiments/adapters/repro_math_batch.py` | 两阶段 collect/grade runner |
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

结果：**107 项测试通过**（`Ran 107 tests, OK (skipped=2)`；两个跳过项都是需先停 model server 的 Lean 编译集成测试：Putnam 平凡定理、miniF2F+ProofNet 平凡定理）。覆盖此前的新增 8 项适配器测试（下表）、12 项 CORE-Bench、4 项 Spine 重实现、10 项 MLE-bench、2 项提交门、4 项非干扰审计、2 项非 UTF-8 输出回归、3 项模型请求错误、3 项轨迹记录，以及本轮内容/数学适配器新增的 MATH-500/AIME fixture、答案匹配、Putnam cheat 检测、miniF2F/ProofNet loader、逐定理解析与 precheck 过滤等测试。

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

CORE-Bench 新增 12 项：

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
| `test_submit_guard_is_off_by_default` | 默认 `submit_guard=None`，submit 直接接受 |
| `test_submit_guard_requires_report` | opt-in guard 拒绝缺 `report.json` 的 submit，补写后通过 |

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
| `test_submit_guard_is_off_by_default` | 默认 `submit_guard=None`，submit 直接接受 |
| `test_submit_guard_requires_submission` | opt-in guard 拒绝缺 `submission.csv` 的 submit，补写后通过 |

提交门继续逻辑 + 非干扰审计 + 编码回归新增 8 项：

| 测试 | 验证内容 |
| --- | --- |
| `test_base_react_continues_after_rejection` | Base 在 submit 被拒后继续并补写产物 |
| `test_recuris_continues_after_rejection` | Recuris 在 submit 被拒后继续并补写产物 |
| `test_core_metadata_has_no_gold_and_guard_is_off` | CORE metadata 无 gold/checks，guard 默认关闭 |
| `test_mle_metadata_has_no_answers_and_guard_is_off` | MLE metadata 无 answers/gold，guard 默认关闭 |
| `test_host_does_not_expose_checks` | Host 不暴露 checks/answers/gold/hidden_tests |
| `test_adapter_changes_are_schema_mappings_only` | adapter_changes 只描述 schema 映射，不含 prompt/strategy/plan |
| `test_docker_host_replaces_non_utf8_output` | Docker 输出非 UTF-8 字节不崩溃 |
| `test_local_host_replaces_non_utf8_output` | Local 输出非 UTF-8 字节不崩溃 |

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

### 6.2 非干扰保证

适配器层的目标是**不改变方法**，只提供环境与 schema 映射。当前由测试和静态检查保证：

| 保证 | 证据 |
| --- | --- |
| 只映射 action/observation/submit，不增删改序 | `workflow_preserved`、`test_workflow_invariance` |
| 所有方法同一模型、token 预算、工具权限、评分 | `FairnessLedger`、`test_same_budget_and_config` |
| `TaskSpec.metadata` 不含 checks/answers/gold/tests | `test_non_interference` |
| `Host` 不暴露 checks/answers/gold/hidden_tests | `test_non_interference`、`test_no_hidden_test_access` |
| 提交门默认关闭，严格提交需显式 opt-in | `test_submit_guard_is_off_by_default`（CORE/MLE） |
| Spine 重实现与官方插件分开 | `SpineReimplementationAdapter`，不计入官方 8 方法 |
| 方法不能提前评分、不能接触隐藏测试 | `grade_calls_during_run=0`、`hidden_test_access=false` |

验证命令（**不跑 benchmark 复现测试**）：

```bash
.cache/venv/Scripts/python.exe experiments/adapters/verify_adapters.py
```

它刷新 32 行契约矩阵/就绪度，运行适配器测试，并写 `results/adapter-verification.json`。当前结果：**107 项测试通过（2 项 Lean 集成测试因需停 model server 而跳过）、32/32 contract-ready**；真实 benchmark 成绩复现不在本里程碑内。

### 6.3 方法复现 pilot（CORE test split）

协议冻结在 `protocols/core-test-pilot.json`：官方 CORE test split（GPG 解密，passphrase 公开）、3 个最小题、Base/Sentry/Recuris m0-gate/RRSI、1 次、8 步 × 512 tokens、默认无提交门、官方 `report.json` 评分。

| 方法 | capsule-4180912 | capsule-1175539 | capsule-0921079 |
| --- | --- | --- | --- |
| Base | valid, 0/2 | valid, 0/1 | valid, 0/1 |
| Sentry | valid, 2/2 | valid, 0/1 | valid, 0/1 |
| Recuris m0-gate | valid, 0/2 | valid, 0/1 | valid, 0/1 |
| RRSI | valid, 0/2 | valid, 0/1 | valid, 0/1 |

pilot 结果：12 次运行中 **1 次通过**（Sentry `capsule-4180912`，2/2 checks）；总 checks 2/16。失败分类：

- **10/12：`report.json` missing** —— 模型读了结果后直接 submit，没有写任务要求的产物；默认无提交门，这是模型的停止行为，不是适配器 bug。
- **1/12：Sentry `capsule-0921079` 答错** —— 该题含 vision question（检查键带 `fig`），文本模型没有可用的图像答案。
- **1/12：通过** —— Sentry 在 `capsule-4180912` 上写了正确 report。

pilot 第一轮还暴露了适配器编码 bug：R capsule 的 `results/output` 含非 UTF-8 字节，旧 `subprocess` 用 GBK 解码导致 `proc.stdout=None`。已改为 UTF-8 + `errors="replace"`，并加 Docker/LocalHost 回归测试；当时 62 项测试通过。逐次结果在 `results/core-test-pilot/`。

**边界**：8 步 × 512 tokens、1 次、3 题只是 pilot；不能当完成率或方法收益。下一步应扩大预算/题量并做 3 次独立运行；vision 题需要单独处理（文本模型不可答）。

**提交门（opt-in）**：默认关闭；只有显式 `enforce_submission=True` 时，CORE/MLE host 才在 `submit` 时检查任务要求的产物（`report.json` / `submission.csv`）。它不暴露 hidden tests 或答案，且对所有方法一致。表中的 guard 行是这个显式条件；默认 no-guard 行才是无额外反馈的执行。Base/Recuris m0/m0-gate 的 0/3 → 3/3 是 host-level 提交校验 + agent 继续逻辑的作用，不是模型收益；Sentry/RRSI 本来就会写 report，guard 未改变它们的结果。

### 6.4 四 benchmark × 四方法覆盖 pilot

目标不是分数，而是每个已实现方法在每个 benchmark 上都能产生有效评分。`results/method-benchmark-coverage.json` 记录 16 个组合，**16/16 valid**：

| Benchmark | 任务 | Base | Sentry | Recuris m0-gate | RRSI |
| --- | --- | ---: | ---: | ---: | ---: |
| TB 2.1 | `regex-log` | 0/1 | 0/1 | 0/1 | 0/1 |
| LHTB 2.0 | `2048` | 0/1 | 0/1 | 0/1 | 0/1 |
| CORE test split | `capsule-4180912` | 0/2 | **2/2** | 0/2 | 0/2 |
| MLE synthetic | `synthetic` | 1/1 | 1/1 | 1/1 | 1/1 |

- “valid”只表示 Agent 执行 + 官方评分链路跑通；passed 是另一列，不能混。
- 预算很短：TB Base 8 步，其余 4 步；LHTB 4 步；CORE/MLE 8 步；每步 512 tokens。不是正式复现。
- MLE 是**合成 competition**（真实 Kaggle 数据缺失）；真实 MLE 分数未跑。
- 官方 Spine Pi/Node、openJiuwen、LHH、Opera 仍是 contract-only，只在 32 行契约矩阵里覆盖，不在这次真实覆盖中。
- TB Sentry 8 步时上下文超过 16k，llama-server 返回 400；已把模型请求错误降级为 `agent_error` 并继续评分，4 步重跑得到 valid 结果，不再崩溃。

### 6.5 轨迹记录 pilot

`protocols/tb-recorder-pilot.json` 用 `repro_runner.py` 跑 Base × TB `regex-log` + LHTB `2048`。记录 `trajectory.jsonl`（model_request / model_response / action / observation / submit）、`agent-result.json`、`grading/result.json`；原始文件在 `.cache/adapters/tb-recorder-pilot/`，汇总在 `experiments/adapters/results/tb-recorder-pilot/summary.json`。

| 任务 | 终止 | tokens | valid | checks |
| --- | --- | ---: | --- | --- |
| TB 2.1 `regex-log` | `timeout_wall`（300 s） | 15,895 | true | 0/1 |
| LHTB `2048` | `timeout_tokens`（50k） | 50,555 | true | 0/1 |

50k token 上限在 LHTB 上已经触到；正式 corpus 的 token 上限应高于 pilot P90。这是 recorder smoke，不是 50 题 corpus。

### 6.6 100k token pilot

`protocols/tb-pilot-100k.json`：Base × 3 题，100k token 预算，`max_steps=100`，wall 900/900/5400 s，loop 检测 5 次。

| 任务 | 终止 | tokens | Agent 秒 | 动作 | valid | checks |
| --- | --- | ---: | ---: | ---: | --- | --- |
| TB `regex-log` | `timeout_tokens` | 105,500 | 704.5 | 9 | true | 0/1 |
| TB `sqlite-db-truncate` | `timeout_tokens` | 108,404 | 386.0 | 9 | true | 0/1 |
| LHTB `2048` | `timeout_tokens` | 103,358 | 53.0 | 24 | true | 0/1 |

- 三题都先触到 100k token 预算，而不是 wall；TB 900s、LHTB 5400s 都没有走完。
- 总量略高于 100k（103k–108k），因为最后一次调用先记账、再触发预算上限。
- 100k 大致等于本轮 pilot 的 P90；如果正式 corpus 要减少预算截断，应把上限提高到 120k 以上。当前按你的要求保留 100k。
- 三题 valid 但 0/1：链路正常，任务没完成；不能当方法分数。

### 6.7 数学适配器（PutnamBench / MATH-500 / AIME）

- **PutnamBench**：672 道 Lean 4 题，`loader → Lean 工程 host → agent → grade` 已接。评分前拒绝 `sorry`/`admit` 和新增的 `axiom`/`constant`/`opaque`/`unsafe` 声明，再调用固定版本的 Lean 4.33.1 + Mathlib 做内核检查。
- **工具链**：优先使用 `.cache/tools/lean4-4.33.1/.../bin`，跳过 `~/.elan/bin` 的 shim；elan 在 v4.33.1 已安装时仍可能尝试联网更新并挂起。
- **内存条件**：本机 16 GB，`import Mathlib` 约需 5.5 GB commit。9B server 常驻时只剩约 1 GB，Lean 会在随机 `.olean.private` 上报读取失败。`repro_math_pilot.py --release-model` 在评分前停 server、等 commit 余量、评分后按协议重启并 health check。
- **smoke**：`protocols/math-smoke.json`，Base × `putnam_1962_a1`，6 步上限。终止 `max_steps`，1 action，9,942 tokens，243.8 s；评分 valid、0/1（`proof uses sorry`）。释放前 commit 2.10 GB，释放后 8.12 GB（2 s），重启 8.1 s 后 `/health` OK。首个 action 直接读取 `src/putnam_1962_a1.lean`，不再误用 `lean4/src` 前缀。
- **Lean 编译链路**：`RUN_LEAN_TESTS=1` 写入一个平凡已证定理，`lake env lean` 实际编译通过（178.7 s）。默认测试跳过，因为必须先停掉 model server。
- **MATH-500 / AIME**：本地 JSON/JSONL（`problem`/`answer`）或两题 fixture；agent 写 `answer.txt`，评分取最后一个 `\boxed{}` 或末行，支持字符串、数值相对容差和分数交叉相乘；AIME 限 0–999。`protocols/math-informal-smoke.json` 的 2026-11-14 Base smoke：AIME 1/1（603 tokens，3 actions），MATH-500 0/1（模型把正确答案 `5` 只写进 final 通道，没有生成 `answer.txt`；这是指令遵循失败，不是评分错误）。
- **miniF2F / ProofNet**：`prepare_formal_math.py` 把 `yangky11/miniF2F-lean4`（488 个单定理文件）和 `rahul3613/ProofNet-lean4`（11 个文件、360 个定理）复制进统一的 v4.33.1 工程。上游分别 pin v4.24.0 / v4.20.0；为了跨 benchmark 同一 Lean/Mathlib 版本，统一用 v4.33.1，`--precheck` 负责剔除不兼容文件。2026-11-14 干净环境 precheck（8 GB commit）：miniF2F 抽样 20/20 通过；ProofNet 5/11 文件通过（Cambridge-Tripos、Ireland-Rosen、Pugh、Putnam、Shakarchi，共 66 个定理），其余 6 个文件（Artin、Axler、Dummit-Foote、Herstein、Munkres、Rudin）依赖 v4.33 之前的 Mathlib API，由 `precheck.json` 过滤。miniF2F 以文件为任务；ProofNet 以单个定理为任务，评分时把 Lean 的 `declaration uses 'sorry'` 警告行映射回目标定理块。`RUN_LEAN_TESTS=1` 的实际编译测试（168.9 s）验证了：miniF2F 平凡定理通过；ProofNet 同一文件中已证的定理通过、仍为 `sorry` 的定理被拒绝。
- **两阶段 runner**：`repro_math_batch.py --phase all --release-model` 先在 server 运行时收集所有解答（`solution.lean` + `pristine.lean`），然后只停一次 server 批量评分并恢复。可断点续跑，`--status` 查看已收集/已评分数量。2026-11-14 smoke：2 Putnam + 1 miniF2F + 1 ProofNet，4/4 收集、4/4 评分 valid 0/1（解答仍为 `sorry`）；评分阶段只停一次 server（commit 4.27 → 5.8 GB，因 Docker 也在运行，6.0 GB 阈值等满 90 s），8.1 s 后恢复 `/health`。

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
| 测试数 | 14 | 107 |
| 真实 9B smoke | 未跑 | TB Base 0/1；LHTB 四方法 0/1（band 0）；CORE Sentry/RRSI 3/3；Base/Recuris 0/3 → 3/3（加提交门） |
| 方法分数 | 无 | 仍无正式预算/收益结论 |

## 9 边界与未做

- 真实 9B smoke/pilot 是 4–8 步 × 512 token 的接线 smoke，不是正式预算；CORE pilot 只有 3 道 test 题，不能当完成率或方法收益结论。
- TB `regex-log` 第一次官方评分卡在 `apt-get update`，按 D-apt 环境失败处理；重跑后拿到 valid 0/1。
- CORE 上 Sentry/RRSI 3/3；Base/Recuris 在未加提交门时 0/3，加提交门后 3/3。这是 host-level 提交校验的作用，必须作为不同条件分别报告，不能把 0/3 → 3/3 当模型收益。
- LHTB `2048` 是长程游戏；6 步只能到 band 0，四个方法都是 0/1。这是预算描述，不是方法差异。
- 提交门默认关闭；只有显式 `enforce_submission=True` 才启用（CORE `report.json`、MLE `submission.csv`）。它改变了 host 反馈，因此有/无 guard 的结果不能直接合并；默认 no-guard 行才是无额外反馈的执行。
- Sentry 在 CORE 上 detector 触发 6 次并 3/3；verifier/updater 的 H=10 软恢复仍未触发。
- Recuris 只跑 m0/m0-gate，没有 tta meta-agent patch loop；seed 记忆来自 TB2.1，不是 TB8 演化产物。
- RRSI 只跑 Evaluate 半，搜索环需要 Anthropic Vertex。
- Spine 的官方原生 loop 是 Pi/Node 插件，尚未桥接到 Python 公共契约；`agents/spine.py` 是明确标注的 Python 重实现，只验证 `spine_open/close/next` 协议和 memory 折叠，`spine_spawn` 未执行，上下文折叠是简化版，不能当官方插件成绩。
- openJiuwen、LongHorizon-Harness、Opera 的上游没有接入。
- CORE-Bench 方法 pilot 使用官方 **test split**（GPG 解密，passphrase 公开）；train split 只用于早期适配器验证。test split 的 3 道题是开发 pilot，不是完整 45 题。
- 4×4 覆盖（16/16 valid）只证明每个已实现方法在每个 benchmark 上能执行并得到官方评分；TB Base 8 步、其余 4 步，MLE 是合成 competition，不能当方法分数。
- TB Sentry 8 步时上下文超过 16k，llama-server 返回 400；已把模型请求错误降级为 `agent_error` 并继续评分，4 步重跑得到 valid 结果，不再崩溃。
- 轨迹记录 pilot 只有 2 题、300s/50k 上限；LHTB 已触 token 上限。它是 recorder smoke，不是 50 题 corpus，也不能直接定正式 token 预算。
- 100k pilot 三题都在 token 预算处停止（103k–108k），wall 未到；100k 是绑定上限，正式 corpus 若想减少截断需提高到 120k+。
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
- 4×4 覆盖矩阵：`experiments/adapters/results/method-benchmark-coverage.json`（16/16 valid）
- 轨迹记录 pilot：`experiments/adapters/results/tb-recorder-pilot/summary.json`
- 轨迹记录代码：`experiments/adapters/recording.py`、`repro_runner.py`、`protocols/tb-recorder-pilot.json`
- CORE test pilot：`experiments/adapters/results/core-test-pilot/summary.json`
- MLE 合成 pilot：`experiments/adapters/results/mle-synthetic-pilot/summary.json`
- 数学适配器：`experiments/adapters/benchmarks/content.py`（PutnamBench、MATH-500、AIME）
- miniF2F / ProofNet：`experiments/adapters/benchmarks/formal_math.py`、`prepare_formal_math.py`
- 两阶段 runner：`experiments/adapters/repro_math_batch.py`、`protocols/math-batch-smoke.json`、`results/math-batch-smoke/summary.json`
- 形式化数据来源与预检：`.cache/upstream/putnambench/lean4/formal/README.json`、`precheck.json`（本机缓存）
- PutnamBench pilot：`experiments/adapters/repro_math_pilot.py`、`protocols/math-smoke.json`、`results/math-smoke/summary.json`
- 非形式数学 smoke：`experiments/adapters/protocols/math-informal-smoke.json`、`results/math-informal-smoke/summary.json`
- 数学适配器测试：`experiments/adapters/tests/test_content_adapters.py`（Lean 编译测试需 `RUN_LEAN_TESTS=1`）
- 适配器验证：`experiments/adapters/results/adapter-verification.json`
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
