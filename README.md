# Mingle Reading

Mingle Reading 是一个面向长篇文学作品的 AI 伴读系统。它将书籍文本转化为结构化时态知识图谱，支持章节感知的问答、角色扮演对话、名家领读以及防剧透保护。

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    前端阅读器                         │
│  index.html  ·  graph.html (3D 图谱)  ·  app.js      │
├──────────────────────────────────────────────────────┤
│                    Agent 层                           │
│  Celebrity Agent (名家伴读 QA)                        │
│  Character Agent (角色扮演对话)                        │
│  Inline Bubbles (行内批注)                            │
├──────────────────────────────────────────────────────┤
│                  知识图谱层                            │
│  Chapter → Episode → Entity → Relation (四层精简)     │
│  叙事依赖边 · 时间追踪 · 实体消歧                      │
├──────────────────────────────────────────────────────┤
│                 数据管道层                             │
│  TXT/PDF/EPUB 解析 → 章节分割 → 滑动窗口 → LLM 提取   │
└──────────────────────────────────────────────────────┘
```

### 知识图谱结构

四层精简架构，Community / Saga / ChapterTimeline 已移除：

| 层 | 节点类型 | 数量(百年孤独) | 说明 |
|------|---------|:--:|------|
| Chapter | 章节容器 | 23 | 汇总本章实体和关系，携带剧透等级 |
| Episode | 叙事节拍 | 838 | LLM 提取结果容器，携带依赖边 |
| Entity | 实体 | ~340 | 人物/地点/物品/团体/概念 |
| Relation | 关系 | ~800 | 9 种关系类型，带时间戳和原文引用 |

实体间通过 2,500+ 条叙事依赖边连接，支持跨章节因果追溯。

### Agent 工作流

**Celebrity Agent (QA)**：用户提问 → 剧透检测 → 混合检索（文本关键词 + 图谱多路并行）→ 图谱知识格式化 → 名家风格注入（鲁迅/马克吐温）→ LLM 回复

**Character Agent (角色扮演)**：用户提问 → 剧透检测 → 实体中心检索（直接定位角色，拉取全部关系和邻居）→ 角色画像生成 → 分组格式化（血缘/互动/原文证据）→ LLM 以第一人称回复

## 核心功能

- 支持 `.txt`、`.pdf` 和 `.epub` 文件上传
- 从文本自动构建时态知识图谱（增量构建 + 断点恢复）
- 3D 知识图谱可视化（`graph.html`），支持节点/边过滤
- 进度感知的问答和角色对话，严格防剧透
- 名家伴读模式：鲁迅、马克·吐温、张爱玲
- 角色扮演模式：选择任意角色进行第一人称对话
- 行内批注气泡（Persona 模式 / Character 模式）
- 全文检索、章节导航、段落级阅读进度

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装

```bash
pip install -r requirements.txt
```

### 配置

将 `.env.example` 复制为 `.env`，配置 LLM API 端点：

```env
GRAPHITI_EXTRACTOR_API_KEY=your_key
GRAPHITI_EXTRACTOR_BASE_URL=https://api.deepseek.com
GRAPHITI_EXTRACTOR_MODEL_NAME=deepseek-v4-flash

MUSE_NEUTRAL_API_KEY=your_key
MUSE_NEUTRAL_BASE_URL=https://api.deepseek.com
MUSE_NEUTRAL_MODEL_NAME=deepseek-v4-flash

LU_XUN_API_KEY=your_key
LU_XUN_BASE_URL=https://api.deepseek.com
LU_XUN_MODEL_NAME=deepseek-v4-flash
```

### 启动

```bash
python main.py
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

上传 EPUB 后自动构建知识图谱并接入所有 Agent 功能。构建进度在前端实时可见。

## API 概览

| 端点 | 说明 |
|------|------|
| `GET /api/books` | 列出可用书籍 |
| `GET /api/books/{id}` | 书籍详情 |
| `POST /api/upload` | 上传 TXT/PDF/EPUB |
| `POST /api/qa` | 名家伴读 QA |
| `POST /api/books/{id}/characters/chat` | 角色对话 |
| `POST /api/books/{id}/characters/profile` | 角色画像 |
| `GET /api/books/{id}/characters/candidates` | 可对话角色列表 |
| `POST /api/books/{id}/inline-bubbles` | 行内批注气泡 |
| `POST /api/books/{id}/graph/query` | 图谱查询 |
| `GET /api/books/{id}/graph/view` | 图谱可视化数据 |

## 仓库结构

```text
backend/
  api/                    FastAPI 端点和请求模型
  agents/                 Agent 实现
    celebrity/            名家伴读 (answering + persona RAG + retrieval)
    character/            角色对话 (profile + chat + inline bubbles)
  knowledge_graph/        知识图谱核心
    builder.py            图谱构建器 (滑动窗口 + 增量实体解析)
    models.py             四层数据模型 (Chapter/Episode/Entity/Relation)
    retrieval.py          图谱检索器 (评分 + 重排 + BFS 扩展)
    llm_extraction.py     LLM 提取提示词 (CoT 消歧 + 描述缓存)
    extraction_window.py  滑动窗口构建器 (前导上下文 + 窗口分块)
    orchestration/        混合检索编排 (EntityNetworkResult + OrchestrationService)
  data_pipeline/          文本解析 (TXT/PDF/EPUB) + 书籍/图谱存储
  safety/                 防剧透检测
  config.py               路径和 .env 加载
frontend/
  index.html              阅读器 UI
  graph.html               3D 知识图谱可视化 (Three.js)
  app.js                   前端逻辑
  main.css                 样式
```

## 构建知识图谱

```bash
# 全量构建
python rebuild_experiment.py --method 2

# 完成后比较不同配置
python compare_methods.py
```

图谱保存在 `backend/runtime/graphs/{book_id}.graph.json`，支持增量续建和断点恢复。

## 评测

```bash
python backend/eval/run_eval.py
```

覆盖 `highlight_qa`、`anti_spoiler`、`chapter_summary` 三类基准测试。

## 开源说明

本仓库按可安全开源的结构组织：schema、示例、脚本和合成评测数据已包含；受版权保护的书籍内容保留在公开发布之外。
