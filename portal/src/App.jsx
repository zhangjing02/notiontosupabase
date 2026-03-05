import React, { useState, useEffect } from 'react';
import { createClient } from '@supabase/supabase-js';
import { Search, ExternalLink, Hash, Command } from 'lucide-react';
import './index.css';

// 这里的环境变量之后可以通过 Vite 的 .env 注入
const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
const NVIDIA_API_KEY = import.meta.env.VITE_NVIDIA_API_KEY;

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

function App() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [errorInfo, setErrorInfo] = useState('');

    const getEmbedding = async (text) => {
        const { data, error } = await supabase.functions.invoke('get-embedding', {
            body: { input: text }
        });
        if (error) throw error;
        return data.embedding;
    };

    // 快捷搜索函数 (语义 + 关键词)
    const performSearch = async (searchTerm) => {
        if (searchTerm.length < 2) {
            setResults([]);
            return;
        }

        setLoading(true);
        setErrorInfo('');
        try {
            // 1. 并行发起三个维度的检索：向量语义、标题精确匹配、内容关键词匹配
            const embeddingPromise = getEmbedding(searchTerm).then(emb =>
                supabase.rpc('match_knowledge_base', {
                    query_embedding: emb,
                    match_threshold: 0.22, // 进一步微调阈值
                    match_count: 10
                })
            );

            const titleMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('title', `%${searchTerm}%`)
                .limit(10);

            const contentMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('content', `%${searchTerm}%`)
                .limit(5);

            const [vectorResponse, titleResponse, contentResponse] = await Promise.all([
                embeddingPromise,
                titleMatchPromise,
                contentMatchPromise
            ]);

            // 提取结果并打分排序
            const resultMap = new Map();

            // 类型 1: 标题命中 (权重最高: 10分)
            (titleResponse.data || []).forEach(item => {
                resultMap.set(item.notion_id, { ...item, score: 10 });
            });

            // 类型 2: 向量命中 (权重中等: 相似度 * 8)
            (vectorResponse.data || []).forEach(item => {
                const existing = resultMap.get(item.notion_id);
                const vectorScore = (item.similarity || 0.5) * 8;
                if (!existing || vectorScore > existing.score) {
                    resultMap.set(item.notion_id, { ...item, score: vectorScore });
                }
            });

            // 类型 3: 内容命中 (权重最低: 2分，仅作为补充)
            (contentResponse.data || []).forEach(item => {
                if (!resultMap.has(item.notion_id)) {
                    resultMap.set(item.notion_id, { ...item, score: 2 });
                }
            });

            // 最终排序：按总分倒序
            const finalResults = Array.from(resultMap.values())
                .sort((a, b) => b.score - a.score)
                .slice(0, 10);

            setResults(finalResults);
        } catch (err) {
            console.error('Search error:', err);
            setErrorInfo(err.message || '搜索服务暂时不可用');
        } finally {
            setLoading(false);
        }
    };

    // 防抖处理逻辑
    useEffect(() => {
        const timer = setTimeout(() => {
            if (query) performSearch(query);
        }, 600); // 600ms 防抖

        return () => clearTimeout(timer);
    }, [query]);

    const handleSearchChange = (e) => {
        setQuery(e.target.value);
    };

    return (
        <div className="app-container">
            <div className="bg-gradient"></div>

            <div className="search-container">
                <div className="search-inner">
                    <Search size={28} color="#94a3b8" />
                    <input
                        type="text"
                        placeholder="Search your Notion knowledge..."
                        value={query}
                        onChange={handleSearchChange}
                        autoFocus
                    />
                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center', opacity: 0.5 }}>
                        <Command size={14} />
                        <span style={{ fontSize: '12px' }}>K</span>
                    </div>
                </div>
            </div>

            <div className="results-list">
                {loading && <div className="loading-state">🔍 正在深钻知识库...</div>}

                {errorInfo && <div className="error-state">⚠️ {errorInfo}</div>}

                {results.map((item, idx) => (
                    <div key={item.notion_id || idx} className="result-card">
                        <div className="card-header">
                            <h3>{item.title}</h3>
                            <span className="category-tag">{item.category || 'Uncategorized'}</span>
                        </div>
                        <p>{item.content}</p>

                        {/* Notion 原生链接跳转 */}
                        <a
                            href={item.metadata?.url || `https://www.notion.so/${item.notion_id?.replace(/-/g, '')}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="notion-link"
                        >
                            <ExternalLink size={14} />
                            <span>Open in Notion</span>
                        </a>
                    </div>
                ))}

                {!loading && query.length > 2 && results.length === 0 && (
                    <div style={{ textAlign: 'center', color: '#94a3b8' }}>No matching thoughts found.</div>
                )}
            </div>
        </div>
    );
}

export default App;
