# RRSI → TB8 domain adapter (prompt-only evaluation)

RRSI 的官方 coding domain 是 Terminal-Bench 2.1 + Harbor，搜索角色（proposer /
analyst / critic）通过 AnthropicVertex 调 Claude Opus。本适配器把 **Evaluate()
这一半**接到本地 TB8：候选 harness 是 `domains/tb8/harness/system_prompt.txt`，
运行时用 Pi 1.1.0 + 本地 Qwen3.5-9B 跑 8 道历史题，A/V/Y 与 AB 冒烟完全同协议。

## 能跑什么

- 在本地 TB8 上评估一个候选 system prompt（一个“prompt-only harness”）。
- `smoke`、`run`、`score`、`load_trial`、`render_trace`、`task_row` 都按 RRSI
  的 `Domain` 接口实现。
- `k=1`，每题一次全新尝试；`rrsi.json` 的 `delta` 设为 null，需要时用 RRSI 的
  calibrate 重估。

## 不能跑什么

- **RRSI 的搜索环本身**：`rrsi/llm.py` 仍硬编码 `AnthropicVertex`，需要
  `RRSI_VERTEX_PROJECTS`。本机没有 Vertex，搜索环不能启动。
- 候选只能改 system prompt，不能改 Pi/Spine/Sentry 的代码、工具、预算或评分。
  这不是完整 RRSI harness 编辑空间；它是一个最小、可审计的 prompt-only 域。
- 没有 TB2.1 的 89 题和 Harbor；数字只与本地 TB8 冒烟比，不与论文 TB2.1 比。

## 安装

```powershell
# 把本目录复制到 RRSI checkout 的 domains/tb8/
Copy-Item -Recurse -Force experiments\tb-eval\adapters\rrsi `
  .cache\upstream\rrsi\domains\tb8
```

然后让 RRSI 用 `--domain tb8`；`HW_TB_EVAL_ROOT` 指向本仓库
（`G:\Documents\liuzhenyu\研一上\long-horizon-replicate`）。

## 运行前提

1. 模型 server 在 `127.0.0.1:8080`（Qwen3.5-9B，16k，`-ngl 26`）。
2. `.cache/round8/base-images.json` 和 8 个 `tb__<task>__client` 镜像存在。
3. RRSI 的 `domains/tb8/harness/system_prompt.txt` 存在。
4. 搜索环另需 Vertex；没有 Vertex 时只能手工调用 `score` 评估一个固定候选。

## 证据

`runs_dir/jobs/<job>/pi/cases/<task>/result.json`，与 AB 冒烟的 Pi-only 证据同格式。
`source.json` 的 `adapter` 字段是 `rrsi-tb8-prompt-only`，`candidateSystemPrompt`
记录候选 prompt 的 SHA-256。

## 已知差异

- 不是 RRSI 原论文的 TB2.1 设置；不能把本地 TB8 的分数写成 RRSI 论文成绩。
- 只支持 `k=1`；多 trial 需要扩展 `run` 的 runs 目录命名。
- 搜索环的 Claude 角色未替换成本地模型；本地 9B 是否适合做 proposer 未验证。
