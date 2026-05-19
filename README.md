# Muse Reading

Muse Reading 是一个面向长文本的 AI 阅读工作空间。它将可上传的书籍文本、进度感知检索、内联高亮问答、章节摘要、轻量级角色引导式陪伴阅读以及防剧透控制整合为一个可本地运行的 MVP，并可作为开源项目进行扩展。

本仓库是该构想的当前工程骨架。其核心原则是：先跑通阅读闭环，再通过更好的数据集、更丰富的时间图、更强的角色一致性以及更完整的评测来深化智能。

## 项目目标

- 将上传的阅读文本转化为结构化、可检索的阅读语料库。
- 支持沉浸式阅读，提供段落级导航和阅读进度追踪。
- 从用户高亮文本中回答问题，且不泄露未来剧情。
- 根据当前阅读进度生成章节级摘要。
- 支持角色引导式陪伴阅读，作为可插拔层。
- 围绕检索、防剧透行为和阅读理解构建数据集与评测流水线。

## 核心功能

- 支持 `.txt`、`.pdf` 和 `.epub` 文件的文本上传与本地书籍导入。
- 章节与段落解析，附带 chunk 级元数据。
- 基于上传书籍内容生成时间图。
- 阅读器 UI：章节导航、段落选择、内容预览。
- 高亮触发式问答，带进度感知检索。
- 章节摘要端点，支持角色感知生成。
- 完整的运行时路径：通过角色 RAG 加 OpenAI 兼容模型端点，支持鲁迅、马克·吐温和张爱玲三位领读 Agent。
- 基准测试数据：`highlight_qa`、`anti_spoiler`、`chapter_summary`。

## 系统架构

Muse Reading 目前包含四个协作层：

1. `前端交互层`
   [frontend](/C:/Users/21358/Desktop/MuseReading/frontend) 中的静态 Web 阅读器处理上传、章节导航、段落选择、摘要触发和提问提交。

2. `应用与编排层`
   [backend/api/app.py](/C:/Users/21358/Desktop/MuseReading/backend/api/app.py) 中的 FastAPI 应用暴露了上传、书籍、角色、问答、编排、摘要和图谱等端点。

3. `知识与检索层`
   后端从上传文本中构建归一化的书籍记录、检索 chunk 和时间上下文图。检索是进度感知的，并设计为在生成回答之前支持防剧透过滤。

4. `数据集与评测层`
   仓库包含 schema、清单（manifest）、示例、基准测试数据和评测脚本，以便对导入、问答、摘要和防剧透行为进行回归测试，并可扩展为更完备的基准测试套件。

### 当前运行时流程

```text
上传文本
  -> 归一化为书籍记录
  -> 解析章节和段落
  -> 构建检索 chunk
  -> 构建时间图
  -> 在前端阅读
  -> 提出高亮问题或请求章节摘要
  -> 仅检索可见上下文
  -> 以角色风格生成回答，附带防剧透保护
```

## 数据集构建策略

仓库采用 schema 优先、元数据优先的结构，而非打包大型受版权保护的语料。

### 数据分类

- `书籍文本语料`
  用户上传的文本、演示文本，以及未来的公版或授权书籍。
- `角色源语料`
  用于塑造领读 Agent 的资料，如论文、信件、演讲、序言、传记和评论。
- `标注数据`
  `highlight_qa`、`chapter_evolution`、显著性标签，以及未来的阅读会话标注。
- `评测数据`
  检索、角色一致性、防剧透以及面向用户研究的评测包。

### 当前数据布局

```text
backend/assets/data/
  raw/
    books/
    persona_sources/
  processed/
    books/
    personas/
  annotations/
    highlight_qa/
    chapter_evolution/
  eval/
    retrieval/
    persona_consistency/
    anti_spoiler/
  manifests/
```

### 分层文本表示

当前项目为上传的书籍文本保留了一个层级化表示：

- `L0`：原始段落单元
- `L1`：检索就绪的 chunk
- `L2`：章节结构摘要
- `L3`：全局主题或路径索引
- `L4`：引用、立场或评论就绪层

此层级的首次实际应用已存在于本地数据集构建脚本和图谱导出流水线中。

## 快速开始

### 环境要求

- 推荐 Python `3.10+`
- `pip`

### 安装

```bash
python -m pip install -r requirements.txt
```

### 配置角色 Agent

要使用 `lu-xun`、`mark-twain` 或 `zhang-ailing`，请将 [`.env.example`](/C:/Users/21358/Desktop/MuseReading/.env.example) 复制为 `.env`，并为每个 Agent 填入你自己的 OpenAI 兼容端点、模型名称和 API key。应用启动时会自动加载此根目录下的 `.env` 文件。

### 运行 API 和阅读器

```bash
uvicorn backend.api.app:app --reload
```

然后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

启动时，如果 [backend/assets/examples/muse_demo_book.txt](/C:/Users/21358/Desktop/MuseReading/backend/assets/examples/muse_demo_book.txt) 存在，应用会自动加载该内置演示书籍。

