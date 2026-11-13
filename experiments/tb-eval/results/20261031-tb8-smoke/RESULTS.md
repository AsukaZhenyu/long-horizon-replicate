# 实验结果：20261031-tb8-smoke

由 `python harness/export_results.py` 生成，勿手工编辑；解读写在 `ANALYSIS.md`。

A = 冻结产物通过原始测试；V = 预算内正常提交；Y = A×V。A 为 null 表示评分无效，不当作 0。

## Pi 1.1.0 + @spinejit/pi-spinejit 0.1.3

n=8  已跑=8  A=2  AInvalid=0  V=4  Y=2  

AInvalid 只统计「跑过但评分无效」的题；没跑的题是「无证据」，不算无效。

| 任务 | 层 | 组 | A | V | Y | 模型请求 | Agent 秒 | 评分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sqlite-db-truncate | H | debugging | 0 | 0 | 0 | 16 | 300.1 | {"failed": 1} |
| jq-data-processing | H | data | 0 | 0 | 0 | 4 | 7.0 | {"passed": 1, "failed": 13} |
| hello-world | H | file-operations | 1 | 1 | 1 | 2 | 14.2 | {"passed": 2} |
| regex-log | H | data | 0 | 0 | 0 | 1 | 203.2 | {"failed": 1} |
| cprofiling-python | H | debugging | 0 | 0 | 0 | 13 | 300.1 | {"failed": 2} |
| fix-permissions | H | system-administration | 0 | 1 | 0 | 3 | 24.0 | {"failed": 1} |
| log-summary | H | system-administration | 1 | 1 | 1 | 7 | 37.5 | {"passed": 3} |
| cancel-async-tasks | H | software-engineering | 0 | 1 | 0 | 2 | 43.7 | {"passed": 5, "failed": 1} |

## Sentry 0.11.0 core + controlled terminal host

n=8  已跑=8  A=4  AInvalid=0  V=6  Y=4  

AInvalid 只统计「跑过但评分无效」的题；没跑的题是「无证据」，不算无效。

| 任务 | 层 | 组 | A | V | Y | 模型请求 | Agent 秒 | 评分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sqlite-db-truncate | H | debugging | 0 | 0 | 0 | 7 | 300.1 | - |
| jq-data-processing | H | data | 0 | 1 | 0 | 10 | 143.2 | - |
| hello-world | H | file-operations | 1 | 1 | 1 | 6 | 48.8 | - |
| regex-log | H | data | 0 | 1 | 0 | 8 | 163.3 | - |
| cprofiling-python | H | debugging | 0 | 0 | 0 | 17 | 300.1 | - |
| fix-permissions | H | system-administration | 1 | 1 | 1 | 5 | 49.4 | - |
| log-summary | H | system-administration | 1 | 1 | 1 | 13 | 140.3 | - |
| cancel-async-tasks | H | software-engineering | 1 | 1 | 1 | 5 | 134.7 | - |

## Pi 1.1.0 (no Spine, base-agent control)

n=8  已跑=8  A=3  AInvalid=0  V=4  Y=3  

AInvalid 只统计「跑过但评分无效」的题；没跑的题是「无证据」，不算无效。

| 任务 | 层 | 组 | A | V | Y | 模型请求 | Agent 秒 | 评分 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sqlite-db-truncate | H | debugging | 0 | 0 | 0 | 11 | 300.1 | {"failed": 1} |
| jq-data-processing | H | data | 0 | 0 | 0 | 4 | 26.8 | {"passed": 1, "failed": 13} |
| hello-world | H | file-operations | 1 | 1 | 1 | 2 | 10.6 | {"passed": 2} |
| regex-log | H | data | 0 | 0 | 0 | 1 | 196.2 | {"failed": 1} |
| cprofiling-python | H | debugging | 0 | 0 | 0 | 10 | 300.1 | {"passed": 1, "failed": 1} |
| fix-permissions | H | system-administration | 1 | 1 | 1 | 6 | 36.2 | {"passed": 1} |
| log-summary | H | system-administration | 1 | 1 | 1 | 6 | 31.0 | {"passed": 3} |
| cancel-async-tasks | H | software-engineering | 0 | 1 | 0 | 2 | 53.3 | {"passed": 5, "failed": 1} |

