# 架构升级实施计划（部署基线 → RAG 升级 → 价值闭环 → 可选脱钩）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"主干通、支线断、部署即坏"的魔改 open_deep_research 基线修至可部署，并按 DeepSearcher / LocalRAG 对照补齐 RAG 质量与私有化能力，最终形成"公网多源 + 私有语料"深度研究产品的差异化价值。

**Architecture:** 分六阶段：P0 部署基线修复（本计划含完整代码级任务）；P1 docstore→pgvector + embedding provider 抽象；P2 混合检索与重排；P3 报告回流 / 双向溯源 / per-session 知识库绑定；P4 工程完备性（诊断端点、e2e 测试、容器化、SearXNG 决策、前端补齐）；P5 可选的 LangChain 脱钩资产提取。P1–P5 在本计划中为任务级路线图，动工前各阶段须再用 writing-plans 细化为代码级计划。

**Tech Stack:** Python 3.10+ / uv、FastAPI + SSE、LangGraph 1.2.9（P5 前保留）、Postgres 16 → pgvector/pgvector:pg16、SQLAlchemy 2 async + asyncpg、alembic、Vite 8 + React 19。

**Spec / 证据来源:** 2026-09-18 会话审计报告（未落盘为独立 spec，关键证据已内嵌于本文各任务的"来源"字段）。仓库：`G:\Code\open_deep_research`；对照项目：`G:\Code\deep-searcher-master\deep-searcher-master`（Zilliz DeepSearcher）、`hicoldcat/LocalRAG`。

## Global Constraints

- 依赖只经 uv 管理（`uv add <pkg>`），不手工编辑 uv.lock。
- `tests/server/` 必须保持离线可跑（无网络、无数据库）；依赖 PG 的新测试一律用 `pytest.mark.skipif(os.environ.get("ODR_TEST_PG") != "1", ...)` 隔离。
- Windows + Git Bash 开发环境：路径用 `os.path.join`，命令用 POSIX sh 语法。
- 内核 `src/open_deep_research/` 仅允许触碰 `configuration.py`、`utils.py`、`deep_researcher.py`、`retrievers.py`、`docstore.py`，保持 `langgraph.json` 与 Studio 调试路径不受影响。
- `.env` 不提交；模板改动只落 `.env.example`。
- 每个任务一个 commit；commit message 用 `fix(scope): ...` / `feat(scope): ...`。

---

## 差距来源（审计 + 对照项目 → 补齐任务映射）

| # | 不足（证据） | 对标来源 | 补齐任务 |
|---|---|---|---|
| G1 | SSE 未开 subgraphs，子图事件与 token 全丢（`sessions.py:293`） | — | T3 |
| G2 | server 不 load `.env`（仅 `migrations/env.py:17`）；`.env.example:21` 与 compose 端口/密码双错（5432/odr vs 5433/nodr） | — | T1 |
| G3 | `alembic.ini:89` 占位 DSN 短路 `env.py:25`，迁移体系失效 | — | T2 |
| G4 | 工具重名 conflict-check 死代码（`utils.py:601-605`，update 后无人读取） | — | T4 |
| G5 | embedding 只支持 `openai:` 云端（`docstore.py:33-36`），"私有"名不副实；无本地模型档 | DeepSearcher 17 LLM/15 embedding 工厂；LocalRAG sentence-transformers | P1 |
| G6 | docstore 全局 JSON 文件 + 进程级单例、无 user/KB 隔离（`docstore.py:64,148-156`） | LocalRAG 多知识库独立 collection；DeepSearcher `collection_router.py:106-128` | P1 / P3 |
| G7 | 检索为纯 dense top-5 余弦，无混合无重排（`docstore.py:134-145`） | DeepSearcher `deep_search.py:33` RERANK_PROMPT 逐 chunk YES/NO | P2 |
| G8 | 引用是 prompt 层 `SOURCE N` 约定，结构化溯源（doc_id/page/score）不回传前端 | DeepSearcher reference 入库即绑定贯穿 RetrievalResult；LocalRAG `chat/prompt.py build_sources()` | P3 |
| G9 | 无成本归因报表、无检索质量评估闭环 | DeepSearcher 每步累计 `total_tokens` 返回（`deep_search.py:214-257`）+ `evaluation/`（2WikiMultiHopQA Recall@K） | P3 / P4 |
| G10 | 迭代次数由 LLM tool-call 自主决定，成本不可控 | DeepSearcher `max_iter` 显式 + `_check_has_enough_info` 早停 | P2（gap 迭代检索）|
| G11 | 内核深度绑定 LangGraph runtime（19 处 import，checkpointer 为真依赖） | DeepSearcher 零框架自研 loop | P5 |
| G12 | SearXNG+nginx 死基础设施、6/10 端点前端零入口、health 恒 200、async 端点内同步阻塞 | LocalRAG 诊断面板 / 一键 sidecar | P4 |

