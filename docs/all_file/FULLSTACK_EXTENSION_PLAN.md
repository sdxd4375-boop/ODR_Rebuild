# Open Deep Research 前后端扩展可行性分析与实施方案

> **适用读者**：团队技术负责人、后端/前端工程师、以及想上手改造本项目的开发者
> **语言风格**：尽量说人话。遇到必须用的术语，第一次出现时会用括号解释
> **版本基准**：`open_deep_research` v0.0.16，分支 `main`
> **配套文档**：《代码库研究报告》`docs/RESEARCH_REPORT.md`（含逐行代码位置索引，本文档是它的"落地篇"）

---

## 写在最前面：一句话结论

**这个项目现在是"纯后端"，而且是一个"没有自己服务器的后端"——它是一段被平台托管运行的 Python 图程序。**

好消息是：**托管它的 LangGraph 平台已经自带一整套 HTTP 接口**，并且还允许你**把一段自己写的 FastAPI 程序"塞进"同一个服务里**。

所以扩展路线非常清晰：

```
现在：  [没有界面]  ──HTTP──>  [LangGraph 平台 + 你的研究程序]

目标：  [React 前端] ──HTTP/SSE──> [LangGraph 平台（内置接口 + 你新加的 FastAPI 接口）]
                                            └──> [同一个研究程序，代码几乎不用改]
```

**最关键的一点：整个扩展过程中，`src/open_deep_research/` 下的核心研究代码可以做到"一行不改"。** 这是本方案最大的价值。

---

## 目录

