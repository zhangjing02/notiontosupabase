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
    const [page, setPage] = useState(0);
    const [hasMore, setHasMore] = useState(true);

    const getEmbedding = async (text) => {
        const { data, error } = await supabase.functions.invoke('get-embedding', {
            body: { input: text }
        });
        if (error) throw error;
        return data.embedding;
    };

    const performSearch = async (searchTerm, isNewSearch = true) => {
        if (searchTerm.length < 2) {
            setResults([]);
            return;
        }

        if (isNewSearch) {
            setLoading(true);
            setPage(0);
            setHasMore(true);
        }

        setErrorInfo('');
        try {
            const currentPage = isNewSearch ? 0 : page + 1;
            const pageSize = 10;
            const offset = currentPage * pageSize;

            // 1. 并行发起三个维度的检索
            const embeddingPromise = getEmbedding(searchTerm).then(emb =>
                supabase.rpc('match_knowledge_base', {
                    query_embedding: emb,
                    match_threshold: 0.18, // 进一步降低阈值，确保召回更多
                    match_count: 50 // RPC 召回多一些，前端由于聚合做分页
                })
            );

            const titleMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('title', `%${searchTerm}%`)
                .order('created_at', { ascending: false });

            const contentMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('content', `%${searchTerm}%`)
                .order('created_at', { ascending: false });

            const [vectorResponse, titleResponse, contentResponse] = await Promise.all([
                embeddingPromise,
                titleMatchPromise,
                contentMatchPromise
            ]);

            // 提取结果并打分排序 (聚合所有结果)
            const resultMap = new Map();

            (titleResponse.data || []).forEach(item => {
                resultMap.set(item.notion_id, { ...item, score: 10 });
            });

            (vectorResponse.data || []).forEach(item => {
                const existing = resultMap.get(item.notion_id);
                const vectorScore = (item.similarity || 0.5) * 8;
                if (!existing || vectorScore > existing.score) {
                    resultMap.set(item.notion_id, { ...item, score: vectorScore });
                }
            });

            (contentResponse.data || []).forEach(item => {
                if (!resultMap.has(item.notion_id)) {
                    resultMap.set(item.notion_id, { ...item, score: 2 });
                }
            });

            // 排序并进行前端分页
            const sortedAll = Array.from(resultMap.values())
                .sort((a, b) => b.score - a.score);

            const pagedResults = sortedAll.slice(offset, offset + pageSize);

            if (isNewSearch) {
                setResults(pagedResults);
            } else {
                setResults(prev => [...prev, ...pagedResults]);
            }

            setPage(currentPage);
            setHasMore(offset + pageSize < sortedAll.length);
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
            if (query) performSearch(query, true);
            else setResults([]);
        }, 600);

        return () => clearTimeout(timer);
    }, [query]);

    // 无限滚动监听
    useEffect(() => {
        const observer = new IntersectionObserver(
            entries => {
                if (entries[0].isIntersecting && hasMore && !loading && query) {
                    performSearch(query, false);
                }
            },
            { threshold: 0.1 }
        );

        const target = document.querySelector('#load-more-trigger');
        if (target) observer.observe(target);

        return () => observer.disconnect();
    }, [hasMore, loading, query, page]);

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
                {results.map((item, idx) => (
                    <div key={item.notion_id || idx} className="result-card">
                        <div className="card-header">
                            <h3>{item.title}</h3>
                            <span className="category-tag">{item.category || 'Uncategorized'}</span>
                        </div>
                        <p>{item.content}</p>

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

                <div id="load-more-trigger" style={{ height: '20px', margin: '10px 0' }}>
                    {loading && <div className="loading-state">🔍 正在搜寻更多关联知识...</div>}
                </div>

                {!loading && query.length > 2 && results.length === 0 && (
                    <div style={{ textAlign: 'center', color: '#94a3b8' }}>No matching thoughts found.</div>
                )}

                {!hasMore && results.length > 0 && (
                    <div style={{ textAlign: 'center', color: '#64748b', fontSize: '12px', marginTop: '20px' }}>
                        已到达知识边界，暂无更多结果。
                    </div>
                )}
            </div>
        </div>
    );
}

export default App;
