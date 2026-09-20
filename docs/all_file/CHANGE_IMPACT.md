# 变更效果与影响面量化说明

> 变更范围：扩展模块（检索插件化 / 本地文档 RAG / 代码沙箱 / 图表管道 / PPTX-DOCX 导出 / 用量计量）
> + 内核 3 处最小改动（`extra_retrievers` 字段、`get_all_tools` 钩子、`or True` 异常吞噬修复）。
> 数据口径：标注【实测】的数据来自本机 pytest/ruff 执行记录；标注【推算】的为基于代码结构的
> 有依据估计，**未经性能压测验证**（本机无 Postgres/Docker，端到端基线未建立）。

---

## 一、正向效果

### 1.1 已实测的收益【实测】

| 指标 | 变更前 | 变更后 | 度量来源 |
|---|---|---|---|
| 服务层测试用例数 | 13 | **33（+154%）** | `uv run pytest tests/server` 两次执行记录 |
| 研究员可用检索源 | 1（Tavily）+ 2 原生 | **+3**（DuckDuckGo / arXiv / 本地文档 RAG） | `RETRIEVER_TOOLS` 注册表（3 passed 断言） |
| API 端点路径数 | 5 | **9（+80%）** | OpenAPI schema 冒烟：`/api/documents`×2、`/charts`、`/export/{fmt}` |
| 异常可见性 | 研究阶段**任何**异常静默终止并出低质报告（`deep_researcher.py:334`） | 仅 token 超限静默降级；其余异常显式抛出 → SSE `error` 事件 | 代码审查 + 单测覆盖分支 |
| 成本归因能力 | **零**（token 用量不可追溯） | 按会话×节点×模型的用量台账（`usage_events`），`done` 事件实时下发 | 单测 `test_aggregate_usage_*` |
| 安全执行能力 | 无（模型生成的代码无处可跑） | AST 导入白名单 + `python -I` 隔离子进程 + 超时 + 独立缓存目录 | 5 个沙箱单测（含白名单拒绝、超时、真实出图） |
| ruff 检查 | — | 本次新增/修改文件 **0 违规** | `uvx ruff check` 执行记录 |

### 1.2 基于结构的推算收益【推算，待压测验证】

| 收益 | 依据 | 预期量级 |
|---|---|---|
| 主研究路径零延迟回归 | `load_extra_retrievers` 空配置时仅做一次字典/字符串解析即返回（`retrievers.py`） | 未启用新检索源时，工具装配路径新增开销 < 1ms |
| 本地文档检索延迟 | NumPy 余弦相似度单矩阵运算：10k chunks × 1536 维约 10⁷ 次乘加 | 数十 ms 量级/查询；10 万 chunks 后建议迁移 pgvector（`TECHNICAL_SUMMARY` §8.1 已注明） |
| 报告产物扩展 | 出图为按需触发（`POST /charts`），不阻塞主研究链路 | 单图成本 = LLM 一次调用 + 沙箱执行 ≤ 30s（硬超时） |
| 混合调研覆盖 | 私有文档 + 公网检索同场可用（此前私域资料无法进入研究员上下文） | 质量收益待评估脚本（`tests/run_evaluate.py`）对照 |
| 成本治理前置条件 | `usage_events` 按 (user, thread, node, model) 计量 | 配额表/计费的功能前提已就绪（原为不可能） |

### 1.3 未产生影响的方面（同等重要）

- **核心研究图行为**：未配置 `extra_retrievers` 时，除 `or True` 修复外，图执行路径逐行等价；
- **检查点格式**：`AgentState` 未改动，旧检查点完全兼容；
- **部署形态**：无新增必需外部服务（向量索引为零依赖实现）。

---

## 二、负面风险与接口兼容性

### 2.1 风险清单

