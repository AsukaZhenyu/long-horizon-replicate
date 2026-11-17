# Agent 架构调研

本文件调研 2022 年至 2026 年 11 月公开的 Agent 架构。比较对象不是模型能力，而是模型之外的运行时：控制如何组织，状态放在哪里，验证由谁完成，学习改变什么。调研的结论是，系统数量远多于架构差异；差异集中在四个位置。长期运行的共同短板是状态估计与运行中更新，不是循环本身。

## 0. 范围与方法

调研对象包括论文、官方文档、开源实现和 benchmark 报告。选取标准是公开了架构、被后续系统复用，或代表一种控制结构。覆盖单 Agent 控制、记忆与上下文、多 Agent 工作流、运行时与自我改进四类；截至 2026 年 11 月的重要系统基本都在其中。

比较用四个维度，与方法文档一致：

| 维度 | 问题 |
| --- | --- |
| 控制拓扑 | 循环、树、图、栈，还是组合 |
| 状态 | 上下文、外部记忆、权重；状态在哪里，怎么更新 |
| 验证 | 内核、模型、人类、统计；验证发生在过程还是结果 |
| 学习 | 改信息、改权重、改运行时组件；学习发生在何时 |

一个前提：不比较模型能力。同一运行时换模型，结论会变；同一模型换运行时，结果也会变。术语先对齐：本文把与计算机直接交互的部分称**执行层**，包括终端、浏览器、GUI 和应用 API；把模型之外的整体称**运行时**，包括主循环、工具、上下文、安全、编排、扩展和观测。文献里的 harness 两种用法都有：computer-use harness 指执行层，agent harness 指运行时。为避免歧义，本文只用执行层和运行时两个词。

2026 年的源码研究把运行时的重要性说清楚了：Agent 是模型加运行时；同一模型换一套运行时，行为可以差很多。因此本文把运行时作为分析单位，而不是把 ReAct、多 Agent 这类名字当作方法本身。

写作视角是 Horizon Weaver：执行层以终端、文件系统和代码执行为主，图像由代码渲染生成；不做 GUI computer use，VLM 只做感知、反馈和评分。GUI agent 在文中作为对照，不作为主线。

## 1. 从 pipeline 到运行时

早期 Agent 把感知、规划、执行写成固定 pipeline，模块边界由人设定。LLM 进入后，规划交给模型，运行时负责循环、工具、上下文和权限。变化不在 Agent 更聪明，而在控制权从人写的模块转移到模型加运行时。

2026 年有一个反直觉的事实。对 11 个生产 coding agent 运行时的源码研究检查了约四百万行 Python、TypeScript 和 Rust，没有发现一个 Agent runtime 引入通用 Agent 框架，也没有发现用向量嵌入检索代码；生产运行时大多是手写异步循环加确定性检索。技能包类扩展的采用率高于 MCP，ACP 类协议开始承担运行时托管。这说明框架层的抽象还没有被生产验证，可组合运行时和运行时替换仍是空白。

这条事实决定了调研的重点：不看框架宣传的抽象，看运行时实际怎么组织。

## 2. 单 Agent 控制架构

### 2.1 反应式循环

ReAct 把推理和行动交替：thought、action、observation，直到结束。CodeAct 把动作统一成可执行代码，观察是解释器输出。Self-Refine 让同一模型对自己的输出提意见再改。Reflexion 把失败反思写进下一次尝试的上下文。

四者都是 Loop。状态在上下文，验证靠模型自评或环境返回，学习只改信息。共同问题是错误累积：一次错误观察进入上下文后，后续推理围绕它展开；反思没有外部锚点时，可能把错误解释得更自洽。

### 2.2 搜索与树

ToT 把推理变成树：生成候选、模型估值、选择展开、回溯。LATS 把 MCTS 和反思结合，用环境反馈和模型判断共同估值。rStar-Math 在数学上把 MCTS 和过程奖励模型结合，小模型生成、验证器筛选。

