# 测试执行报告 —— 扩展模块（检索插件 / RAG / 沙箱 / 图表 / 导出 / 用量计量）

| 项目 | 内容 |
|---|---|
| 报告编号 | TR-2026-0906-01 |
| 测试对象 | `TECHNICAL_SUMMARY.md` §8 扩展模块 + 内核 3 处改动 |
| 执行日期 | 2026-09-06 |
| 执行环境 | Windows 10.0.26200 / Python 3.13 / pytest 9.0.3 / 无网络依赖（单测级） |
| 结论 | **PASS（附条件）** —— 33/33 通过；端到端链路（Postgres + 真实 LLM/搜索）未验证，见 §6 |

---

## 1. 执行总览

| 指标 | 数值 |
|---|---|
| 用例总数 | 33（本轮前 13 + 新增 20） |
| 通过 | 33 |
| 失败 | 0 |
| 跳过 | 0 |
| 通过率 | **100%** |
| 执行耗时 | 4.10s（末次全量） |
| 静态检查 | ruff：新增/修改文件 0 违规（存量 2 处非本次范围，见 §5.3） |

```
命令：uv run pytest tests/server -q
结果：33 passed, 27 warnings in 4.10s
```

## 2. 新增/修改调用链 → 用例覆盖矩阵

| 调用链（对照 C4_COMPONENT.md 蓝红路径） | 覆盖用例 | 覆盖度 |
|---|---|---|
| ① `get_all_tools` → `load_extra_retrievers` 钩子 | `test_load_extra_retrievers_resolves_known_skips_unknown`、`test_parse_extra_retrievers_*`、`test_retriever_registry_has_expected_engines` | ✅ 全覆盖 |
| ② retriever 输出格式 → 提示词约定 | `test_format_sources_matches_prompt_convention`、`test_format_sources_truncates_long_content` | ✅ 全覆盖（含 4000 字符截断边界） |
| ③ 文档入库 → 索引 → `local_docs_search` | `test_docstore_add_search_remove_roundtrip`、`test_chunk_text_*`、`test_docstore_search_empty_index` | ✅ 核心 + 边界（空索引、跨页分块、持久化重载、删除幂等） |
| ④ 沙箱：白名单 / 执行 / 超时 / 出图 | `test_check_imports_*`、`test_sandbox_runs_whitelisted_code`、`test_sandbox_rejects_disallowed_import_*`、`test_sandbox_rejects_oversized_code`、`test_sandbox_timeout`、`test_sandbox_can_render_matplotlib_chart` | ✅ 全覆盖（含真实 matplotlib 渲染） |
| ⑤ 图表注入报告 Markdown | `test_inject_chart_after_first_section`、`test_inject_chart_appends_without_headings` | ✅ 结构覆盖；**LLM 抽数环节未覆盖**（需真实 LLM，见 §6） |
| ⑥ PPTX/DOCX 导出 | `test_export_to_pptx_and_docx`、`test_parse_blocks_structure` | ✅ 含产物回读断言（幻灯片标题、段落文本） |
| ⑦ 用量计量：流内记录 → 聚合 → 落库 | `test_aggregate_usage_last_chunk_per_call_wins`、`test_aggregate_usage_empty` | ⚠️ 聚合逻辑全覆盖；**落库 `_record_usage` 无 DB 集成测试** |
| ⑧ 内核改动：`or True` 修复 | 无直接单测（行为=异常向上传播，需运行整图） | ⚠️ 依赖端到端验证（见 §6 行动项 A-1） |
| ⑨ 新路由注册 | 启动冒烟（OpenAPI 9 路径清点）+ 既有 `test_auth_mode_*` 鉴权链 | ✅ 注册层验证 |

## 3. 边界条件覆盖度审查

**已覆盖的边界**：
- 输入尺寸：超长代码（32KB 上限）、超长摘要内容（4000 字符截断）；
- 空态：空索引检索、空用量聚合、无标题文档注入图表；
- 重试/退避：DuckDuckGo 3 次指数退避（结构实现，未注入故障实测）；
- 幂等/重复：文档重复入库（同 doc_id 覆盖）、用量末次值去重（模拟 OpenAI/Anthropic 两种流式语义）；
- 分块边界：滑窗重叠（1200 字符 → 3 块）、`\f` 分页符强制分块。

**未覆盖的边界（缺口）**：
- PDF 解析失败/加密 PDF/扫描件（`documents.py::_extract_text` 无单测）；
- 上传 20MB 上限、非法后缀的 HTTP 层验证（属集成测试范围）；
- 嵌入 API 失败时的入库回滚（`add_document` 在 embed 抛异常时不落盘——代码路径存在但未断言）；
- 并发入库（多请求同时 `add_document`，锁为进程内 threading.Lock）。

