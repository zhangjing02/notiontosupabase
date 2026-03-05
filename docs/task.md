# Notion to Supabase 迁移任务清单

## 当前状态
- [x] 基础设施搭建 (Supabase & Notion API)。
- [x] Notion 数据整理 (API Key 归集与资产补完)。
- [/] 全量数据智能迁移 (Option A)
    - [x] 优化 `ingest_notion.py` 过滤与重试逻辑 (v4/v5 Robust版)。
    - [/] 执行全量扫描与同步 (进度：145+ / 788 页面)。
    - [ ] 迁移结果核对与指标统计。
- [ ] 增量更新与 GitHub 自动化设计
    - [x] 构思“时间戳对账”与“块级精准同步”方案。
    - [ ] 升级 SQL Schema (增加 `last_notion_edited_at` 等)。
    - [ ] 设计针对“原子块”的 `ingest_incremental.py`。
    - [ ] 环境部署至正式项目目录 `D:\PersonalProject\NotionTosupabase`。

## 已完成里程碑
- 100+ 页面同步达成。
- 全量自动化分类 (33+ 分类已识别)。
- 数据库 Schema 完成 1024 维 HNSW 索引优化。
