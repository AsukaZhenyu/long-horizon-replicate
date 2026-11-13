# A/B 阶段复现实验报告：TB8 八题冒烟

生成时间：2026-11-01 17:04 中国标准时间　轮次：`20261031-tb8-smoke`　任务：Terminal-Bench 0.2.18 历史八题

> 本报告由 `.cache/report/build_ab_report.py` 从逐题证据生成，数字不手工填写。
> 这是开发集冒烟，不是留出集、排行榜或泛化证据。A 为 null 表示评分无效，不当作 0。

## 1 结果摘要

| 方法 | 完成 | 已启动 | 未跑 | A | A 无效 | V | Y |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Sentry 0.11.0 + 受控终端 | 8/8 | 0 | 0 | 4 | 0 | 6 | 4 |
| Pi 1.1.0 + Spine 0.1.3 | 8/8 | 0 | 0 | 2 | 0 | 4 | 2 |
| Pi 1.1.0（无 Spine，基础对照） | 8/8 | 0 | 0 | 3 | 0 | 4 | 3 |
| Recuris m0（tb21_seed 记忆） | 8/8 | 0 | 0 | 3 | 0 | 3 | 3 |
| Recuris m0-gate（+完成门） | 8/8 | 0 | 0 | 4 | 0 | 4 | 4 |

A = 冻结产物通过原任务全部检查；V = 预算内按宿主协议正常交付；Y = A×V。

**覆盖**：Sentry、Spine 原生 TB8；Recuris 为 m0/m0-gate 适配；RRSI 只完成 Evaluate 半；MESH/RiseHarness 无公开实现；Better Harnesses/EffGen 不是 TB8 runner。

## 2 A 阶段：论文与实现核验

论文标题取自 arXiv API；仓库、许可证与提交取自实际 clone 或 GitHub API。

| 文献 | arXiv | 代码 | 许可证 | 本轮状态 |
| --- | --- | --- | --- | --- |
| Sentry | 2610.02994 | nuglifeleoji/Sentry @ 1d91bca | MIT | 已 clone，已跑 8 题 |
| Spine | 2610.37224 | GhabiX/spine-plugin @ b599498 | Apache-2.0 | 已 clone，已跑 8 题（机制未触发） |
| Recuris | 2608.24876 | Gen-Verse/Recuris | Apache-2.0 | TB8 m0 adapter 已写并跑 8 题；tta 未实现 |
| RRSI | 2609.24972 | google-research/rrsi | Apache-2.0 | TB8 域 adapter 已写；Evaluate 8 题 A=3/V=3/Y=3；搜索环需 Vertex，未跑 |
| MESH-Harness | 2610.05300 | 规划未给代码入口 | — | 无公开实现；未跑 |
| Better Harnesses | 2607.08938 | malusamayo/slm-harness-adaptation | MIT | 代码存在；辅助轨道，未跑 |
| effGen | — | ctrl-gaurav/effGen | Apache-2.0 | 代码存在；结构参照，未跑 |
| RiseHarness | 2610.27435 | 规划未给代码入口 | — | 无公开实现；未跑 |

复核边界：Sentry、Spine 做了代码/提交/运行入口核验并完成 TB8 冒烟；Recuris、RRSI、Better Harnesses、effGen 读了 README/依赖/入口，确认评测对象或模型接口不匹配；MESH、RiseHarness 没有公开实现。第二批 Recuris/RRSI 的评测分别绑 τ²-Bench 和 Terminal-Bench 2.1/Anthropic Vertex，不能直接套 TB8；第三批 MESH/RiseHarness 无公开实现，Better Harnesses 是辅助轨道复现包，effGen 是通用框架。因此本轮 TB8 冒烟覆盖 Sentry、Spine、Pi-only 三组；其余方法按可运行性归档，不硬凑数字。

## 3 复现卡与共同条件

| 条件 | 冻结值 |
| --- | --- |
| 模型 | Qwen3.5-9B Q4_K_M，SHA-256 03b74727…52b7e8 |
| 上下文 / 并发 | 16384 / 1 |
| 探索预算 | 300 s/题 |
| 尝试 | 每题 1 次全新尝试，跨任务经验清空 |
| 评分 | 冻结容器 → `/app` 归档 → `docker commit` → 独立容器原测试；评分阶段模型/Agent 调用为 0 |
| 反馈 | 任务指令 + 初始环境 + 普通工具输出；隐藏测试在停止后注入 |

