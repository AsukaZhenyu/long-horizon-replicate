# A/B 阶段：复现卡、资源盘点与 8 题冒烟

> 依据 `docs/plan/2026-10-29.docx` 与 `docs/plan/2026-10-31.docx` 的 A/B 阶段。
> A 阶段：核验论文、代码、模型、任务，冻结复现卡，明确可变项、反馈权限、可获得实现与资源。
> B 阶段：每方法 1 个种子、8 题冒烟，要求能自主运行、正常交付、独立评分，并留下完整成本记录。
> 本文件是工作记录；成稿 Word 报告另存。所有未经本轮实测的数字都标为“未验证”。

## 1 论文与公开实现核验（2026-10-31）

论文标题取自 arXiv API，仓库信息取自 GitHub API；许可证与提交取自实际 clone。

| 文献 | arXiv | 公开代码 | 许可证 | 本轮状态 |
| --- | --- | --- | --- | --- |
| Sentry: Learning to Recover from LLM Agent Failures at Test Time | 2610.02994 | [nuglifeleoji/Sentry](https://github.com/nuglifeleoji/Sentry) @ `1d91bca`，0.11.0 | MIT | **已完成 8 题（A=4，V=6，Y=4）** |
| Spine: Compiling Subtask Trees into Structured Context for Long-Horizon Coding Agents | 2610.37224 | [GhabiX/spine-plugin](https://github.com/GhabiX/spine-plugin) @ `b599498`，插件 0.1.3 / Pi 1.1.0 | Apache-2.0 | **已完成 8 题（A=2，V=4，Y=2；机制未触发）** |
| Recursive Experiential-Working Memory Evolution for Long-Horizon Agent Harnesses (Recuris) | 2608.24876 | [Gen-Verse/Recuris](https://github.com/Gen-Verse/Recuris) | Apache-2.0 | **代码已核验；TB8 m0/m0-gate adapter 已跑 8 题（m0-gate A=4/V=4/Y=4）；tta meta-agent 未实现** |
| RRSI: Regularized Recursive Self-Improvement of Agent Harnesses | 2609.24972 | [google-research/rrsi](https://github.com/google-research/rrsi) | Apache-2.0 | **代码已核验；TB8 Evaluate adapter 已跑 8 题（A=3/V=3/Y=3）；搜索环需 Vertex，未跑** |
| MESH-Harness: Self-Improving Agent Harnesses via Bandit-Guided Compositional Evolution | 2610.05300 | 规划文档未给代码入口 | — | 无公开实现；未跑，须标“论文重实现” |
| Better Harnesses, Smaller Models: Building 90% Cheaper Agents via Automated Harness Adaptation | 2607.08938 | [malusamayo/slm-harness-adaptation](https://github.com/malusamayo/slm-harness-adaptation) | MIT | 代码已核验；辅助轨道/复现包，未跑 |
| effGen: Enabling Small Language Models as Capable Autonomous Agents (ICML 2026) | — | [ctrl-gaurav/effGen](https://github.com/ctrl-gaurav/effGen) | Apache-2.0 | 代码已核验；通用框架，无 TB8 runner，仅作结构参照 |
| Harness Self-Evolution for Long-Horizon Terminal Agents (RiseHarness) | 2610.27435 | 规划文档未给代码入口 | — | 无公开实现；未跑 |
| Rethinking the Evaluation of Harness Evolution for Agents | 2607.12227 | — | — | 方法论参照，不运行 |
| Long-Horizon-Terminal-Bench 2.0 | 2610.14146 | 未取得 | — | 本机不跑，服务器阶段 |
| CORE-Bench | 2409.11363 | 未取得 | — | 本机不跑，服务器阶段 |

**A 阶段的诚实边界**：本轮只对 Sentry 与 Spine 做了代码、许可证、提交和运行入口核验；其余方法只核到“公开仓库是否存在、许可证、最近推送时间”，没有读代码、没有复现，不能写“已验证可运行”。

### 1.1 第二批/第三批的可运行性判断（2026-11-01）

| 方法 | 代码 @ commit | 许可 | 入口与依赖 | 论文 benchmark | 本地模型兼容 | TB8 AB 冒烟 |
| --- | --- | --- | --- | --- | --- | --- |
| Recuris | [Gen-Verse/Recuris](https://github.com/Gen-Verse/Recuris) @ `7d3745a` | Apache-2.0 | Python ≥3.12；`src/recuris`；`tau2`/`metaagent` extras | τ²-Bench retail/airline；skillflow adapter | 支持 OpenAI 兼容 `api_base` | **TB8 m0-gate adapter 已写并跑 8 题；tta meta-agent 未实现** |
| RRSI | [google-research/rrsi](https://github.com/google-research/rrsi) @ `be50316` | Apache-2.0 | Python ≥3.10；`anthropic[vertex]`；coding domain 用 harbor 拉 TB 2.1 | Terminal-Bench 2.1、SWE-bench、Harvey LAB 等 | search roles 绑定 Anthropic Vertex；agent harness 可走 litellm | **TB8 域 adapter 已写；Evaluate 8 题 A=3/V=3/Y=3；搜索环需 Vertex，未跑** |
| Better Harnesses | [malusamayo/slm-harness-adaptation](https://github.com/malusamayo/slm-harness-adaptation) @ `2d31e17` | MIT | Python ≥3.14；OpenHands SDK；figshare 复现包 | WebArena/OpenHands 等 | 强模型/辅助轨道，不是本地主表 | **不跑**：复现包 + 辅助轨道，不是 TB8 runner |
| effGen | [ctrl-gaurav/effGen](https://github.com/ctrl-gaurav/effGen) @ `37de05a` | Apache-2.0 | Python ≥3.11；OpenAI 兼容 `base_url` | 通用 agent 框架 | 支持本地模型 | **不跑**：没有 TB8 runner；仅代码审查/结构参照 |
| MESH | 规划未给代码入口 | — | — | — | — | 无公开实现；论文重实现风险 |
| RiseHarness | 规划未给代码入口 | — | — | — | — | 无公开实现；仅代码审查（若后续找到） |

**判断**：方案第一批的 Sentry/Spine 已完成；第二批 Recuris/RRSI 的代码存在，但它们的评测对象分别是 τ²-Bench 和 Terminal-Bench 2.1/Anthropic Vertex，**不是 TB8**。在写 TB8 adapter 之前，直接跑出来的数字不可比，不能硬凑进同一张表。本轮 AB 阶段因此只把 Sentry、Spine 和 Pi-only 控制组放进 TB8 冒烟；其余方法按上表归档为“需适配/辅助轨道/无实现”。

**适配器**：已写 `experiments/tb-eval/adapters/recuris/`（m0：固定 seed 工作记忆注入，已跑 8 题）和 `experiments/tb-eval/adapters/rrsi/`（TB8 `Domain` 的 Evaluate 半，候选 harness 是 prompt-only；Evaluate 8 题 A=3/V=3/Y=3；RRSI 搜索环仍需 Anthropic Vertex，未跑）。两者都复用 Pi 1.1.0 宿主和同一评分器，并在 `source.json` 记录 adapter 名。


## 2 复现卡：Sentry

| 字段 | 内容 |
| --- | --- |
| 身份 | `nuglifeleoji/Sentry`，`1d91bca14fa6a4e17908856cc787eb8e8354395f`，`sentry-failure-manager 0.11.0`，MIT |
| 论文 | arXiv 2610.02994 |
| 要复现的能力 | 失败识别（detector）、恢复验证（verifier）、经验写入/复用（updater）；三者必须在审计日志中真实触发才进入效果比较 |
| 官方任务/模型 | 论文报告 AppWorld、WebShop、SWE-bench Lite、Mind2Web Replay；本轮不重跑论文原始配置 |
| 本轮任务 | Terminal-Bench 0.2.18 的 8 道历史开发题（TB8） |
| 本轮模型 | 本地 Qwen3.5-9B Q4_K_M，16384 ctx，temperature 0.2，`reasoning off`，单次输出 ≤2048 |
| 宿主适配 | 官方 `SentryRunner.start_task/step/finalize` 与 detector/verifier/playbook 源码不改；actor 动作格式为受控终端的 `{"command"}` / `{"final"}`，每命令 60 s 上限，整题 300 s |
| 可变项 | 宿主动作解码、基准任务、模型、预算；Sentry 核心算法与提示不改 |
| 反馈权限 | 只有任务指令、初始环境、普通命令输出；隐藏测试在候选冻结后注入；运行中不提供测试结果或参考答案 |
| 成本项 | 模型输入/输出 token、请求数、actor/辅助调用、墙钟、容器准备、评分、清理 |
| 进入效果比较的条件 | 三项机制在审计日志中触发（首轮 hello-world 为 0/0/0，不能据此证明恢复能力；8 题轮的干预与恢复次数单独记录） |
| 已知差异 | TB 0.2.18 而非 2.1；受控终端宿主而非官方 AppWorld 驱动；跨任务经验在 8 题冒烟中按协议清空；本机 6 GB 显存、模型部分卸载 |

## 3 复现卡：Spine

| 字段 | 内容 |
| --- | --- |
| 身份 | `GhabiX/spine-plugin`，`b599498be489d31b9356d77af678bfd3c7220fc0`，`@spinejit/pi-spinejit 0.1.3`，Pi 1.1.0，Apache-2.0 |
| 论文 | arXiv 2610.37224 |
| 要复现的能力 | 把长任务组织成子任务树：当前子任务完整保留，已完成子任务折叠为记忆；显式 goal/start/end 边界 |
| 官方任务/模型 | 论文报告 SWE-Milestone、ProgramBench、FrontierSWE；本轮不重跑论文原始配置 |
| 本轮任务 | Terminal-Bench 0.2.18 的 8 道历史开发题（TB8） |
| 本轮模型 | 本地 Qwen3.5-9B Q4_K_M，16384 ctx，temperature 0.2，`thinking off`，单次输出 ≤2048 |
| 宿主适配 | Pi 1.1.0 + 官方插件 0.1.3，运行在独立 Node 22 运行时卷；插件源码不改；受控终端协议与 Sentry 轮相同 |
| 可变项 | 宿主、任务、模型、预算；Spine 插件不改 |
| 反馈权限 | 同上：只有任务指令、初始环境、普通工具输出；隐藏测试在候选冻结后注入 |
| 成本项 | 同上 |
| 进入效果比较的条件 | 迁移到共同终端协议后仍可运行；插件操作在轨迹中真实出现 |
| 已知差异 | TB 0.2.18 而非 2.1；没有 Pi-only 配对消融，因此不能把整体表现归因于 Spine 单个组件；本机 6 GB 显存、模型部分卸载 |

## 4 本轮共同条件与偏差

| 条件 | 冻结值 |
| --- | --- |
| 模型 | Qwen3.5-9B Q4_K_M，SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8` |
| 上下文 / 并发 | 16384 / 1 |
| 探索预算 | 300 s/题（8 题历史题的既有本地协议） |
| 尝试次数 | 每题 1 次全新尝试，不重跑、不择优 |
| 评分 | 暂停容器 → 取 `/app` → `docker commit` → 独立容器用未修改的原测试评分；评分阶段模型调用与 Agent 动作为 0 |
| 跨任务经验 | 每题重置 |

**必须记录的偏差**：

1. **D-budget**：10-31 规划写 8 项冒烟 20 min/题、24 项初筛 30 min/题；本轮实际沿用 TB8 的 300 s/题。因此本轮是“300 s 冒烟”，不能当作规划里的 20/30 min 初筛结果。
2. **D-gpu**：设计文档写本机 8 GB 显存；实际 RTX 3050 为 6 GB，只能用 Vulkan 部分卸载（本轮 `-ngl 26`，实测约 10.3 tok/s，显存剩约 384 MiB）。
3. **D-python**：项目 venv 使用 Python 3.12.10；系统默认 Python 3.15.2 因缺 aiohttp/fastuuid 预编译轮子不用于本项目。
4. **D-apt**：构建部分任务镜像时 `archive.ubuntu.com` 间歇 502（与 `ANALYSIS.md` D5 同源）；构建失败按预注册规则记环境排除，不算方法失败。
5. **D-host**：Sentry 使用受控终端宿主，不是官方 AppWorld 驱动；Spine 使用 Pi 运行时卷。两者比较的是完整集成，不做组件级归因。
6. **D-proxy**：评分容器需要宿主代理时按 `ANALYSIS.md` D2 处理；本轮 8 题走历史离线路径，不注入代理。
7. **D-mirror**：`jq-data-processing` 镜像构建时 Debian 源经代理间歇 502，改用清华 Debian 镜像完成 apt；任务 Dockerfile 的测试文件、包版本与数据生成步骤未改。
8. **D-path**：`harness/spine/paths.mjs` 的 `repoRoot` 少算一层，默认会去 `experiments/.cache/terminal-bench` 找任务；本轮修正为仓库根。`experiments/tb-eval/.local/env.ps1` 必须保持纯 ASCII，因为 Windows PowerShell 5.1 按 ANSI 读取 `.ps1`，直接写中文路径会被解码坏。
9. **D-grade**：`harness/grade_original.py` 原先把 case 目录限制在 `harness/` 下，而运行目录在 `.cache/runs-*`，导致 snapshot 直接退出；本轮改为限制在 `paths.RUNS` 下。另，Docker 29 的 `docker commit` 弃用提示会污染 stdout 里的镜像 ID，已改为解析最后的 `sha256:` 行。
10. **D-regrade**：`sqlite-db-truncate` 首次评分因上述镜像 ID 污染而无效；对同一冻结候选重评，新增模型/Agent 调用为 0，原无效记录保留在 `grading-invalid-image-id/`。
11. **D-spine-grade**：`harness/spine/run.mjs` 原先把 `grade_original.py` 解析到 round 目录（`.cache/round8/`），而文件在 `harness/`，导致第一轮 Spine 每题 snapshot 直接失败。已改为从 runner 所在目录解析；修复后的第二轮 8 题全部产生有效评分。
12. **D-oom**：第一轮 Spine 运行期间 host 内存压力触发系统保护，模型 server 与 Spine runner 被停止。第一轮的 5 个已启动 case 已显式归档到 `.cache/runs-tb8-smoke/spine/cases-infra-failed-20261031/`，不参与第二轮；随后把 Docker VM 内存限制为 6 GiB，第二轮完整跑完。

## 5 资源盘点（2026-10-31 实测）

| 项 | 实测 |
| --- | --- |
| CPU | Intel i5-14490F，16 线程 |
| 内存 | 15.8 GB 总量，模型服务工作集约 5.5 GB |
| GPU | RTX 3050，6 GB；Vulkan 后端，无 CUDA |
| 模型推理 | `-ngl 26` + 16384 ctx：约 10.3 tok/s；纯 CPU：约 3.0 tok/s |
| Docker | Docker Desktop 4.97.0 / Engine 29.9.2，Linux 容器，WSL2；本轮为避免 OOM 将 VM 内存限制为 6 GiB、8 CPU |
| Docker 磁盘 | VM 盘 1007 GB 虚拟；vhdx 在 C:，C: 剩约 139 GB |
| Python | 项目 venv 3.12.10；系统 3.15.2（不兼容部分轮子） |
| Node / Git | Node 26.13.0 / Git 2.56.0 |
| 模型文件 | 5.3 GB，SHA-256 与协议一致 |
| 离线评分工具 | uv 0.7.13（Linux ELF）、pytest 8.4.1 + 5 个依赖；jq/cprofiling 另备 cp313 的 PyYAML 6.0.2、Pillow 11.2.1、imagehash 4.3.2 及 numpy/scipy/PyWavelets |

**容量判断**：8 题镜像 + 评分缓存约占数 GB；24 题全量镜像和 .cache 原始证据远大于此，C: 的 139 GB 需要持续观察。

## 6 B 阶段执行流程与结果

本轮只跑 8 道历史题，使用独立 round 目录，避免把冒烟结果混进 24 题正式轮：

```
.cache/round8/protocol.json      8 题子协议（round=20261031-tb8-smoke）
.cache/round8/base-images.json   8 题镜像 ID
.cache/runs-tb8-smoke/{spine,sentry}/cases/<task>/   逐题证据（与 24 题正式轮隔离）
```

本轮结果（逐题与机制计数见 `AB阶段复现实验报告.docx`）：

| 方法 | 完成 | A | V | Y | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| Sentry 0.11.0 + 受控终端 | 8/8 | 4 | 6 | 4 | 评分全部有效；detector/verifier/updater 均触发 |
| Pi 1.1.0 + Spine 0.1.3 | 8/8 | 2 | 4 | 2 | 评分全部有效；轨迹中无 `spine_*` 工具调用，只算执行冒烟 |
| Pi 1.1.0（无 Spine，基础对照） | 8/8 | 3 | 4 | 3 | 同宿主/模型/预算；比 Spine 多通过 fix-permissions |
| RRSI TB8 Evaluate（prompt-only） | 8/8 | 3 | 3 | 3 | Domain Evaluate 半；搜索环需 Vertex，未跑 |
| Recuris m0（tb21_seed 记忆） | 8/8 | 3 | 3 | 3 | 固定 seed 记忆注入；与 Pi-only 同 Y |
| Recuris m0-gate（+完成门） | 8/8 | 4 | 4 | 4 | 4 次 bounce；cancel-async 被救回；tta meta-agent 未实现 |

**Spine 的当前信号是负面的**：8 题上 Pi-only（Y=3）高于 Spine（Y=2），且轨迹中没有 `spine_*` 工具调用。已逐请求确认：每次模型请求的 `tools` 数组都包含 `spine_open/spine_close/spine_next/spine_spawn`，system prompt 也包含 `<spine_instruction>`；模型一次都没有调用。因此这不是插件加载 bug，而是本地 9B 模型没有遵循 Spine 的工具协议。要公平检验 Spine，需要 prompt/guard 适配（或更强模型），不能把这次 Y=2 当成方法结论。

每题证据目录应包含：

| 文件 | 说明 |
| --- | --- |
| `source.json` | 任务、镜像 ID、模型、上下文、预算、路径 |
| `preflight.json` / `initial-container-identity.json` | 镜像与容器身份核对 |
| `http-trace.jsonl` | 完整模型请求/响应（Spine 经本地代理） |
| `events.jsonl` / `requests/` | Agent 动作轨迹与 Sentry 各阶段调用 |
| `agent-result.json` | 退出码、是否触截止、模型请求数、工具调用、重复命令、V |
| `grading/result.json` | 原测试结果、A、检查计数、评分阶段新增调用=0 |
| `result.json` | A、V、Y 与完整 trial 时间 |
| `cleanup.json` | 容器清理记录 |

### 结果表

（跑完后由 `export_results.py` 生成，不手工填。）

## 7 结论边界

- 8 题是项目长期开发集，不是留出集；本轮结果只能写“TB 0.2.18 八题冒烟”，不能写泛化或排行榜成绩。
- 300 s 预算低于规划中的 20/30 min，失败更多反映预算而非方法上限。
- 本机 6 GB 显存导致模型部分卸载，速度与 8 GB 机器不可直接比较。
- Sentry 的经验写入、Spine 的跨任务收益在单题/8 题冒烟中不可测；本轮只验证执行链路、正常交付和独立评分。
