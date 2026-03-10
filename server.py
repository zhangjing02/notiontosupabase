import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from ingest_notion import migrate_notion_to_supabase

app = FastAPI(title="Notion to Supabase Portal API")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 同步锁，防止重复触发
class SyncStatus:
    def __init__(self):
        self.is_running = False
        self.last_result = None
        self.lock = asyncio.Lock()

sync_manager = SyncStatus()

class SyncResponse(BaseModel):
    status: str
    message: str
    data: dict = None

@app.post("/api/sync", response_model=SyncResponse)
async def trigger_sync():
    async with sync_manager.lock:
        if sync_manager.is_running:
            return SyncResponse(status="error", message="同步任务正在运行中，请稍后再试")
        
        sync_manager.is_running = True
    
    try:
        # 在此处调用同步逻辑
        # 注意：由于 ingest_notion 是同步阻塞的，在生产环境下建议放入 run_in_executor
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, migrate_notion_to_supabase)
        
        sync_manager.last_result = stats
        return SyncResponse(status="success", message="同步完成", data=stats)
    except Exception as e:
        return SyncResponse(status="error", message=f"同步失败: {str(e)}")
    finally:
        async with sync_manager.lock:
            sync_manager.is_running = False

@app.get("/api/sync/status")
async def get_sync_status():
    return {
        "is_running": sync_manager.is_running,
        "last_result": sync_manager.last_result
    }

# 静态文件服务 (仅在 portal/dist 存在时)
dist_path = os.path.join(os.path.dirname(__file__), "portal", "dist")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