---

## P0：部署基线修复（本计划范围内，完整 TDD）

### Task 1: server 启动加载 .env + 补齐 .env.example

**Files:**
- Modify: `src/server/deps.py`（新增 `ensure_env_loaded()`）
- Modify: `src/server/app.py:18-31`（lifespan 首行调用）
- Modify: `.env.example:21`（DSN 对齐 compose）+ 文末追加扩展变量段
- Test: `tests/server/test_server_unit.py`

**Interfaces:**
- Produces: `ensure_env_loaded() -> None`（幂等，进程内只真正加载一次）
- Consumes: 无

- [ ] **Step 1: 写失败测试**

在 `tests/server/test_server_unit.py` 追加：

```python
def test_ensure_env_loaded_reads_env_file(tmp_path, monkeypatch):
    import os
    from server import deps
    (tmp_path / ".env").write_text("ODR_SENTINEL_KEY=loaded_ok\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ODR_SENTINEL_KEY", raising=False)
    deps._env_loaded = False          # 重置幂等标记
    deps.ensure_env_loaded()
    assert os.environ["ODR_SENTINEL_KEY"] == "loaded_ok"
    monkeypatch.delenv("ODR_SENTINEL_KEY", raising=False)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/server/test_server_unit.py::test_ensure_env_loaded_reads_env_file -v`
Expected: FAIL（`AttributeError: module 'server.deps' has no attribute 'ensure_env_loaded'`）

- [ ] **Step 3: 最小实现**

`src/server/deps.py` 末尾追加（文件头 import 区补 `import os` 若缺）：

```python
_env_loaded = False

def ensure_env_loaded() -> None:
    """Load repository .env into os.environ (idempotent, non-override)."""
    global _env_loaded
    if _env_loaded:
        return
    from dotenv import load_dotenv
    load_dotenv(override=False)
    _env_loaded = True
```

`src/server/app.py:19-21` lifespan 内、`db.init_engine()` 之前插入一行：

```python
async def lifespan(app: FastAPI):
    """Initialize DB + graph on startup; record readiness flags for /api/health."""
    deps.ensure_env_loaded()
    app.state.db_ready = await db.init_engine()
```

（`app.py:11` 已有 `from server.deps import auth_mode`，改为 `from server import deps` 并同步调用点，或在原 import 追加 `ensure_env_loaded`。）

依赖检查（一次性）：Run `grep dotenv pyproject.toml || uv add python-dotenv`

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `uv run pytest tests/server -q`
Expected: 34 passed（原 33 + 新 1）

- [ ] **Step 5: 更新 `.env.example`**

第 21 行替换为与 `docker-compose.dev.yml` 一致的值：

```
DATABASE_URL=postgresql+asyncpg://postgres:nodr@localhost:5433/nodr
```

文末追加：

