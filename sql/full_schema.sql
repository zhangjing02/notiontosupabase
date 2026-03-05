-- 1. 开启 pgvector 插件
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 创建知识库主表 (已根据 v5 稳健版优化)
CREATE TABLE IF NOT EXISTS public.knowledge_base (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    notion_id TEXT UNIQUE, -- Notion 页面 ID，唯一索引
    title TEXT,            -- 自动截断至 250 字符
    content TEXT NOT NULL, -- 完整 Markdown 内容
    embedding VECTOR(1024),-- NVIDIA nv-embedqa-e5-v5 (1024维)
    
    -- 分类元数据
    category TEXT,
    sub_category TEXT,
    project_name TEXT,
    project_type TEXT,
    tags TEXT[],
    
    -- 增量更新核心字段 (规划中)
    notion_block_id TEXT,       -- 块级更新标识
    last_notion_edited_at TIMESTAMPTZ, -- 感知 Notion 最后修改时间
    
    metadata JSONB,             -- 额外扩展数据 (url, source 等)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- 3. 构建索引
CREATE INDEX IF NOT EXISTS idx_kb_notion_id ON knowledge_base(notion_id);
CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_kb_tags ON knowledge_base USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_kb_embedding ON knowledge_base USING hnsw (embedding vector_cosine_ops);
