# Notion 块级增量同步与自动化方案

为了实现“改一个字也只更新这一行”的精准同步目标，本方案将同步颗粒度从页面级细化到块级。

## 架构逻辑

1.  **原子化对账**：
    *   数据库 `knowledge_base` 表中的每一行对应 Notion 里的一个块 (Block)。
    *   通过 `notion_block_id` 建立一对一索引。
2.  **增量捕捉**：
    *   利用 Notion API 的 `block.last_edited_time`。
    *   同步流程：获取页面所有 Block -> 对比数据库记录 -> 仅对 TimeStamp 不同的块执行 `update`。
3.  **自动化流水线**：
    *   GitHub Actions 每日对账。
    *   断点续传机制，确保网络波动后自动接力。

## 待办事项

- [ ] 改造 `ingest_notion.py` 为分块读取。
- [ ] 实现针对具体 Block 的向量生成逻辑。
- [ ] 验证 GitHub Actions 环境变量安全性。