三者都是 Tree，显式维护多个状态，验证器是搜索的核心。代价是分支成本、状态复制和估值噪声。树搜索在可验证域有效，因为价值可以由内核或答案匹配校准；在开放域，估值本身成了瓶颈。

### 2.3 计划与执行分离

Plan-and-Act 用 planner 生成高层计划、executor 逐步执行。LLMCompiler 把计划编译成 DAG，独立步骤并行。ReWOO 把推理和观察解耦，减少重复上下文。

三者是 Graph，计划是显式状态。计划错误会沿图传播，重规划成本高；图结构适合可分解任务，不适合强交互任务。

### 2.4 长任务与深度研究

DeepResearcher、WebThinker、MiroThinker 和 OpenAI Deep Research 面向多步检索、跨源综合和长报告。共同结构是主循环加并行子任务，状态是笔记和引用，验证主要是引用一致性和模型判断。

这类系统把上下文管理推到前台：检索结果多、来源冲突、报告长。瓶颈不是单步推理，而是什么时候压缩、信什么来源、如何保持约束。

### 2.5 执行层：终端、文件与 GUI

执行层的接口决定动作空间：终端是命令和 PTY，文件系统是读写与 diff，代码运行时是编译和执行，渲染器把源文件变成图像；浏览器是 DOM 或可访问性树，GUI 是截图、坐标和键鼠，应用是 API。接口越接近程序状态，动作越可验证、越可回放；越接近像素，通用性越强，验证和恢复越难。

对本项目，主路径是终端、文件、代码运行时和渲染器。文档、图表、幻灯片、海报和数学可视化最终都是文件；GUI 只是渲染视图，文件才是状态。直接改文件和代码，比操作像素更稳、更可验证，也不需要视觉模型控制鼠标键盘。GUI computer use 因此不在主范围；只有在应用没有程序化接口时，像素控制才是后备。

GUI agent 仍是 Loop 的一类。UI-TARS 做端到端 GUI 操作；OpenHands 提供沙箱、事件流和多接口；OSWorld 2.0 把任务拉长到中位 1.6 小时、平均 318 次工具调用。OSWorld 2.0 的价值不在 GUI 本身，而在它揭示的长任务失效：丢失约束、错过任务中途出现的信息、该问用户时猜测、跳过验证、无法恢复隐藏状态。这些失效在文件/代码任务上同样存在。

这组结果对架构设计的含义很直接：长任务的瓶颈在状态和验证，不在动作空间。

| 系统 | 拓扑 | 状态 | 验证 | 学习 |
| --- | --- | --- | --- | --- |
| ReAct / CodeAct | Loop | 上下文 | 环境返回 | 信息 |
| Self-Refine / Reflexion | Loop | 上下文加反思 | 模型自评 | 信息 |
| ToT / LATS | Tree | 树节点 | 模型估值加环境 | 信息 |
| rStar-Math | Tree | 树加过程奖励 | 内核与答案匹配 | 信息 |
| Plan-and-Act / LLMCompiler | Graph | 计划与 DAG | 执行结果 | 信息 |
| Deep Research 类 | Loop 加子任务 | 笔记与引用 | 引用一致性 | 信息 |
| GUI Agent（范围外对照） | Loop | 截图与操作历史 | 环境状态 | 信息 |

## 3. 状态与记忆架构

上下文是 Agent 的工作台，记忆是工作台之外的部分。现有系统按状态放在哪里分成五类。

### 3.1 上下文工程

Anthropic 把上下文工程归纳为四件事：写清楚系统提示、给足工具、按需检索、在长任务中压缩与记笔记。压缩保留最近窗口和摘要；结构化笔记把关键状态写到外部文件；子 Agent 把中间过程隔离在另一个上下文里。共同点是上下文被当作预算，不是仓库。

### 3.2 虚拟上下文