```
# ---------------------------------------------------------------------------
# 扩展检索器与本地文档（src/open_deep_research/retrievers.py, docstore.py）
# ---------------------------------------------------------------------------
# 全局兜底：运行时未显式传 extra_retrievers 时启用（逗号分隔：duckduckgo,arxiv,local_docs）
EXTRA_RETRIEVERS=
# 本地文档索引目录（JSON 存储，P1 迁移 pgvector 后废弃）
ODR_DOCS_DIR=data/docs
# docstore 嵌入模型，格式 provider:model（当前仅支持 openai:）
EMBEDDING_MODEL=openai:text-embedding-3-small
# 图表输出目录（server/routers/charts 使用）
ODR_CHARTS_DIR=data/charts
```

- [ ] **Step 6: 提交**

```bash
git add src/server/deps.py src/server/app.py .env.example tests/server/test_server_unit.py pyproject.toml uv.lock
git commit -m "fix(server): load .env at startup and align .env.example with compose"
```

> 注：本地已有 `.env`（未跟踪），执行者需手工把其 `DATABASE_URL` 改为 5433/nodr 值。

---

### Task 2: 激活 alembic 迁移

**Files:**
- Modify: `alembic.ini:89`
- Test: 命令验证（无单测——纯配置）

**Interfaces:**
- Consumes: T1 的 `.env`（`env.py:17` 自行 load_dotenv，但依赖正确 DSN）
- Produces: 可用的 `alembic upgrade head`（P1 的 0003 迁移依赖此）

- [ ] **Step 1: 清空占位 DSN**

`alembic.ini:89`：

```ini
# 原: sqlalchemy.url = driver://user:pass@localhost/dbname
sqlalchemy.url =
```

留空后 `migrations/env.py:25-32` 的 `DATABASE_URL` 注入分支即生效（该逻辑已在库中，无需改动）。

- [ ] **Step 2: 端到端验证**

```bash
docker compose -f docker-compose.dev.yml up -d postgres
uv run alembic upgrade head
uv run alembic current
```
Expected: `0002_usage_ledger (head)`；重跑 `upgrade head` 幂等无报错。

- [ ] **Step 3: 提交**

```bash
git add alembic.ini
git commit -m "fix(migrations): blank placeholder sqlalchemy.url so DATABASE_URL is honored"
```

---

### Task 3: SSE 全量事件流（subgraphs + 可测试映射函数）

**Files:**
- Modify: `src/server/routers/sessions.py:289-324`（`event_stream` 循环体）
- Test: `tests/server/test_server_unit.py`

**Interfaces:**
- Produces: `_map_stream_item(ns, mode, payload, usage_acc) -> tuple[list[tuple[str, dict]], str | None]`（纯函数）；SSE `node` 事件 data 新增 `subgraph: bool` 字段（前端向后兼容，忽略即可）
- Consumes: 既有 `_sse(event, data)`（`sessions.py:62-64`）、`_extract_text`、`aggregate_usage`

- [ ] **Step 1: 写失败测试**

```python
from types import SimpleNamespace
from server.routers.sessions import _map_stream_item

def test_map_updates_root_report():
    events, report = _map_stream_item(
        (), "updates", {"final_report_generation": {"final_report": "R"}}, {}
    )
    assert events == [("node", {"node": "final_report_generation", "subgraph": False})]
    assert report == "R"

def test_map_updates_subgraph_node_emitted():
    events, report = _map_stream_item(
        ("research_supervisor:abc",), "updates", {"researcher": {}}, {}
    )
    assert events == [("node", {"node": "researcher", "subgraph": True})]
    assert report is None

def test_map_messages_collects_usage_and_text():
    chunk = SimpleNamespace(
        id="m1", content="hi",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        response_metadata={"model_name": "test-model"},
    )
    acc = {}
    events, _ = _map_stream_item(
        ("supervisor:x",), "messages", (chunk, {"langgraph_node": "researcher"}), acc
    )
    assert acc[("researcher", "m1")] == {
        "input": 1, "output": 2, "total": 3, "model": "test-model"
    }
    assert events == [("message", {"node": "researcher", "content": "hi"})]

def test_map_messages_usage_keyed_per_message_not_overwritten():
    # 回归：研究员子图内多条消息必须各自计入（旧实现只收根节点）
    c1 = SimpleNamespace(id="m1", content="", usage_metadata=None, response_metadata=None)
    acc = {}
    events, _ = _map_stream_item(("s:x",), "messages", (c1, {"langgraph_node": "r"}), acc)
    assert events == [] and acc == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/server/test_server_unit.py -k map_stream -v`
