import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def check_progress():
    # 1. 获取总记录数
    res = supabase.table("knowledge_base").select("id", count="exact").execute()
    total_count = res.count
    print(f"Total rows in knowledge_base: {total_count}\n")

    # 2. 获取分类分布
    res_cats = supabase.table("knowledge_base").select("category").execute()
    categories = [row["category"] for row in res_cats.data]
    
    dist = {}
    for cat in categories:
        dist[cat] = dist.get(cat, 0) + 1
    
    print("Category Distribution:")
    # 按数量排序输出
    sorted_dist = sorted(dist.items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_dist:
        print(f"- {cat}: {count}")

if __name__ == "__main__":
    check_progress()
