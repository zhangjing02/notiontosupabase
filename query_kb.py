import os
import sys
import json
import httpx
from dotenv import load_dotenv
from supabase import create_client, Client as SupabaseClient

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def get_embedding(text: str):
    url = "https://integrate.api.nvidia.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "input": [text],
        "model": "nvidia/nv-embedqa-e5-v5",
        "input_type": "query",
        "encoding_format": "float"
    }
    response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    response.raise_for_status()
    return response.json()['data'][0]['embedding']

def query_knowledge_base(query_text: str, limit: int = 5):
    print(f"🔍 正在搜索: {query_text}...")
    embedding = get_embedding(query_text)
    
    # 使用 Supabase 的 rpc 调用 vector search 函数
    # 注意：你需要确保数据库中已经定义了 match_documents 函数
    # 如果没有定义，我们可以尝试直接 select 并手动计算（但性能不佳）
    # 或者使用 supabase.rpc('match_knowledge_base', ...)
    
    try:
        # 尝试使用通用的 match_documents 逻辑（假设已按 full_schema.sql 或标准模板创建）
        # 如果报错，请检查 sql/ 目录下的函数定义
        rpc_params = {
            "query_embedding": embedding,
            "match_threshold": 0.5,
            "match_count": limit,
        }
        res = supabase.rpc("match_knowledge_base", rpc_params).execute()
        return res.data
    except Exception as e:
        print(f"⚠️ RPC 搜索失败: {e}")
        # fallback: 简单文本搜索
        print("💡 尝试回退至简单文本搜索...")
        res = supabase.table("knowledge_base").select("*").ilike("content", f"%{query_text}%").limit(limit).execute()
        return res.data

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "Android Studio 快捷键"
    results = query_knowledge_base(query)
    
    if not results:
        print("❌ 未找到相关内容。")
    else:
        print(f"✅ 找到 {len(results)} 条相关结果:\n")
        for i, row in enumerate(results, 1):
            print(f"{i}. 【{row.get('title')}】 (类别: {row.get('category')})")
            content_preview = row.get('content', '')[:200].replace('\n', ' ')
            print(f"   摘要: {content_preview}...")
            print(f"   Notion ID: {row.get('notion_id')}\n")
