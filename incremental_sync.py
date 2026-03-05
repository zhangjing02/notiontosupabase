import os
import json
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client
from supabase import create_client, Client as SupabaseClient
import httpx

load_dotenv()

# --- 核心改进：引入增量对账逻辑 ---

def calculate_content_hash(text: str) -> str:
    """计算内容哈希值，用于精确识别『改一个字也感知』"""
    if not text: return ""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_last_sync_time(supabase: SupabaseClient, notion_id: str):
    """从数据库获取该页面的最后同步时间及内容哈希"""
    try:
        res = supabase.table("knowledge_base").select("last_notion_edited_at, metadata").eq("notion_id", notion_id).execute()
        if res.data:
            record = res.data[0]
            last_edited_at = record.get("last_notion_edited_at")
            # 兼容旧版本元数据中的 hash (如果存在)
            metadata = record.get("metadata", {})
            old_hash = metadata.get("content_hash", "")
            return last_edited_at, old_hash
    except Exception:
        pass
    return None, None

def check_revision_needed(notion_page: dict, old_time_str: str, current_content: str, old_hash: str) -> bool:
    """
    判断逻辑：
    1. 如果时间戳不同 -> 可能有变动
    2. 如果时间戳相同但 Hash 不同 (万一时间没变内容变了) -> 必有变动
    """
    notion_time_str = notion_page.get("last_edited_time")
    new_hash = calculate_content_hash(current_content)
    
    # 转换为统一的 ISO 格式进行比较
    if old_time_str:
        # Notion API 返回的是 ISO 格式，带 Z。Supabase 存的可能是带偏移量的。
        # 简单字符串前缀比较通常足够 (YYYY-MM-DDTHH:MM:SS)
        if notion_time_str[:19] != old_time_str[:19]:
            return True, new_hash
            
    if old_hash != new_hash:
        return True, new_hash
        
    return False, new_hash

# 这个文件目前作为逻辑参考，下一步将直接注入到 ingest_notion.py