**本轮偏离**：TB 0.2.18 而非 2.1；300 s 而非规划中的 20/30 min；6 GB 显存部分卸载（`-ngl 26`，约 10.3 tok/s 生成、约 50 tok/s prompt）；Sentry 用受控终端宿主而非官方 AppWorld 驱动；Spine 未做 Pi-only 消融；jq 镜像使用清华 Debian 镜像完成 apt（任务文件与包版本未改）。`sqlite-db-truncate` 首次评分因 Docker 29 的 commit 弃用提示污染镜像 ID 而无效，已对同一冻结候选重评，新增模型/Agent 调用为 0；原无效记录保留在 `grading-invalid-image-id/`。第一轮 Spine 因 `grade_original.py` 路径错误与 host OOM 失败，失败 case 归档在 `.cache/runs-tb8-smoke/spine/cases-infra-failed-20261031/`；修复后把 Docker VM 限制为 6 GiB 重跑，第二轮 8 题评分全部有效。

## 4 B 阶段：八题冒烟

执行入口：`experiments/tb-eval/scripts/run_round.ps1`；round 目录 `.cache/round8/`；证据目录 `.cache/runs-tb8-smoke/`。

### 4.1 Sentry

| 任务 | A | V | Y | 检查 | 干预 | 硬恢复 | 软恢复 | 经验条目 | 请求 | actor/detector/verifier/updater | 输入/输出 token | Agent 秒 | 结束 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |
| sqlite-db-truncate | 0 | 0 | 0 | {'failed': 1} | 1 | 0 | 0 | 0 | 7 | 6/1/0/0 | 5373/2938 | 300.0729784 | wall_timeout |
| jq-data-processing | 0 | 1 | 0 | {'passed': 12, 'failed': 2} | 2 | 1 | 0 | 0 | 10 | 9/1/0/0 | 32829/1146 | 143.18246970000018 | submitted |
| hello-world | 1 | 1 | 1 | {'passed': 2} | 0 | 0 | 0 | 0 | 6 | 3/3/0/0 | 3778/474 | 48.83080519999976 | submitted |
| regex-log | 0 | 1 | 0 | {'failed': 1} | 5 | 2 | 0 | 0 | 8 | 7/1/0/0 | 18035/1553 | 163.33308970000007 | submitted |
| cprofiling-python | 0 | 0 | 0 | {'failed': 2} | 2 | 0 | 1 | 1 | 17 | 13/2/1/1 | 44873/2369 | 300.06490250000024 | wall_timeout |
| fix-permissions | 1 | 1 | 1 | {'passed': 1} | 1 | 0 | 0 | 0 | 5 | 4/1/0/0 | 3327/484 | 49.361305099999754 | submitted |
| log-summary | 1 | 1 | 1 | {'passed': 3} | 1 | 1 | 0 | 0 | 13 | 7/6/0/0 | 14019/1344 | 140.27143530000012 | submitted |
| cancel-async-tasks | 1 | 1 | 1 | {'passed': 6} | 1 | 0 | 0 | 0 | 5 | 4/1/0/0 | 6859/1416 | 134.65088389999983 | submitted |

### 4.2 Spine

| 任务 | 状态 | A | V | Y | 检查 | 请求 | 总 token | Agent 秒 | 工具计数 | Spine 操作 | 结束 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | --- |
| sqlite-db-truncate | done | 0 | 0 | 0 | {'failed': 1} | 16 | 79122 | 300.114 | bash:15 | 0 | error |
| jq-data-processing | done | 0 | 0 | 0 | {'passed': 1, 'failed': 13} | 4 | 4700 | 6.98 | read:1 | 0 | error |
| hello-world | done | 1 | 1 | 1 | {'passed': 2} | 2 | 6867 | 14.178 | write:1 | 0 | stop |
| regex-log | done | 0 | 0 | 0 | {'failed': 1} | 1 | 5642 | 203.202 | — | 0 | length |
| cprofiling-python | done | 0 | 0 | 0 | {'failed': 2} | 13 | 63879 | 300.087 | bash:7, write:5 | 0 | error |
| fix-permissions | done | 0 | 1 | 0 | {'failed': 1} | 3 | 10509 | 23.964 | bash:1, read:1 | 0 | stop |
| log-summary | done | 1 | 1 | 1 | {'passed': 3} | 7 | 26265 | 37.454 | bash:4, read:1, write:1 | 0 | stop |
| cancel-async-tasks | done | 0 | 1 | 0 | {'passed': 5, 'failed': 1} | 2 | 7638 | 43.678 | write:1 | 0 | stop |

### 4.3 Pi-only 基础 Agent（Spine 的消融对照）