1. [项目现状梳理](#1-项目现状梳理)
2. [前端扩展可行性分析](#2-前端扩展可行性分析)
3. [后端扩展可行性分析](#3-后端扩展可行性分析)
4. [前后端协作方案](#4-前后端协作方案)
5. [实施方案：分阶段落地步骤](#5-实施方案分阶段落地步骤)
6. [常见问题与注意事项](#6-常见问题与注意事项)
7. [附录：速查表](#7-附录速查表)

---

## 1. 项目现状梳理

### 1.1 用一个比喻理解现在的架构

把它想成一家"自动化调研公司"：

| 角色 | 对应代码 | 干什么活 |
| --- | --- | --- |
| **前台接待** | `clarify_with_user`（`deep_researcher.py:60`） | 听懂客户需求，不清楚就追问 |
| **项目经理** | `write_research_brief` + `supervisor`（`:118`、`:178`） | 把需求拆成几份调研任务，分派下去 |
| **调研员（多人同时干活）** | `researcher` 子图（`:365`） | 各自上网搜资料、做笔记 |
| **资料整理员** | `compress_research`（`:511`） | 把调研员的笔记压缩成一段通顺的文字 |
| **总编** | `final_report_generation`（`:607`） | 把所有整理稿汇总成最终报告 |
| **公司老板（AI）** | 各个大模型 | 上面每一个角色其实都是同一个 AI 在"换帽子" |

而**"公司办公大楼"（服务器、接口、数据库）不是你自己盖的，是 LangGraph 平台提供的**。你只交了"员工手册"（图程序）。

### 1.2 技术栈现状

| 层 | 现状 | 说明 |
| --- | --- | --- |
| 界面层 | **无** | 官方用 LangGraph Studio（调试工具）和 OAP（另一个独立产品）代替 |
| 接口层 | **无自建** | 由 LangGraph 平台自动生成 REST 接口 |
| 业务层 | `src/open_deep_research/`（5 个文件，2360 行） | 三层嵌套"状态图"：主图 → 主管子图 → 研究员子图 |
| 工具层 | `utils.py`（925 行） | 搜索（默认 Tavily）、MCP 外部工具、令牌限制判断 |
| 数据层 | **无自建数据库** | 对话历史与长期记忆由平台托管（开发时是内存，重启即丢） |
| 鉴权层 | `src/security/auth.py`（156 行） | 用 Supabase 校验 JWT（登录令牌），做用户数据隔离 |

### 1.3 模块划分与依赖

```mermaid
graph TD
    DR["deep_researcher.py<br/>（图定义 + 5 个节点函数）"]
    UTL["utils.py<br/>（搜索 / MCP / 令牌判断）"]
    CFG["configuration.py<br/>（全部可调参数）"]
    ST["state.py<br/>（数据传递格式）"]
    PRM["prompts.py<br/>（7 套提示词）"]
    AUTH["security/auth.py<br/>（登录校验）"]

    DR --> UTL
    DR --> CFG
    DR --> ST
    DR --> PRM
    UTL --> CFG
    UTL --> ST
    UTL --> PRM
```

**特点**：依赖是"单向"的（像水流一样只会往下流，不会绕回来），这一点非常健康，意味着你可以放心地在外围加东西，不会把核心代码搅乱。

### 1.4 前后端职责边界：现在是"零前端"

| 传统项目 | 本项目 |
| --- | --- |
| 前端负责页面、交互 | ❌ 没有 |
| 后端提供接口 | ⚠️ 由平台自动生成，非项目代码 |
| 后端写业务逻辑 | ✅ 全在图程序里 |
| 数据库存数据 | ⚠️ 由平台托管，项目未定义任何表 |

**结论：当前是 100% 纯后端（更准确说是"纯计算逻辑"）。**

### 1.5 扩展的起点在哪里？

扩展起点是**一个配置文件 + 一个符号名**：

```json
// langgraph.json —— 整个项目对外的"唯一门牌号"
{
  "graphs": {
    "Deep Researcher": "./src/open_deep_research/deep_researcher.py:deep_researcher"
  },
  "auth": { "path": "./src/security/auth.py:auth" },
  "python_version": "3.11",
  "env": "./.env",
  "dependencies": ["."]
}
```

这句话的意思是：**"请把我这个文件里叫 `deep_researcher` 的对象，当作一个可远程调用的服务暴露出去"**。

后续所有扩展，本质上都是围绕这两个入口做文章：

| 想做的事 | 改哪里 |
| --- | --- |
| 加一个网页界面 | 新建 `web/` 目录，调平台已有接口 |
| 加自己的接口（比如"历史报告列表"） | 给 `langgraph.json` 加 `http.app`，指向你新建的 FastAPI 文件 |
| 换模型 / 换搜索引擎 / 调并发数 | **什么都不用改**，改配置即可（`configuration.py`，平台界面上就能调） |

---

## 2. 前端扩展可行性分析

### 2.1 可行性结论

| 评估项 | 结论 |
| --- | --- |
| 技术可行性 | ★★★★★ **非常高**。平台已提供完整接口 + 官方 JS 客户端 |
| 对现有代码影响 | ★★★★★ **几乎为零**。不需要动 `src/` 下任何代码 |
| 工期（最小可用版本） | 2~3 人日 |
| 工期（完整产品） | 14~20 人日 |
| 主要风险 | 成本失控（用户狂点按钮）、长任务断线、报告内容安全 |

### 2.2 前端要"连"的东西是什么？

平台自动给你这些接口（不需要你写一行后端）：

| 用途 | 接口 | 通俗解释 |
| --- | --- | --- |
| 开一个会话 | `POST /threads` | "开一个聊天窗口" |
| 发问题并**实时接收结果** | `POST /threads/{id}/runs/stream` | "提问，并像看直播一样看 AI 一个字一个字往外吐" |
| 发问题并**等结果** | `POST /threads/{id}/runs/wait` | "提问，然后干等，最后一次性拿到结果" |
| 查看会话当前状态 | `GET /threads/{id}/state` | "看看现在进展到哪一步了" |
| 查看历史 | `GET /threads/{id}/history` | "回放整个过程" |
| 保存配置组合 | `POST /assistants` | "把一套参数存成模板" |

> 那个"像看直播一样"的接口叫 **SSE**（Server-Sent Events，服务器推送事件）。它不是 WebSocket，是单向的：服务器 → 浏览器，正好适合"AI 边写边给你看"的场景。

### 2.3 前端技术选型建议

#### 推荐方案（新手友好）：Vite + React + TypeScript

```
web/
├── index.html
├── package.json
├── vite.config.ts        ← 开发代理配置（关键）
├── .env.development      ← 开发环境变量
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── lib/
    │   ├── langgraph.ts   ← 平台客户端封装
    │   └── types.ts       ← 接口数据类型
    ├── components/
    │   ├── ChatPanel.tsx        ← 输入框 + 消息列表
    │   ├── ResearchTimeline.tsx ← 研究进度时间线（本项目最大亮点）
    │   ├── ReportView.tsx       ← Markdown 报告渲染
    │   └── ConfigPanel.tsx      ← 参数配置面板
    └── styles/
```

| 选择 | 推荐 | 为什么 |
| --- | --- | --- |
| 框架 | **React**（而非 Vue） | 官方 JS 客户端和社区示例以 React 为主，踩坑少 |
| 构建工具 | **Vite**（而非 Next.js） | 这是纯客户端应用，不需要服务端渲染；Vite 启动快、配置简单 |
| 语言 | **TypeScript** | 接口返回的数据结构复杂，有类型提示能省一半调试时间 |
| UI 组件 | **Tailwind CSS + shadcn/ui** | 不用自己写样式，几天就能做出专业外观 |
| Markdown 渲染 | **react-markdown + remark-gfm** | 报告本身就是 Markdown 格式 |
| 安全过滤 | **rehype-sanitize** | ⚠️ 必须加，原因见 §6 |

> **什么时候该选 Next.js？**
> 如果你需要：服务端渲染、SEO、把接口藏在自己的服务端后面做配额控制 → 选 Next.js（它的 Route Handler 可以直接当"中转站"）。
> 如果只是内部工具或 Demo → Vite 足够，别上复杂度。

#### 官方客户端

```bash
npm install @langchain/langgraph-sdk
```

这是 LangChain 官方的 JS/TS 客户端，把上面那些 REST 接口都封装好了，你不用手写 SSE 解析。

### 2.4 与现有后端的集成方式

**方式一：直连（最快，适合内部工具 / Demo）**

```
浏览器 ──(带登录令牌)──> LangGraph 平台 :2024
```

**方式二：加一层"中转站"（推荐用于对外产品）**

```
浏览器 ──> 你的中转服务 ──> LangGraph 平台
             ↑
        在这里做：登录校验、配额限制、计费、审计
```

本文档第 3 节会介绍一个**更巧妙的做法**：把"中转站"直接塞进 LangGraph 服务里，省掉一个独立部署单元。

### 2.5 对现有项目结构、构建、部署的影响

| 维度 | 影响 | 说明 |
| --- | --- | --- |
| `src/` 目录 | ✅ 零改动 | 核心代码完全不动 |
| `langgraph.json` | ⚠️ 加 2 处配置 | `http.cors`（允许跨域）；阶段 3 后加 `http.app` |
| `pyproject.toml` | ⚠️ 加 1~3 个依赖 | 若挂载 FastAPI 需加 `fastapi`、`uvicorn` |
| 新增目录 | `web/` | 与 Python 代码物理隔离，互不干扰 |
| Python 构建 | ✅ 不受影响 | 前端产物是静态文件 |
| 部署 | ⚠️ 多一条流水线 | 前端可部署到 Vercel / 对象存储 / 或让 FastAPI 直接托管 |
| 团队协作 | ✅ 变清晰 | 前端只管 `web/`，后端只管 `src/`，靠接口契约说话 |

### 2.6 改造步骤（概览，详细命令见第 5 节）

| 步骤 | 做什么 | 产出 |
| --- | --- | --- |
| 1 | 配 `langgraph.json` 的 CORS | 浏览器能跨域访问 |
| 2 | 用 Vite 创建 React 项目 | `web/` 骨架跑起来 |
| 3 | 配 Vite 代理 | 开发时不用管跨域，一键联调 |
| 4 | 写客户端封装 + 提问框 | 能发出第一个问题 |
| 5 | 接 SSE 流式渲染 | 报告一个字一个字往外冒 |
| 6 | 加研究进度时间线 | 看到"几个调研员在并行干活" |
| 7 | 加参数配置面板 | 用户能自己调模型/并发数 |
| 8 | 加会话历史 | 能回看之前的报告 |
| 9 | 加安全过滤 | 报告渲染防注入 |

---

## 3. 后端扩展可行性分析

### 3.1 现状评估：扩展性到底好不好？

| 维度 | 评分 | 说明 |
| --- | --- | --- |
| **加新接口** | ★★★★★ | 平台支持挂载自定义 FastAPI，**与图程序同进程部署** |
| **换模型/搜索引擎** | ★★★★★ | 纯配置驱动，改 `configuration.py` 或运行时传参即可 |
| **加新数据源（MCP）** | ★★★★☆ | 已有完整 MCP 支持，配个 URL 就能挂外部工具 |
| **加数据库** | ★★★☆☆ | 目前完全没有数据层，需要从零建；但平台已托管了检查点和存储 |
| **微服务拆分** | ★☆☆☆☆ | **不建议拆**（理由见 3.3） |
| **性能优化** | ★★★☆☆ | 瓶颈在外部 API，本地可优化空间有限但有明确抓手 |

### 3.2 🔑 最重要的发现：可以把 FastAPI "塞进"同一个服务

`langgraph.json` 支持一个 `http.app` 配置项，指向你自己写的 FastAPI（或 Starlette）应用对象。效果是：

> **你的自定义接口和图程序跑在同一个服务进程里，共用同一个端口、同一套鉴权、同一次部署。**

这意味着你**不需要**单独起一个后端服务、不需要处理服务间调用、不需要再配一次 CORS。

配置长这样（注意对比现状，只多了 `http` 这一段）：

```json
{
  "dockerfile_lines": [],
  "graphs": {
    "Deep Researcher": "./src/open_deep_research/deep_researcher.py:deep_researcher"
  },
  "python_version": "3.11",
  "env": "./.env",
  "dependencies": ["."],
  "auth": { "path": "./src/security/auth.py:auth" },

  "http": {
    "app": "./src/server/app.py:app",
    "cors": {
      "allow_origins": ["http://localhost:5173"],
      "allow_methods": ["GET", "POST", "OPTIONS"],
      "allow_headers": ["Content-Type", "Authorization", "x-supabase-access-token"],
      "allow_credentials": true,
      "max_age": 600
    }
  }
}
```

**CORS 配置字段说明**（`CorsConfig`，`langgraph-cli` v0.4+ 支持）：

| 字段 | 作用 |
| --- | --- |
| `allow_origins` | 允许哪些网址访问（如 `["https://your-app.com"]`）。默认很严格，等于全禁 |
| `allow_methods` | 允许哪些请求方法 |
| `allow_headers` | 允许携带哪些请求头（`Authorization` 一定要加，否则带不了登录令牌） |
| `allow_credentials` | 是否允许携带凭据（Cookie / 认证头） |
| `allow_origin_regex` | 用正则匹配来源，适合多子域名场景 |
| `expose_headers` | 允许浏览器读取哪些响应头 |
| `max_age` | 预检请求缓存秒数 |

> ⚠️ **`allow_origins` 千万不要填 `["*"]` 同时又开 `allow_credentials: true`**，这会让任何网站都能拿着用户的令牌访问你的服务。

### 3.3 关于"微服务拆分"：明确建议不要拆

| 理由 | 说明 |
| --- | --- |
| 状态强耦合 | 图的状态（消息、笔记、迭代次数）是一个整体，拆开就要跨服务传状态，复杂度爆炸 |
| 瓶颈不在 CPU | 一次研究 90% 的时间在等外部 API（大模型、搜索），拆服务不会变快 |
| 团队规模不匹配 | 这是个单体图应用，拆分带来的运维成本 >> 收益 |
| 平台已做横向扩展 | LangGraph 平台本身就负责任务调度与并发 |

**正确做法：单体 + 模块化。**

```
src/
├── open_deep_research/     ← 【不动】核心研究逻辑
├── security/               ← 【不动】鉴权
└── server/                 ← 【新增】你的服务端代码
    ├── app.py              ← FastAPI 应用入口
    ├── db.py               ← 数据库连接
    ├── models.py           ← 数据表定义
    ├── routers/
    │   ├── health.py
    │   ├── config.py       ← 把可调参数暴露给前端生成表单
    │   ├── reports.py      ← 历史报告
    │   └── quota.py        ← 配额与用量
    └── services/
        ├── quota.py        ← 配额校验逻辑
        ├── cost.py         ← 成本统计
        └── reports.py      ← 报告读写
```

**如果将来真的要拆**，只建议把这类"无状态、可独立"的活拆出去：报告导出 PDF、报告翻译、批量任务调度。核心图永远别拆。

### 3.4 数据层：从"没有"到"有"

**现状问题**：开发模式（`langgraph dev`）用的是**内存存储，服务一重启，所有会话和报告全没了**。

**演进路线**：

| 阶段 | 方案 | 适用场景 |
| --- | --- | --- |
| 阶段 1（现在） | 内存存储 | 本地开发、Demo |
| 阶段 2 | **PostgreSQL 持久化** | 自托管生产环境 |
| 阶段 3 | 平台托管存储 | LangGraph Platform Cloud（不用自己管库） |

**需要建的业务表**（项目本身一张表都没有，下面是最小的三张）：

```sql
-- 报告归档（便于列表、搜索、分享，不用每次去翻图的内部状态）
CREATE TABLE reports (
    id            UUID PRIMARY KEY,
    user_id       TEXT NOT NULL,          -- 对应用户，做隔离
    thread_id     TEXT NOT NULL UNIQUE,   -- 关联平台会话
    question      TEXT NOT NULL,          -- 用户原始问题
    research_brief TEXT,                  -- AI 整理后的研究提纲
    content_md    TEXT NOT NULL,          -- 最终报告（Markdown）
    raw_notes     TEXT,                   -- 原始调研笔记（供溯源）
    status        TEXT NOT NULL,          -- running / done / failed
    error_message TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    finished_at   TIMESTAMPTZ
);
CREATE INDEX idx_reports_user ON reports(user_id, created_at DESC);

-- 用量记录（成本统计与计费的基础）
CREATE TABLE usage_events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    thread_id   TEXT,
    event_type  TEXT NOT NULL,            -- run_start / run_end / tool_call
    model       TEXT,
    input_tokens  BIGINT DEFAULT 0,
    output_tokens BIGINT DEFAULT 0,
    cost_cents  NUMERIC(12,4) DEFAULT 0,  -- 用"分"存，避免浮点误差
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_usage_user ON usage_events(user_id, created_at DESC);

-- 配额（防止成本失控的关键）
CREATE TABLE quotas (
    user_id          TEXT PRIMARY KEY,
    monthly_cent_budget INTEGER NOT NULL DEFAULT 5000,  -- 例：每月 50 元
    used_cent        INTEGER NOT NULL DEFAULT 0,
    max_concurrent_runs INTEGER NOT NULL DEFAULT 1,
    updated_at       TIMESTAMPTZ DEFAULT now()
);
```

> **为什么必须建 `usage_events` 和 `quotas`？**
> 一次完整研究可能花几块钱。如果没有配额表，一个好奇的用户点十次，账单就很难看。这是**上线前必做**的事，不是"以后再说"的事。

### 3.5 服务层：现在"没有服务层"，要不要补？

**现状**：所有逻辑都写在图的节点函数里，没有传统意义上的"服务层"。

**建议**：**不要去重构图的内部**（风险高、收益低），而是在**外围**补三类服务：

| 服务 | 职责 | 为什么必须放在外面 |
| --- | --- | --- |
| **配额服务** | 开跑前检查余额、并发数；跑完扣费 | 属于"平台治理"，不该污染研究逻辑 |
| **用量统计服务** | 从 LangSmith 追踪或回调中汇总 token/成本 | 需要跨运行聚合，图内部做不到 |
| **报告归档服务** | 运行结束后把 `final_report` 落库 | 图的状态由平台托管，查询能力弱 |

**实现思路（不用改图代码）**：

1. 在自定义 FastAPI 路由里包一层"发起研究"，先查配额 → 再调平台接口 → 异步任务在结束后写库和扣费；
2. 用平台的 **Webhook** 或 **lifespan 钩子**（自定义生命周期事件）在任务结束时触发归档；
3. 成本数据从 LangSmith 的 trace 里按 `thread_id` 汇总（项目已经接入 LangSmith）。

### 3.6 接口层：从"只有平台自动接口"到"平台接口 + 自定义接口"

最终对外接口分两类：

**A 类：平台自动接口（不要重复造轮子）**

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/threads` | 新建会话 |
| POST | `/threads/{thread_id}/runs/stream` | 流式发起研究（**主力接口**） |
| GET | `/threads/{thread_id}/state` | 查看进度/取中间产物 |
| GET | `/threads/search` | 会话列表 |

**B 类：你新增的自定义接口**

| 方法 | 路径 | 用途 | 阶段 |
| --- | --- | --- | --- |
| GET | `/api/health` | 健康检查（部署验证用） | 1 |
| GET | `/api/me` | 当前登录用户信息 | 2 |
| GET | `/api/config-schema` | **把可调参数导出给前端自动生成表单** | 2 |
| GET | `/api/reports` | 历史报告列表（分页） | 3 |
| GET | `/api/reports/{id}` | 报告详情 | 3 |
| GET | `/api/quota` | 剩余配额 | 4 |
| POST | `/api/reports/{id}/export` | 导出 PDF / Markdown | 5 |

### 3.7 性能优化：抓手在哪里？

**先搞清楚一件事**：一次研究动辄几分钟，其中 **95% 的时间在等外部服务**（大模型 + 搜索）。所以"让代码跑更快"意义不大，真正的抓手是**减少无谓的外部调用**。

| 优化项 | 位置 | 做法 | 预期收益 |
| --- | --- | --- | --- |
| MCP 连接复用 | `utils.py:499-504` | 现在**每一轮工具循环都重新连一次 MCP 服务器**。改成按会话缓存连接 | 减少握手延迟，降低连接数 |
| 摘要并发上限 | `utils.py:100-110` | 现在是"有多少结果就并发多少"。加一个信号量（比如最多 8 个同时） | 避免触发限流 |
| 网页截断长度 | `configuration.py:141-152` | 默认 50000 字符。对多数场景可降到 20000 | 摘要输入 token 直接减 60% |
| 迭代上限 | `configuration.py:94-119` | `max_researcher_iterations=6`、`max_react_tool_calls=10` | 成本与质量的主要旋钮 |
| 并发单元数 | `configuration.py:64-76` | 默认 5。降到 2~3 可省一半成本 | 成本减半，质量略降 |
| 搜索结果缓存 | 新增 | 相同查询 24 小时内复用（Redis 或 Postgres） | 重复问题几乎零成本 |
| 报告结果缓存 | 新增 | 完全相同的问题 + 配置 → 直接返回历史报告 | 同上 |

> 💡 **最容易见效的一步**：把 `max_concurrent_research_units` 从 5 调到 3、`max_content_length` 从 50000 调到 20000。改两个数字，成本可能降 40%，而报告质量下降通常不明显。**建议先用评估脚本（`tests/run_evaluate.py`）跑一小批样本对比后再定。**

---

## 4. 前后端协作方案

### 4.1 协作模式选择

| 模式 | 做法 | 适用 |
| --- | --- | --- |
| **完全分离** | 前端独立仓库/目录，只通过 HTTP 接口通信 | 团队有专职前端；本项目推荐 |
| **一体化（推荐落地形态）** | 前端构建产物交给 FastAPI 用 `StaticFiles` 托管，**一个端口搞定全栈** | 小团队、内部工具、想省部署成本 |

**推荐**：开发时"分离"（各自热更新，效率高），部署时"一体化"（一个容器，一条流水线）。

```
开发时：
  前端 :5173 (Vite 热更新)  ──代理──>  后端 :2024 (langgraph dev)

生产时：
  浏览器 ──> :2024 (LangGraph 服务)
                ├── /api/*      你的 FastAPI 接口
                ├── /threads/*  平台内置接口
                └── /*          前端静态文件（web/dist）
```

### 4.2 接口规范

**统一约定**

| 项目 | 约定 |
| --- | --- |
| 协议 | HTTP/1.1 + SSE |
| 数据格式 | `application/json`；SSE 为 `text/event-stream` |
| 字符编码 | UTF-8（研究报告含多语言，必须统一） |
| 命名 | 字段用 `snake_case`（与 Python/Pydantic 保持一致） |
| 时间 | ISO 8601 字符串，带时区（如 `2026-09-04T10:30:00Z`） |
| 金额 | 用"分"为单位的整数，字段名带 `_cent` 后缀 |
| 分页 | `?limit=20&offset=0`，返回 `{items: [], total: 100}` |
| 错误 | 统一结构：`{"error": {"code": "...", "message": "...", "trace_id": "..."}}` |

**前端 → 后端：发起一次研究**

```jsonc
// POST /threads/{thread_id}/runs/stream
{
  "assistant_id": "Deep Researcher",     // 就是 langgraph.json 里配的图名
  "input": {
    "messages": [
      { "role": "user", "content": "帮我调研 2026 年推理芯片市场的竞争格局" }
    ]
  },
  "config": {
    "configurable": {
      "research_model": "openai:gpt-4.1",
      "summarization_model": "openai:gpt-4.1-mini",
      "search_api": "tavily",
      "max_concurrent_research_units": 3,
      "max_researcher_iterations": 4,
      "allow_clarification": true
    }
  },
  "stream_mode": ["updates", "messages"]  // updates=进度, messages=报告正文
}
```

> 💡 `config.configurable` 里的**每一个键**，都对应 `src/open_deep_research/configuration.py` 里的一个字段。**前端不需要硬编码这些字段** —— 见下一条。

**后端 → 前端：SSE 事件格式**

| event | 含义 | data 示例 |
| --- | --- | --- |
| `updates` | 某个节点跑完了（**用来画进度条**） | `{"supervisor_tools": {"research_iterations": 2}}` |
| `messages` | 报告正文的一个片段 | `[{"role":"assistant","content":"## 概述\n..."}, {"langgraph_node":"final_report_generation"}]` |
| `values` | 完整状态快照 | `{"messages":[...], "final_report":"..."}` |
| `error` | 出错了 | `{"message": "..."}` |
| `end` | 结束 | — |

**⚡ 免费福利：自动生成的配置表单**

`configuration.py` 里每个字段都带了一段 `x_oap_ui_config` 元数据，长这样：

```python
max_concurrent_research_units: int = Field(
    default=5,
    metadata={"x_oap_ui_config": {
        "type": "slider", "default": 5, "min": 1, "max": 20, "step": 1,
        "description": "Maximum number of research units to run concurrently..."
    }}
)
```

**这意味着：前端的配置面板可以自动生成，不用手写十几个表单项！** 你只需要在后端加一个接口把它导出来：

```python
# src/server/routers/config.py
from fastapi import APIRouter
from open_deep_research.configuration import Configuration

router = APIRouter(prefix="/api", tags=["config"])

def _ui_config(field) -> dict | None:
    """兼容 metadata 为 dict 或 list 两种写法。"""
    md = getattr(field, "metadata", None)
    if isinstance(md, dict):
        return md.get("x_oap_ui_config")
    if isinstance(md, list):
        for item in md:
            if isinstance(item, dict) and "x_oap_ui_config" in item:
                return item["x_oap_ui_config"]
    return None

@router.get("/config-schema")
def config_schema():
    """把可调参数导出给前端，用于自动生成配置表单。"""
    return {
        name: cfg
        for name, field in Configuration.model_fields.items()
        if (cfg := _ui_config(field))
    }
```

前端拿到后按 `type` 渲染即可（项目里已经用到了 `slider`/`select`/`number`/`boolean`/`text`/`mcp` 六种类型）。

### 4.3 鉴权方式

**链路**（沿用现有 `src/security/auth.py`，不重复造轮子）：

```
① 用户登录 Supabase        → 拿到 JWT（登录令牌）
② 前端每次请求带上令牌      → Authorization: Bearer <JWT>
③ 平台调用 auth.py 校验    → 解出 user.id
④ auth.py 给会话打上 owner  → 用户只能看到自己的会话
⑤ 你的自定义接口也读同一个令牌 → 做配额与归档
```

**前端侧写法**：

```ts
// web/src/lib/langgraph.ts
import { Client } from "@langchain/langgraph-sdk";

export function createClient(getToken: () => Promise<string | null>) {
  return new Client({
    // 开发环境留空 → 走 Vite 代理（同源，无跨域问题）
    // 生产环境填 https://your-server.com
    apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL || "",
    defaultHeaders: async () => {
      const token = await getToken();
      return token ? { Authorization: `Bearer ${token}` } : {};
    },
  });
}
```

**三条安全红线**：

1. ❌ **绝不能**把 `OPENAI_API_KEY`、`TAVILY_API_KEY` 放进前端（会以明文出现在浏览器里）。
2. ❌ **绝不能**把 `allow_origins` 设为 `["*"]` 又开启 `allow_credentials`。
3. ✅ 前端只需要持有**用户自己的登录令牌**，其他密钥一律留在服务端。

### 4.4 三套环境的部署建议

| 环境 | 后端 | 前端 | 数据 | 特点 |
| --- | --- | --- | --- | --- |
| **开发** | `langgraph dev --allow-blocking`（:2024，内存存储） | `npm run dev`（:5173，Vite 代理） | 内存（重启即丢） | 秒级热更新，零成本调试 |
| **测试** | Docker 自托管（`langgraph up`）或平台 Preview 环境 | 构建后由 FastAPI 静态托管 | PostgreSQL（容器） | 尽量贴近生产 |
| **生产** | LangGraph Platform Cloud（GitHub 集成，push 即部署）或自托管 | 与后端同域，由 FastAPI 托管 / 或独立静态托管 | 平台托管或自建 Postgres | 开监控、配额、告警 |

**各环境变量清单**

| 变量 | 开发 | 测试 | 生产 |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` 等模型密钥 | ✅ | ✅ | ✅（走 CI/CD Secrets） |
| `TAVILY_API_KEY` | ✅ | ✅ | ✅ |
| `LANGSMITH_API_KEY` | 可选 | ✅ | ✅（必须，用于成本统计） |
| `LANGSMITH_TRACING` | `false` | `true` | `true` |
| `SUPABASE_URL` / `SUPABASE_KEY` | 可选 | ✅ | ✅ |
| `GET_API_KEYS_FROM_CONFIG` | `false` | `false` | `true`（OAP 场景） |
| `DATABASE_URL`（新增） | — | ✅ | ✅ |

---

## 5. 实施方案：分阶段落地步骤

> 每个阶段包含：**目标** / **操作内容** / **预期结果**
> 命令以 Windows PowerShell 为主，macOS/Linux 用户把 `.venv\Scripts\activate` 换成 `source .venv/bin/activate`

---

### 阶段 0：跑通现状（预计 0.5 天）

**目标**：确认现有项目能在你机器上正常跑起来，能手动触发一次研究。

**操作**

1. 安装依赖并启动：

```powershell
cd g:\Code\open_deep_research
uv venv
.venv\Scripts\activate
uv sync
cp .env.example .env          # 然后打开 .env 填入你的密钥
```

2. 启动开发服务器：

```powershell
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.11 langgraph dev --allow-blocking
```

3. 打开 `http://127.0.0.1:2024/docs`，你应该能看到平台自动生成的接口文档（Swagger 页面）。

4. 在 Swagger 里手动试一次：
   - `POST /threads` → 记下返回的 `thread_id`
   - `POST /threads/{thread_id}/runs/stream`，body 填：
     ```json
     {
       "assistant_id": "Deep Researcher",
       "input": { "messages": [{"role": "user", "content": "用三句话介绍 MCP 协议"}] },
       "config": { "configurable": { "max_concurrent_research_units": 1, "max_researcher_iterations": 1 } }
     }
     ```
   - 观察返回的流式内容

> 💡 第一次务必把 `max_concurrent_research_units` 和 `max_researcher_iterations` 调到最小，否则一次测试可能花掉几块钱。

**预期结果**：接口文档能打开，一次迷你研究能跑完并看到输出。**这一步没跑通，不要往下走。**

---

### 阶段 1：后端开个口子（预计 0.5 天）

**目标**：让浏览器能跨域访问后端，并加一个自定义接口验证"FastAPI 能塞进服务"。

**操作**

1. 安装依赖：

```powershell
uv add fastapi uvicorn
```

2. 新建 `src/server/__init__.py`（空文件）和 `src/server/app.py`：

```python
"""自定义 HTTP 接口：与 LangGraph 服务同进程部署。"""

from fastapi import FastAPI

app = FastAPI(title="Open Deep Research API", version="0.1.0")


@app.get("/api/health")
def health():
    """健康检查：部署后第一个要访问的接口。"""
    return {"status": "ok"}
```

3. 修改 `langgraph.json`，加上 `http` 段（**只加这一段，其他保持原样**）：

```json
{
  "dockerfile_lines": [],
  "graphs": {
    "Deep Researcher": "./src/open_deep_research/deep_researcher.py:deep_researcher"
  },
  "python_version": "3.11",
  "env": "./.env",
  "dependencies": ["."],
  "auth": { "path": "./src/security/auth.py:auth" },
  "http": {
    "app": "./src/server/app.py:app",
    "cors": {
      "allow_origins": ["http://localhost:5173"],
      "allow_methods": ["GET", "POST", "OPTIONS"],
      "allow_headers": ["Content-Type", "Authorization"],
      "allow_credentials": true
    }
  }
}
```

4. 重启服务，访问 `http://127.0.0.1:2024/api/health`

**预期结果**：浏览器返回 `{"status":"ok"}`。此时原有的研究和新接口**共存于同一个端口**。

> ⚠️ 如果你还没配 Supabase（`SUPABASE_URL`/`SUPABASE_KEY` 为空），`auth.py` 会对所有非 Studio 请求返回 500。本地开发建议先用 LangGraph Studio 调试，或在 `.env` 里配好 Supabase，或临时把 `langgraph.json` 的 `auth` 段注释掉（**仅限本地**）。

---

### 阶段 2：创建前端项目 + 配置代理联调（预计 1 天）

**目标**：前端骨架跑起来，能通过代理访问后端，并成功发出第一个问题。

**操作**

1. 创建项目：

```powershell
cd g:\Code\open_deep_research
npm create vite@latest web -- --template react-ts
cd web
npm install
npm install @langchain/langgraph-sdk
npm install react-markdown remark-gfm rehype-sanitize
```

2. 配置开发代理 —— 新建/修改 `web/vite.config.ts`：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 平台内置接口：会话、运行、助手
      "/threads":    { target: "http://127.0.0.1:2024", changeOrigin: true },
      "/runs":       { target: "http://127.0.0.1:2024", changeOrigin: true },
      "/assistants": { target: "http://127.0.0.1:2024", changeOrigin: true },
      // 我们自己的接口
      "/api":        { target: "http://127.0.0.1:2024", changeOrigin: true },
      // 对象存储（长期记忆），暂时用不到，先留着
      "/store":      { target: "http://127.0.0.1:2024", changeOrigin: true },
    },
  },
});
```

> 💡 **代理是干嘛的？**
> 浏览器有个安全限制：网页在 `localhost:5173`，就不许直接请求 `localhost:2024`（这叫"跨域"）。
> Vite 代理相当于一个"传话筒"：浏览器请求 `localhost:5173/api/health`，Vite 悄悄转发给 `localhost:2024/api/health`，再把结果送回来。浏览器以为大家都是 5173，就不拦了。
> **这是开发阶段的标配做法，生产环境不需要（同域部署后自然没有跨域问题）。**

3. 新建 `web/.env.development`：

```ini
# 留空 = 走 Vite 代理，请求发往当前域名（5173）
VITE_LANGGRAPH_API_URL=
VITE_ASSISTANT_ID=Deep Researcher
```

4. 新建 `web/src/lib/client.ts`：

```ts
import { Client } from "@langchain/langgraph-sdk";

export const client = new Client({
  apiUrl: import.meta.env.VITE_LANGGRAPH_API_URL || "",
});

export const ASSISTANT_ID = import.meta.env.VITE_ASSISTANT_ID || "Deep Researcher";
```

5. 写一个最小提问组件 `web/src/App.tsx`（先只做"发问题 → 拿到最终结果"）：

```tsx
import { useState } from "react";
import { client, ASSISTANT_ID } from "./lib/client";

export default function App() {
  const [question, setQuestion] = useState("");
  const [report, setReport] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setReport("");
    try {
      const thread = await client.threads.create();
      const result = await client.runs.wait(thread.thread_id, ASSISTANT_ID, {
        input: { messages: [{ role: "user", content: question }] },
        config: {
          configurable: {
            max_concurrent_research_units: 1,
            max_researcher_iterations: 1,
            allow_clarification: false,
          },
        },
      });
      setReport((result as any).final_report ?? "没有拿到报告");
    } catch (e) {
      setReport(`出错了：${String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: "40px auto", fontFamily: "system-ui" }}>
      <h1>Open Deep Research</h1>
      <textarea
        rows={3}
        style={{ width: "100%" }}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="输入你的研究问题……"
      />
      <button onClick={run} disabled={busy || !question} style={{ marginTop: 8 }}>
        {busy ? "研究中（可能需要几分钟）…" : "开始研究"}
      </button>
      <pre style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{report}</pre>
    </div>
  );
}
```

6. 两个终端同时开：

```powershell
# 终端 1（后端）
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.11 langgraph dev --allow-blocking

# 终端 2（前端）
cd web
npm run dev
```

打开 `http://localhost:5173`，输入问题，点按钮。

**预期结果**：等一两分钟，页面上出现 Markdown 格式的报告文本（此时还没渲染，是纯文本）。**前后端联调打通。**

---

### 阶段 3：流式输出 + 研究进度可视化（预计 2~3 天）

**目标**：从"干等几分钟"变成"看着 AI 边查边写"，体验质变。

**操作**

1. 把 `runs.wait` 换成 `runs.stream`，同时监听进度和正文：

```tsx
async function runStream() {
  setBusy(true);
  setReport("");
  setSteps([]);

  const thread = await client.threads.create();

  const stream = client.runs.stream(thread.thread_id, ASSISTANT_ID, {
    input: { messages: [{ role: "user", content: question }] },
    config: { configurable: { allow_clarification: false } },
    streamMode: ["updates", "messages"],   // ← 关键：两种事件一起收
  });

  for await (const chunk of stream) {
    if (chunk.event === "updates") {
      // 某个节点跑完了 → 更新进度时间线
      const node = Object.keys((chunk.data as any) ?? {})[0];
      if (node) setSteps((s) => [...s, `${new Date().toLocaleTimeString()}  ${node}`]);
    }

    if (chunk.event === "messages") {
      // 报告正文片段 → 追加渲染
      const [msg] = chunk.data as any[];
      if (msg?.content) setReport((r) => r + msg.content);
    }
  }
  setBusy(false);
}
```

2. 渲染 Markdown（**必须加安全过滤**）：

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";

<ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
  {report}
</ReactMarkdown>
```

3. 做一个"研究时间线"侧边栏，把 `steps` 显示出来。你会看到类似：

```
14:02:11  clarify_with_user
14:02:14  write_research_brief
14:02:16  supervisor
14:02:19  supervisor_tools      ← 这一条意味着同时开了好几个调研员
14:03:41  supervisor
14:03:44  supervisor_tools
14:04:50  final_report_generation
```

**预期结果**：报告边生成边显示；侧边栏能看到研究推进到哪一步。**这一步做完，产品就有了"灵魂"—— 用户愿意等，因为看得见进展。**

> 💡 **本项目最大的产品卖点就是这个进度可视化**。竞品大多只给最终报告，而你能展示"3 个调研员正在并行查资料"——这是架构（并行子图）带来的天然优势，一定要用上。

---

### 阶段 4：配置面板（预计 1 天）

**目标**：用户能在界面上调模型、并发数、搜索引擎，而不用改代码。

**操作**

1. 后端加接口（见 §4.2 的 `config_schema` 代码），放到 `src/server/routers/config.py`，并在 `app.py` 里注册：

```python
# src/server/app.py
from fastapi import FastAPI
from server.routers import config as config_router

app = FastAPI(title="Open Deep Research API", version="0.1.0")
app.include_router(config_router.router)

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

2. 前端调 `/api/config-schema` 拿到字段清单，按 `type` 渲染控件：

| `type` 值 | 渲染成 |
| --- | --- |
| `slider` | 滑块（用 `min`/`max`/`step`） |
| `select` | 下拉框（用 `options`） |
| `number` | 数字输入框 |
| `boolean` | 开关 |
| `text` | 文本框 |
| `mcp` | 专门的 MCP 配置组件 |

3. 把用户选择的值塞进 `config.configurable` 一起提交。

**预期结果**：界面出现配置面板，改一个参数（比如并发数从 5 改成 2），下次运行就生效。

---

### 阶段 5：数据持久化（预计 2~3 天）

**目标**：服务重启后，历史报告和会话不丢。

**操作**

1. 起一个 PostgreSQL（最简单是用 Docker）：

```powershell
docker run -d --name odr-pg -e POSTGRES_PASSWORD=odr -e POSTGRES_DB=odr -p 5432:5432 postgres:16
```

2. 安装数据库依赖：

```powershell
uv add sqlalchemy psycopg[binary] alembic
uv add langgraph-checkpoint-postgres
```

3. 建表（SQL 见 §3.4），用 Alembic 管理迁移：

```powershell
uv run alembic init migrations
uv run alembic revision --autogenerate -m "init reports/usage/quotas"
uv run alembic upgrade head
```

4. 在 FastAPI 的**启动钩子**里初始化连接池（平台支持自定义生命周期事件）：

```python
# src/server/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from server import db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()      # 启动时建连接池
    yield
    await db.close_pool()     # 关闭时释放

app = FastAPI(title="Open Deep Research API", lifespan=lifespan)
```

5. `.env` 加 `DATABASE_URL=postgresql+psycopg://postgres:odr@localhost:5432/odr`

**预期结果**：重启服务后，历史报告列表还在。

> ⚠️ 注意区分两件事：
> - **图的状态**（消息、笔记）→ 由平台的 checkpointer 管。开发模式是内存，生产要换成 Postgres checkpointer。
> - **业务数据**（报告归档、用量、配额）→ 你自己的表，本阶段建的。
> 两者都要持久化，别漏了前者。

---

### 阶段 6：鉴权、配额与成本护栏（预计 3~4 天）⭐ 上线前必做

**目标**：防止账单失控，防止用户看到别人的报告。

**操作**

1. 前端接入 Supabase 登录（或你自己的登录体系），拿到 JWT。

2. 自定义接口里校验令牌，提取用户 ID：

```python
# src/server/deps.py
from fastapi import Header, HTTPException

async def current_user_id(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "缺少登录令牌")
    token = authorization.split(" ", 1)[1]
    # 与 security/auth.py 保持同一套校验方式
    user_id = verify_supabase_token(token)      # 实现见 security/auth.py
    if not user_id:
        raise HTTPException(401, "登录令牌无效")
    return user_id
```

3. 在"发起研究"前查配额：

```python
@router.post("/api/runs")
async def start_run(payload: RunRequest, user_id: str = Depends(current_user_id)):
    ok, reason = await quota_service.check(user_id)     # 余额 + 并发数
    if not ok:
        raise HTTPException(429, reason)
    thread = await platform_create_thread(user_id)
    return {"thread_id": thread}
```

4. 运行结束后（用平台 Webhook 或轮询）落库 + 扣费：

```python
await reports_service.archive(thread_id, final_report, raw_notes)
await quota_service.charge(user_id, cost_cent)
```

5. 前端展示剩余配额，并在开跑前做二次确认。

**预期结果**：
- 用户 A 看不到用户 B 的报告；
- 配额用尽时返回 429，前端给出友好提示；
- 每一笔花费都能追溯到人和会话。

> 🚨 **这一步不要省。** 前文 §3.4 说过，一次研究可能几块钱。没有护栏就对外开放，等于把信用卡放在门口。

---

### 阶段 7：生产部署（预计 2~3 天）

**目标**：一键部署，push 代码即上线。

**操作（方案 A：LangGraph Platform Cloud，最省事）**

1. 在 LangSmith 控制台连接 GitHub 仓库；
2. 选择分支与环境（dev / prod），配置环境变量为 Secrets；
3. Push 即自动部署。

**操作（方案 B：自托管 Docker）**

1. 根目录新建 `Dockerfile`（平台会自动生成，通常不需要手写；如需定制可用 `dockerfile_lines`）：

```json
{
  "dockerfile_lines": [
    "RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils"
  ]
}
```

2. 构建前端并把产物交给 FastAPI 托管：

```python
# src/server/app.py
import os
from fastapi.staticfiles import StaticFiles

WEB_DIST = os.getenv("WEB_DIST", "web/dist")
if os.path.isdir(WEB_DIST):
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
```

3. 构建流程：

```powershell
cd web && npm ci && npm run build && cd ..
# 然后照常 langgraph build / docker build
```

**预期结果**：访问生产域名直接看到完整应用（前端 + 接口 + 研究服务，一个入口）。

---

### 阶段汇总

| 阶段 | 内容 | 工期 | 产出 |
| --- | --- | --- | --- |
| 0 | 跑通现状 | 0.5 天 | 能手动触发一次研究 |
| 1 | 后端开口子 | 0.5 天 | `/api/health` 可用，CORS 配好 |
| 2 | 前端骨架 + 代理联调 | 1 天 | 能提问并拿到报告 |
| 3 | 流式输出 + 进度可视化 | 2~3 天 | **体验质变**，边查边写 |
| 4 | 配置面板 | 1 天 | 用户可调参数 |
| 5 | 数据持久化 | 2~3 天 | 重启不丢数据 |
| 6 | 鉴权 + 配额 + 成本 | 3~4 天 | **可对外上线** |
| 7 | 生产部署 | 2~3 天 | 一条流水线 |
| **合计** | | **约 12~18 人日** | |

> **最小可演示版本（阶段 0~3）只需 4~5 人日**，就能做出一个明显优于"只能看命令行"的产品。建议先做到这里拿反馈，再决定是否投入阶段 5~7。

---

## 6. 常见问题与注意事项

### 6.1 环境类

**Q1：启动报 `Authorization header missing` 或 500？**
`src/security/auth.py` 需要 Supabase。若 `.env` 里没有 `SUPABASE_URL`/`SUPABASE_KEY`，`supabase` 对象是 `None`，所有非 Studio 请求直接 500。
→ 本地开发：配好 Supabase，或临时注释 `langgraph.json` 的 `auth` 段（**仅限本地，切勿提交**）。

**Q2：改了 `langgraph.json` 没生效？**
每次改完都要**重启** `langgraph dev`。它不会热加载配置文件。

**Q3：重启后之前的会话全没了？**
开发模式用的是内存存储，这是设计如此。
→ 需要持久化就上阶段 5（Postgres）。

**Q4：Windows 上路径/换行出问题？**
- 激活虚拟环境用 `.venv\Scripts\activate`（不是 `source`）
- Git 建议设 `git config core.autocrlf input`，避免 shell 脚本被转成 CRLF 后在 Linux 容器里执行失败

### 6.2 前端联调类

**Q5：浏览器报 CORS 错误？**
按顺序排查：
1. `langgraph.json` 的 `http.cors.allow_origins` 是否包含你的前端地址（**要含协议和端口**：`http://localhost:5173`，不能只写 `localhost:5173`）
2. 是否重启了服务
3. 开发环境其实**可以完全不用管 CORS**——走 Vite 代理即可（见阶段 2）

**Q6：SSE 不"流"，要等几分钟才一次性出来？**
几乎一定是某层做了缓冲。检查：
- Nginx 反代要设 `proxy_buffering off;` 和 `proxy_read_timeout 3600s;`
- 响应头加 `X-Accel-Buffering: no`
- 别在中间套会压缩/缓冲的中间件

**Q7：页面显示研究完成了但没内容？**
检查 `final_report` 是否以 `Error generating final report:` 开头——本项目会把异常原文写进报告字段（`deep_researcher.py:687`）。前端应该识别这个前缀并以错误态展示。

**Q8：改了前端代码但页面没变？**
确认 Vite dev server 在跑且没有报错退出。另外 `.env.development` 改动需要重启 Vite（Vite 不热更新 env 文件）。

### 6.3 成本与性能类

**Q9：一次研究花多少钱？**
差别很大，取决于模型与参数。默认配置下大致在几毛到几块人民币量级。README 提示跑 100 条评估需 20~100 美元。
→ **调试时一定要把 `max_concurrent_research_units` 和 `max_researcher_iterations` 调到最小。**

**Q10：成本怎么降？**
按性价比排序：
1. `max_concurrent_research_units`：5 → 2~3（省约 40~50%）
2. `max_content_length`：50000 → 20000（摘要输入减 60%）
3. `summarization_model` 换成更便宜的（如 `gpt-4.1-mini` → `gpt-4.1-nano`）
4. 相同问题加结果缓存
→ 每次调整都建议用 `tests/run_evaluate.py` 跑小样本对比质量，别拍脑袋。

**Q11：为什么感觉很慢？**
这是正常的——一次研究要跑几十到几百次大模型调用和搜索。**不要试图"优化代码让它变快"**，应该：
- 用流式输出让用户看见进展（阶段 3）
- 提供"后台运行 + 完成通知"
- 降低并发数和迭代数

### 6.4 安全类

**Q12：报告渲染有安全风险吗？**
**有，而且不小。** 报告内容来自网上抓回来的网页，攻击者可以在网页里埋指令或恶意 HTML。
→ 必须用 `rehype-sanitize` 过滤；链接协议限制为 `http/https/mailto`。

**Q13：API 密钥会不会泄露到前端？**
只要遵守"只把 `VITE_` 前缀的变量放前端"就不会。Vite 只会把 `VITE_` 开头的变量打进前端包，其他环境变量根本不会暴露。
→ **规则：任何真正的密钥，变量名都不要以 `VITE_` 开头。**

**Q14：用户能看到别人的报告吗？**
只要你的自定义接口都用 `current_user_id` 依赖做过滤，且平台侧 `auth.py` 正常工作，就看不到。
→ **每加一个新接口，第一件事就是加鉴权依赖。** 建议写个测试专门扫这个。

### 6.5 架构类

**Q15：能不能把核心研究逻辑改一改？**
能，但**强烈建议前 4 个阶段完全不要动 `src/open_deep_research/`**。先在外围扩展，等对系统足够熟悉再考虑内部优化。
如果确实要改，请务必先补测试（见《代码库研究报告》第 4 节）——目前这个项目**零单元测试**，改核心代码没有安全网。

**Q16：要不要拆微服务？**
不要。理由见 §3.3。除非你要把"导出 PDF""批量任务"这类无状态功能独立出去。

**Q17：`src/legacy/` 要不要删？**
它和主实现完全独立、互不引用。如果确定不用，可以删掉以减小维护面积（约 3300 行）。但删之前确认没有外部脚本引用它。

**Q18：前端字段和后端参数不同步怎么办？**
不要手写字段清单——始终从 `/api/config-schema` 动态生成（阶段 4）。
再写一个契约测试，断言后端返回的字段集合与预期一致，这样后端改参数时 CI 会立刻报警。

---

## 7. 附录：速查表

### 7.1 关键文件位置

| 我想改… | 去这里 |
| --- | --- |
| 服务端口/图入口/CORS/自定义应用 | `langgraph.json` |
| 所有可调参数的默认值 | `src/open_deep_research/configuration.py` |
| 前端表单的元数据（`x_oap_ui_config`） | `src/open_deep_research/configuration.py:42-233` |
| 研究流程（5 个节点） | `src/open_deep_research/deep_researcher.py` |
| 三层图的装配 | `deep_researcher.py:353`（主管）、`:589`（研究员）、`:701`（主图） |
| 搜索工具实现 | `src/open_deep_research/utils.py:43-213` |
| 登录校验 | `src/security/auth.py` |
| 提示词（决定输出质量） | `src/open_deep_research/prompts.py` |
| 评估脚本 | `tests/run_evaluate.py` |

### 7.2 常用命令

```powershell
# 启动后端（开发）
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.11 langgraph dev --allow-blocking

# 启动前端（开发）
cd web && npm run dev

# 构建前端
cd web && npm run build

# 代码检查
uv run ruff check .

# 跑评估（注意：会花钱！）
python tests/run_evaluate.py
```

### 7.3 默认参数与调优建议

| 参数 | 默认 | 调试建议 | 省钱建议 |
| --- | --- | --- | --- |
| `allow_clarification` | `true` | 调试时设 `false`（省一轮） | 保持 `true`（质量更好） |
| `max_concurrent_research_units` | 5 | 1 | 2~3 |
| `max_researcher_iterations` | 6 | 1 | 3~4 |
| `max_react_tool_calls` | 10 | 3 | 5 |
| `max_content_length` | 50000 | 5000 | 20000 |
| `summarization_model` | `gpt-4.1-mini` | `gpt-4.1-nano` | `gpt-4.1-nano` |
| `search_api` | `tavily` | 保持 | 保持（结果质量最好） |

### 7.4 推荐阅读顺序（新手）

1. 本文档 §1（搞清现在是什么）
2. `README.md` 的 Quickstart（跑起来）
3. 阶段 0 → 阶段 3（做出能用的东西）
4. 《代码库研究报告》§2（理解全流程细节）
5. 《代码库研究报告》§3（了解已知坑）
6. 本文档 §5 阶段 5~7（工程化）

---

*本文档基于 `main` 分支实际代码编写。所有配置字段与接口路径均已对照官方文档核实。若后续项目升级，请重点复核 `langgraph.json` 的 `http` 配置段与 `@langchain/langgraph-sdk` 的版本兼容性。*

---

## 8. 落地记录：自研服务器方案已实施（2026-09-06）

> 本节记录 §5 中"核心三件套"（自定义接口 + 会话持久化 + 前端）的**实际落地结果**。
> 与上文方案的一个关键差异：**没有**采用"把 FastAPI 塞进 LangGraph 服务（`http.app`）"，
> 而是选了**完全自研的独立 FastAPI 服务**直接调用研究图。原因：不依赖 langgraph-cli 版本
> （CORS 配置需要 ≥0.4，仓库锁定 0.3.1）、鉴权与归档完全自主可控、`langgraph.json` 保持
> 原样（LangGraph Studio 调试路径不受影响）。

### 8.1 架构（已实现）

```
web/ (Vite + React + TS, :5173 dev / dist 静态产物)
   │  HTTP + SSE（/api 代理，生产同域）
   ▼
src/server/ (FastAPI :8000, uvicorn)
   ├── graphs.py  从 deep_researcher_builder 重新编译图，
   │              注入 AsyncPostgresSaver 检查点  ← 会话持久化的关键
   ├── db.py / models.py / migrations/          ← 业务归档表
   ├── deps.py   AUTH_MODE=local(免鉴权+成本上限) | supabase(JWT)
   └── routers/  sessions(SSE 流式) + health
   ▼
PostgreSQL 16（docker-compose.dev.yml）
   同一库承载：langgraph 检查点表（自动建） + research_reports 业务表
```

**核心代码零改动**：`src/open_deep_research/` 未做任何修改；服务端只 import
`deep_researcher_builder`（`deep_researcher.py:701`）自行 `compile(checkpointer=...)`。

### 8.2 关键文件索引

| 文件 | 作用 |
| --- | --- |
| `src/server/app.py` | FastAPI 入口；lifespan 中初始化 DB + 编译图；生产托管 `web/dist` |
| `src/server/graphs.py` | `GraphManager`：AsyncPostgresSaver 生命周期 + 图单例 |
| `src/server/deps.py` | `get_current_user_id`（local/supabase 双模式）+ `apply_cost_caps` 成本护栏 |
| `src/server/routers/sessions.py` | 会话 CRUD + `POST /{id}/runs/stream` SSE 流式端点 + 完成后归档 |
| `src/server/db.py` / `models.py` | SQLAlchemy async 引擎 + `research_reports` 表 |
| `migrations/` | Alembic（async 模板），`0001_initial` 建业务表 |
| `docker-compose.dev.yml` | 本地 Postgres 16（无 Docker 时可指向任意外部 Postgres） |
| `web/src/lib/api.ts` | fetch 封装 + 手工 SSE 解析（POST 流式不支持 EventSource） |
| `web/src/App.tsx` 等 | 会话列表 / 对话+进度时间线 / Markdown 报告（rehype-sanitize 必加） |
| `tests/server/test_server_unit.py` | 13 个无网络单元测试（鉴权模式、成本上限、SSE 格式等） |

### 8.3 接口清单（已实现）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 返回 `{status, db, graph, auth_mode}`，DB/图不可用时仍返回 200 + false |
| POST | `/api/sessions` | 创建会话（`{question}`），id 即 LangGraph thread_id |
| GET | `/api/sessions` | 当前用户会话列表（分页，按创建时间倒序） |
| GET | `/api/sessions/{id}` | 详情：归档字段 + 从检查点读取的完整消息历史 |
| POST | `/api/sessions/{id}/runs/stream` | **SSE 流式研究**：`node`（节点完成）/`message`（LLM 文本增量，带节点名）/`done`（status + final_report）/`error` |

会话状态机：`created → running → awaiting_input（澄清等待用户回复）| completed | failed`。
澄清续聊：直接再次 `runs/stream` 带 `{message}`，检查点按 thread_id 恢复上下文。

### 8.4 启动步骤（Windows PowerShell/cmd）

```powershell
:: 1. 准备环境与数据库
copy .env.example .env       :: 填入 LLM/搜索密钥；DATABASE_URL 保持默认
docker compose -f docker-compose.dev.yml up -d   :: 或指向任意 Postgres
uv run alembic upgrade head  :: 建业务表（AUTH_MODE=local 时启动也会自动建）

:: 2. 启动后端（:8000）
uv run uvicorn server.app:app --app-dir src --port 8000

:: 3. 启动前端（:5173，另开终端）
cd web && npm install && npm run dev

:: 生产模式：cd web && npm run build 后重启后端，直接访问 :8000（同域托管）
```

### 8.5 与原方案的差异 / 当前限制

| 项 | 原方案 | 实际落地 |
| --- | --- | --- |
| 接口层 | `http.app` 挂进 LangGraph 服务 | 独立 FastAPI 进程（LangGraph 服务器仅留作 Studio 调试） |
| CORS | `langgraph.json` 的 `http.cors`（需 langgraph-cli ≥0.4） | 开发走 Vite 代理；生产前后端同域，天然无跨域 |
| 会话持久化 | `langgraph up` 自动托管 | 自研 `AsyncPostgresSaver` 检查点（线程/消息/报告状态全持久化） |
| 配置面板 | `/api/config-schema` 动态表单 | 未实现（后续阶段 4） |
| 用量/配额表 | `usage_events` + `quotas` | 未实现（上线前必做，见 §3.4/§5 阶段 6） |
| MCP OAuth | 依赖平台 Store | 当前服务进程未挂 Store，`mcp_config.auth_required=true` 的场景不可用 |
| 断线恢复 | — | SSE 断开则本次 run 中断；状态已持久化，重新发送即可续聊 |

### 8.6 验证记录

- `uv run pytest tests/server -q` → **13 passed**（无网络、无 DB）。
- 无 DB 启动冒烟：`/api/health` 返回 `db:false, graph:false`；业务接口返回 503 + 明确提示；`web/dist` 静态托管 200。
- 端到端持久化验证（重启服务后会话/报告仍在）需 Postgres：本机无 Docker/Postgres，按 §8.4 启动数据库后即可复验。