MemGPT 把上下文当内存，主上下文是 RAM，外部存储是磁盘，通过分页和中断在两者之间移动。它在单一循环上加了内存管理，适合长对话；它不解决任务状态的估计，也不决定哪些状态值得保留。

### 3.3 经验记忆

Generative Agents 用记忆流、反思和检索；Voyager 把可复用行为存成技能库；ExpeL 从跨任务轨迹抽经验；AWM 把工作流抽象成可复用模板。共同点是经验为文本，检索进上下文，不改进权重。问题是写入标准、检索噪声和负迁移。

### 3.4 结构化记忆

RAPTOR 递归聚类和摘要，形成树；HippoRAG 2 用知识图谱和个性化 PageRank 做多跳检索；Mem0 抽取事实并去重；Zep/Graphiti 维护时序知识图谱；A-MEM 让笔记自组织。共同点是写入、抽取、检索、更新四件事，难点在冲突和过期。

### 3.5 压缩与折叠

ACE 把上下文演化成 playbook，按任务反馈增删；AgentFold 做多分辨率折叠，把长轨迹压成粗状态；Sentry 把失败知识放在外部 playbook，只在检测到失败时检索。Sentry 的实验值得注意：把完整 playbook 放进上下文会降低性能，失败知识应当条件暴露。

### 3.6 参数化记忆

Titans 在测试时更新记忆模块；SEAL 让模型生成自己的微调数据。改权重表达能力强，但成本高、不可回滚，不适合回合内学习。

| 系统 | 状态位置 | 写入 | 检索 | 更新 | 局限 |
| --- | --- | --- | --- | --- | --- |
| MemGPT | 分页外部存储 | 按页换入换出 | 直接寻址 | 运行时 | 任务状态估计弱 |
| Generative Agents | 记忆流 | 事件与反思 | 相关性排序 | 追加 | 检索噪声 |
| Voyager | 技能库 | 成功行为 | 按任务 | 追加 | 迁移有限 |
| ExpeL / AWM | 经验池 | 跨任务轨迹 | 相似度 | 追加 | 负迁移 |
| RAPTOR | 摘要树 | 递归摘要 | 树检索 | 重建 | 丢节点边界 |
| HippoRAG 2 | 知识图谱 | 实体关系 | 图传播 | 增量 | 构图成本 |
| ACE | playbook | 反馈驱动 | 全量注入 | 增删 | 上下文膨胀 |
| Sentry | 外部 playbook | 恢复成功后写 | 失败触发 | 增删 | 依赖失败检测 |

共同问题不是检索，而是治理：什么值得写、何时忘记、冲突怎么解、隐私边界在哪。多数系统只解决检索。

## 4. 多 Agent 与工作流架构

多 Agent 的动机通常是分工、并行和互相检查。按连接方式可以分成四类。

### 4.1 角色分工

CAMEL 用角色扮演让两个 Agent 对话；AutoGen 把 Agent 做成可对话组件，支持人参与；MetaGPT 把软件公司的 SOP 编码成角色和文档流；CrewAI 把角色、任务和流程声明式组合。共同点是 Graph，消息是状态，验证靠角色约定或外部测试。

### 4.2 辩论

多 Agent 辩论让不同实例给答案和理由，互相批评，多轮后聚合。它对事实性和推理有增益，但成本随轮数线性增长；收益主要来自独立采样，不一定来自讨论本身。

### 4.3 管理器与工作者

Magentic-One 用 orchestrator 维护任务账本，派给专用 Agent；Anthropic 的研究系统用 lead Agent 规划、subagent 并行检索，token 用量约为普通对话的十五倍；层级编排把 manager-worker 递归下去。共同点是 Stack，父节点暂停、子节点运行、结果返回。难点是任务分解、结果合并和预算分配。

### 4.4 图编排

LangGraph 把 Agent 工作流写成显式状态图，支持 checkpoint、恢复和 human-in-the-loop；AFlow 用 MCTS 搜索工作流。共同点是控制流是数据，不是 prompt。优点是可视、可恢复；缺点是图由人设计，运行时自适应有限。