## 前端使用

阅读器 UI 由 FastAPI 直接从 [frontend/index.html](/C:/Users/21358/Desktop/MuseReading/frontend/index.html) 提供服务。

当前 UI 能力：

- 上传 `.txt`、`.pdf` 或 `.epub` 书籍
- 浏览章节和段落内容
- 选中段落作为阅读焦点
- 查看 `reading_progress` 和 `selection_context`
- 从当前阅读上下文提问
- 请求章节摘要
- 从本地角色注册表中切换角色

截图占位：

- 公开发布前，在 `backend/docs/` 或专用的 `screenshots/` 目录下添加截图。

## API 概览

[backend/api/app.py](/C:/Users/21358/Desktop/MuseReading/backend/api/app.py) 当前暴露的端点：

- `GET /api/health`
- `GET /api/books`
- `GET /api/books/{book_id}`
- `GET /api/books/{book_id}/graph`
- `GET /api/personas`
- `POST /api/upload`
- `POST /api/qa`
- `POST /api/orchestrate`
- `POST /api/summary`

### API 简要说明

- `POST /api/upload`
  上传 `.txt`、`.pdf` 或 `.epub` 文件，解析为书籍记录并构建时间图。
- `POST /api/qa`
  接收 `book_id`、`question`，可选参数 `highlight_text`、`current_chapter`、`persona_id`。
- `POST /api/orchestrate`
  在可见 chunk 和图谱上下文中运行混合检索。
- `POST /api/summary`
  生成当前章节的摘要，可选角色风格。

## 仓库结构

```text
architecture/        接口与系统设计说明
backend/             后端应用、数据、知识库、安全与 LLM 记忆模块
backend/benchmarks/          用于冒烟评测的基准测试数据
backend/assets/data/                原始、处理后、标注、评测和清单资产
backend/docs/                架构与数据设计文档
eval/                评测运行器
backend/assets/examples/            演示阅读文本
frontend/            静态阅读器 UI 和浏览器端资源
backend/assets/schemas/             JSON schema 定义
backend/scripts/             数据集与注册表构建脚本
backend/workspace_state/     本地运行时产物，如已保存的书籍和图谱
```

### 后端模块布局

```text
backend/
  api/               FastAPI 端点和应用接线
  common/            共享配置和 Pydantic 模型
  backend/assets/data/              数据导入和本地持久化
  knowledge_base/    图谱、问答检索和角色模块
  safety/            防剧透保护
  llm_memory/        角色、编排和摘要生成
```

## 评测

当前仓库包含一个最小但可运行的评测框架。

### 运行基准测试

```bash
python backend/eval/run_eval.py
```

### 运行测试

```bash
```

### 当前覆盖内容

- `highlight_qa`
  检查是否检索到预期的支撑 chunk 并返回答案。
- `anti_spoiler`
  检查未来剧情问题是否被拒绝或正确约束。
- `chapter_summary`
  检查摘要是否包含预期短语并避免禁止短语。

目前这些属于冒烟和回归检查，尚不是完整的排行榜级基准测试。

## 当前局限

- `pdf` 支持目前期望 PDF 包含可选文本层，而非扫描版图片 PDF。
- 时间图提取是启发式且轻量级的。
- 前端文案在多处包含占位或草稿文本。
- 角色输出依赖 `.env` 中本地配置的模型凭证。
- 评测规模仍然较小且偏合成，与目标基准测试范围有差距。
- 受版权保护的语料主要通过清单和示例呈现，而非完整的已发布文本。

## 路线图

- 为 `epub`、`docx` 和受控 `pdf` 工作流增加更丰富的导入功能。
- 强化时间图提取和图谱感知检索。
- 扩展中文领读角色和角色一致性评测。
- 构建更大规模的检索、叙事理解、长对话和防剧透基准测试。
- 添加截图资源、部署说明和公开发布打包。
- 改进前端文本质量，打磨阅读交互闭环。

## 开源发布说明

本仓库的结构设计为可安全开源：

- schema、清单、示例和脚本已包含在内
- 基准测试数据量小且为合成数据
- 受版权保护的书籍内容应保持在公开发布之外，除非具备明确的再分发权利
- 公版或授权内容可通过现有数据结构后续添加

## 相关项目文档

- [架构对齐](/C:/Users/21358/Desktop/MuseReading/backend/docs/architecture_alignment.md)
- [README 架构摘要](/C:/Users/21358/Desktop/MuseReading/backend/docs/readme_architecture_summary.md)
- [数据设计](/C:/Users/21358/Desktop/MuseReading/backend/docs/data/muse_reading_data_design.md)
- [基准测试 README](/C:/Users/21358/Desktop/MuseReading/backend/benchmarks/README.md)
- [数据骨架 README](/C:/Users/21358/Desktop/MuseReading/backend/assets/data/README.md)