| # | 风险 | 等级 | 影响面 | 缓解措施（已实现） | 遗留缺口 |
|---|---|---|---|---|---|
| R-01 | **报告脏写**：`POST /charts` 会把图表注入后的 Markdown **覆盖** `research_reports.final_report`，原文不保留 | 中 | 报告归档 | 注入为纯追加式（仅在标题后插图片引用） | ⚠️ 原始报告未快照；建议增加 `final_report_original` 列（P0 修复项） |
| R-02 | **用量重复计数**（provider 差异）：流式 usage 语义不一致（OpenAI 末次快照 vs Anthropic 累计） | 中 | 计量准确性 | 按 (节点, 消息ID) 取**末次值**聚合，两类语义均已正确（单测覆盖） | 未对 Gemini/DeepSeek 等其余 provider 实测语义 |
| R-03 | **沙箱逃逸面**：subprocess 隔离弱于容器（无内存/网络硬限制，Windows 无 rlimit） | 中 | 安全 | 导入白名单（AST）+ `-I` 隔离 + 30s 超时 + 独立临时目录 | 生产部署必须切换 Docker 执行（`TECHNICAL_SUMMARY` §8.2 已标注） |
| R-04 | **本地文档索引并发写**：JSON 原子替换仅进程内加锁，多进程同时入库可能丢失更新 | 低 | 文档数据 | 单进程 uvicorn 下安全（threading.Lock） | 多 worker 部署时需迁移到数据库存储 |
| R-05 | **DuckDuckGo 限流**：无 key 引擎依赖爬取，频率高时被限 | 低 | 检索可用性 | 3 次指数退避重试；Tavily 仍为默认主源 | 高频场景应优先付费源 |
| R-06 | 出网面扩大：研究员新增两个外部检索目标 | 低 | 网络/合规 | 均为只读检索协议 | 部署环境需放行相应域名 |

### 2.2 接口兼容性结论：**无强制升级**

| 契约 | 变更类型 | 兼容性 |
|---|---|---|
| SSE `done` 事件 | **增量字段** `usage` | 旧客户端忽略即可，无破坏 |
| SSE `error` 事件 | 触发频率增加（原被吞掉的异常现在上报） | 语义增强；本仓库前端已有 `error` 分支，**无需升级**；仅依赖“研究必出报告”假设的第三方消费者需知悉 |
| REST 端点 | 全部为新增（`/api/documents*`、`/charts`、`/export/{fmt}`） | 纯增量，旧路径签名不变 |
| LangGraph 配置 | 增量字段 `extra_retrievers` | 缺省空 = 行为不变；Studio/OAP 调用方不受影响 |
| 数据库 | 新增表 `usage_events`（迁移 0002） | 不触碰既有表；旧版本代码可读写同库（无列变更） |

**结论：所有客户端（含第三方 LangGraph SDK 消费者）无需强制升级；`error` 事件行为增强是唯一需要周知的语义变化。**

---

## 三、回滚策略

| 变更 | 回滚方式 | 验证手段 | 数据处理 |
|---|---|---|---|
| 1. `extra_retrievers` 钩子 | 清空配置项 / env `EXTRA_RETRIEVERS`，或 revert `utils.py` 一处 + 字段（git 单 commit） | 单测 `test_load_extra_retrievers_*`（空配置返回 `[]`） | 无数据 |
| 2. `or True` 修复 | revert `deep_researcher.py` 单行 | `git revert` 后跑全量测试 | 无数据；行为回退为静默降级（可接受的历史行为） |
| 3. 用量计量 | `uv run alembic downgrade 0001`（drop `usage_events`）+ revert sessions.py 计量块 | 迁移工具自带 down 验证 | 台账数据随表删除（如需保留先 `pg_dump` 单表） |
| 4. 文档 RAG | 移除 `extra_retrievers` 中的 `local_docs` + 删除 `data/docs/` 目录；代码可整文件删除（无被依赖方） | 单测 `test_docstore_*` | 索引为可再生数据（重新上传即恢复） |
| 5. 图表/导出端点 | 纯增量路由，直接 revert `routers/export.py` + `charts.py` + `exporters.py` + `sandbox.py`；主链路无任何引用 | 服务启动冒烟（health 不依赖这些模块） | `data/charts`、`data/exports` 可直接删除 |
| 6. 全量回滚 | `git revert <release-commit>` + `alembic downgrade 0001` + 删除 `data/` | 全量 33 测试 + 启动冒烟 | 见各项 |

**回滚设计原则**：所有新能力均满足“配置可关、代码可整文件撤除、主链路零耦合”三条件——
唯一需要数据库操作的是 `usage_events`（独立表，down 迁移已内置）。

---

## 四、变更面总账

| 维度 | 数值 |
|---|---|
| 新增 Python 模块 | 8 个（retrievers / docstore / sandbox / charts / exporters / documents·export 路由 / 0002 迁移） |
| 修改的既有文件 | 5 个（configuration.py / utils.py / deep_researcher.py / sessions.py / models.py / app.py） |
| 内核（open_deep_research 包）改动行数 | 约 27 行（字段 +13、钩子 +10、异常修复净 +4） |
| 新增依赖 | 3 个（matplotlib / python-pptx / python-docx，均为锁定版本的成熟库） |
| 新增配置项 | 4 个（`extra_retrievers` / `EMBEDDING_MODEL` / `ODR_DOCS_DIR` / `ODR_CHARTS_DIR`） |
| 数据库迁移 | 1 个（0002，仅新增表） |
