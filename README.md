# Notion to Supabase Sync Engine

这是一个由 AI 驱动的 Notion 知识库迁移与同步引擎。它能够智能地将您的 Notion 页面、块及其元数据同步到 Supabase 高性能向量数据库中。

## 核心功能

- 🚀 **智能迁移**：多维过滤无意义内容，确保数据库质量。
- 🧠 **语义识别**：利用 NVIDIA AI (Llama 405B) 自动为内容打标签、分类。
- 🔍 **向量检索 (RAG Ready)**：自动生成向量嵌入 (Embedding)，支持语义搜索。
- 🔄 **(规划中) 块级增量同步**：精准识别 Notion 内的局部修改，仅同步有变动的块，节省 API 额度。
- 🤖 **GitHub Actions 集成**：支持每天定时自动对账同步。

## 目录结构

- `ingest_notion.py`: 核心同步引擎 v6 (支持原子级增量同步)。
- `check_progress.py`: 实时查询同步进度与数据分布。
- `requirements.txt`: Python 依赖清单。
- `sql/`: 数据库初始化与升级脚本。
- `.github/workflows/`: 定时任务配置（即将部署）。

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

---
*注：本项目作为您的私人知识库枢纽，旨在实现 Notion 与 AI 应用的无缝连接。*
