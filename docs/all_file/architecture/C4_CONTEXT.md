# C4 架构视图 L1 —— 系统上下文（System Context）

> 红色实线框/连线 = **本次新增模块与新增接口**；蓝色虚线 = **受本次变更影响的上下游依赖路径**。
> 变更基准：v0.0.16 + 自研服务层（详见 `docs/FULLSTACK_EXTENSION_PLAN.md` §8）+ 扩展模块（详见 `docs/TECHNICAL_SUMMARY.md` §8.3）。

```mermaid
graph TB
    user["研究用户<br/>(浏览器)"]

    subgraph system["Open Deep Research 系统"]
        odr["深度调研智能体<br/>LangGraph 双层多智能体<br/>+ 自研 FastAPI 服务层"]
    end

    llm["LLM 提供商<br/>OpenAI / Anthropic / Google / ..."]
    tavily["Tavily 搜索 API"]
    ddg["DuckDuckGo 搜索"]
    arxiv["arXiv 学术库"]
    mcp["MCP 服务器<br/>(streamable-http)"]
    supabase["Supabase<br/>(JWT 认证)"]
    pg["PostgreSQL 16<br/>检查点 + 业务表 + 用量台账"]
    langsmith["LangSmith<br/>(追踪/评估)"]
    studio["LangGraph Studio<br/>(开发者调试)"]

    user -->|"HTTPS / SSE"| odr
    studio -.->|"开发者调试（未变更）"| odr
    odr -->|"模型调用"| llm
    odr -->|"默认搜索"| tavily
    odr ==>|"新增检索源"| ddg
    odr ==>|"新增检索源"| arxiv
    odr -.->|"MCP 工具（未变更）"| mcp
    odr -.->|"JWT 校验（未变更）"| supabase
    odr ==>|"用量台账 usage_events（新增表）"| pg
    odr -.->|"追踪"| langsmith

    classDef newmod fill:#ffe3e3,stroke:#cc0000,stroke-width:2px,color:#7a0000
    classDef sysnode fill:#f5f7fa,stroke:#37505d,stroke-width:1.5px
    classDef ext fill:#ffffff,stroke:#7e8588
    classDef extnew fill:#ffe3e3,stroke:#cc0000,stroke-width:2px

    class odr sysnode
    class ddg,arxiv extnew
    class user,llm,tavily,mcp,supabase,pg,langsmith,studio ext

    linkStyle 0 stroke:#cc0000,stroke-width:2px
    linkStyle 4 stroke:#cc0000,stroke-width:2px
    linkStyle 5 stroke:#cc0000,stroke-width:2px
    linkStyle 8 stroke:#cc0000,stroke-width:2px
    linkStyle 1 stroke:#2563eb,stroke-dasharray:6 4
```

## 本次变更在 L1 视图上的含义

| 变更 | 类型 | 说明 |
|---|---|---|
| DuckDuckGo / arXiv 检索源 | 新增外部交互 | 经 `extra_retrievers` 配置启用，未配置时零行为差异 |
| `usage_events` 用量台账 | 新增数据库表 | PostgreSQL 迁移 `0002`，独立于检查点表 |
| 用户 ↔ 系统 SSE 契约 | 接口扩展（向后兼容） | `done` 事件新增 `usage` 字段；`error` 语义增强（原静默失败现显式上报） |
| 本地文档库 | 新增内部能力 | 属 L2 视图的 `docstore` 组件（文件系统存储，无新增外部服务） |

> 完整调用链与受影响路径见 [C4_CONTAINER.md](C4_CONTAINER.md) 与 [C4_COMPONENT.md](C4_COMPONENT.md)。