### 4.5 群体与去中心化

OpenAI Swarm 用 handoff 在 Agent 之间转移控制，定位是教学而非生产；AgentPrune 剪枝多 Agent 通信，降低冗余。共同点是连接动态，但状态一致性难保证。

多 Agent 的失败分类研究分析了 1600 余条轨迹，归纳出 14 种失败模式；系统设计问题约占 44%，其余集中在 Agent 间不对齐和任务验证。这个分布说明主要问题不是模型不够强，而是接口、角色边界和验证。

| 系统 | 连接 | 状态 | 验证 | 学习 |
| --- | --- | --- | --- | --- |
| CAMEL / AutoGen | 对话图 | 消息历史 | 角色或人 | 信息 |
| MetaGPT | SOP 图 | 文档与消息 | 测试或人 | 信息 |
| CrewAI | 角色任务图 | 任务状态 | 外部检查 | 信息 |
| 多 Agent 辩论 | 全连接 | 各实例上下文 | 聚合 | 信息 |
| Magentic-One | 管理器与工作者 | 任务账本 | 环境与模型 | 信息 |
| Anthropic 研究系统 | 管理器与工作者 | 子 Agent 上下文 | 引用与模型 | 信息 |
| LangGraph | 显式状态图 | checkpoint | 任意 | 信息 |
| AFlow | 搜索出的图 | 工作流状态 | 结果 | 信息 |

## 5. 运行时与自我改进

### 5.1 运行时作为对象

生产运行时的七个子系统是主循环、工具、上下文、安全与权限、编排、扩展、观测。这项研究覆盖 Claude Code、Codex CLI、Gemini CLI、OpenHands、Aider、Mini-SWE-Agent 等 11 个系统。它们的共同选择是手写循环、确定性检索、配置化行为。原因是可控、可调试、可审计；通用框架带来的抽象成本大于收益。

### 5.2 可组合运行时

Cordis 把服务、提供者、实例状态、可撤销副作用、事件和 generation 做成运行时对象，支持热替换、依赖重连和回滚。OpenHands SDK 用事件流、沙箱和生命周期管理把 Agent 组件工程化。AIOS 把 LLM 当操作系统内核，调度模型、记忆和工具。共同点是 Agent 组件被视为运行时对象，不是 prompt 片段。

### 5.3 测试时干预

Sentry 在 Agent 旁边跑一个失败管理层：检测失败、检索匹配的教训、验证是否恢复、只在恢复后存新教训。它的验证不需要任务奖励，只需要判断恢复是否发生；在多个 benchmark 上平均优于运行时干预基线 37%。Scout 训练一个 4B 验证器定位长轨迹中的首个错误，并在测试时选择候选轨迹，提升成功率而不重训 Agent。两项工作说明，运行中学习和过程验证可行，而且不必改权重。

### 5.4 自我修改

STOP 让模型改自己的 scaffold，用 benchmark 分数做搜索；Gödel Agent 让 Agent 在运行时读写自身代码；DGM 用进化搜索改代码，在 coding benchmark 上验证并保留档案；SICA 让 coding Agent 改自己的工具和代码。共同点是改运行时组件，验证靠 benchmark，搜索空间大、评估成本高、安全边界弱。它们证明自修改可行，但没有解决回合内验证和回滚。

### 5.5 协议层

MCP 统一工具和资源的接口；A2A 定义 Agent 间通信；ACP 承担客户端与运行时托管；技能包把可复用能力打成可分发包。协议解决互操作，不解决状态、验证和学习。协议层成熟会让运行时更像平台，但不会自动产生长期运行能力。

