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

    const getEmbedding = async (text) => {
        const response = await fetch("https://integrate.api.nvidia.com/v1/embeddings", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${NVIDIA_API_KEY}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                input: [text],
                model: "nvidia/nv-embedqa-e5-v5",
                input_type: "query",
                encoding_format: "float"
            })
        });
        const data = await response.json();
        return data.data[0].embedding;
    };

    const handleSearch = async (e) => {
        const value = e.target.value;
        setQuery(value);

        if (value.length < 2) {
            setResults([]);
            return;
        }

        setLoading(true);
        try {
            const embedding = await getEmbedding(value);
            const { data, error } = await supabase.rpc('match_knowledge_base', {
                query_embedding: embedding,
                match_threshold: 0.4, // 适当降低阈值以获得更多结果
                match_count: 5
            });

            if (error) throw error;

            // 补充：不仅要 RPC 的结果，如果是普通文本，也尝试搜索
            if (!data || data.length === 0) {
                const { data: simpleData } = await supabase
                    .from('knowledge_base')
                    .select('*')
                    .ilike('content', `%${value}%`)
                    .limit(5);
                setResults(simpleData || []);
            } else {
                setResults(data);
            }
        } catch (err) {
            console.error('Search error:', err);
        } finally {
            setLoading(false);
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
                        placeholder="Search your Notion knowledge..."
                        value={query}
                        onChange={handleSearch}
                        autoFocus
                    />
                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center', opacity: 0.5 }}>
                        <Command size={14} />
                        <span style={{ fontSize: '12px' }}>K</span>
                    </div>
                </div>
            </div>

            <div className="results-list">
                {loading && <div style={{ textAlign: 'center', opacity: 0.5 }}>Searching deep into knowledge...</div>}

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