Expected: FAIL（`ImportError: cannot import name '_map_stream_item'`）

- [ ] **Step 3: 实现纯函数并接入**

`sessions.py` 中 `_sse` 附近新增：

```python
def _map_stream_item(ns, mode, payload, usage_acc):
    """Translate one astream item (with subgraph namespace) into SSE events.

    Returns (events, final_report_or_None). Kept pure so tests can cover the
    event contract without a live graph.
    """
    events: list[tuple[str, dict]] = []
    report: str | None = None
    if mode == "updates":
        for node, update in (payload or {}).items():
            if node == "final_report_generation" and update:
                report = update.get("final_report") or None
            events.append(("node", {"node": node, "subgraph": bool(ns)}))
    else:  # messages: (chunk, metadata)
        chunk, metadata = payload
        node = (metadata or {}).get("langgraph_node", "")
        um = getattr(chunk, "usage_metadata", None)
        if um and getattr(chunk, "id", None):
            # Last chunk per (node, message id) wins — see aggregate_usage.
            usage_acc[(node, chunk.id)] = {
                "input": um.get("input_tokens", 0),
                "output": um.get("total_tokens", um.get("output_tokens", 0) + um.get("input_tokens", 0)),
                "total": um.get("total_tokens", 0),
                "model": (getattr(chunk, "response_metadata", {}) or {}).get("model_name"),
            }
        content = _extract_text(getattr(chunk, "content", ""))
        if content:
            events.append(("message", {"node": node, "content": content}))
    return events, report
```

`event_stream` 内 `sessions.py:293-324` 的整个 `async for` 块替换为：

```python
            async for ns, mode, payload in graph.astream(
                inputs, config,
                stream_mode=["updates", "messages"],
                subgraphs=True,
            ):
                events, report = _map_stream_item(ns, mode, payload, usage_acc)
                for name, data in events:
                    yield _sse(name, data)
                final_report = report or final_report
```

（循环之后的 `aget_state` 状态推断、`aggregate_usage`、`_record_usage`、`_archive`、`done` 帧保持不变。）

- [ ] **Step 4: 运行确认通过 + 回归**

Run: `uv run pytest tests/server -q` → Expected: 全部通过
Run: `uvx ruff check src/server tests/server` → 0 violations

- [ ] **Step 5: 手工端到端验证（需 API key 与 PG）**

启动 server，`curl -N` 跑一个真实研究会话，Expected: `node` 事件流中能看到 `researcher` / `compress_research` / `supervisor_tool_node` 等子图节点，`done.usage.total` 显著大于修复前（研究员 token 计入）。

- [ ] **Step 6: 提交**

```bash
git add src/server/routers/sessions.py tests/server/test_server_unit.py
git commit -m "fix(server): stream subgraph events and usage via astream(subgraphs=True)"
```

---

### Task 4: 工具重名去重真正生效（清除死代码）

**Files:**
- Modify: `src/open_deep_research/utils.py:597-607`
- Test: `tests/server/test_extensions.py`

**Interfaces:**
- Consumes: `load_extra_retrievers(config)`（`retrievers.py:198`）
- Produces: `get_all_tools` 返回的列表内工具名唯一（extra 与内置/MCP 重名时丢弃 extra）

