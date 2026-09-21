# CLAUDE.md — 本仓库工作须知

本仓库是 [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research)（上游 v0.0.16）
的 **分支 + 本地全栈扩展**。远端为 `sdxd4375-boop/ODR_Rebuild`。
上游的深度研究内核基本保留，外围新增了一套自托管服务层与前端。

## 两个入口，两条存储面

| 入口 | 启动方式 | 说明 |
|------|----------|------|
| `langgraph.json` → `deep_researcher` | `uvx langgraph dev` | LangGraph Studio / 调试用，**不要改这个文件** |
| `src/server/app.py:app` | `uv run python -m server` | 自托管 FastAPI + SSE + 前端 |

两条存储面共用同一个 PostgreSQL，但所有者不同：

- **业务表** `research_reports` / `usage_events` —— 由 alembic 拥有（`migrations/`），
  ORM 在 `src/server/models.py`。`AUTH_MODE=local` 时 `db.init_engine()` 会用
  `create_all` 兜底建表；若该库之后要转用迁移，先 `alembic stamp head`。
- **LangGraph checkpoint 表** `checkpoints` / `checkpoint_writes` / `checkpoint_blobs` /
  `checkpoint_migrations` —— 由 `AsyncPostgresSaver.setup()` 拥有，不要手写迁移去碰它们。
- 约定：`ResearchReport.id == thread_id`（会话即报告）。

## 目录

```
src/open_deep_research/   上游内核（configuration / deep_researcher / utils / prompts / state
                          / retrievers / docstore）—— 尽量少动
src/server/               自托管服务层：app、graphs（checkpointer）、db、models、deps（鉴权/env）
                          routers/（sessions、documents、export、health）、sandbox、charts、exporters
src/security/auth.py      上游的鉴权辅助
src/legacy/               上游旧实现（plan-and-execute / multi_agent），仅参考
web/                      Vite + React 19 前端；构建产物 web/dist 由 FastAPI 挂载
migrations/               alembic 迁移（0001 业务表、0002 用量表）
scripts/                  env_check、dev_server 等开发脚本
docs/all_file/            文档库，索引见 docs/README.md
```

## 常用命令

```bash
uv run python -m server        # 启动 API（Windows 必须用这个入口，见下）
uv run pytest tests/server -q  # 离线用例：无网络 / 无数据库 / 无 LLM
uvx ruff check src/open_deep_research src/server tests/server scripts migrations
uv run python scripts/env_check.py [--strict]
uv run alembic upgrade head    # 需要 PostgreSQL
cd web && npm run build        # 前端
```

CI 见 `.github/workflows/ci.yml`：lint + 离线用例 + Postgres service 真跑迁移 + 前端构建。

## 平台约定（Windows 上尤其重要）

- **启动入口用 `uv run python -m server`**。uvicorn 会先建 ProactorEventLoop，psycopg 的异步模式
  会直接拒绝它，checkpointer 起不来；`src/server/__main__.py` 在 uvicorn 之前切到 Selector 策略。
- **DSN 主机写 `127.0.0.1`，不要写 `localhost`**。compose 只把 5433 发布在 IPv4 上；`localhost`
  可能先解析到 `::1`，psycopg 异步连接会静默挂起（asyncpg 不受影响，容易误判为「数据库没问题」）。
- `uv.toml` 固定了清华 PyPI 镜像（网络原因），不是安全策略。
- 每个改动都要能离线验证：不新增依赖真实 API/网络的测试；真实研究类验收记为 `BLOCKED-BY-#4`。

## 修改约定

- **不要改 `langgraph.json`**；内核 `src/open_deep_research/` 的改动集中在
  `configuration.py`、`utils.py`、`deep_researcher.py`、`retrievers.py`、`docstore.py`。
- 新增副作用必须可回收（连接、上下文管理器、后台任务），启动失败要降级而不是崩溃：
  `/api/health` 用 503 + `status=degraded` 表达 `db` / `graph` 未就绪。
- 日志里**不要打印带密码的 DSN**，用 `server.graphs._redact()` 那一类的写法。
- 已知未决事项：`.env` 的 `OPENAI_BASE_URL` 指向 DashScope，而默认模型名仍是 `openai:gpt-4.1*`，
  两者不匹配 —— 属「模型配置」范畴，**当前按用户要求不做修正**，只在 `env_check --strict` 里告警。
  因此真实研究链路尚未端到端验证过。
- 改动服务层/迁移/启动方式时，同步更新 `README.md` 的 Testing 一节与 `docs/README.md`。