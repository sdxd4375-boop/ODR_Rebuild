# C4 架构视图 L2 —— 容器图（Container）

> 红色 = **本次新增模块 / 修改的接口**；蓝色虚线 = **受影响的上下游依赖路径**。

```mermaid
graph TB
    user["研究用户"]

    subgraph frontend["web/ —— 前端 (React + Vite)"]
        spa["SPA<br/>会话列表 / 对话+进度 / 报告渲染"]
    end

    subgraph server["src/server/ —— FastAPI 服务层 (:8000)"]
        rs["sessions 路由<br/>SSE 流式研究"]
        rd["documents 路由<br/>文档上传/列表/删除"]
        re["export 路由<br/>出图 / PPTX/DOCX 导出"]
        gm["GraphManager<br/>编译图 + AsyncPostgresSaver"]
        dep["deps.py<br/>AUTH_MODE 双模鉴权 + 成本钳制"]
        sb["sandbox.py<br/>受限代码执行器"]
        ch["charts.py<br/>图表生成管道"]
        ex["exporters.py<br/>PPTX/DOCX 转换"]
    end

    subgraph core["src/open_deep_research/ —— 核心研究图"]
        graph["deep_researcher.py<br/>clarify→brief→supervisor⇄researcher→compress→report"]
        gat["get_all_tools<br/>工具装配咽喉"]
        ret["retrievers.py<br/>duckduckgo/arxiv/local_docs"]
        dsi["docstore.py<br/>本地向量索引"]
        cfg["configuration.py<br/>extra_retrievers 字段"]
    end

    pgdb[("PostgreSQL<br/>checkpoints / research_reports / usage_events")]
    fs[("文件存储 data/<br/>docs_index.json / charts/ / exports/")]

    llm["LLM 提供商"]
    engines["外部搜索引擎<br/>Tavily / DuckDuckGo / arXiv"]

    user -->|"HTTP/SSE"| spa
    spa -->|"/api/sessions/*"| rs
    spa ==>|"/api/documents/*（新增）"| rd
    spa ==>|"/api/sessions/{id}/charts、/export/*（新增）"| re
    rs --> gm
    rs -.->|"done 事件新增 usage 字段（受影响）"| spa
    rd ==> dsi
    re ==> ex
    re ==> ch
    ch ==> sb
    gm --> graph
    graph --> gat
    gat ==>|"tools.extend(load_extra_retrievers)（新增钩子）"| ret
    ret ==> dsi
    cfg -.->|"extra_retrievers 透传（受影响）"| gat
    ret ==>|"检索请求（新增出网）"| engines
    graph -.->|"Tavily（默认，未变更）"| engines
    graph --> llm
    gm ==>|"检查点写入（未变更）"| pgdb
    rs ==>|"归档 + usage_events（新增表）"| pgdb
    ex -.->|"读取 charts/（受影响）"| fs
    dsi ==>|"docs_index.json（新增）"| fs

    classDef newmod fill:#ffe3e3,stroke:#cc0000,stroke-width:2px,color:#7a0000
    classDef modiface fill:#fff0cc,stroke:#b8860b,stroke-width:2px
    classDef container fill:#f5f7fa,stroke:#37505d,stroke-width:1.5px
    classDef store fill:#ffffff,stroke:#7e8588

    class rd,re,sb,ch,ex,ret,dsi newmod
    class cfg,gat,rs modiface
    class frontend,server,core container
    class spa,gm,dep container
    class pgdb,fs,engines,llm,user store

    linkStyle 2 stroke:#cc0000,stroke-width:2px
    linkStyle 3 stroke:#cc0000,stroke-width:2px
    linkStyle 6 stroke:#cc0000,stroke-width:2px
    linkStyle 7 stroke:#cc0000,stroke-width:2px
    linkStyle 8 stroke:#cc0000,stroke-width:2px
    linkStyle 9 stroke:#cc0000,stroke-width:2px
    linkStyle 12 stroke:#cc0000,stroke-width:2px
    linkStyle 13 stroke:#cc0000,stroke-width:2px
    linkStyle 15 stroke:#cc0000,stroke-width:2px
    linkStyle 19 stroke:#cc0000,stroke-width:2px
    linkStyle 21 stroke:#cc0000,stroke-width:2px
    linkStyle 5 stroke:#2563eb,stroke-dasharray:6 4
    linkStyle 14 stroke:#2563eb,stroke-dasharray:6 4
    linkStyle 20 stroke:#2563eb,stroke-dasharray:6 4
```

## 受影响上下游依赖路径说明（蓝色虚线）

| 路径 | 影响 | 兼容性 |
|---|---|---|
| 前端 ← `done` 事件 | 新增 `usage` 字段 | **向后兼容**：字段可选，旧客户端忽略即可 |
| 前端 ← `error` 事件 | `or True` 修复后研究阶段异常显式上报（原为静默出低质报告） | 行为增强；前端已实现 `error` 分支，无需强制升级 |
| `configuration → get_all_tools` | 新增 `extra_retrievers` 配置透传 | 增量字段；缺省为空 = 行为不变 |
| `exporters ← charts/` | 导出器解析报告内 `charts/<file>` 相对引用 | 新约定，旧报告无该引用则不受影响 |
| `sessions → usage_events` | 新增写入路径，best-effort（失败不阻断 run） | 对主链路无侵入 |
