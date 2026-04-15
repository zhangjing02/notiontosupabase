# Notion to Supabase 迁移任务清单

## 当前状态
- [x] 基础设施搭建 (Supabase & Notion API)。
- [x] Notion 数据整理 (API Key 归集与资产补完)。
- [/] 全量数据智能迁移 (Option A)
    - [x] 优化 `ingest_notion.py` 过滤与重试逻辑 (v4/v5 Robust版)。
    - [x] 执行全量扫描与同步（已具备页面级增量能力）。
    - [ ] 迁移结果核对与指标统计（待补统一验收报告）。
- [/] 增量更新与 GitHub 自动化设计
    - [x] 构思“时间戳对账”与“块级精准同步”方案。
    - [x] 升级 SQL Schema (增加 `last_notion_edited_at`、`notion_block_id`、向量检索 RPC)。
    - [x] 实现针对“原子块”的 `incremental_sync.py`（最小可用版）。
    - [x] GitHub Actions 支持页面级/块级分路调度（含手动 target 选择）。
    - [/] 环境部署至正式项目目录 `D:\PersonalProject\NotionTosupabase`（代码已就位，待线上环境执行 SQL 与联调）。

## 已完成里程碑
- 100+ 页面同步达成。
- 全量自动化分类 (33+ 分类已识别)。
- 数据库 Schema 完成 1024 维 HNSW 索引优化。
