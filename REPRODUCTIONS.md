# 复现与评测总表

一页看完这个仓库里有什么、钉在哪个版本、结论是什么。每份的完整执行路径在读它自己的目录。

## 方法复现

| 方法 | 上游 @ pin | 任务 / 数据 | 本机结论 | 报告 |
| --- | --- | --- | --- | --- |
| **CLM**<br>真实上下文编辑 | [facebookresearch/context-language-models](https://github.com/facebookresearch/context-language-models) @ `4831982`（CC-BY-NC-4.0）<br>[RulinShao/ContextBench](https://github.com/RulinShao/ContextBench) @ `fb533c1`（Apache-2.0） | ContextBench `kv-store-R1000-seed42`：1000 条记录、24 查询、34 流操作，流 SHA256 已钉 | 16/24（66.7%），`budget_wall` 后 partial；已答 16 题全部正确，但任务未完成。真实 context-edit 次数与下一请求 snapshot 已核对 | [`reports/local-sanity.md`](reproductions/clm/reports/local-sanity.md) |
| **MAGE**<br>有界工程复现 | [Komorebi660/MAGE](https://github.com/Komorebi660/MAGE) @ `ace6931`<br>MemoryArena `formal_reasoning_math/data.jsonl` @ `da1a37c`，SHA256 已钉 | MemoryArena math1 第 0 题（5 个相互依赖的子任务） | **本地 judge 不可信**：把子任务 4 的空答案判成正确。原始分 `[1,1,1,1,0]` 保留，原生最终子任务成功率 **0/1**。token/准确率结论不成立 | [`report.md`](reproductions/mage/report.md) |
| **StateAct / ReAct** | [ai-nikolai/StateAct](https://github.com/ai-nikolai/StateAct) @ `8fb47be`；ALFWorld 0.4.2 / TextWorld 1.6.2 / fast-downward-textworld 20.6.3；官方 few-shot `1 0` | ALFWorld `valid_unseen`，env0 与 indices 1/2 两种批量方式 | 冒烟：原生 `won` 均为 1/1（env0）与 2/2（indices 1/2）。原文是 Qwen2.5-14B + vLLM 的 108/134，**本机不能与之数值比较** | [`INITIAL_REPORT.md`](reproductions/stateact/INITIAL_REPORT.md) |
| **TB8**<br>历史 8 题对照 | Terminal-Bench 0.2.18 开发集；原生 Terminus2 与官方 mini-swe-agent | 开发期反复使用的 8 题（不是留出集） | Terminus2 **5/8** 整项通过（原始 4/8，含 2 次原始测试恢复、零额外 Agent 尝试）；mini-swe-agent **3/8**。均保留 `parse_error` 原始记录 | [`REPORT.md`](reproductions/tb8/REPORT.md) |

## 评测装置

| 装置 | 对象 | 状态 | 结果 |
| --- | --- | --- | --- |
| [`experiments/tb-eval`](experiments/tb-eval/README.md) | Terminal-Bench 0.2.18 的 24 题分层开发集（8 历史 + 16 新，10 桶，seed 20261031）<br>轨道 A：Pi 1.1.0 + `@spinejit/pi-spinejit` 0.1.3<br>轨道 B：Sentry 0.11.0 核心 + 受控终端宿主 | 装置与断点续跑就绪；24 题全量轮次尚未开始，只有冒烟记录 | 指标 A（冻结产物通过原始测试）/ V（预算内正常提交）/ Y=A×V；A 为 null 是「评分无效」，不是 0 |

## 执行路径完备度

| 方法 | 1 pin | 2 环境锁 | 3 命令 | 4 产出 | 5 差异说明 |
| --- | --- | --- | --- | --- | --- |
| clm | `upstream.lock.json`（含许可证文件 SHA256） | `requirements-ubuntu-py312.lock.txt` | `bootstrap.sh`、`run-sanity.sh` | `reports/*.json` 8 份 + `initial.md` | `reports/local-sanity.md` |
| mage | `sources.json`（上游、数据集、基础镜像 digest） | `linux-wheels.lock.json`、`requirements-math.lock.txt` | `prepare.py`、`run.py`、`Dockerfile`、`offline_check.py` | `results/math1-sanity.json`、`sandbox-check.json` | `report.md`、`patches/` |
| stateact | `config.json`、`data-manifest.json` | `requirements-resolved.txt`、`environment-check.json` | `setup.sh`、`prepare_data.py`、`run.py`、`launch.py` | `preflight.json`、`paired-*.json` | `INITIAL_REPORT.md` |
| tb8 | `protocol.json`、`capture_provenance.py` | 镜像与依赖见协议 | `run.py`、`mini_preflight.py` | `results/*-summary.json` | `REPORT.md` |
| tb-eval | `config/protocol.json`、`config/base-images.json` | `bootstrap/` 固定 uv 0.7.13、pytest 8.4.1、镜像 ID | `scripts/run_round.ps1` | `results/<round>/` | `ANALYSIS.md` 的 D1–D6 |

## 读这些结论时要注意

- 四份复现用的都是**本地 Qwen3.5-9B Q4_K_M**（tb8 之外各自有说明），与原文的模型/后端不同；
  除 tb8 的 8 题内部对照外，都不构成与原文分数的数值比较。
- TB8 与 tb-eval 的任务集都是**开发期反复使用**的，不是留出集，不能当作泛化证据。
- `budget_wall`、评分器解析失败、judge 误判都属于**结果**，保留在报告里，不做二次修饰。
