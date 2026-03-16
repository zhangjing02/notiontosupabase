import React, { useState, useEffect } from 'react';
import { createClient } from '@supabase/supabase-js';
import { Search, ExternalLink, Hash, Command, Copy, Check, ChevronDown, ChevronUp, Clock } from 'lucide-react';

// 格式化相对时间
const formatDistanceToNow = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    const now = new Date();
    const diffInSeconds = Math.floor((now - date) / 1000);

    if (diffInSeconds < 60) return '刚刚';
    if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}分钟前`;
    if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}小时前`;
    if (diffInSeconds < 2592000) return `${Math.floor(diffInSeconds / 86400)}天前`;
    return date.toLocaleDateString();
};

// 搜索词高亮组件
const HighlightedText = ({ text, highlight }) => {
    if (!highlight.trim()) return <span>{text}</span>;
    const parts = text.split(new RegExp(`(${highlight})`, 'gi'));
    return (
        <span>
            {parts.map((part, i) =>
                part.toLowerCase() === highlight.toLowerCase() ? (
                    <mark key={i} className="highlight">{part}</mark>
                ) : (
                    part
                )
            )}
        </span>
    );
};

const ResultCard = ({ item, searchQuery }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const [copied, setCopied] = useState(false);

    const handleCopy = (e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(item.content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    // 增强代码判断：包含常见代码特征或换行较多
    const isCodeLike = 
        (item.content?.includes('{') && item.content?.includes('}')) || 
        item.content?.includes('const ') || 
        item.content?.includes('import ') ||
        (item.content?.split('\n').length > 5);

    return (
        <div className={`result-card ${isExpanded ? 'expanded' : ''}`} onClick={() => setIsExpanded(!isExpanded)}>
            <div className="card-header">
                <h3><HighlightedText text={item.title} highlight={searchQuery} /></h3>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span className="category-tag">{item.category || '未分类'}</span>
                    <button className={`icon-btn ${copied ? 'active' : ''}`} onClick={handleCopy} title="Copy content">
                        {copied ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                </div>
            </div>

            <div className="content-wrapper">
                <p className={isCodeLike ? 'is-code' : ''}>
                    <HighlightedText text={item.content} highlight={searchQuery} />
                </p>

                {item.content?.length > 80 && (
                    <button className="expand-toggle" onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}>
                        {isExpanded ? (
                            <><ChevronUp size={14} /> 收起内容</>
                        ) : (
                            <><ChevronDown size={14} /> 展开全部 ({item.content.length}字)</>
                        )}
                    </button>
                )}
            </div>

            <div className="card-footer">
                <a
                    href={item.metadata?.url || `https://www.notion.so/${item.notion_id?.replace(/-/g, '')}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="notion-link"
                    onClick={(e) => e.stopPropagation()}
                    translate="no"
                >
                    <ExternalLink size={14} />
                    <span>Open in Notion</span>
                </a>

                {item.last_notion_edited_at && (
                    <div className="time-badge">
                        <Clock size={10} style={{ marginRight: '4px' }} />
                        最后编辑于 {formatDistanceToNow(item.last_notion_edited_at)}
                    </div>
                )}
            </div>
        </div>
    );
};

// 初始化 Supabase 客户端
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const supabase = createClient(supabaseUrl, supabaseAnonKey);

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

    const performSearch = React.useCallback(async (searchTerm, isNewSearch = true) => {
        if (loadingRef.current && !isNewSearch) return;

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
        } else {
            setLoading(true);
        }

        try {
            const currentPage = isNewSearch ? 0 : pageRef.current + 1;
            const pageSize = 12;
            const offset = currentPage * pageSize;

            const embeddingPromise = getEmbedding(normalizedTerm);

            const titleMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('title', `%${normalizedTerm}%`)
                .order('last_notion_edited_at', { ascending: false });

            const contentMatchPromise = supabase
                .from('knowledge_base')
                .select('*')
                .ilike('content', `%${normalizedTerm}%`)
                .order('last_notion_edited_at', { ascending: false });

            const [embedding, titleResponse, contentResponse] = await Promise.all([
                embeddingPromise,
                titleMatchPromise,
                contentMatchPromise
            ]);

            if (currentSearchId !== searchIdRef.current) return;

            let vectorData = [];
            if (embedding) {
                const { data, error } = await supabase.rpc('match_knowledge_base', {
                    query_embedding: embedding,
                    match_threshold: 0.1,
                    match_count: 50
                });
                if (!error) vectorData = data || [];
            }

            const resultMap = new Map();
            const lowerSearch = normalizedTerm.toLowerCase();

            (titleResponse.data || []).forEach(item => {
                const lowerTitle = (item.title || '').toLowerCase();
                let score = 0;
                if (lowerTitle.includes(lowerSearch)) {
                    score = 1000;
                    if (lowerTitle === lowerSearch) score += 500;
                    else if (lowerTitle.startsWith(lowerSearch)) score += 200;
                }
                resultMap.set(item.notion_id, { ...item, score });
            });

            (contentResponse.data || []).forEach(item => {
                const existing = resultMap.get(item.notion_id);
                const contentScore = 200;
                if (!existing) {
                    resultMap.set(item.notion_id, { ...item, score: contentScore });
                } else {
                    existing.score += contentScore;
                }
            });

            vectorData.forEach(item => {
                const existing = resultMap.get(item.notion_id);
                const vectorContribution = (item.similarity || 0) * 15;

                if (!existing) {
                    if ((item.similarity || 0) > 0.3) {
                        resultMap.set(item.notion_id, { ...item, score: vectorContribution });
                    }
                } else {
                    existing.score += vectorContribution;
                }
            });

            const finalCandidates = Array.from(resultMap.values()).filter(item => {
                if (item.score >= 100) return true;
                const hasKeywordInText = (item.title + (item.content || '')).toLowerCase().includes(lowerSearch);
                return hasKeywordInText || item.score > 8;
            });

            const sortedAll = finalCandidates.sort((a, b) => {
                if (b.score !== a.score) return b.score - a.score;
                return new Date(b.last_notion_edited_at) - new Date(a.last_notion_edited_at);
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
    }, []);

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
        }, 400);

        return () => clearTimeout(timer);
    }, [query, performSearch]);

    useEffect(() => {
        const observer = new IntersectionObserver(
            entries => {
                if (entries[0].isIntersecting && hasMore && !loading && query.trim()) {
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
                <div className="search-inner">
                    <Search size={28} color="#94a3b8" />
                    <input
                        type="text"
                        placeholder="想找点什么知识？"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        autoFocus
                    />
                </div>

                {syncStats && (
                    <div className="sync-report">
                        ✨ 同步成功: 新增 {syncStats.synced} | 更新 {syncStats.updated} | 跳过 {syncStats.skipped}
                        <button onClick={() => setSyncStats(null)} style={{ marginLeft: '10px', opacity: 0.5, background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
                    </div>
                )}
            </div>


            <button
                className={`sync-button ${syncing ? 'syncing' : ''}`}
                onClick={handleSync}
                disabled={syncing}
                title="Sync from Notion"
            >
                <Hash size={18} className={syncing ? 'rotate-anim' : ''} />
                <span>{syncing ? '同步中...' : '开始同步'}</span>
            </button>

            <div className="results-list">
                {results.map((item, idx) => (
                    <ResultCard key={item.notion_id || idx} item={item} searchQuery={query} />
                ))}

                <div id="load-more-trigger" style={{ height: '20px', margin: '10px 0' }}>
                    {loading && <div className="loading-state">🔍 正在搜寻更多关联知识...</div>}
                </div>

                {!loading && query.length >= 2 && results.length === 0 && (
                    <div className="loading-state" style={{ background: 'rgba(255, 255, 255, 0.02)', borderStyle: 'dashed' }}>
                         🤷‍♂️ 未找到匹配的知识，建议尝试换个关键词。
                    </div>
                )}

                {!hasMore && results.length > 0 && query.length >= 2 && (
                    <div style={{ textAlign: 'center', color: '#64748b', fontSize: '12px', marginTop: '20px', paddingBottom: '2rem' }}>
                        已到达知识边界。
                    </div>
                )}
            </div>
        </div>
    );
}

export default App;