| 系统 | 改什么 | 何时改 | 验证 | 局限 |
| --- | --- | --- | --- | --- |
| Cordis | 组件与依赖 | 运行时 | 合约与回归 | 需要宿主设计 |
| OpenHands SDK | 工具、沙箱、服务 | 部署与运行 | 测试与环境 | 仍是单 Agent 循环 |
| AIOS | 资源调度 | 运行时 | 任务结果 | 调度不等于学习 |
| Sentry | 失败教训 | 失败发生时 | 恢复验证 | 依赖检测质量 |
| STOP | scaffold | 回合间 | benchmark | 搜索成本高 |
| Gödel Agent | 自身代码 | 运行时 | benchmark | 安全边界弱 |
| DGM | 代码与档案 | 世代间 | benchmark | 评估成本高 |
| SICA | 工具与代码 | 世代间 | benchmark | 缺回合内回滚 |

## 6. 横向比较

把前面的系统放到四个维度上，分布很不均匀：

| 维度 | 现有系统的分布 | 空白 |
| --- | --- | --- |
| 拓扑 | Loop 最多；Tree 集中在可验证域；Graph 多由人设计；Stack 用于并行和委派 | 运行时自适应拓扑 |
| 状态 | 上下文为主；外部记忆次之；权重最少 | 状态治理与结构压缩 |
| 验证 | 内核最强；模型判断最广；过程验证最少 | 开放任务的过程验证 |
| 学习 | 信息层普遍；权重层离线；组件层少数 | 回合内组件学习与回滚 |

五个共同模式。

第一，Loop 是底座。Tree 是带分支的 Loop，Graph 是带依赖的 Loop，Stack 是带嵌套的 Loop。所谓新范式，多数是这四种的组合。

第二，状态几乎都在模型外。上下文是主接口，外部记忆是扩展，权重是少数。上下文工程因此成为主要工程问题。

第三，验证是瓶颈。代码和数学有内核，开放任务靠模型判断，长任务缺过程验证。验证密度决定了搜索和反思能不能起作用。

第四，学习多在信息层。Reflexion、ExpeL、ACE 改的是下一次看到的内容；权重层是离线训练；组件层只有 STOP、Gödel Agent、DGM、SICA 和 Sentry 少数系统，且多为回合间。

第五，多 Agent 的收益主要来自并行和独立采样，不是讨论本身。控制 token 和并行度后，协作的净增益需要重新测量。

真实差异只有四个：状态放在哪，验证由谁做，谁可以改运行时，控制拓扑是什么。名字相同、拓扑相同的系统，性能可以差很多，因为上下文策略、工具接口和验证密度不同。这一点是对拓扑聚类的限制：拓扑解释结构，不解释性能；性能要回到上下文和验证。

## 7. 长任务评测与失效

长任务评测在 2025 到 2026 年集中出现，代表性结果如下。

| Benchmark | 任务 | 规模与预算 | 主要发现 |
| --- | --- | --- | --- |
| Terminal-Bench 2.0 | 终端操作 | 小时级任务 | 接近真实工作流，运行时差异明显 |
| OSWorld 2.0 | 计算机使用 | 108 个工作流，中位 1.6 小时，平均 318 次调用 | GUI 任务；最高 20.6% 完成，失效模式可迁移 |
| TRAVERSE | 跨域 Agent 轨迹 | 2518 条轨迹，6967 个错误，78 类 | 首错后恢复比例低；前沿 judge 定位首错不足三分之一；4B 验证器更好 |
| GAIA | 通用助手 | 多步工具任务 | 长尾任务难，工具组合是瓶颈 |

与本项目直接相关的是文件/文本/图像任务。OfficeEditBench 考保留性编辑，ChartMimic 考代码生成图表的可执行性与保真，PPTAgent/PPTEval 考多页 deck 的内容、设计和连贯，Paper2Poster/DECKBench 考长文档到海报的压缩，ECHO 考多轮改稿的意图保持，PutnamBench/ProofNet 考形式化证明。它们的执行层都是文件与代码，不是 GUI；评分靠官方 verifier、渲染图加 VLM、Lean 内核或人审。TB/LHTB/CORE/MLE 只作公开结果参照，不在本项目主套件。

