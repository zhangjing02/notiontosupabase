# Notion to Supabase Sync Engine

这是一个由 AI 驱动的 Notion 知识库迁移与同步引擎。它能够智能地将您的 Notion 页面、块及其元数据同步到 Supabase 高性能向量数据库中。

## 核心功能（当前）

- 🚀 **智能迁移**：多维过滤无意义内容，确保数据库质量。
- 🧠 **语义识别**：利用 NVIDIA AI (Llama 405B) 自动为内容打标签、分类。
- 🔍 **向量检索 (RAG Ready)**：自动生成向量嵌入 (Embedding)，支持语义搜索。
- 🔄 **页面级增量同步（已实现）**：基于 `last_notion_edited_at + content_hash` 执行更新对账。
- 🧱 **块级增量同步（MVP 已实现）**：支持按 `notion_block_id` 做增量对账，同步策略仍可继续精细化。
- 🤖 **GitHub Actions 集成**：支持每天定时自动对账同步。

## 目录结构

- `ingest_notion.py`: 核心同步引擎（当前为 v8.x 页面级增量同步）。
- `incremental_sync.py`: 块级增量同步引擎（按 `notion_block_id` 对账）。
- `check_progress.py`: 实时查询同步进度与数据分布。
- `requirements.txt`: Python 依赖清单。
- `sql/`: 数据库初始化脚本（含 `match_knowledge_base` 语义检索 RPC）。
- `.github/workflows/`: 已启用的定时任务配置。

## 快速开始

1. **安装依赖**:
   ```bash
   pip install -r requirements.txt
   ```

2. **配置环境变量**:
   创建 `.env` 文件并填入以下内容：
   ```env
   NOTION_TOKEN=您的_Notion_Token
   SUPABASE_URL=您的_Supabase_URL
   SUPABASE_SERVICE_ROLE_KEY=您的_Supabase_Key
   NVIDIA_API_KEY=您的_NVIDIA_Token
   ```

3. **运行同步**:
   ```bash
   python ingest_notion.py
   ```

4. **运行块级增量同步（可选）**:
   ```bash
   python incremental_sync.py
   ```

## API 端点

- `POST /api/sync`：触发页面级同步。
- `POST /api/sync/blocks`：触发块级增量同步。
- `POST /api/embed`：生成查询 embedding（前端回退通道）。
- `GET /api/sync/status`：查看同步运行状态。

## 自动化调度

- 工作流文件：`.github/workflows/notion-sync.yml`
- 定时任务：
  - 页面级同步：每天 `00:00 UTC`
  - 块级同步：每天 `00:30 UTC`
- 手动触发：
  - 在 GitHub Actions 的 `workflow_dispatch` 中选择 `page_sync / block_sync / both`
- 建议：
  - `ENABLE_BLOCK_CLASSIFICATION=false` 先用于块级同步，降低成本与时延

---
*注：本项目作为您的私人知识库枢纽，旨在实现 Notion 与 AI 应用的无缝连接。*
