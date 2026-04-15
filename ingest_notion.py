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
    print("[ERROR] 环境变量 NOTION_TOKEN 为空")

# 初始化客户端
notion = Client(auth=NOTION_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

SKIP_TITLES = ["Untitled", "无标题", "未命名"]
MIN_CONTENT_LENGTH = 0  # 放宽限制，确保导航页也能同步
TOKEN_KEYWORDS = ["sk-", "nvapi-", "github_pat", "token", "key", "密钥"]

def get_embedding(text: str) -> list:
    """调用 NVIDIA API 获取 text-embedding"""
    if not NVIDIA_API_KEY:
        print("[WARN] NVIDIA_API_KEY 未设置，跳过向量生成。")
        return None
    
    # 防御性检查：API 不接受空字符串数组或列表
    if not text or not text.strip():
        return None
        
    # E5-v5 限制 512 tokens，截断 500 字符（更加均衡，确保高密度文档不溢出）
    clean_text = text[:500].replace("\n", " ").strip()
    if not clean_text:
        return None
    
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
        error_msg = str(e)
        if hasattr(e, 'response') and e.response:
             error_msg += f" | Details: {e.response.text}"
        print(f"[ERROR] 获取向量失败: {error_msg}")
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
            
            print(f"[INFO] 尝试使用 {provider}/{model} 进行分析...", flush=True)
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
            print(f"[WARN] 模型 {model} 调用失败: {e}，尝试下一个...", flush=True)
            continue
            
    # 如果全部失败，返回默认值
    print("[ERROR] 所有模型均告失败，使用默认分类", flush=True)
    return {"category": "未分类", "sub_category": "其他", "project_name": "未知", "project_type": "未知", "tags": []}

def get_page_content(page_id: str, obj_type: str = "page"):
    """
    提取页面或数据库的内容。
    """
    if obj_type == "database":
        try:
            db_obj = notion.databases.retrieve(database_id=page_id)
            title = "".join([t.get("plain_text", "") for t in db_obj.get("title", [])])
            props = db_obj.get("properties", {})
            return f"Notion Database: {title}\nProperties: " + ", ".join(props.keys())
        except Exception:
            return "Notion Database (No details available)"

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

def extract_database_row_content(row: dict) -> str:
    """
    提取数据库中单行（Page）的内容，将各列属性拼接为一段文本
    """
    row_parts = []
    try:
        props = row.get("properties", {})
        for p_name, p_val in props.items():
            if not p_val or not isinstance(p_val, dict): continue
            p_type = p_val.get("type")
            text = ""
            
            if p_type == "title":
                text = "".join([t.get("plain_text", "") for t in p_val.get("title", [])])
            elif p_type == "rich_text":
                text = "".join([t.get("plain_text", "") for t in p_val.get("rich_text", [])])
            elif p_type == "select":
                sel = p_val.get("select")
                if sel: text = sel.get('name', '')
            elif p_type == "multi_select":
                sels = [s.get("name", "") for s in p_val.get("multi_select", [])]
                if sels: text = ", ".join(sels)
            elif p_type in ["url", "email", "phone_number"]:
                text = p_val.get(p_type, "")
            elif p_type == "status":
                status = p_val.get("status")
                if status: text = status.get('name', '')
            elif p_type == "checkbox":
                text = str(p_val.get("checkbox", False))
            elif p_type == "number":
                num = p_val.get("number")
                if num is not None: text = str(num)
            
            if text:
                row_parts.append(f"{p_name}: {text}")
    except Exception as e:
        print(f"[WARN] 提取数据库单行内容失败: {e}")
    
    return " | ".join(row_parts)

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
        print(f"[INFO] 已从数据库预加载 {len(cache)} 条同步记录", flush=True)
    except Exception as e:
        print(f"[WARN] 批量预加载失败，将逐条查询: {e}", flush=True)
    return cache

def migrate_notion_to_supabase():
    print(f"[START] 启动[智能增量同步版 v8.4 - 深度上下文增强] - {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    
    # 核心优化：启动时一次性批量预加载所有已同步状态，避免逐页查数据库
    sync_cache = fetch_all_sync_status()
    
    all_pages = []
    database_titles = {} # 缓存数据库标题
    next_cursor = None
    while True:
        try:
            results = notion.search(start_cursor=next_cursor)
            res_list = results.get("results", [])
            
            # 记录数据库标题
            for item in res_list:
                if item.get("object") == "database":
                    db_id = item.get("id")
                    db_title = "Untitled Database"
                    if item.get("title"):
                        db_title = "".join([t.get("plain_text", "") for t in item["title"]])
                    database_titles[db_id] = db_title

            for item in res_list:
                obj_type = item.get("object")
                
                # 定义递归发现内联数据库的辅助函数
                def find_inline_databases(parent_id, current_title):
                    try:
                        children = notion.blocks.children.list(block_id=parent_id).get("results", [])
                        for child in children:
                            if child["type"] == "child_database":
                                db_id = child["id"]
                                # 检索数据库完整信息以供同步
                                try:
                                    db_obj = notion.databases.retrieve(database_id=db_id)
                                    if db_id not in [p["id"] for p in all_pages]:
                                        db_obj["_is_found_inline"] = True
                                        all_pages.append(db_obj)
                                        database_titles[db_id] = "".join([t.get("plain_text", "") for t in db_obj.get("title", [])])
                                        print(f"[INFO] 发现内联数据库: {database_titles[db_id]}", flush=True)
                                except Exception: pass
                            elif child["type"] == "child_page":
                                # 暂不深度递归 child_page，因为搜索已经处理了 page 级
                                pass
                    except Exception: pass

                if obj_type == "database":
                    all_pages.append(item) # 索引数据库本身
                    try:
                        db_pages = notion.databases.query(database_id=item["id"])
                        db_title = database_titles.get(item["id"], "Database")
                        for row in db_pages.get("results", []):
                            row["_is_database_row"] = True
                            row["_parent_db_title"] = db_title
                            all_pages.append(row)
                    except Exception as e:
                        print(f"[WARN] 查询数据库 {item['id']} 的行失败: {e}", flush=True)
                elif obj_type == "page":
                    if item.get("parent", {}).get("type") == "database_id":
                        item["_is_database_row"] = True
                        db_id = item["parent"]["database_id"]
                        if db_id not in database_titles:
                            try:
                                db_obj = notion.databases.retrieve(database_id=db_id)
                                database_titles[db_id] = "".join([t.get("plain_text", "") for t in db_obj.get("title", [])])
                            except: database_titles[db_id] = "Unknown Database"
                        item["_parent_db_title"] = database_titles.get(db_id)
                    
                    all_pages.append(item)
                    # 对每个发现的页面，主动探测其是否含有内联数据库
                    find_inline_databases(item["id"], item.get("title", ""))
            
            next_cursor = results.get("next_cursor")
            print(f"[INFO] 已搜索并展开到 {len(all_pages)} 条记录 (数据库标题缓存规模: {len(database_titles)})...", flush=True)
            if not next_cursor: break
        except Exception as e:
            print(f"[WARN] Notion 搜索异常: {e}", flush=True)
            time.sleep(3)

    print(f"[INFO] 发现需处理的授权页面总数: {len(all_pages)}", flush=True)
    total = len(all_pages)
    stats = {"synced": 0, "updated": 0, "skipped": 0, "errors": 0}
    
    for i, page in enumerate(all_pages):
        page_id = page["id"]
        notion_last_edited = page.get("last_edited_time")
        obj_type = page.get("object", "page")
        is_database_row = page.get("_is_database_row", False)
        
        # 从内存缓存中查
        cached = sync_cache.get(page_id, {})
        db_last_edited = cached.get("last_edited")
        db_hash = cached.get("hash", "")
        
        # 提取标题
        title = "Untitled"
        if obj_type == "database" and page.get("title"):
            title = "".join([t.get("plain_text", "") for t in page["title"]])
        else:
            props = page.get("properties", {})
            for prop_name, prop_data in props.items():
                if isinstance(prop_data, dict) and prop_data.get("type") == "title" and prop_data.get("title"):
                    title = prop_data["title"][0].get("plain_text", "Untitled")
                    break
        
        # 实时显示进度条 (单行刷新)
        print(f"\r[{i+1}/{total}] {title[:35].ljust(35)} | {obj_type:8} | ", end='', flush=True)

        if any(skip in title for skip in SKIP_TITLES):
            stats["skipped"] += 1
            continue

        is_update = page_id in sync_cache
        has_embed = cached.get("has_embedding", False)
        
        # 增量对账
        should_skip = False
        if is_update and db_last_edited and notion_last_edited:
            # 简单的时间戳前缀比较 (YYYY-MM-DDTHH:MM:SS)
            if notion_last_edited[:19] == db_last_edited[:19]:
                # 时间戳一致，但我们需要确认 Hashes 是否也一致 (对于数据库行，强制校验以应用新 Context)
                if db_hash and has_embed and not is_database_row:
                    should_skip = True

        if should_skip:
            stats["skipped"] += 1
            print("[SKIP] 跳过", flush=True)
            continue
        
        # 强制更新数据库行逻辑
        is_database_row = page.get("_is_database_row", False)
        if is_database_row:
            print(f"FORCING DB ROW: {title}", flush=True)

        max_retries = 2
        for attempt in range(max_retries):
            try:
                # 确定内容来源
                if obj_type == "database":
                    # 索引数据库本身：标题 + 属性列名
                    content = f"Notion Database: {title}\nProperties: " + ", ".join(props.keys())
                    # 不需要在这里 continue，让它走下面的同步逻辑存入 Supabase
                elif is_database_row:
                    content = extract_database_row_content(page)
                    db_title = page.get("_parent_db_title")
                    if not db_title and page.get("parent", {}).get("type") == "database_id":
                        db_id = page["parent"]["database_id"]
                        db_title = database_titles.get(db_id, "Database")
                    
                    if db_title:
                        content = f"[Context-RAG: {db_title}] {content}"
                else:
                    # 更新内容详情
                    content = get_page_content(page_id, obj_type)
                
                # 增量标识：通过版本号确保逻辑变更时能触发重新计算
                RAG_VERSION = "v8.4"
                new_hash = calculate_content_hash(content + RAG_VERSION)
                
                # 再次校验内容哈希，如果内容完全一致，则跳过后续昂贵的 API 调用
                if is_update and db_hash == new_hash and has_embed:
                    print(f"[SKIP] 内容无变化，跳过更新: {title}", flush=True)
                    stats["skipped"] += 1
                    continue

                # 调试日志：识别被处理的记录
                print(f"[SYNC] 处理变更: {title} (ID: {page_id})", flush=True)
                
                is_token = any(kw in content.lower() for kw in TOKEN_KEYWORDS)
                if not content.strip() and not is_token: content = title
                if len(content.strip()) < MIN_CONTENT_LENGTH and not is_token:
                    stats["skipped"] += 1
                    break

                if is_database_row:
                    print(f"DEBUG DB ROW PAYLOAD: {title} | Content Sample: {content[:100]}", flush=True)

                embedding = get_embedding(content)
                analysis = analyze_content(content)

                # 鲁棒性防守：确保分析结果是字典且字段不为空 (针对部分模型返回 null 的情况)
                if not isinstance(analysis, dict):
                    analysis = {"category": "未分类", "sub_category": "其他", "project_name": "未知", "project_type": "未知", "tags": []}
                
                # 遍历所有字段进行 None 值的兜底处理
                safe_tags = analysis.get("tags")
                if not isinstance(safe_tags, list): safe_tags = []

                data = {
                    "notion_id": page_id,
                    "title": title[:250],
                    "content": content,
                    "embedding": embedding,
                    "category": str(analysis.get("category") or "未分类")[:250],
                    "sub_category": str(analysis.get("sub_category") or "")[:250],
                    "project_name": str(analysis.get("project_name") or "")[:250],
                    "project_type": str(analysis.get("project_type") or "")[:250],
                    "tags": safe_tags[:5],
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
                
                print(f"[OK] 同步成功: {title}", flush=True)
                break 
                
            except Exception as e:
                print(f"[WARN] {page_id} Error: {e}", flush=True)
                if attempt == max_retries - 1: stats["errors"] += 1
                time.sleep(2)
        
    print(f"\n[DONE] 任务圆满结束！ 新增: {stats['synced']} | 更新: {stats['updated']} | 跳过: {stats['skipped']} | 错误: {stats['errors']}", flush=True)
    return stats

if __name__ == "__main__":
    migrate_notion_to_supabase()
