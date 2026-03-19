import os
import sys
import json
import time
from dotenv import load_dotenv
from notion_client import Client
from supabase import create_client, Client as SupabaseClient
import httpx

# Removed sys.stdout re-encoding for better background compatibility
# if sys.stdout.encoding != 'utf-8':
#     import io
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "").strip()

# 自动切换模型链
LLM_FALLBACK_CHAIN = [
    {"provider": "nvidia", "model": "meta/llama-3.1-405b-instruct"},
    {"provider": "nvidia", "model": "meta/llama-3.3-70b-instruct"},
    {"provider": "nvidia", "model": "meta/llama-3.1-70b-instruct"},
    {"provider": "zhipu", "model": "glm-4"}
]

if not NOTION_TOKEN:
    print("❌ 错误: 环境变量 NOTION_TOKEN 为空")

# 初始化客户端
notion = Client(auth=NOTION_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

SKIP_TITLES = ["Untitled", "无标题", "未命名"]
MIN_CONTENT_LENGTH = 0  # 放宽限制，确保导航页也能同步
TOKEN_KEYWORDS = ["sk-", "nvapi-", "github_pat", "token", "key", "密钥"]

def get_embedding(text: str) -> list:
    """调用 NVIDIA API 获取 text-embedding"""
    if not NVIDIA_API_KEY:
        print("⚠️ 警告: NVIDIA_API_KEY 未设置，跳过向量生成。")
        return None
    
    # E5-v5 对长度有一定限制，这里简单截断（通常 512-1024 tokens）
    # 截断前 8000 字符大致对应其 token 限制范围
    clean_text = text[:8000].replace("\n", " ")
    
    url = "https://integrate.api.nvidia.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "input": [clean_text],
        "model": "nvidia/nv-embedqa-e5-v5",
        "input_type": "passage", # 存入数据库使用 passage
        "encoding_format": "float"
    }
    
    try:
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload, timeout=20.0)
            response.raise_for_status()
            return response.json()['data'][0]['embedding']
    except Exception as e:
        print(f"❌ 获取向量失败: {e}")
        return None

def analyze_content(text: str):
    """
    分析内容并提取分类信息，支持多模型自动切换/降级。
    """
    prompt = f"""分析以下文本，并提取分类信息。请仅返回 JSON 格式，包含：category, sub_category, project_name, project_type, tags. 文本内容:\n{text[:2000]}"""
    
    for cfg in LLM_FALLBACK_CHAIN:
        provider = cfg["provider"]
        model = cfg["model"]
        
        try:
            if provider == "nvidia":
                if not NVIDIA_API_KEY: continue
                url = "https://integrate.api.nvidia.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"}
                }
            elif provider == "zhipu":
                if not ZHIPU_API_KEY: continue
                url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
                headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                }
            
            print(f"🤖 尝试使用 {provider}/{model} 进行分析...", flush=True)
            response = httpx.post(url, headers=headers, json=payload, timeout=40.0)
            response.raise_for_status()
            
            result_str = response.json()['choices'][0]['message']['content']
            # 清理部分模型可能带有的 markdown 标识符
            if result_str.startswith("```json"):
                result_str = result_str.split("```json")[1].split("```")[0].strip()
            elif result_str.startswith("```"):
                result_str = result_str.split("```")[1].split("```")[0].strip()
                
            return json.loads(result_str)
            
        except Exception as e:
            print(f"⚠️ 模型 {model} 调用失败: {e}，尝试下一个...", flush=True)
            continue
            
    # 如果全部失败，返回默认值
    print("❌ 所有模型均告失败，使用默认分类", flush=True)
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

def extract_database_content(database_id: str):
    """
    提取数据库中所有行（Page）的内容并合并
    """
    rows_text = []
    try:
        # 这里限制只读取前 100 行，避免超大数据库卡死
        response = notion.databases.query(database_id=database_id, page_size=100)
        for row in response.get("results", []):
            row_parts = []
            props = row.get("properties", {})
            for p_name, p_val in props.items():
                p_type = p_val.get("type")
                if p_type == "title":
                    text = "".join([t["plain_text"] for t in p_val["title"]])
                    row_parts.append(f"{p_name}: {text}")
                elif p_type == "rich_text":
                    text = "".join([t["plain_text"] for t in p_val["rich_text"]])
                    row_parts.append(f"{p_name}: {text}")
                elif p_type == "select":
                    sel = p_val.get("select")
                    if sel: row_parts.append(f"{p_name}: {sel['name']}")
                elif p_type == "multi_select":
                    sels = [s["name"] for s in p_val.get("multi_select", [])]
                    if sels: row_parts.append(f"{p_name}: {', '.join(sels)}")
                elif p_type in ["url", "email", "phone_number"]:
                    val = p_val.get(p_type)
                    if val: row_parts.append(f"{p_name}: {val}")
                elif p_type == "status":
                    status = p_val.get("status")
                    if status: row_parts.append(f"{p_name}: {status['name']}")
                elif p_type == "checkbox":
                    val = p_val.get("checkbox")
                    row_parts.append(f"{p_name}: {val}")
            
            if row_parts:
                rows_text.append(" | ".join(row_parts))
    except Exception as e:
        print(f"⚠️ 提取数据库 {database_id} 内容失败: {e}")
    
    return "\n".join(rows_text)

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
            res = supabase.table("knowledge_base").select("notion_id, last_notion_edited_at, metadata, embedding").range(offset, offset + page_size - 1).execute()
            if not res.data:
                break
            for record in res.data:
                nid = record.get("notion_id")
                if nid:
                    cache[nid] = {
                        "last_edited": record.get("last_notion_edited_at"),
                        "hash": record.get("metadata", {}).get("content_hash", ""),
                        "has_embedding": record.get("embedding") is not None
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
            # 取消 object: page 过滤，允许同步 database
            results = notion.search(start_cursor=next_cursor)
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
        obj_type = page.get("object", "page")
        
        if obj_type == "database":
            title_list = page.get("title", [])
            if title_list:
                title = title_list[0].get("plain_text", "Untitled")
        else:
            props = page.get("properties", {})
            for name_prop in ["title", "Name", "名称"]:
                if name_prop in props and props[name_prop].get("title"):
                    title = props[name_prop]["title"][0].get("plain_text", "Untitled")
                    break
        
        if any(skip in title for skip in SKIP_TITLES):
            stats["skipped"] += 1
            continue

        is_update = page_id in sync_cache
        has_embed = cached.get("has_embedding", False)
        
        # 只有在 (1)已经是更新状态 (2)时间戳没变 (3)已经有向量 的情况下才跳过
        if is_update and db_last_edited and notion_last_edited[:19] <= db_last_edited[:19] and has_embed:
            # print(f"⏭️ 跳过已同步、时间戳未变且有向量的页面: {title}", flush=True)
            stats["skipped"] += 1
            continue

        max_retries = 2
        for attempt in range(max_retries):
            try:
                if obj_type == "database":
                    content = extract_database_content(page_id)
                else:
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
