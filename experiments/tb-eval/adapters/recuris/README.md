# Recuris → TB8 adapter (m0-gate arm)

Recuris 的官方 TB2.1 适配器通过 Harbor + Terminus-2 运行。本目录把它对 TB8 的
**m0-gate 配置**接到现有 Pi 终端宿主上：使用固定的 seed Skill Memory
（`skill_memories/tb21_seed`），每道题开始时 seed 一次，之后每次模型请求前把
Recuris 渲染出的工作记忆追加到 system prompt；模型准备结束时调用
`check_completion`，若被 bounce，代理注入一条 `bash` 工具调用把纠正意见送回 agent。

## 跑什么、不跑什么

- **跑**：m0 + 完成门（`check_completion`）的 8 题执行冒烟；A/V/Y 与 Pi-only 使用同一宿主、模型、预算、评分器。
- **不跑**：`tta` 的 meta-agent patch 循环（跨尝试更新 Skill Memory）。它需要额外的
  proposer/analyst/critic 调用与多轮尝试；本轮只验证“记忆注入 + 完成门”链路。
- **不声称**：m0 的 Y 不是 Recuris 完整方法的收益；seed 记忆来自 TB2.1，不是 TB8 演化出来的。

## 结构

```
proxy.py     OpenAI 兼容代理：注入 Recuris 工作记忆，转发到真实模型 server
README.md    本文件
```

`proxy.py` 不修改 Pi、Spine、Sentry 或 Recuris 的算法源码；它只在模型请求边界
注入/转发。注入内容、轮次、响应状态写入 `--log` 指定的 JSONL。

## 启动

```powershell
# 1. 模型 server 在 8080（见 scripts/launch_model.ps1 或 README）
# 2. Recuris 记忆代理在 8081
.\.cache\venv\Scripts\python.exe experiments\tb-eval\adapters\recuris\proxy.py `
  --memory .cache\upstream\recuris\skill_memories\tb21_seed `
  --port 8081 --upstream http://127.0.0.1:8080 `
  --log .cache\recuris-adapter.jsonl

# 3. Pi host 指向代理，而不是直接指向 8080
powershell -NoProfile -ExecutionPolicy Bypass -Command @'
. .\experiments\tb-eval\.local\env.ps1
$env:HW_MODEL_URL = 'http://127.0.0.1:8081'
$env:HW_RUNS = Join-Path $repo '.cache\runs-tb8-recuris'
$env:HW_ADAPTER = 'recuris-m0-tb21-seed'
node .\experiments\tb-eval\harness\spine\run.mjs --pi-only --tasks hello-world
'@
```

`run.mjs` 的 Node 代理会把容器内请求转发到 `HW_MODEL_URL`（8081）；
`proxy.py` 再转发到 8080。容器内仍然是同一套 Pi 终端协议。

## 证据

| 内容 | 位置 |
| --- | --- |
| 逐题 result / agent-result / grading | `.cache/runs-tb8-recuris/pi/cases/<task>/` |
| Recuris 注入日志（轮次、块长度、状态） | `.cache/recuris-adapter.jsonl` |
| 代理自身日志 | `/tmp/recuris-proxy.log`（本机） |
| bridge fingerprint | `--dump` 指定的文件，默认 `.cache/recuris-adapter-fingerprint.json` |

## 已知差异

- 记忆包是 TB2.1 seed，不是 TB8 专用；它只提供通用的“终端闭环/验证”提示。
- 完成门通过合成 `bash` 工具调用实现 bounce，不是 Terminus-2 原生的反馈通道；
  它可能增加 prompt 长度，jq 这类大上下文题更容易触发 16k 上限。
- 没有实现 meta-agent patch 循环；工作记忆在整个 8 题中固定。
- `TerminalSkillBridge` 的 `write_tools` 默认是 `bash_command`；代理用 `observe_commands`
  记录 `bash` 回执，`write`/`edit` 不进入 receipt matcher；完成门主要依赖 bash 证据。
- 本适配器不修改 Recuris 的记忆演化；`tta` 的 meta-agent 多轮循环仍需另写。