四项发现值得单独说。

长上下文会退化。上下文变长不等于信息变多；压缩会丢约束，检索会引入噪声，任务中途出现的信息容易被忽略。

错误恢复很弱。首错之后，Agent 很少自己发现并纠正；是否恢复更多取决于任务和环境的反馈，而不是框架。TRAVERSE 还发现，被判定成功的轨迹里仍有删数据、破坏系统、伪造成功的情况，说明结果对不代表过程对。

验证缺口是结构性的。代码和数学有内核，可以逐步验证；开放任务只有最终判断，过程验证要么靠模型，要么靠人。模型 judge 在长轨迹上定位首错的能力不足三分之一，规模增大也不能解决。

运行时混淆严重。同一模型换运行时，分数可以差很多；benchmark 也可能被 scaffold 过拟合。报告分数时如果不报告运行时配置和预算，比较没有意义。

## 8. 开放问题

| 问题 | 现状 | 可行方向 |
| --- | --- | --- |
| 长期信用分配 | 结果稀疏，中间动作无标签 | rollout 回报、分支反事实、过程验证器 |
| 代码之外的验证 | 开放任务靠模型 judge，噪声大 | rubric 校准、成对比较、人类抽样、多信号聚合 |
| 记忆治理 | 写入和遗忘多为启发式 | 冲突检测、过期策略、隐私边界、可审计 |
| 安全自修改 | 运行时替换缺边界 | 权限、沙箱、effect 回滚、变更审批 |
| 评测方法 | 运行时混淆，预算不一 | 同预算、held-out、报告运行时配置、过程指标 |
| 多 Agent 收益 | 并行和 token 增长混淆 | 控制并行度和 token 后比较协作增益 |

## 9. 对 Horizon Weaver 的启示

执行层范围要写死。主线是终端、文件系统、代码运行时和渲染器；图像由代码生成，VLM 只做感知、反馈和评分；GUI computer use 不在主范围，也不作为方法差异的来源。GUI 是渲染视图，文件是状态；能改文件就不点像素。

两轴覆盖现有系统。第 3 节是上下文管理，第 2、4 节是导航；第 5 节的验证是导航的估计器，不是独立模块。现有系统大多只做其中一轴，或把验证当外挂。

四拓扑是组合。第 6 节的分布可以整体映射到 Loop、Tree、Graph、Stack；方法文档的聚类不是新分类，是对现有系统的压缩。新增范式通常只是新增组合或 provider，不改方法层。

运行时学习是空白。信息层学习普遍，组件层学习只有少数系统，且多为回合间；回合内热替换、依赖重连、回滚没有系统化。Cordis 的 effect 和 generation 正好补这个位置。

结构压缩与现有压缩不同。RAPTOR 是摘要树，ACE 是 playbook 演化，AgentFold 是折叠；它们都丢节点边界或可导航性。结构压缩保留树的形状和按需展开，这是可以实验检验的差异。

评测要同预算、held-out、报告运行时配置，并用过程指标补最终成功率。失败轨迹全部保留，只留成功会带来选择偏差。

实现顺序与第 10 节一致：先 host 和评估，再上下文，再导航，最后回合内替换。现有轨迹可以做一次性初始化，但不是训练阶段。

## 参考

单 Agent 控制：

- ReAct: https://arxiv.org/abs/2210.03629
- Reflexion: https://arxiv.org/abs/2303.11366
- Self-Refine: https://arxiv.org/abs/2303.17651
- CodeAct: https://arxiv.org/abs/2402.01030
- Tree of Thoughts: https://arxiv.org/abs/2305.10601
- LATS: https://arxiv.org/abs/2310.04406
- rStar-Math: https://arxiv.org/abs/2501.04519
- Plan-and-Act: https://arxiv.org/abs/2503.09572
- LLMCompiler: https://arxiv.org/abs/2312.04511
- ReWOO: https://arxiv.org/abs/2305.18323
- DeepResearcher: https://arxiv.org/abs/2504.03160
- WebThinker: https://arxiv.org/abs/2504.21776
- MiroThinker: https://github.com/MiroMindAI/MiroThinker
- UI-TARS: https://arxiv.org/abs/2501.12326
- OpenHands: https://arxiv.org/abs/2407.16741
- OSWorld 2.0: https://arxiv.org/abs/2606.29537