- [ ] **Step 1: 写失败测试**

```python
def test_conflicting_extra_retrievers_dropped(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import open_deep_research.utils as U
    import open_deep_research.retrievers as R

    async def fake_load(config=None):
        return [SimpleNamespace(name="think_tool"), SimpleNamespace(name="arxiv_search")]
    async def fake_search(api):
        return []
    async def fake_mcp(config, names):
        return []

    monkeypatch.setattr(R, "load_extra_retrievers", fake_load)
    monkeypatch.setattr(U, "get_search_tool", fake_search)
    monkeypatch.setattr(U, "load_mcp_tools", fake_mcp)
    tools = asyncio.run(U.get_all_tools({"configurable": {"search_api": "none"}}))
    names = [t.name for t in tools]
    assert names.count("think_tool") == 1      # 重名 extra 被丢弃
    assert "arxiv_search" in names             # 新名字正常加入
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/server/test_extensions.py::test_conflicting_extra_retrievers_dropped -v`
Expected: FAIL（当前实现无条件 extend，`count == 2`）

- [ ] **Step 3: 实现**

`utils.py:597-607` 替换为：

```python
    # Add optional pluggable retrievers (duckduckgo / arxiv / local_docs, ...),
    # dropping any whose name collides with a tool assembled above.
    from open_deep_research.retrievers import load_extra_retrievers

    for extra in await load_extra_retrievers(config):
        name = extra.name if hasattr(extra, "name") else extra.get("name", "")
        if name and name not in existing_tool_names:
            tools.append(extra)

    return tools
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest tests/server -q` → Expected: 全部通过
（若 Step 1 因 `search_api="none"` 枚举解析报错，改测 `{"configurable": {"search_api": "none"}}` 前先 `monkeypatch.setenv("SEARCH_API", "none")`。）

- [ ] **Step 5: 提交**

```bash
git add src/open_deep_research/utils.py tests/server/test_extensions.py
git commit -m "fix(core): enforce tool-name conflict check for extra retrievers"
```

---

### Task 5: 基线冒烟验收（配置项，无代码）

- [ ] **Step 1: 冷启动全流程**

```bash
docker compose -f docker-compose.dev.yml up -d
uv run alembic upgrade head
uv run uvicorn server.app:app --app-dir src --port 8000
curl -s localhost:8000/api/health
```
Expected: health 响应中 db/graph 就绪标志为真（当前 health 恒 200，字段见 `routers/health.py:10-18`；P4-T4.1 会分项化）。

- [ ] **Step 2: 前端主链路**

`web && npm run dev`，创建会话 → 发起研究 → 观察进度时间线出现子图节点（依赖 T3）→ 报告渲染。若 `data/docs` 下有入库文档且 `EXTRA_RETRIEVERS=local_docs`，报告引用区出现 `local://` 来源。

- [ ] **Step 3: 记录验收结论**

把两条命令输出粘贴到本文件末尾"验收记录"小节并提交：

```bash
git add docs/superpowers/plans/2026-09-18-architecture-upgrade.md
git commit -m "docs: record P0 smoke acceptance"
```

**P0 完成定义：`docker compose up` + `alembic upgrade head` + uvicorn 三步冷启动可用；SSE 携带子图事件与完整 token 计量。**

---

## P1：docstore 升级（及格线补齐，动工前细化为代码级计划）

