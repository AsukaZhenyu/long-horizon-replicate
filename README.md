# Long Horizon Replicate

Horizon Weaver 的复现与评测证据库。

这里不放 Agent 实现——v0 / v1 / v2 三个版本的实现见
[horizon-weaver](https://github.com/AsukaZhenyu/horizon-weaver)。这里只放两样东西：
**别人方法的复现**，以及**对 Agent 的评测装置**。两者都要回答同一个问题：这个数字是怎么来的。

## 证据标准

复现的核心产出不是分数，是**完全的执行路径 + 实验报告**。一份复现算完成，要同时能回答：

| # | 问题 | 落在哪里 |
| --- | --- | --- |
| 1 | 复现的是谁、哪个版本 | 上游仓库 + 完整 commit SHA + 许可证，`sources.json` / `upstream.lock.json` |
| 2 | 环境到底是什么 | 解析后的依赖锁（`*.lock.txt`、`linux-wheels.lock.json`、`data-manifest.json`） |
| 3 | 怎么跑出来的 | README 里的命令序列 + `run.py` / `launch.py` / `run-sanity.sh` 入口 |
| 4 | 跑出了什么 | `reports/` 或 `results/` 里的 JSON/表格，**失败轨迹同样保留** |
| 5 | 该怎么信它 | 报告里写清与原文的差异（换模型、换后端、缩预算），以及哪些结论不成立 |

原始大文件（上游 clone、venv、日志、镜像上下文）不入库，留在被忽略的 `_work/`
（或 `.horizon/`）里，报告引用它们的路径。小体积、可核查的判定文件入库。

## 目录

```
reproductions/
  clm/        CLM 真实上下文编辑（ContextBench kv-store）
  mage/       MAGE 有界工程复现（MemoryArena math1）
  stateact/   StateAct / ReAct（ALFWorld，原生 runner）
  tb8/        历史 TB8 开发集上的 Terminus2 与 mini-swe-agent
experiments/
  tb-eval/    24 题分层评测装置（Pi+Spine 插件 vs Sentry 核心）
reports/      成稿的 Word 报告
docs/         实验规划与口径
```

一份方法一张表，见 [`REPRODUCTIONS.md`](REPRODUCTIONS.md)。

## 分支与标签

长期只有 `main` 一条分支，所有方法同处一棵树——跨方法对照表必须在同一个提交上读得出来。

| 类型 | 命名 | 用途 |
| --- | --- | --- |
| 长期分支 | `main` | 唯一的开发与阅读入口 |
| 短命分支 | `repro/<方法>` | 复现进行中才开，报告落地即合入 `main` 并删除 |
| 注记标签 | `repro/<方法>@<上游短 SHA>` | 冻结一份复现，标签注释含上游仓库、pin、报告路径、一行结论 |
| 存档标签 | `archive/<原分支名>` | 从 horizon-weaver 迁入前的原始 tip |

不要把方法做成长期分支：复现的标识是「方法 + 上游 pin + 报告」，那是标签的语义；
分支表达的是还在变化的东西。只有某个复现转成长期维护的移植（持续适配新模型/新数据）
才值得开 `port/<方法>`。

## 迁入来源

本仓库由 horizon-weaver 的实验分支按目录迁入，每份一次提交，提交信息写明来源：

| 目录 | 来源分支 | 来源提交 |
| --- | --- | --- |
| `reproductions/clm/` | `codex/repro-clm` | `e4bb7fa5e48690cc024d27b9a041f4bf5111d355` |
| `reproductions/mage/` | `codex/repro-mage` | `0df3efdfb84e6645d696199f99f96717b44bb67e` |
| `reproductions/stateact/` | `codex/repro-stateact` | `548c4ecd6a1b54da14c76f68f0fbf75830ae3f05` |
| `reproductions/tb8/` | `codex/repro-tb8` | `82aea933227a524b00d5029b9962cc00251b69b7` |
| `experiments/tb-eval/` | `codex/tb-eval-harness` | `7a5c305fec437c026603efb8a8b81a88016d7c4c` |

## 本机路径

每份复现都把自己的大文件放在被忽略的目录里，换机器后要重新准备（命令在各自的 README）：

| 目录 | 内容 |
| --- | --- |
| `_work/` | 上游 clone、虚拟环境、原始日志、镜像上下文 |
| `.horizon/reproductions/<方法>/` | StateAct 等按方法隔离的数据与 venv |
| `.cache/` | tb-eval 的 Terminal-Bench 检出、模型、镜像与逐题证据 |
| `_work/legacy/` | 从 horizon-weaver 迁入的历史证据，见下 |

### `_work/legacy/`

迁入时只搬运行记录，可重建的缓存（pip/npm wheel、上游 checkout、venv、镜像上下文）
按需保留或丢弃；这里的东西一律不入库，换机器要重跑才有。

| 子目录 | 内容 | 体积 |
| --- | --- | --- |
| `methods/<方法>/` | 四个复现的原始 runs / console / 清单；已剔除 venv、wheel、上游 clone | 约 38 MiB |
| `tb-eval-week8/` | round2/3/4 逐题证据与脚本、spine 与 sentry 的原始运行日志；其中 `grading-wheel-staging`、`spine/upstream`、`sentry/venv-appworld` 等缓存仍可重建 | 约 818 MiB |
| `week8-doc/` | 生成 Word 报告的脚本、报告源 txt、被取代的旧版 docx | 约 0.4 MiB |
| `week8-strat/` | 24 题分层抽样与镜像构建的设计记录 | 约 0.2 MiB |
| `horizon-weaver-repro-branches.bundle` | 四个 `codex/repro-*` 分支删除前的 git bundle；`git bundle verify` 可查，`git clone` 可从它恢复 | 0.7 MiB |

上表里的 `codex/repro-*` 分支已从 horizon-weaver 删除（那边只剩 `v0` / `v1` / `v2`），
内容在 [`迁入来源`](#迁入来源)一节按目录落到本仓库，历史则留在这个 bundle 里。

模型服务是外部的，两条评测轨道共用；`experiments/tb-eval/README.md` 记录了冻结的
启动参数。评测跑分之前先确认 `/health`，否则 502 会被误记成 Agent 失败。
