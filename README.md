# 智能代码审查助手 (aicr) v2

基于 Python + FastAPI 的 AI 代码审查平台，参考 [PICO](https://gitee.com/htxoffical/pico)
与 [repo-context-aware-rag-ai-code-review](https://github.com/skalrn/repo-context-aware-rag-ai-code-review)
的构建机制：多 Provider 抽象、配置优先级链、运行工件追踪、批量审查，并加入
**知识库 + RAG + 上下文管理** 与 **多 Agent 协作审查**，让审查反馈贴合项目自身规范与架构。

## 功能特性

- **多 Provider**：DeepSeek（默认）/ OpenAI 兼容 / Anthropic / Ollama 本地模型，
  一套接口自由切换
- **多种审查入口**
  - 粘贴单文件代码
  - 上传多个文件批量审查（并发 3 路）
  - 扫描本地目录（跳过 `node_modules`/`.git` 等，限制文件大小与数量）
  - Git 仓库未提交变更 / 已暂存（staged）diff 审查
- **知识库 + RAG（Repo-Context）**：把项目文档、编码规范、架构说明摄入向量库
  （Qdrant + 本地 sentence-transformers），审查时语义检索并注入项目专属上下文，
  校验代码是否违反项目规范，减少泛泛而谈的反馈
- **上下文管理**：token 预算估算、按预算裁剪检索上下文、imports 提取（关联文件线索）
- **多 Agent 协作（LangGraph）**：总览 + 架构/安全/性能/风格/测试 5 个专项专家并行审查，
  由合成器合并去重，每条 issue 带 `category` 标签标注来源专家；可按 `focus` 只启用部分专家
- **结构化报告**：评分、摘要、亮点、问题列表（严重级别/行号/建议）、改进建议
- **运行工件追踪**：每次审查落盘 `data/runs/<run_id>/`（`meta.json` /
  `trace.jsonl` / `report.json`），记录 `kb_retrieved` 等 RAG 事件
- **多轮对话**：支持思考型模型（DeepSeek R1 / Claude thinking），自动续写被截断回答
- **Web UI + CLI 双入口**

## 快速开始

```bash
# 安装（Python 3.10+）
pip install -e ".[rag]"    # 含知识库所需的 sentence-transformers

# 配置：首次启动后打开 http://127.0.0.1:3000/settings.html 填写 API Key，
# 或复制 .env.example 为 .env 填入 CRV_DEEPSEEK_API_KEY

# 启动 Web 服务
python -m aicr serve            # 默认 127.0.0.1:3000
python -m aicr serve --port 8000 --reload   # 开发模式
```

### 知识库（RAG）使用

```bash
# 摄入项目（收集 README.md、docs/、*.md 及源码）
python -m aicr kb ingest D:\projects\demo --recreate

# 语义检索
python -m aicr kb search "数据库访问层规范" -k 5

# 查看/清空
python -m aicr kb stats
python -m aicr kb clear
```

在「设置」页开启「启用知识库」后，每次审查会自动检索并注入项目上下文。

> **国内网络提示**：embedding 模型从 HuggingFace 下载，需设置镜像环境变量
> `HF_ENDPOINT=https://hf-mirror.com`（或写入 `.env`），否则无法拉取模型。

向量库默认**本地内嵌**（无需 Docker）；也可在设置中填写 Qdrant 服务地址接入
Docker / Qdrant Cloud。

### 多 Agent 协作审查

基于 LangGraph 编排，单次审查拆解为 6 个专家**并行**执行，再由合成器合并去重：

```
orchestrator（按 focus 选择专家）
   ├─ 总览与正确性（summary / score / highlights / recommendations）
   ├─ 架构与最佳实践
   ├─ 安全
   ├─ 性能
   ├─ 风格与可读性
   └─ 测试与可测性
        └─ synthesizer（确定性合并，issue 打 category 标签，去重）
```

- 开启方式：CLI 加 `--multi`、设置 `CRV_REVIEW_MODE=multi`，或 Web 页勾选「多 Agent 协作审查」
- `focus` 关注点可裁剪启用的专家（如只勾选「安全」则只跑总览 + 安全两个专家），节省额度
- 每个专家复用同一 Provider 与 RAG 检索上下文，默认并发上限 3
- 多 Agent 更全面但会发起多次 LLM 调用（默认单 Agent 更省），按需选择

### CLI 用法

```bash
python -m aicr review demo.py              # 审查单个文件
python -m aicr review demo.py --multi      # 多 Agent 协作审查
python -m aicr review ./src -e py -e ts    # 批量审查目录
python -m aicr diff /path/to/repo          # 审查仓库未提交变更
python -m aicr diff . --staged             # 只看已暂存变更
python -m aicr chat                        # 多轮对话（支持思考型模型，--show-thinking 查看思考）
```

## 配置优先级链（PICO 式）

```
请求参数 > 环境变量(.env) > config.json > 内置默认值
```

环境变量命名：`CRV_<PROVIDER>_<FIELD>`，并回退到通用名，例如：

| 变量 | 说明 |
|---|---|
| `CRV_PROVIDER` | 当前 provider（deepseek/openai/anthropic/ollama） |
| `CRV_REVIEW_MODE` | 审查模式：`single`（默认）/ `multi`（多 Agent 协作） |
| `CRV_DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEY` | DeepSeek Key |
| `CRV_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | Anthropic Key |
| `CRV_OPENAI_BASE_URL` | OpenAI 兼容服务地址 |
| `CRV_KB_ENABLED` | 是否启用知识库 RAG |
| `CRV_KB_QDRANT_URL` | 远程 Qdrant 地址（留空用本地内嵌） |
| `CRV_KB_QDRANT_PATH` | 本地内嵌存储路径（默认 `data/kb`） |
| `CRV_KB_QDRANT_API_KEY` | 远程 Qdrant 鉴权 Key |
| `CRV_KB_COLLECTION` | 集合名称（默认 `aicr_kb`） |
| `CRV_KB_EMBEDDING_MODEL` | embedding 模型 |
| `CRV_KB_TOP_K` / `CRV_KB_CHUNK_SIZE` / `CRV_KB_CHUNK_OVERLAP` | 检索条数 / 分块大小 / 分块重叠 |
| `HF_ENDPOINT` | HuggingFace 镜像（国内网络建议 `https://hf-mirror.com`） |

旧版 Node 项目的扁平 `config.json`（`apiKey`/`model`…）与 `data/history.json`
均可自动兼容/迁移。

## 项目结构

```
aicr/
├── cli.py               # CLI 入口：serve / review / diff / chat / kb
├── config.py            # 配置优先级链、多 provider 段 + KB 段管理
├── dotenv.py            # 轻量 .env 解析
├── collector.py         # 目录扫描 / git diff 解析 / 文件收集
├── prompts.py           # 提示词构建与 JSON 提取（含 kb_context）
├── engine.py            # 审查编排：provider → RAG 检索 → 校验 → 工件
├── context.py           # 上下文管理：token 预算 / 裁剪 / imports 提取
├── rag.py               # RAG 检索与上下文组装
├── conversation.py      # 多轮对话（思考续写）
├── runs.py              # 运行工件持久化与查询
├── agents/
│   ├── specialists.py   # 专项 agent 定义（总览 + 架构/安全/性能/风格/测试）
│   ├── synthesizer.py   # 多专家报告合并去重
│   └── graph.py         # LangGraph 编排（orchestrator → 并行 agent → synthesizer）
├── knowledge/
│   ├── embeddings.py    # embedding 抽象 + 本地 sentence-transformers
│   ├── vector_store.py  # Qdrant（远程 / 本地内嵌 / 内存）
│   └── ingest.py        # 来源收集 / 分块 / 入库
├── providers/
│   ├── base.py          # BaseProvider 抽象（chat_full / ChatResult）
│   ├── openai_protocol.py    # OpenAI 兼容协议（DeepSeek/Ollama 复用）
│   └── anthropic_protocol.py # Anthropic Messages 协议
├── web/server.py        # FastAPI REST API
└── static/              # 前端页面（原生 HTML/JS/CSS）
tests/                   # pytest 测试（MockTransport / FakeStore，无真实网络）
```

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务状态与配置检测 |
| GET/POST | `/api/settings` | 读取（脱敏）/保存配置 |
| GET | `/api/providers` | 可用 provider 列表 |
| POST | `/api/providers/test` | 连通性测试 |
| POST | `/api/review` | 单文件审查（code / path / git_repo） |
| POST | `/api/review/batch` | 目录或 git diff 批量审查 |
| POST | `/api/review/files` | 多文件上传批量审查 |
| POST | `/api/chat` | 多轮对话 |
| DELETE | `/api/chat/{session_id}` | 结束并清空会话 |
| GET/DELETE | `/api/runs` `/api/runs/{id}` | 历史记录查询与删除 |
| GET | `/api/kb/stats` | 知识库统计 |
| POST | `/api/kb/ingest` | 摄入目录/文件到向量库 |
| POST | `/api/kb/search` | 语义检索 |
| DELETE | `/api/kb` | 清空知识库 |

## 开发与测试

```bash
pip install -e ".[dev]"
ruff check aicr tests     # Lint
pytest tests -q           # 测试走 MockTransport/FakeStore，不消耗额度、无需向量库
```

## 安全说明

- API Key 仅保存在本地 `config.json` / `.env`，接口返回时一律脱敏
- 每次审查的完整 trace 存于 `data/runs/`，不包含密钥字段
- 知识库向量与分块存于本地 `data/kb/`（本地内嵌模式），不联网
