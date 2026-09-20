# 国内环境下的搜索引擎使用与替代方案

## 1. Tavily API Key 获取

Tavily 官方控制台为 [https://app.tavily.com](https://app.tavily.com)。

基本流程：

1. 注册并登录 Tavily；
2. 在控制台创建 API Key；
3. 将 Key 写入项目根目录 `.env`：

```env
TAVILY_API_KEY=tvly-xxxxxxxx
```

项目通过 `src/open_deep_research/utils.py` 中的 `AsyncTavilyClient`
调用 Tavily。官方 API 地址为：

```text
https://api.tavily.com/search
```

不要把 API Key 写入源代码、提交到 Git 或发送给其他人。

## 2. 国内网络可用性判断

Tavily 是否可用不能仅通过“注册成功”判断，应从实际部署机器验证：

```powershell
$env:TAVILY_API_KEY = "tvly-你的Key"

curl.exe https://api.tavily.com/search `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:TAVILY_API_KEY" `
  -d '{"query":"人工智能发展趋势","max_results":3}'
```

结果判断：

| 结果 | 含义 |
| --- | --- |
| 返回 JSON 搜索结果 | DNS、HTTPS、鉴权和搜索均正常 |
| DNS、连接或 TLS 超时 | 当前网络无法访问或代理配置有问题 |
| `401` / `403` | API Key 无效、过期或权限不足 |
| `429` | 额度或速率达到限制 |
| `5xx` | 服务端暂时异常，应记录日志并重试 |

因此，国内环境下推荐先进行小规模验证，再决定是否将 Tavily 作为生产主搜索。

## 3. 当前项目的搜索能力

当前核心配置 `SearchAPI` 只包括：

```text
anthropic
openai
tavily
none
```

默认值是 `tavily`，定义在：

```text
src/open_deep_research/configuration.py
```

扩展检索器定义在：

```text
src/open_deep_research/retrievers.py
```

当前可加载：

```text
duckduckgo
arxiv
local_docs
```

扩展检索器不会自动替代核心 Tavily 工具，需要通过 `EXTRA_RETRIEVERS`
或运行时 `configurable.extra_retrievers` 显式启用。

## 4. 已修复的扩展检索器问题

`retrievers.py` 的 `_run_in_thread()` 原来没有将参数传给线程函数：

```python
asyncio.to_thread(fn)
```

但 DuckDuckGo 和 ArXiv 调用都需要传入查询参数。现已修复为：

```python
asyncio.to_thread(fn, *args)
```

否则 `_duckduckgo_sync(query)` 或 `_arxiv_sync(query)` 可能因缺少
`query` 参数而失败。

## 5. Tavily 不可用时的替代方案

### 5.1 国内商业搜索 API（长期推荐）

可以评估：

- 博查 AI；
- 智谱开放平台联网搜索；
- 其他国内云厂商的搜索或联网检索 API。

参考入口：

- [博查 AI 开放平台](https://open.bochaai.com/)
- [智谱开放平台](https://docs.bigmodel.cn/)

具体 API 地址、计费、区域可达性和数据合规要求必须以供应商当前文档及账户控制台为准。

这类服务不能只通过修改 `.env` 接入，因为不同供应商的请求和响应格式不同，
需要增加适配器。

### 5.2 DuckDuckGo

DuckDuckGo 不需要 API Key，可作为开发或低频备用搜索：

```env
EXTRA_RETRIEVERS=duckduckgo
```

但它可能受限流、验证码和网络波动影响，不建议作为高并发生产主搜索。

### 5.3 自建 SearXNG

SearXNG 可以部署在自己的服务器上，再由项目访问内部地址：

```text
研究系统 -> SearXNG -> 已配置的上游搜索引擎
```

参考：[SearXNG 文档](https://docs.searxng.org/)

优点是可控和可统一管理，缺点是需要维护服务、上游引擎和限流策略。

### 5.4 ArXiv、PubMed 和本地文档

这些检索器适合专门场景：

- `arxiv`：学术论文；
- `local_docs`：企业或用户上传的私有资料；
- PubMed：如后续增加对应适配器，可用于医学文献。

它们不能完全替代通用网页搜索，但可以作为垂直领域回退。

### 5.5 OpenAI 或 Anthropic 原生 Web Search

项目已有 OpenAI 和 Anthropic 搜索选项，但它们仍依赖相应模型 API
在当前网络和账户区域可用，不能视为国内网络的确定性解决方案。

## 6. 推荐的生产接入架构

```text
研究员
  -> 统一搜索适配层
       -> 国内商业搜索 API
       -> SearXNG
       -> DuckDuckGo
       -> ArXiv
       -> 本地文档
  -> 统一标题、URL、摘要格式
  -> 压缩与引用
  -> 最终报告
```

所有供应商应统一输出：

```python
{
    "title": "...",
    "url": "...",
    "content": "..."
}
```

这样不需要修改研究图的监督器、研究员和最终报告节点。

推荐新增一个搜索适配模块，例如：

```text
src/open_deep_research/search_providers.py
```

每个适配器提供统一的异步 `search()` 方法，并负责：

1. 请求认证；
2. 超时和有限重试；
3. 供应商响应转换；
4. URL、标题和正文清洗；
5. 返回空结果或错误状态；
6. 标记实际使用的 provider。

## 7. 主备搜索策略

推荐顺序：

```text
主搜索：国内商业搜索 API
第一备用：自建 SearXNG
第二备用：DuckDuckGo
垂直补充：ArXiv、local_docs
```

只有在网络错误、超时或明确的服务端 `5xx` 时才自动切换。
对于 `401`、`403` 和配置错误，应直接记录并提示管理员，避免静默掩盖错误。

## 8. 实施顺序

1. 使用测试 Key 验证 Tavily 的 DNS、HTTPS、鉴权、额度和中文搜索结果；
2. 保留 Tavily 作为当前默认实现；
3. 使用 `EXTRA_RETRIEVERS=duckduckgo,arxiv,local_docs` 验证扩展检索器；
4. 选择一家国内搜索服务并依据官方文档编写 Provider；
5. 将 Provider 接入统一搜索适配层；
6. 增加超时、重试、限流、日志和来源标记；
7. 配置 SearXNG 或 DuckDuckGo 作为备用；
8. 用中文、英文、无结果、鉴权失败和网络超时场景回归测试。

## 9. 结论

- Tavily 在国内环境是否可用必须以部署机器的实际请求结果为准；
- 当前项目可以直接使用 Tavily，但没有内置国内商业搜索 API；
- DuckDuckGo、ArXiv 和本地文档已经有扩展入口；
- 已修复扩展检索器线程调用中的参数透传错误；
- 长期生产方案建议采用“国内商业搜索 API + SearXNG/DuckDuckGo 备用 +
  ArXiv/本地文档垂直补充”；
- `legacy` 中的历史搜索代码不会自动接入当前主研究图，不能把它视为当前已经启用的搜索能力。