| ID | 任务 | Files | 验收标准 | 依赖 | 估算 |
|---|---|---|---|---|---|
| 1.1 | compose 镜像换 `pgvector/pgvector:pg16`；迁移 `0003_docs_pgvector`：`documents` / `doc_chunks(doc_id, kb_id, user_id, page, chunk_index, text, embedding vector(1536), ts tsvector)` + HNSW 索引 | `docker-compose.dev.yml:4-21`, `migrations/versions/0003_*.py` | `alembic upgrade head` 建表成功；`\dx` 见 vector 扩展 | P0（T2） | 0.5d |
| 1.2 | `PgDocIndex` 实现与 `LocalDocIndex` 相同接口（`add_document/remove_document/search`），构造参数收 `user_id/kb_id`，检索 SQL 级隔离；`get_doc_index(user_id, kb_id)` 按 (user,kb) 缓存实例 | `src/open_deep_research/docstore.py`（保留旧类为 fallback） | 越权用例：user B 检索不到 user A 的 chunk（`ODR_TEST_PG=1` 集成测试） | 1.1 | 1d |
| 1.3 | embedding provider 注册表 `{openai, ollama, sentence-transformers}`，惰性 import；`EMBEDDING_MODEL=provider:model` 解析；默认模型维度写入表注释 | `docstore.py:28-40` | fake-embed 单测 3 provider 分派；sentence-transformers 档可离线跑小模型（可选 skip） | — | 1d |
| 1.4 | 结构感知切分：markdown 标题 → `\f` 分页 → 中文句界（。！？）递归，替代 500 滑窗；chunk 保留 `heading_path` metadata | `docstore.py:43-54` | 黄金样例测试：固定 md 文本切分结果断言 heading/page 归属 | — | 0.5d |
| 1.5 | `documents.py:53` 嵌入调用改 `asyncio.to_thread`；上传支持 `.pdf/.md/.txt` 白名单显式校验 | `src/server/routers/documents.py` | 上传期间 event loop 不被阻塞（并发请求冒烟） | 1.2 | 0.5d |

**合计 ≈ 3.5 人日。** 旧 JSON 索引提供一次性导入脚本（`scripts/import_legacy_docs.py`）迁移。

## P2：检索质量（差异化起点）

| ID | 任务 | 验收标准 | 依赖 | 估算 |
|---|---|---|---|---|
| 2.1 | 混合检索：dense（HNSW top-50）⊕ BM25（`tsvector` top-50）→ RRF 融合 top-k | 固定语料黄金查询：混合 Recall@5 > 纯 dense（`ODR_TEST_PG=1`） | P1 | 1d |
| 2.2 | 可选 LLM 重排级：仿 DeepSearcher `deep_search.py:33` YES/NO 判据，仅对融合后 top-20；开关走 session configurable，重排 token 计入 usage 台账 | 重排开/关对比噪声率；成本上限生效 | 2.1 | 1d |
| 2.3 | gap 驱动迭代检索：`local_docs` 结果不足时研究员可触发子查询分解（借 DeepSearcher SUB_QUERY_PROMPT），限定 max_iter=2 早停 | 多跳合成题冒烟：单次 top-k 答不出的问题经 2 轮补齐 | 2.1 | 2d（先 spike 半天） |

## P3：价值闭环（只有本架构能做）

| ID | 任务 | 验收标准 | 依赖 | 估算 |
|---|---|---|---|---|
| 3.1 | 报告回流：`_archive` 成功后将 final_report ingest 进 `kb=reports:{user}`；新会话可选"基于历史报告增量研究" | 第二次研究会话引用到首次报告内容 | P1, P0-T3 | 1d |
| 3.2 | 结构化溯源：检索命中携带 `(doc_id, page, score, kb_id)` → 落 `run_sources` 表 → `done` 事件与 `getSession` 下发 → ReportView 来源侧栏（契约仿 LocalRAG `build_sources()`）；`SOURCE N` ↔ 结构化源一对一绑定 | 前端点击引用跳转到文档页码定位 | 1.2 | 2d |
| 3.3 | per-session 知识库绑定：`configurable.kb_ids` 替代全局 `EXTRA_RETRIEVERS` 决定 `local_docs_search` 查询范围；`retrievers.py` 从 configurable 读取 | 两会话挂不同 KB，检索结果互斥 | 1.2 | 1d |
| 3.4 | 成本报表：`usage_events`（T3 后为全量子图数据）聚合出 per-session/per-user 成本视图 + 导出 | 报表数字与 LangSmith 对照误差 <5% | P0-T3 | 1d |
| 3.5 | 评估 harness：仿 DeepSearcher `evaluation/`，固定 20 题黄金集 + LLM-as-judge 引用正确率/覆盖度，产出 jsonl | `python tests/run_eval_golden.py` 可复跑 | 3.2 | 2d |

