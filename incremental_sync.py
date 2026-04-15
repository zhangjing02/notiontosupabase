import hashlib
import os
import time

from dotenv import load_dotenv
from notion_client import Client
from supabase import Client as SupabaseClient
from supabase import create_client

from ingest_notion import analyze_content, get_embedding

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
ENABLE_BLOCK_CLASSIFICATION = os.getenv("ENABLE_BLOCK_CLASSIFICATION", "false").lower() == "true"
EMBEDDING_AVAILABLE = bool(os.getenv("NVIDIA_API_KEY", "").strip())
BLOCK_RAG_VERSION = "block-v1"

if not NOTION_TOKEN:
    print("[ERROR] 环境变量 NOTION_TOKEN 为空")

notion = Client(auth=NOTION_TOKEN)
supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)


def calculate_content_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def extract_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for _, prop_data in props.items():
        if isinstance(prop_data, dict) and prop_data.get("type") == "title" and prop_data.get("title"):
            return prop_data["title"][0].get("plain_text", "Untitled")
    return "Untitled"


def get_block_plain_text(block: dict) -> str:
    b_type = block.get("type")
    content = block.get(b_type, {})

    if not isinstance(content, dict):
        return ""

    if "rich_text" in content:
        return "".join([t.get("plain_text", "") for t in content.get("rich_text", [])]).strip()

    if b_type in {"child_page", "child_database"}:
        return str(content.get("title", "")).strip()

    if b_type == "table_row":
        cells = content.get("cells", [])
        parts = []
        for cell in cells:
            if isinstance(cell, list):
                parts.append("".join([t.get("plain_text", "") for t in cell]))
        return " | ".join([p.strip() for p in parts if p.strip()])

    return ""


def iterate_blocks_recursively(root_block_id: str, max_depth: int = 8):
    stack = [(root_block_id, 0)]

    while stack:
        block_id, depth = stack.pop()
        if depth > max_depth:
            continue

        next_cursor = None
        while True:
            res = notion.blocks.children.list(block_id=block_id, start_cursor=next_cursor)
            children = res.get("results", [])

            for child in children:
                yield child, depth
                if child.get("has_children"):
                    stack.append((child["id"], depth + 1))

            next_cursor = res.get("next_cursor")
            if not next_cursor:
                break


def fetch_existing_block_cache() -> dict:
    cache = {}
    offset = 0
    page_size = 1000

    while True:
        res = (
            supabase.table("knowledge_base")
            .select("notion_id, notion_block_id, last_notion_edited_at, metadata, embedding")
            .range(offset, offset + page_size - 1)
            .execute()
        )

        data = res.data or []
        if not data:
            break

        for record in data:
            block_id = record.get("notion_block_id")
            metadata = record.get("metadata") or {}
            if not block_id and metadata.get("sync_granularity") == "block":
                block_id = record.get("notion_id")
            if not block_id:
                continue

            cache[block_id] = {
                "last_edited": record.get("last_notion_edited_at"),
                "hash": metadata.get("content_hash", ""),
                "has_embedding": record.get("embedding") is not None,
            }

        if len(data) < page_size:
            break
        offset += page_size

    print(f"[INFO] 预加载块级缓存: {len(cache)} 条")
    return cache


def build_block_content(page_title: str, block_type: str, depth: int, text: str) -> str:
    safe_title = page_title or "Untitled"
    return f"[Context-Page: {safe_title}] [BlockType: {block_type}] [Depth: {depth}] {text}".strip()


def migrate_notion_blocks_incremental() -> dict:
    print(f"[START] 块级增量同步启动 - {time.strftime('%Y-%m-%d %H:%M:%S')}")

    sync_cache = fetch_existing_block_cache()
    stats = {
        "pages_scanned": 0,
        "blocks_scanned": 0,
        "synced": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    next_cursor = None
    while True:
        try:
            search_result = notion.search(start_cursor=next_cursor, page_size=100)
            items = search_result.get("results", [])
            pages = [item for item in items if item.get("object") == "page"]

            for page in pages:
                stats["pages_scanned"] += 1
                page_id = page["id"]
                page_title = extract_page_title(page)
                page_url = page.get("url")

                for block, depth in iterate_blocks_recursively(page_id):
                    stats["blocks_scanned"] += 1

                    block_id = block.get("id")
                    block_type = block.get("type", "unknown")
                    block_text = get_block_plain_text(block)
                    if not block_id or not block_text:
                        continue

                    content = build_block_content(page_title, block_type, depth, block_text)
                    block_last_edited = block.get("last_edited_time") or page.get("last_edited_time")
                    content_hash = calculate_content_hash(content + BLOCK_RAG_VERSION)

                    cached = sync_cache.get(block_id, {})
                    is_update = block_id in sync_cache

                    if (
                        is_update
                        and cached.get("hash") == content_hash
                        and cached.get("last_edited")
                        and block_last_edited
                        and cached["last_edited"][:19] == block_last_edited[:19]
                        and (cached.get("has_embedding") or not EMBEDDING_AVAILABLE)
                    ):
                        stats["skipped"] += 1
                        continue

                    embedding = get_embedding(content)

                    if ENABLE_BLOCK_CLASSIFICATION:
                        analysis = analyze_content(content)
                        if not isinstance(analysis, dict):
                            analysis = {}
                    else:
                        analysis = {}

                    safe_tags = analysis.get("tags")
                    if not isinstance(safe_tags, list):
                        safe_tags = []

                    payload = {
                        "notion_id": block_id,
                        "notion_block_id": block_id,
                        "title": page_title[:250],
                        "content": content,
                        "embedding": embedding,
                        "category": str(analysis.get("category") or "未分类")[:250],
                        "sub_category": str(analysis.get("sub_category") or "")[:250],
                        "project_name": str(analysis.get("project_name") or "")[:250],
                        "project_type": str(analysis.get("project_type") or "")[:250],
                        "tags": safe_tags[:5],
                        "last_notion_edited_at": block_last_edited,
                        "metadata": {
                            "source": "notion_block_incremental",
                            "url": page_url,
                            "parent_page_id": page_id,
                            "parent_page_url": page_url,
                            "block_type": block_type,
                            "block_depth": depth,
                            "sync_granularity": "block",
                            "content_hash": content_hash,
                        },
                    }

                    try:
                        if is_update:
                            supabase.table("knowledge_base").update(payload).eq("notion_id", block_id).execute()
                            stats["updated"] += 1
                        else:
                            supabase.table("knowledge_base").insert(payload).execute()
                            stats["synced"] += 1
                    except Exception as exc:
                        print(f"[WARN] 块同步失败 block={block_id}: {exc}")
                        stats["errors"] += 1
                        continue

                    sync_cache[block_id] = {
                        "last_edited": block_last_edited,
                        "hash": content_hash,
                        "has_embedding": embedding is not None,
                    }

            next_cursor = search_result.get("next_cursor")
            if not next_cursor:
                break
        except Exception as exc:
            print(f"[WARN] Notion 搜索异常: {exc}")
            stats["errors"] += 1
            time.sleep(2)

    print(
        "[DONE] 块级增量同步结束 | "
        f"pages={stats['pages_scanned']} blocks={stats['blocks_scanned']} "
        f"new={stats['synced']} updated={stats['updated']} skipped={stats['skipped']} errors={stats['errors']}"
    )
    return stats


if __name__ == "__main__":
    migrate_notion_blocks_incremental()
