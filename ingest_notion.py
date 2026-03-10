import os
import sys
import json
import time
from dotenv import load_dotenv
from notion_client import Client
from supabase import create_client, Client as SupabaseClient
import httpx

# 强制使用 UTF-8 输出
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()

if not NOTION_TOKEN:
    print("❌ 错误: 环境变量 NOTION_TOKEN 为空")

notion = Client(auth=NOTION_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

SKIP_TITLES = ["Untitled", "无标题", "未命名"]
MIN_CONTENT_LENGTH = 0  # 放宽限制，确保导航页也能同步
TOKEN_KEYWORDS = ["sk-", "nvapi-", "github_pat", "token", "key", "密钥"]

def get_embedding(text: str):
    url = "https://integrate.api.nvidia.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    safe_text = text.strip()[:500] if text else "empty content"
    if not safe_text: safe_text = "untitled page"
    payload = {
        "input": [safe_text],
        "model": "nvidia/nv-embedqa-e5-v5",
        "input_type": "passage",
        "encoding_format": "float"
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json()['data'][0]['embedding']
    except Exception as e:
        print(f"⚠️ Embedding API 错误: {e}")
        raise e

def analyze_content(text: str):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""分析以下文本，并提取分类信息。请仅返回 JSON 格式，包含：category, sub_category, project_name, project_type, tags. 文本内容:\n{text[:2000]}"""
    payload = {
        "model": "meta/llama-3.1-405b-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
        "response_format": {"type": "json_object"}
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=40.0)
        response.raise_for_status()
        result = response.json()['choices'][0]['message']['content']
        return json.loads(result)
    except Exception:
        return {"category": "未分类", "sub_category": "其他", "project_name": "未知", "project_type": "未知", "tags": []}

def extract_page_content(page_id: str):
    full_text = []
    try:
        blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
        for block in blocks:
            b_type = block["type"]
            content = block.get(b_type, {})
            if isinstance(content, dict) and "rich_text" in content:
                for rt in content["rich_text"]:
                    full_text.append(rt.get("plain_text", ""))
    except Exception: pass
    return "\n".join(full_text)

import hashlib

def calculate_content_hash(text: str) -> str:
    """计算内容哈希值，识别微小改动"""
    if not text: return ""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def fetch_all_sync_status() -> dict:
    """一次性批量拉取数据库中所有已同步页面状态，返回以 notion_id 为 key 的字典"""
    cache = {}
    try:
        page_size = 1000
        offset = 0
        while True:
            res = supabase.table("knowledge_base").select("notion_id, last_notion_edited_at, metadata").range(offset, offset + page_size - 1).execute()
            if not res.data:
                break
            for record in res.data:
                nid = record.get("notion_id")
                if nid:
                    cache[nid] = {
                        "last_edited": record.get("last_notion_edited_at"),
                        "hash": record.get("metadata", {}).get("content_hash", "")
                    }
            if len(res.data) < page_size:
                break
            offset += page_size
        print(f"📦 已从数据库预加载 {len(cache)} 条同步记录", flush=True)
    except Exception as e:
        print(f"⚠️ 批量预加载失败，将逐条查询: {e}", flush=True)
    return cache

def migrate_notion_to_supabase():
    print(f"🚀 启动[智能增量同步版 v7 - 批量预加载优化] - {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    
    # 核心优化：启动时一次性批量预加载所有已同步状态，避免逐页查数据库
    sync_cache = fetch_all_sync_status()
    
    all_pages = []
    next_cursor = None
    while True:
        try:
            results = notion.search(filter={"property": "object", "value": "page"}, start_cursor=next_cursor)
            all_pages.extend(results.get("results", []))
            next_cursor = results.get("next_cursor")
            if not next_cursor: break
        except Exception as e:
            print(f"⚠️ Notion 搜索异常: {e}", flush=True)
            time.sleep(3)

    print(f"📊 发现授权页面总数: {len(all_pages)}", flush=True)
    stats = {"synced": 0, "updated": 0, "skipped": 0, "errors": 0}
    
    for page in all_pages:
        page_id = page["id"]
        notion_last_edited = page.get("last_edited_time")
        
        # 从内存缓存中查，O(1) 查询，无网络开销
        cached = sync_cache.get(page_id, {})
        db_last_edited = cached.get("last_edited")
        db_hash = cached.get("hash", "")
        
        title = "Untitled"
        props = page.get("properties", {})
        for name_prop in ["title", "Name", "名称"]:
            if name_prop in props and props[name_prop].get("title"):
                title = props[name_prop]["title"][0].get("plain_text", "Untitled")
                break
        
        if any(skip in title for skip in SKIP_TITLES):
            stats["skipped"] += 1
            continue

        is_update = True if db_last_edited else False
        if is_update and notion_last_edited[:19] <= db_last_edited[:19]:
            stats["skipped"] += 1
            continue

        max_retries = 2
        for attempt in range(max_retries):
            try:
                content = extract_page_content(page_id)
                new_hash = calculate_content_hash(content)
                
                if is_update and db_hash == new_hash:
                    supabase.table("knowledge_base").update({"last_notion_edited_at": notion_last_edited}).eq("notion_id", page_id).execute()
                    stats["skipped"] += 1
                    break

                is_token = any(kw in content.lower() for kw in TOKEN_KEYWORDS)
                if not content.strip() and not is_token: content = title
                if len(content.strip()) < MIN_CONTENT_LENGTH and not is_token:
                    stats["skipped"] += 1
                    break

                print(f"🔄 深度对账 [Hash变动]: {title}", flush=True)
                
                embedding = get_embedding(content)
                analysis = analyze_content(content)

                data = {
                    "notion_id": page_id,
                    "title": title[:250],
                    "content": content,
                    "embedding": embedding,
                    "category": str(analysis.get("category", "未分类"))[:250],
                    "sub_category": str(analysis.get("sub_category", ""))[:250],
                    "project_name": str(analysis.get("project_name", ""))[:250],
                    "project_type": str(analysis.get("project_type", ""))[:250],
                    "tags": analysis.get("tags", [])[:5],
                    "last_notion_edited_at": notion_last_edited,
                    "metadata": {
                        "source": "notion_v6_web_trigger", 
                        "url": page.get("url"),
                        "content_hash": new_hash
                    }
                }
                
                if is_update:
                    supabase.table("knowledge_base").update(data).eq("notion_id", page_id).execute()
                    stats["updated"] += 1
                else:
                    supabase.table("knowledge_base").insert(data).execute()
                    stats["synced"] += 1
                
                print(f"✨ 同步成功: {title}", flush=True)
                break 
                
            except Exception as e:
                print(f"⚠️ {page_id} Error: {e}", flush=True)
                if attempt == max_retries - 1: stats["errors"] += 1
                time.sleep(2)
        
    print(f"\n🏁 任务圆满结束！ 新增: {stats['synced']} | 更新: {stats['updated']} | 跳过: {stats['skipped']} | 错误: {stats['errors']}", flush=True)
    return stats

if __name__ == "__main__":
    migrate_notion_to_supabase()
