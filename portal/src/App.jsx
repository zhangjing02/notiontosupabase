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
    const searchIdRef = React.useRef(0);
    const pageRef = React.useRef(0);
    const loadingRef = React.useRef(false);

    const getEmbedding = async (text) => {
        try {
            const { data, error } = await supabase.functions.invoke('get-embedding', {
                body: { input: text }
            });
            if (error) throw error;
            return data.embedding;
        } catch (e) {
            console.error('Embedding error:', e);
            return null;
        }
    };

    const performSearch = React.useCallback(async (searchTerm, isNewSearch = true) => {
        if (loadingRef.current && !isNewSearch) return; // 防止重复加载更多

        const currentSearchId = ++searchIdRef.current;
        const normalizedTerm = searchTerm.trim();

        if (normalizedTerm.length < 2) {
            setResults([]);
            setLoading(false);
            setHasMore(false);
            loadingRef.current = false;
            return;
        }

        setErrorInfo('');
        loadingRef.current = true;

        if (isNewSearch) {
            setLoading(true);
            pageRef.current = 0;
            setPage(0);
            setHasMore(true);
            // 这里不立即 setResults([])，而是在数据回来后再替换，防止闪烁
            // 或者：只有在用户输入变动较大时才清空
        } else {
            setLoading(true);
        }

        try {
            const currentPage = isNewSearch ? 0 : pageRef.current + 1;
            const pageSize = 12;
            const offset = currentPage * pageSize;

            // 1. 发起并行检索
            const embeddingPromise = getEmbedding(normalizedTerm);

            const titleMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('title', `%${normalizedTerm}%`)
                .order('created_at', { ascending: false });

            const contentMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('content', `%${normalizedTerm}%`)
                .order('created_at', { ascending: false });

            const [embedding, titleResponse, contentResponse] = await Promise.all([
                embeddingPromise,
                titleMatchPromise,
                contentMatchPromise
            ]);

            // 竞态检查
            if (currentSearchId !== searchIdRef.current) return;

            let vectorData = [];
            if (embedding) {
                const { data, error } = await supabase.rpc('match_knowledge_base', {
                    query_embedding: embedding,
                    match_threshold: 0.15,
                    match_count: 50
                });
                if (!error) vectorData = data || [];
            }

            // 2. 增强型打分与强制过滤算法 (Stricter Mode)
            const resultMap = new Map();
            const lowerSearch = normalizedTerm.toLowerCase();

            // 规则 A: 标题命中 (最高优先级)
            (titleResponse.data || []).forEach(item => {
                const lowerTitle = (item.title || '').toLowerCase();
                let score = 0;
                if (lowerTitle.includes(lowerSearch)) {
                    score = 1000; // 绝对最高分
                    // 如果标题完全匹配或以关键词开头，再给点奖励
                    if (lowerTitle === lowerSearch) score += 500;
                    else if (lowerTitle.startsWith(lowerSearch)) score += 200;
                }
                resultMap.set(item.notion_id, { ...item, score });
            });

            // 规则 B: 内容命中 (中等优先级)
            (contentResponse.data || []).forEach(item => {
                const existing = resultMap.get(item.notion_id);
                const contentScore = 200;
                if (!existing) {
                    resultMap.set(item.notion_id, { ...item, score: contentScore });
                } else {
                    // 如果已经有分数，且内容也命中，累加
                    existing.score += contentScore;
                }
            });

            // 规则 C: 向量语义匹配 (最低优先级，仅作为辅助)
            // 策略：如果一个项既没有标题命中也没有内容命中，但向量相似度很高，我们保留它但给低分
            // 如果已经命中了，加上相似度分作为同分排序依据
            vectorData.forEach(item => {
                const existing = resultMap.get(item.notion_id);
                // 相似度归一化加分 (0-15)
                const vectorContribution = (item.similarity || 0) * 15;

                if (!existing) {
                    // 瞎联想拦截：如果向量相似度不够高 (e.g. < 0.35)，且没有文字命中，直接不显示
                    if ((item.similarity || 0) > 0.35) {
                        resultMap.set(item.notion_id, { ...item, score: vectorContribution });
                    }
                } else {
                    existing.score += vectorContribution;
                }
            });

            // 最终过滤：二次确认是否有任何关键词子串命中
            // 解决“歌手”搜出“指纹”的问题：如果得分非常低（纯靠联想且相似度一般），则剔除
            const finalCandidates = Array.from(resultMap.values()).filter(item => {
                // 如果分数 > 100，说明至少命中了标题或内容，保留
                if (item.score >= 100) return true;
                // 如果只有向量分，但标题和内容里压根没有这个词的影子，剔除（防止瞎联想）
                const hasKeywordInText = (item.title + (item.content || '')).toLowerCase().includes(lowerSearch);
                return hasKeywordInText || item.score > 10; // 极高相关度的联想才保留
            });

            const sortedAll = finalCandidates.sort((a, b) => {
                if (b.score !== a.score) return b.score - a.score;
                // 同分时按创建时间倒序
                return new Date(b.created_at) - new Date(a.created_at);
            });

            const pagedResults = sortedAll.slice(offset, offset + pageSize);

            if (currentSearchId !== searchIdRef.current) return;

            if (isNewSearch) {
                setResults(pagedResults);
            } else {
                setResults(prev => [...prev, ...pagedResults]);
            }

            pageRef.current = currentPage;
            setPage(currentPage);
            setHasMore(offset + pageSize < sortedAll.length);
        } catch (err) {
            console.error('Search error:', err);
            if (currentSearchId === searchIdRef.current) setErrorInfo('搜索连接异常');
        } finally {
            if (currentSearchId === searchIdRef.current) {
                setLoading(false);
                loadingRef.current = false;
            }
        }
    }, []); // 彻底稳定引用，防止无限循环

    // 防抖处理逻辑
    useEffect(() => {
        const term = query.trim();
        if (!term) {
            setResults([]);
            setLoading(false);
            setHasMore(false);
            return;
        }

        const timer = setTimeout(() => {
            performSearch(term, true);
        }, 400); // 略微调快响应

        return () => clearTimeout(timer);
    }, [query, performSearch]);

    // 无限滚动监听
    useEffect(() => {
        const observer = new IntersectionObserver(
            entries => {
                if (entries[0].isIntersecting && hasMore && !loading && query.trim()) { // 增加 query.trim() 检查
                    performSearch(query, false);
                }
            },
            { threshold: 0.1 }
        );

        const target = document.querySelector('#load-more-trigger');
        if (target) observer.observe(target);

        return () => observer.disconnect();
    }, [hasMore, loading, query, page, performSearch]);

    const [syncing, setSyncing] = useState(false);
    const [syncStats, setSyncStats] = useState(null);

    const handleSync = async () => {
        if (syncing) return;
        setSyncing(true);
        setSyncStats(null);
        try {
            const apiBase = import.meta.env.VITE_API_URL || '';
            const res = await fetch(`${apiBase}/api/sync`, { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                setSyncStats(data.data);
                // 同步成功后自动触发一次当前 query 的搜索，刷新数据
                if (query.trim()) performSearch(query.trim(), true);
            } else {
                setErrorInfo(data.message);
            }
        } catch (e) {
            setErrorInfo('同步请求失败，请检查后端状态');
        } finally {
            setSyncing(false);
        }
    };

    return (
        <div className="app-container">
            <div className="bg-gradient"></div>

            <div className="search-container">
                <div className="search-inner-wrapper" style={{ display: 'flex', gap: '12px', width: '100%', maxWidth: '800px' }}>
                    <div className="search-inner" style={{ flex: 1 }}>
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

                    <button
                        className={`sync-button ${syncing ? 'syncing' : ''}`}
                        onClick={handleSync}
                        disabled={syncing}
                        title="Sync from Notion"
                    >
                        <Hash size={18} className={syncing ? 'rotate-anim' : ''} />
                        <span>{syncing ? 'Syncing...' : 'Sync'}</span>
                    </button>
                </div>

                {syncStats && (
                    <div className="sync-report">
                        ✨ 同步成功: 新增 {syncStats.synced} | 更新 {syncStats.updated} | 跳过 {syncStats.skipped}
                        <button onClick={() => setSyncStats(null)} style={{ marginLeft: '10px', opacity: 0.5 }}>✕</button>
                    </div>
                )}
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