## P4：工程完备性

| ID | 任务 | 验收标准 | 估算 |
|---|---|---|---|
| 4.1 | 诊断端点：`/api/health` 分项返回 db / checkpointer / embedding 模型 / 各 retriever 探活（LocalRAG 诊断面板思路） | 各分项独立 true/false + 错误摘要 | 0.5d |
| 4.2 | e2e 测试：TestClient + fake graph 覆盖 SSE 事件序列、异常传播（`or True` 修复回归）、documents 上传下载 | `tests/server/test_e2e.py` 全离线通过 | 1.5d |
| 4.3 | 容器化 server+web 进 compose；**SearXNG 二选一**：写 adapter 注册进 `RETRIEVER_TOOLS`（半天，接口即 searxng JSON API，settings.yml 已开启）或删除 `nginx/ searxng/` 死 infra | compose 一键起全栈；死代码清零 | 1d |
| 4.4 | 前端补齐：documents 上传/列表入口、export 下载按钮、`done.usage` 消费展示、awaiting_input 时重取 session 渲染澄清问题、`sessions.py:243` ToolMessage role 修复、`App.tsx:75` 死逻辑删除 | 6/10 端点全部可达 | 2d |
| 4.5 | 打包与清理：`pyproject.toml:67` packages 补 `server.routers`（wheel 冒烟 import）；删 `chart_file_response` 死代码、`docs.zip`、过期审计报告归档 | `pip install .` 干净环境可 import | 0.5d |

## P5：可选 — LangChain 脱钩（前置条件：P0 完成、产品决定长期自维护）

沿用既有对话结论（方案 C），修正其低估：

| ID | 任务 | 与对话结论的差异 | 估算 |
|---|---|---|---|
| 5.1 | Phase 0 资产提取：prompts 抽为独立 `prompts.py`（`{{ }}` 模板 unescape；legacy 与新版分开）；**先修引用记法混用**（`[1]` 与 `SOURCE N` 二选一，保留 `SOURCE N` 以兼容 `format_sources` 与 exporters） | 对话交付的重写 prompt 双轨引用记法不可直接入库 | 1d |
| 5.2 | 自研 loop 替换 StateGraph + mini-supervisor 合并为唯一实现 | 非"200 行"：含 raw_notes 累积、token-limit 跨模型判断、think_tool、Send 并行 ≈ 400–600 行 + agent 内测试 | 5–8d |
| 5.3 | 持久化重建：替换 `AsyncPostgresSaver`（thread 消息史 + `aget_state` 续跑语义），embedding/MCP/arxiv 依赖泄漏一并清除（→ 官方 `mcp` 客户端、`client.embeddings.create`） | 对话未列此层成本 | 3–4d |

**触发建议：** P1–P4 落地后若 LangGraph 升级不再阻塞你，可长期搁置 P5——脱钩本身不产生用户价值，只是风险置换。

---

## 里程碑顺序与总估算

```
P0 (2d) ──► P1 (3.5d) ──► P2 (4d，可并行 P3 前半)
                 │
                 ▼
            P3 (7d) ──► P4 (5.5d) ──► (可选) P5 (9–13d)
```

必做部分合计 **≈ 22 人日**；P5 视决策另计。每阶段结束都是一个可独立发布的软件状态（P0=可部署；P1=私有 RAG 及格线；P2=检索质量；P3=差异化闭环；P4=产品化完备）。

## 验收记录

（T5 Step 3 填写）
