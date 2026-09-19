# Private RAG · 个人知识库

多租户个人知识库 RAG：文档上传入库 → 混合检索 → 带引用问答，并支持 JSONL 本地评分。用户可根据个人收录的知识库文档进行相关问答。
技术栈：React + FastAPI + Postgres + Qdrant + LangChain。


### 业务链路

| 能力 | 流程 |
|------|------|
| **入库** | 上传 → 落盘 → Postgres 记元数据 → `rag_lc` 切块 → 百炼嵌入（批次 ≤10）→ Qdrant upsert（带 `user_id`） |
| **问答** | 发消息 → 按 `user_id` 混合检索 → 拼上下文 → 百炼生成 → 写回消息与 citations |
| **评分** | 导入 JSONL 题库 → 逐题走同一套问答 → LLM/启发式 judge → 存 `eval_runs` / `eval_results` ，依据正确性和有据性来进行批判|

**隔离模型**：Postgres 按 `user_id` 过滤；Qdrant 共用 collection，靠 payload `metadata.user_id` 过滤。

**检索实现**：稠密相似度 + 用户语料 BM25 + RRF 融合。

## 快速开始

### 方式 A：Docker 一键

需要本机已装 Docker。Qdrant 仍用 Cloud（在 `.env` 填写）。

```bash
cp .env.example .env
# 至少填写：OPENAI_API_KEY、OPENAI_BASE_URL、QDRANT_URL、QDRANT_API_KEY、JWT_SECRET

docker compose up -d --build
# 浏览器打开 http://localhost:8080
# API 也可直接访问 http://localhost:8002/health
```

常用命令：

```bash
docker compose logs -f backend
docker compose down          # 停服务（保留 Postgres/上传 volume）
docker compose down -v       # 连数据卷一起删
```

### 方式 B：本机开发

```bash
# 1. 后端环境
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
make dev
# 另装后端依赖：cd app/backend && pip install -e .

# 2. 凭据
cp .env.example .env
# 填写：OPENAI_API_KEY、OPENAI_BASE_URL、QDRANT_*、DATABASE_URL、JWT_SECRET
# RAG_CONFIG=configs/default.china.yaml

# 3. Qdrant Cloud（推荐）或 make qdrant-up 本地

# 4. 后端 :8002
make run-app-backend
# Windows：
#   cd app/backend
#   ..\..\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8002

# 5. 前端 :5172
make run-app-frontend

# 6. 打开 http://localhost:5172 注册登录后，在「文档」页上传入库即可
```

## 功能特性

- **LangChain RAG（`rag_lc/`）** — 摄取、混合检索、生成与引用
- **个人知识库平台** — JWT 登录、会话、文档上传删除、评测历史
- **国内模型** — 百炼兼容模式（对话 + `text-embedding-v3`）
- **向量库** — Qdrant Cloud / 本地
- **评测** — 通过大模型进行离线自动评测，评测题集包含普通题集，挑战集(侧重无答案与错误前提，用于检验拒答与防幻觉能力）通过率约97%。，评测整体，JSONL 题库导入、本地 judge、历史查看与删除

## 仓库结构

| 路径 | 说明 |
|------|------|
| `app/backend/` | FastAPI 平台（`/api/v1`） |
| `app/frontend/` | Vite + React + Tailwind |
| `rag_lc/` | 入库 / 检索 / 生成 |
| `config/` | YAML schema 与环境变量工具 |
| `configs/` | 默认 `default.china.yaml` |
| `evals/` | 数据集 schema、local judge、报告 |
| `prompts/` | `system/assistant.md`、评测 qgen / judge |



## 环境变量

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 百炼兼容接口 |
| `QDRANT_URL` / `QDRANT_API_KEY` | 向量库（Cloud 或本地） |
| `DATABASE_URL` | Postgres（本机开发）；Compose 内自动指向 `db` 服务 |
| `JWT_SECRET` / `JWT_EXPIRE_HOURS` | 登录令牌 |
| `RAG_CONFIG` | YAML 路径，默认 `configs/default.china.yaml` |
| `KNOWLEDGE_CORS_ALLOW_ORIGINS` | 前端来源；Docker 下含 `http://localhost:8080` |

## 前端

```bash
cd app/frontend
npm run dev      # http://localhost:5172
npm run build
npm run lint
```

路由：`/login`、`/`（对话）、`/documents`、`/eval`。

## 评估

### 平台 UI

在「评分」页导入 JSONL（或仓库路径），对**当前用户知识库**跑本地评判；结果写入 Postgres，可查看历史与删除。

每条 JSONL（`{"item": {...}}`）需含：

- `question` / `correct_answer` / `citation_text`
- 可选：`id`、`difficulty`、`tags`

Schema：`evals/datasets/schema.py`。

也可用程序调用 `evals.harness.run_evals(cfg)`（`evals.mode: user|auto`），报告输出到 `evals/reports/`。