| 任务 | 状态 | A | V | Y | 检查 | 请求 | Agent 秒 | 工具计数 | 结束 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| sqlite-db-truncate | done | 0 | 0 | 0 | {'failed': 1} | 11 | 300.108 | bash:10 | error |
| jq-data-processing | done | 0 | 0 | 0 | {'passed': 1, 'failed': 13} | 4 | 26.753 | read:1 | error |
| hello-world | done | 1 | 1 | 1 | {'passed': 2} | 2 | 10.612 | write:1 | stop |
| regex-log | done | 0 | 0 | 0 | {'failed': 1} | 1 | 196.239 | — | length |
| cprofiling-python | done | 0 | 0 | 0 | {'passed': 1, 'failed': 1} | 10 | 300.083 | bash:5, write:5 | toolUse |
| fix-permissions | done | 1 | 1 | 1 | {'passed': 1} | 6 | 36.228 | bash:4, read:1 | stop |
| log-summary | done | 1 | 1 | 1 | {'passed': 3} | 6 | 31.018 | bash:4, write:1 | stop |
| cancel-async-tasks | done | 0 | 1 | 0 | {'passed': 5, 'failed': 1} | 2 | 53.293 | write:1 | stop |

Pi-only 与 Spine 使用同一宿主、模型、预算和 8 题；差异只在 `--extension` 是否加载。逐题差异只作描述，8 题不足以做统计推断。

### 4.4 Recuris m0（固定 tb21_seed 工作记忆）

| 任务 | 状态 | A | V | Y | 检查 | 请求 | Agent 秒 | 工具计数 | 结束 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| sqlite-db-truncate | done | 0 | 0 | 0 | {'failed': 1} | 11 | 300.165 | bash:10 | error |
| jq-data-processing | done | 0 | 0 | 0 | {'passed': 1, 'failed': 13} | 4 | 86.675 | read:1 | error |
| hello-world | done | 1 | 1 | 1 | {'passed': 2} | 2 | 10.954 | write:1 | stop |
| regex-log | done | 0 | 0 | 0 | {'failed': 1} | 1 | 194.402 | — | length |
| cprofiling-python | done | 0 | 0 | 0 | {'passed': 1, 'failed': 1} | 13 | 300.133 | bash:7, edit:2, write:4 | toolUse |
| fix-permissions | done | 1 | 1 | 1 | {'passed': 1} | 5 | 32.694 | bash:3, read:1 | stop |
| log-summary | done | 1 | 1 | 1 | {'passed': 3} | 7 | 37.928 | bash:5, write:1 | stop |
| cancel-async-tasks | done | 0 | 0 | 0 | {'passed': 2, 'failed': 4} | 7 | 300.175 | bash:2, write:4 | error |

Recuris 本轮只跑 m0：固定 seed 记忆注入，没有实现 tta 的 `check_completion` bounce，也没有 meta-agent patch 循环。它与 Pi-only 的差异只作 8 题描述；seed 记忆来自 TB2.1，不是 TB8 演化产物。

### 4.5 Recuris m0-gate（固定记忆 + 完成门）

| 任务 | 状态 | A | V | Y | 检查 | 请求 | Agent 秒 | 工具计数 | 结束 |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| sqlite-db-truncate | done | 0 | 0 | 0 | {'failed': 1} | 9 | 300.078 | bash:8 | error |
| jq-data-processing | done | 0 | 0 | 0 | {'passed': 1, 'failed': 13} | 3 | 43.526 | read:1 | error |
| hello-world | done | 1 | 1 | 1 | {'passed': 2} | 4 | 154.077 | bash:2, write:1 | stop |
| regex-log | done | 0 | 0 | 0 | {'failed': 1} | 1 | 191.832 | — | length |
| cprofiling-python | done | 0 | 0 | 0 | {'failed': 2} | 12 | 300.165 | bash:6, write:5 | error |
| fix-permissions | done | 1 | 1 | 1 | {'passed': 1} | 6 | 31.306 | bash:4, read:1 | stop |
| log-summary | done | 1 | 1 | 1 | {'passed': 3} | 6 | 33.263 | bash:4, write:1 | stop |
| cancel-async-tasks | done | 1 | 1 | 1 | {'passed': 6} | 8 | 142.146 | bash:6, write:1 | stop |

m0-gate 在模型准备结束时调用 Recuris 的 `check_completion`；本轮共触发 4 次 bounce，cancel-async-tasks 被救回。jq-data-processing 仍因请求超过 16k 上下文失败。meta-agent patch 循环未实现。

### 4.6 适配器运行汇总

| 运行 | 完成 | A | V | Y | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| Recuris m0 | 8/8 | 3 | 3 | 3 | 固定 seed 记忆 |
| Recuris m0-gate | 8/8 | 4 | 4 | 4 | 固定 seed 记忆 + 完成门（4 次 bounce） |
| RRSI TB8 Evaluate | 8/8 | 3 | 3 | 3 | prompt-only 候选；**搜索环未跑**（需 Vertex） |