## 4. 异常回放（Chaos Testing）审查

**结论：系统级混沌测试未执行**（当前无可运行的完整栈：Postgres/Docker 缺位）。以下为**单元级韧性验证**（等效的故障注入子集）：

| 故障场景 | 注入方式 | 结果 |
|---|---|---|
| 沙箱内死循环 | `while True` + 2s 超时 | ✅ `TimeoutExpired` 上抛，进程回收 |
| 越权导入 | `import socket` / `subprocess` / `os` | ✅ `SandboxViolation`，代码未执行 |
| 超大输入 | 40k 行代码 | ✅ 字节上限拒绝 |
| 损坏的持久化文件 | `docstore._load` 异常分支 | ✅ 降级为空索引（代码路径），未做文件级注入实测 |
| 检索源故障 | DuckDuckGo 抛异常 | ✅ 工具返回错误字符串（不炸图）——结构实现，未网络注入实测 |
| 计量写入失败 | `_record_usage` 内部 try/except | ✅ best-effort，不阻断 run（代码路径） |
| 未知检索源配置 | `bogus_engine` | ✅ 跳过 + warning |

**建议补充的混沌场景**（按优先级）：
1. 研究中途 kill 沙箱子进程 → 断言主进程存活、报告不受污染；
2. Postgres 断连期间发起 run → 断言 SSE `error` 与检查点一致性；
3. `docs_index.json` 写入时磁盘满 → 断言原子替换不损坏旧索引；
4. 恢复演练：迁移 down/up 循环 + 旧版本代码读取新库。

## 5. 缺陷分布

### 5.1 开发期缺陷（均当轮修复，未流入交付）

| # | 缺陷 | 模块 | 根因 | 修复 |
|---|---|---|---|---|
| D-01 | `NameError: asyncio`（搜索调用崩溃） | docstore.py | 重构时遗漏导入 | 补 `import asyncio` |
| D-02 | 沙箱 preamble 被自身白名单拦截 | sandbox.py | `import os` 引导代码与用户代码共用校验 | 引入 `trusted_preamble` 通道，白名单仅约束用户代码 |
| D-03 | matplotlib 无可写缓存目录 | sandbox.py | `-I` 隔离模式下 HOME 解析失败 | 注入独立 `MPLCONFIGDIR` |
| D-04 | `NameError: Any` | exporters.py | 类型注解遗漏导入 | 补 `from typing import Any` |
| D-05 | 测试文件缺 `import os` | test_extensions.py | 重写时遗漏 | 补导入 |

缺陷阶段分布：**100% 在单元测试阶段发现并修复**，零流入集成/交付。

### 5.2 风险登记（未修复，已登记 `CHANGE_IMPACT.md` §二）

R-01 报告覆盖无原始快照、R-02 非 OpenAI/Anthropic provider 的 usage 语义未实测、R-03 生产环境沙箱需容器化、R-04 多进程并发写索引、R-06 出网面扩大。

### 5.3 存量问题（非本次范围）

`src/open_deep_research/state.py:69`、`utils.py:253` 在新版 ruff（UP045 规则）下告警——均为本次未触碰的历史代码，已核实 `git diff` 不含上述位置。

## 6. 行动项

| # | 行动 | 优先级 |
|---|---|---|
| A-1 | 启动 Postgres 后执行端到端联调：真实研究 → 出图 → 导出 → 重启持久化复验；为 `or True` 修复补传播断言 | P0 |
| A-2 | 引用校验节点落地（P0 项，未在本轮范围） | P0 |
| A-3 | CI workflow（ruff + pytest），将 §2 矩阵固化为必过门禁 | P0 |
| A-4 | 补 §3/§4 缺口：PDF 解析边界单测、4 个混沌场景脚本 | P1 |
| A-5 | 性能基线建立（见 §7） | P1 |

## 7. 性能基线

**当前状态：N/A（未建立）。** 本轮仅含单测级验证，无端到端性能数据。建立基线所需前置条件：
① 可运行的 Postgres + LLM/搜索密钥；② 端到端联调通过。建议基线指标：
`run 端到端耗时（P50/P95）`、`单节点 LLM 调用延迟`、`文档入库吞吐（页/秒）`、
`local_docs 检索延迟 @1k/10k/100k chunks`、`沙箱单图执行耗时`、`export 转换耗时`。
在基线建立前，`CHANGE_IMPACT.md` §1.2 中所有【推算】数据不得用于对外承诺。