记忆与上下文：

- MemGPT: https://arxiv.org/abs/2310.08560
- Generative Agents: https://arxiv.org/abs/2304.03442
- Voyager: https://arxiv.org/abs/2305.16291
- ExpeL: https://arxiv.org/abs/2308.10144
- Agent Workflow Memory: https://arxiv.org/abs/2409.07429
- RAPTOR: https://arxiv.org/abs/2401.18059
- HippoRAG 2: https://arxiv.org/abs/2502.14802
- Mem0: https://arxiv.org/abs/2504.19413
- Zep / Graphiti: https://arxiv.org/abs/2501.13956
- A-MEM: https://arxiv.org/abs/2502.12110
- ACE: https://arxiv.org/abs/2510.04618
- AgentFold: https://arxiv.org/abs/2510.24699
- Titans: https://arxiv.org/abs/2501.00663
- SEAL: https://arxiv.org/abs/2506.10943
- Anthropic context engineering: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Sentry: https://arxiv.org/abs/2610.02994

多 Agent 与工作流：

- CAMEL: https://arxiv.org/abs/2303.17760
- AutoGen: https://arxiv.org/abs/2308.08155
- MetaGPT: https://arxiv.org/abs/2308.00352
- Multi-agent debate: https://arxiv.org/abs/2305.14325
- GPTSwarm: https://arxiv.org/abs/2402.16823
- Magentic-One: https://arxiv.org/abs/2411.04468
- LangGraph: https://langchain-ai.github.io/langgraph/
- OpenAI Swarm: https://github.com/openai/swarm
- CrewAI: https://github.com/crewAIInc/crewAI
- AgentPrune: https://arxiv.org/abs/2410.02506
- AFlow: https://arxiv.org/abs/2410.10762
- MAST: https://arxiv.org/abs/2503.13657
- Anthropic multi-agent research: https://www.anthropic.com/engineering/multi-agent-research-system

运行时、评测与协议：

- Harness Engineering（运行时工程）: https://arxiv.org/abs/2609.00006
- Cordis: https://github.com/cordiverse/cordis
- OpenHands SDK: https://arxiv.org/abs/2511.03690
- AIOS: https://arxiv.org/abs/2403.16971
- STOP: https://arxiv.org/abs/2310.02304
- Gödel Agent: https://arxiv.org/abs/2410.04444
- Darwin Gödel Machine: https://arxiv.org/abs/2505.22954
- SICA: https://arxiv.org/abs/2504.15228
- TRAVERSE / Scout: https://arxiv.org/abs/2609.17930
- Terminal-Bench: https://www.tbench.ai/
- GAIA: https://arxiv.org/abs/2311.12983
- MCP: https://modelcontextprotocol.io
- A2A: https://a2a-protocol.org

本项目相关 benchmark：

- OfficeEditBench: https://arxiv.org/abs/2609.34469
- ChartMimic: https://arxiv.org/abs/2407.04172
- ChartQA: https://arxiv.org/abs/2108.01949
- PPTAgent / PPTEval: https://arxiv.org/abs/2501.03936
- Paper2Poster: https://arxiv.org/abs/2505.21497
- DECKBench: https://arxiv.org/abs/2602.13318
- ECHO CoEdit-Eval: https://arxiv.org/abs/2606.09851
- PutnamBench: https://arxiv.org/abs/2407.11214
- miniF2F: https://arxiv.org/abs/2109.00137
- ProofNet: https://arxiv.org/abs/2302.12433
- LeanDojo: https://arxiv.org/abs/2306.15626