RRSI 这一行是 `Domain` Evaluate 半的 8 题结果，不是 RRSI 搜索环的成绩；Recuris 两行是 m0/m0-gate，不是完整 tta。三者都不能当方法论文的收益结论。

## 5 机制触发审计

Sentry 的三项机制是否真实触发，按 `sentry-events.jsonl` 逐题统计；Spine 的插件操作按工具名统计。

| 方法 | 机制 | 本轮观察 |
| --- | --- | --- |
| Sentry | 失败识别（detector） | 16 次 detector 调用 |
| Sentry | 恢复验证（verifier） | 1 次 verifier 调用；4 次硬恢复、1 次软恢复 |
| Sentry | 经验写入（updater） | 1 次 updater 调用；累计经验条目 1 |
| Spine | 子任务树操作 | 累计 Spine 工具调用 0 次 |
| Pi-only | 无方法机制 | 基础 Agent 对照；用于隔离 Spine 的上下文组织效应 |
| Recuris m0 | 固定 seed 记忆 | 工作记忆注入 system prompt；未实现 tta 完成门/meta-agent |
| Recuris m0-gate | 完成门 | `check_completion` 触发 4 次 bounce；meta-agent patch 未实现 |

Spine 的 8 题轨迹中没有出现 `spine_*` 工具调用；插件可能自动管理上下文，但本轮没有可观察的显式机制操作。按 10-31 规划的准入条件，本轮只算执行冒烟，不能进入效果比较或组件归因。

机制触发不等于效果提升：本轮没有 Pi-only 对照，也没有跨任务学习，因此不能把 Y 的差异归因于单个组件。

## 6 资源与执行流程

| 项 | 实测 |
| --- | --- |
| CPU / 内存 | i5-14490F，16 线程 / 15.8 GB |
| GPU | RTX 3050 6 GB，Vulkan，`-ngl 26`，16k ctx |
| 推理速度 | 生成约 10.3 tok/s；prompt 约 50 tok/s |
| Docker | Docker Desktop 4.97.0 / Engine 29.9.2，WSL2，6 GiB VM（本轮为避 OOM 下调） |
| Python / Node | venv 3.12.10 / Node 26.13.0 |
| 镜像 | 8 道历史题，镜像 ID 见 `.cache/round8/base-images.json` |
| Spine 运行时卷 | node v22.23.4，Pi 1.1.0，extension SHA256 c8d68ac5… |

逐题证据目录包含 `source.json`、`preflight.json`、`http-trace.jsonl` / `requests/`、`agent-result.json`、`grading/result.json`、`result.json`、`cleanup.json`；完整证据留在 `.cache/runs-tb8-smoke/`，不入库。

## 7 结论与边界

- 本轮 Sentry 的 Y 为 4/8，Spine 的 Y 为 2/8；这是 300 s、单次、开发集冒烟。
- Spine 的 8 题轨迹中没有 spine_* 工具调用；机制未在轨迹中出现，不能把 Spine 的 Y=2/8 归因于 Spine 插件。
- Pi-only 的 Y 为 3/8，Spine 为 2/8；8 题只作逐题描述，不能当消融或统计结论。Spine 在这组题上没有超过 Pi-only，结合机制未触发，当前结果不支持 Spine 的收益主张。
- Recuris m0 的 Y 为 3/8，Pi-only 为 3/8；m0 只注入固定 seed 记忆，不能当完整 Recuris 的收益。
- Recuris m0-gate 的 Y 为 4/8，m0 为 3/8，Pi-only 为 3/8；完成门救回 cancel-async（4 次 bounce），但仍是 8 题描述，不能当完整 Recuris 收益。
- 8 题是项目长期开发集，不是留出集；不能写泛化、排行榜或稳定性结论。
- 300 s 预算与 6 GB 显存部分卸载都会压低可完成步数；与 8 GB 机器或规划中的 20/30 min 不可直接比较。
- Sentry 的经验写入、Spine 的跨任务收益在单题/8 题冒烟中不可测；本轮只回答“执行链路、正常交付、独立评分是否跑通”。
- Recuris m0 adapter 已跑 8 题；RRSI 的 TB8 域 adapter 已写并做了 Evaluate 8 题（A=3/V=3/Y=3），但搜索环仍需 Anthropic Vertex，未跑；MESH/RiseHarness 无公开实现，Better Harnesses/effGen 不是 TB8 runner；可运行性判断见 `AB阶段复现卡.md`。

## 8 证据入口

- 逐题裁定：`.cache/runs-tb8-smoke/{spine,sentry}/cases/<task>/result.json`
- 汇总：`.cache/runs-tb8-smoke/{spine,sentry}/summary.json`
- 运行溯源：`.cache/runs-tb8-smoke/run-config.json`、`.cache/server/launch.json`
- 镜像清单：`.cache/round8/base-images.json`

