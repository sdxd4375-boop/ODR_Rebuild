# Open Deep Research 技术总结文档

> **定位**：本文件汇总本轮全部技术工作的结论，是《代码库研究报告》（`RESEARCH_REPORT.md`）与
> 《前后端扩展实施方案》（`FULLSTACK_EXTENSION_PLAN.md`）的顶层索引与增量记录。
> **覆盖内容**：核心架构结论 → 前后端扩展与持久化落地 → 能力/耦合度评估 → token 计量方案 →
> 会话上下文与隔离 → 同类系统对标 → 两大不足的解决方案设计 → 总路线图。
> **基准**：v0.0.16 + 本轮外围扩展，2026-09-06。

---

## 目录

1. [系统是什么：核心架构结论](#一系统是什么核心架构结论)
2. [已落地的扩展：自研服务层 + 前端 + 持久化](#二已落地的扩展自研服务层--前端--持久化)
3. [当前能力与不足清单](#三当前能力与不足清单)
4. [模块耦合度评估](#四模块耦合度评估)
5. [token 用量记录与节约提效方案](#五token-用量记录与节约提效方案)
6. [会话上下文保存与跨会话隔离](#六会话上下文保存与跨会话隔离)
7. [同类系统对标结论](#七同类系统对标结论)
8. [两大不足的解决方案设计（待实施）](#八两大不足的解决方案设计待实施)
9. [总路线图](#九总路线图)

---

## 一、系统是什么：核心架构结论

**定位**：LangGraph 双层多智能体深度调研系统——澄清 → 研究简报 → 主管-研究员循环 → 压缩 → 引用报告。

**三张编译图**（均在 `deep_researcher.py` 模块导入时构建）：

```
主图 deep_researcher (:701-719)
  clarify_with_user (:60) → write_research_brief (:118)
  → research_supervisor（主管子图 :353-363）
      supervisor (:178) ⇄ supervisor_tools (:225)   ← 6 轮循环，asyncio.gather 派发 ≤5 路并行研究员 (:305)
      └── 研究员子图 (:589-605)：researcher (:365) ⇄ researcher_tools (:435) → compress_research (:511)
  → final_report_generation (:607)
```

**三个关键设计**：
- **上下文成本近恒定**：研究员的原始资料经 `compress_research` 压缩后回传主管（`compressed_research`），
  原始内容永不进入主管上下文——这是全系统最重要的节流与扩展性设计；
- **收窄的层间通道**：`ResearcherOutputState`（`state.py:92`）限定子图只输出压缩摘要与原始笔记；
- **`override_reducer`**（`state.py:55`）：支持节点整体替换状态列表，解决简报重置与 notes 清空。

**关键风险点**（上游代码，未修）：
- `deep_researcher.py:334` 的 `if is_token_limit_exceeded(...) or True:` —— **任何异常静默终止研究阶段**；
- `MODEL_TOKEN_LIMITS` 子串匹配误命中（`utils.py:831-846`）；
- `compress_research` 对消息列表原地 `.append()`（`deep_researcher.py:538`），与检查点快照假设相悖。

---

## 二、已落地的扩展：自研服务层 + 前端 + 持久化

采用**纯自研 FastAPI 方案**（而非 LangGraph 服务器 `http.app` 挂载），`langgraph.json` 与核心包零改动。

### 2.1 架构

```
web/ (Vite + React + TS, :5173 dev / dist 静态产物)
   │  HTTP + SSE（开发走 Vite 代理，生产同域托管）
   ▼
src/server/ (FastAPI :8000, uvicorn)
   ├── graphs.py   从 deep_researcher_builder 重新编译 + AsyncPostgresSaver  ← 持久化关键
   ├── deps.py     AUTH_MODE=local（免鉴权 + 成本钳制）| supabase（JWT）
   ├── db/models/migrations（SQLAlchemy async + Alembic）
   └── routers/    sessions（SSE 流式）+ health
   ▼
PostgreSQL 16（docker-compose.dev.yml）：检查点表（自动建）+ research_reports 业务表
```

### 2.2 接口与会话状态机

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | `{status, db, graph, auth_mode}`，子系统不可用时降级返回 |
| POST | `/api/sessions` | 创建会话，id 即 LangGraph thread_id |
| GET | `/api/sessions` / `/{id}` | 列表 / 详情（归档字段 + 检查点实时消息） |
| POST | `/api/sessions/{id}/runs/stream` | SSE：`node`（节点完成）/ `message`（LLM 增量）/ `done` / `error` |

状态机：`created → running → awaiting_input（澄清等待）| completed | failed`。
澄清续聊直接复用同 thread，检查点恢复上下文。

### 2.3 验证状态

- 单元测试 **13 passed**（`tests/server/test_server_unit.py`，无网络无 DB）；
- ruff 全部通过；前端 `npm run build` 通过；
- 无 DB 降级冒烟通过（503 + 明确提示、health false、静态托管 200）；
- **端到端持久化验证待用户启动 Postgres 后复验**（本机无 Docker/Postgres）。

---

## 三、当前能力与不足清单

**能力**：全链路调研闭环、SSE 流式 + 进度时间线、会话持久化与历史回看、澄清续聊、
双模鉴权 + 成本护栏（并发钳 1 / 迭代钳 2）、多模型多搜索热切换。

**不足**（按严重度）：

| # | 不足 | 性质 |
|---|---|---|
| 1 | `or True` 异常吞噬（`deep_researcher.py:334`） | 上游 bug，待修 |
| 2 | token 用量零记录，无配额 | 见 §五，方案已设计 |
| 3 | 可观测性弱（图节点零日志） | 工程债 |
| 4 | `MODEL_TOKEN_LIMITS` 手工维护 + 子串误匹配 | 工程债 |
| 5 | 检查点表无 TTL/清理策略 | 运维项 |
| 6 | MCP OAuth 不可用（服务进程未挂 Store） | 与 §八-记忆层同解 |
| 7 | 断线即中断 run，无后台任务 | 路线图 P1 |
| 8 | 配置优先级：环境变量 > 每次运行 configurable（`configuration.py:244`） | 反直觉，需文档警示 |
| 9 | 核心图零单测、CI 空白 | 路线图 P0 |

---

## 四、模块耦合度评估

**核心包（健康）**：`configuration/prompts/state（叶子）→ utils → deep_researcher` 严格单向无环。

**四个需要注意的耦合点**：

1. **提示词承载控制流**：迭代上限软约束（`prompts.py:103-110`）、防澄清死循环（`prompts.py:12`）
   藏在提示词里——改提示词可能改变行为，属隐性耦合；
2. **`utils.py` 上帝模块倾向**（880 行混装搜索/MCP/OAuth/token 判断）——§八的检索插件化同时是解耦手段；
3. **`configurable_model` 模块级单例**（`deep_researcher.py:56-58`）：模型切换零成本，但测试需 patch 模块属性；
4. **前后端隐性契约**：前端 `App.tsx` 硬编码节点名 `final_report_generation` 判断报告流——
   建议后端在 `message` 事件加 `kind: "report" | "dialog"` 字段消除。

**数据层**：业务表与检查点表逻辑解耦、物理共库（单库故障同损；升级依赖 `langgraph-checkpoint-postgres` 版本）。

---

## 五、token 用量记录与节约提效方案

**现状**：零计量。已有的只有各角色 `max_tokens` 上限、静态 token 表（用于截断）与可选 LangSmith 追踪。

### 5.1 记录方案（三个采集点 + 一个存储面）

| 采集点 | 位置 | 说明 |
|---|---|---|
| **A（推荐）** | `sessions.py` 的 `event_stream()` 消息分支 | 消息块的 `usage_metadata`（input/output/total）按节点累加；注意流式下 usage 通常只在最后一个 chunk，避免重复计 |
| B（兜底） | run 结束后 `aget_state` 遍历 messages 汇总 | 兜住流式中断场景 |
| C（对账） | LangSmith API 按 thread 汇总 | 覆盖 Anthropic 原生搜索等服务端工具消耗 |

存储：`usage_events` 表（`user_id, thread_id, node, model, input/output_tokens, cost_cents`），
在 `_archive()` 同事务写入；`done` 事件携带用量下发前端。配额表 `quotas` + 发起前校验（429）随之实现。

### 5.2 节约提效（按性价比排序）

1. **并发/迭代降档**：`max_concurrent_research_units` 5→2~3、`max_researcher_iterations` 6→3~4、
   `max_react_tool_calls` 10→5（`configuration.py:64/94/107`）——乘法关系，省 40–60%；
2. **摘要输入截断**：`max_content_length` 50000→20000（`configuration.py:141`）；
3. **模型分档**：摘要用 mini/nano，研究/压缩/报告用主力；
4. **修复摘要超时回退**：`utils.py:206-213` 超时返回原文反而更贵，改为返回截断原文；
5. **结果缓存**：相同查询 24h 复用；相同问题+配置直接返回历史报告；
6. **MCP 连接复用**（`utils.py:499-504` 每轮重连）；
7. **降低结构化重试** 3→2。

原则：**先计量、再调参**，每次调参用 `tests/run_evaluate.py` 小样本验证质量不回退。

---

## 六、会话上下文保存与跨会话隔离

### 6.1 保存：双层结构

- **LangGraph 检查点（完整状态）**：`AsyncPostgresSaver` 每个超步写入全部 `AgentState`，
  支撑重启恢复、澄清重入（`goto=END` + START 重入 + add_messages 追加）、断线后续跑；
- **业务归档表（查询快照）**：`research_reports` 存最终产物，详情接口优先取检查点实时值、归档表兜底。

缺口：检查点表无 TTL；`.append()` 原地突变与快照假设相悖（见 §一）。

### 6.2 隔离：三层机制、两层可靠

1. **thread_id 状态隔离**（可靠）：UUID4 不可枚举，并行研究员各自独立状态，结果只经
   `compressed_research`/`raw_notes` 通道回流；
2. **API 层用户隔离**（可靠）：`_get_session()` 校验 `row.user_id`，身份来自 JWT（supabase 模式）；
3. **数据库层隔离（不存在）**：检查点表无 user 列，隔离边界在 API 层——多租户强合规需分库或行级过滤。
   `src/security/auth.py` 的属主过滤只对 LangGraph 平台接口生效，`StudioUser` 豁免不应对外暴露。

**有意取舍**：完全隔离 = 跨会话零记忆。个性化记忆需挂 Postgres Store（user 命名空间），
同时解锁 `utils.py:293-383` 已预留的 MCP OAuth 令牌存取。

---

## 七、同类系统对标结论

对标对象：GPT Researcher（~29k stars）、DeerFlow 2.0（LangGraph 同栈）、STORM（强引用规范）、
HF open-deep-research（极简派）；上限参照 OpenAI/Gemini 闭源产品。

### 7.1 优胜点

1. **配置化/可移植性最强**：BYO 模型/搜索/MCP；
2. **架构级上下文成本控制**：压缩回传 vs 竞品递归展开的线性膨胀；
3. **澄清式交互内建于图** + 并行子研究员墙钟优势；
4. **唯一自带 LLM-as-judge 评估 harness 与公开榜绩**（Deep Research Bench RACE 0.4344，2025-08 时点）。

### 7.2 不足点（对比视角）

| 不足 | 对标差距 |
|---|---|
| 无记忆系统 | DeerFlow 已内置持久记忆与技能 |
| 无代码沙箱与数据产物 | DeerFlow 可执行 Python 出图/PPT |
| 引用无校验（纯提示词） | STORM/GPT-R 有校验机制 |
| 搜索生态窄 | GPT-R 多引擎 + 本地文档 RAG |
| 长任务无后台化 / token 零计量 / 零单测 | 产品级体验与工程成熟度 |

详见 PDF 报告：`docs/深度调研系统对标分析报告.pdf`。

---

## 八、两大不足的解决方案设计（待实施）

> 设计原则沿用已验证模式：**外围新增、内核少动**（全案内核改动 ≤10 行）。

### 8.1 搜索生态扩展（多引擎 + 本地文档 RAG）——约 4~5 天

**关键事实**：legacy 包已有 8 套完整搜索实现可直接改造——`arxiv_search_async`（`src/legacy/utils.py:577`）、
`pubmed_search_async`(:734)、`exa_search`(:374)、`duckduckgo_search`(:1248)、`linkup_search`(:882) 等；
工具装配咽喉唯一：`get_all_tools`（`src/open_deep_research/utils.py:569`）。

```
新文件 src/open_deep_research/retrievers.py
├── @tool duckduckgo_search / arxiv_search / pubmed_search   ← legacy 改造（同步函数包 asyncio.to_thread）
└── @tool local_docs_search                                   ← 查本地向量库，格式对齐 "--- SOURCE N ---"（utils.py:129-134）

内核唯一改动：
utils.py:569 get_all_tools() 末尾 + tools.extend(load_extra_retrievers(config))   # 默认 []
configuration.py 增量字段 extra_retrievers: list[str]                              # 不动 SearchAPI 枚举
```

本地文档 RAG 数据面（server 新增）：`POST/GET /api/documents`（pymupdf 切块 → 嵌入 → 入库）；
向量库选型建议 **Postgres + pgvector**（与现有库同栈，免中途换库）。
来源标注"文档名+页码"替代 URL，引用提示词链路零改动。

### 8.2 代码沙箱与数据产物——约 5 天（+P2 层 1~2 天）

**第一层：报告后处理管道（server 侧，内核零改动）**——在 `event_stream()` 拿到
`final_report` 后、`_archive()` 前插入：

```
图表生成：LLM 抽取数据点 → 生成 matplotlib 代码 → 受限执行 → PNG → 注入报告 Markdown
导出：POST /api/sessions/{id}/export/pptx|docx（python-pptx / python-docx）
```

**沙箱执行器环境阶梯**（本机无 Docker）：

| 档位 | 机制 | 适用 |
|---|---|---|
| 默认 | subprocess + import 白名单（matplotlib/numpy/pandas）+ 资源限制 + 断网 | 本地开发 |
| 生产 | Docker `--network none --memory 512m`，代码 stdin 注入 | 对外部署 |

安全红线：模型生成的代码**永不进主进程执行**；执行前强制 import 白名单校验。

**第二层（P2）**：`python_repl` 沙箱 tool 挂入同一 `extra_retrievers` 钩子，研究员调研中直接计算画图，
图表路径随 `raw_notes` → 压缩 → 报告链路上传；沙箱复用第一层执行器。

### 8.3 实施顺序（两案合并）

1. 钩子先行（0.5 天）：`extra_retrievers` + `get_all_tools` 改动——两案共用接触点；✅
2. DuckDuckGo + arXiv 适配（1 天，无 key 依赖，最小闭环）；✅
3. 本地文档 RAG（3 天）；✅
4. 沙箱执行器 + 图表管道（3.5 天）；✅
5. PPT/DOCX 导出（1.5 天）。✅

**实施状态（2026-09-06）：全部完成并通过 33 个单元测试。**
实际落点：`src/open_deep_research/retrievers.py`（三引擎 + 注册表）、
`src/open_deep_research/docstore.py`（零依赖向量索引：分块 + 余弦检索 + JSON 持久化，嵌入函数可注入）、
`src/server/sandbox.py`（AST 导入白名单 + `python -I` 隔离子进程 + 超时，受信 preamble 不参与校验）、
`src/server/charts.py`（LLM 抽数据 → 沙箱出图 → Markdown 注入，逐图故障隔离）、
`src/server/exporters.py` + `routers/export.py`（PPTX/DOCX 导出 + 按需出图端点）、
`routers/documents.py`（PDF/MD/TXT 上传入库，pymupdf 抽文本）。
内核改动共三处：`configuration.py` 增量字段 `extra_retrievers`、`utils.get_all_tools` 尾部一次
`tools.extend(...)`、`deep_researcher.py:334` 的 `or True` 异常吞噬修复（P0 项）。
同时落地 usage 计量：`UsageEvent` 模型 + 迁移 `0002` + SSE 流内按 (节点, 消息ID) 记录
usage_metadata（取每调用末次值防重复计数），`done` 事件携带用量。

合计约 9~10 个工作日；每步用现有单测 + 评估脚本回归兜底。

---

## 九、总路线图

| 阶段 | 内容 | 工期 | 状态 |
|---|---|---|---|
| ~~已完成~~ | 自研 FastAPI 服务层 + Postgres 持久化 + React 前端 | 4 人日 | ✅ 已落地（待 Postgres 端到端复验） |
| **P0**（1–2 周） | 修 `or True` bug ✅；单测+CI（部分：33 个单测 ✅，CI workflow 待建）；usage_events 计量 ✅；quotas 配额（待建）；引用校验节点（待建） | 1–2 周 | 部分完成 |
| **P1**（2–4 周） | Postgres Store 记忆层（解锁 MCP OAuth）（待建）；Retriever 插件化 + 本地文档 RAG ✅（§8.1）；run 后台化 + 完成通知（待建）；前端配置面板 + 报告导出（导出 ✅） | 2–4 周 | 部分完成 |
| **P2**（4–8 周） | 受限代码沙箱 + 图表内嵌 ✅（§8.2）；PPT 产物 ✅；评估进夜间 CI（待建）；多语言报告与引用格式化（待建） | 4–8 周 | 部分完成 |

**贯穿原则**：外围新增、内核少动；先计量、再调参；每个阶段以评估脚本验证报告质量不回退。

---

## 附：文档索引

| 文档 | 内容 |
|---|---|
| `docs/RESEARCH_REPORT.md` | 全量代码研究报告（架构/流程/难点逐行索引） |
| `docs/FULLSTACK_EXTENSION_PLAN.md` | 前后端扩展方案（§8 为本轮落地记录） |
| `docs/深度调研系统对标分析报告.pdf` | 同类系统对标分析（PDF，8 页） |
| `docs/TECHNICAL_SUMMARY.md` | 本文件 |
