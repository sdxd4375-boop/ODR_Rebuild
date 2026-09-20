# C4 架构视图 L3 —— 组件图（Component，聚焦研究图与服务层内部）

> 红色 = **新增组件**；黄色描边 = **被修改的既有组件**（仅 3 处内核改动 + sessions 路由增强）；蓝色虚线 = **受影响的调用链**。

```mermaid
graph TB
    subgraph graphlayer["核心研究图（deep_researcher.py）"]
        nodes["图节点序列<br/>clarify / brief / supervisor⇄researcher / compress / report"]
        sut["supervisor_tools 异常处理<br/>(deep_researcher.py:334)"]
        gat["get_all_tools (utils.py:594)"]
    end

    subgraph retrievers_["retrievers.py（新增）"]
        reg["RETRIEVER_TOOLS 注册表<br/>parse_extra_retrievers"]
        ddg_t["duckduckgo_web_search<br/>(重试+退避)"]
        ax_t["arxiv_search<br/>(ArxivRetriever)"]
        ld_t["local_docs_search"]
        fmt["format_sources<br/>--- SOURCE N --- 约定"]
    end

    subgraph docstore_["docstore.py（新增）"]
        idx["LocalDocIndex<br/>分块 / 余弦检索 / 原子持久化"]
        emb["default_embed_fn<br/>(EMBEDDING_MODEL, 可注入)"]
    end

    subgraph server_["服务层（src/server）"]
        srun["stream_run (sessions.py)<br/>SSE 生成器"]
        uagg["aggregate_usage / _record_usage<br/>usage_events 台账（新增）"]
        chart["generate_charts（charts.py，新增）"]
        sbx["run_python_code（sandbox.py，新增）"]
        exp["markdown_to_pptx / docx（exporters.py，新增）"]
    end

    subgraph ext["外部"]
        llm["LLM API"]
        net["DuckDuckGo / arXiv 网络"]
        pg[("PostgreSQL")]
        fs[("data/ 文件")]
    end

    nodes -->|"① 工具装配（每轮研究员）"| gat
    gat ==>|"② extra_retrievers 钩子"| reg
    reg --> ddg_t
    reg --> ax_t
    reg --> ld_t
    ddg_t --> fmt
    ax_t --> fmt
    ld_t ==> idx
    idx --> emb
    idx ==> fs
    ddg_t ==> net
    ax_t ==> net
    fmt -.->|"③ 工具结果进 researcher_messages（受影响：来源标签新增）"| nodes
    sut -.->|"④ or True 修复：非 token 异常向上抛（受影响）"| srun
    srun ==>|"⑤ usage_metadata 记录"| uagg
    uagg ==> pg
    srun -.->|"⑥ done 事件带 usage（受影响）"| srun
    chart ==>|"⑦ 生成代码交沙箱执行"| sbx
    sbx ==> fs
    chart -.->|"⑧ 报告 Markdown 注入图片引用（受影响）"| srun
    exp ==> fs
    nodes ==> llm

    classDef newmod fill:#ffe3e3,stroke:#cc0000,stroke-width:2px,color:#7a0000
    classDef modiface fill:#fff0cc,stroke:#b8860b,stroke-width:2px
    classDef normal fill:#f5f7fa,stroke:#37505d
    classDef extn fill:#ffffff,stroke:#7e8588

    class reg,ddg_t,ax_t,ld_t,fmt,idx,emb,uagg,chart,sbx,exp newmod
    class gat,sut modiface
    class nodes,srun normal
    class llm,net,pg,fs extn

    linkStyle 1 stroke:#cc0000,stroke-width:2px
    linkStyle 7 stroke:#cc0000,stroke-width:2px
    linkStyle 9 stroke:#cc0000,stroke-width:2px
    linkStyle 10 stroke:#cc0000,stroke-width:2px
    linkStyle 11 stroke:#cc0000,stroke-width:2px
    linkStyle 14 stroke:#cc0000,stroke-width:2px
    linkStyle 15 stroke:#cc0000,stroke-width:2px
    linkStyle 17 stroke:#cc0000,stroke-width:2px
    linkStyle 18 stroke:#cc0000,stroke-width:2px
    linkStyle 20 stroke:#cc0000,stroke-width:2px
    linkStyle 12 stroke:#2563eb,stroke-dasharray:6 4
    linkStyle 13 stroke:#2563eb,stroke-dasharray:6 4
    linkStyle 16 stroke:#2563eb,stroke-dasharray:6 4
    linkStyle 19 stroke:#2563eb,stroke-dasharray:6 4
```

## 内核改动定位（全部改动清单）

| # | 位置 | 改动 | 行数 |
|---|---|---|---|
| 1 | `src/open_deep_research/configuration.py` | 增量字段 `extra_retrievers: Optional[str]` | +13 |
| 2 | `src/open_deep_research/utils.py:594`（get_all_tools 尾部） | `tools.extend(await load_extra_retrievers(config))` + 名称查重 | +10 |
| 3 | `src/open_deep_research/deep_researcher.py:334` | `or True` 异常吞噬修复：仅 token 超限静默结束，其余向上抛 | 净 +4 |
| — | 其余全部为新增文件 | retrievers.py / docstore.py / sandbox.py / charts.py / exporters.py / documents·export 路由 / UsageEvent / 迁移 0002 | 约 1100 行 |

## 同版本 PlantUML（Component 层）

```plantuml
@startuml
skinparam rectangle {
  BackgroundColor<<new>> #ffe3e3
  BorderColor<<new>> #cc0000
  BackgroundColor<<mod>> #fff0cc
  BorderColor<<mod>> #b8860b
}
skinparam ArrowColor #37505d
skinparam arrow {
  Color<<new>> #cc0000
  Color<<affected>> #2563eb
  Style<<affected>> dashed
}

rectangle "get_all_tools\n(utils.py:594)" <<mod>> as GAT
rectangle "RETRIEVER_TOOLS\n注册表" <<new>> as REG
rectangle "duckduckgo_web_search" <<new>> as DDG
rectangle "arxiv_search" <<new>> as AX
rectangle "local_docs_search" <<new>> as LD
rectangle "LocalDocIndex\ndocstore.py" <<new>> as IDX
rectangle "图节点序列" as NODES
rectangle "supervisor_tools\n异常处理 (:334)" <<mod>> as SUT
rectangle "stream_run\nSSE 生成器" as RUN
rectangle "aggregate_usage /\n_record_usage" <<new>> as UAG
rectangle "generate_charts" <<new>> as CH
rectangle "run_python_code\n(sandbox)" <<new>> as SBX
rectangle "markdown_to_pptx/docx" <<new>> as EXP
database "PostgreSQL" as PG
database "data/ 文件" as FS
cloud "DuckDuckGo / arXiv" as NET

NODES --> GAT
GAT -[#cc0000]-> REG : <<new>> extra_retrievers 钩子
REG --> DDG
REG --> AX
REG --> LD
LD -[#cc0000]-> IDX
DDG -[#cc0000]-> NET
AX -[#cc0000]-> NET
IDX -[#cc0000]-> FS
GAT .[#2563eb].> NODES : <<affected>> 工具集扩展
SUT .[#2563eb].> RUN : <<affected>> or True 修复
RUN -[#cc0000]-> UAG
UAG -[#cc0000]-> PG
CH -[#cc0000]-> SBX
SBX -[#cc0000]-> FS
EXP -[#cc0000]-> FS
RUN .[#2563eb].> RUN : <<affected>> done 事件带 usage
@enduml
```
