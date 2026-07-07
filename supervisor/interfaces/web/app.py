"""FastAPI 应用组装 + 前端静态托管 + 启动入口。

分层铁律：交互层只收发。共享的 Database / ProjectManager 挂到 app.state，
路由从中取用。与 TG Bot 各跑各的进程，读写同一份 data.db。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ...config import Config
from ...core.project_manager import ProjectManager
from ...storage import Database
from .api import router as api_router

logger = logging.getLogger(__name__)

# 前端构建产物目录：web/frontend/dist
_FRONTEND_DIST = (
    Path(__file__).resolve().parents[3] / "web" / "frontend" / "dist"
)


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="监督助手 · Web 控制台", docs_url="/api/docs")

    # 共享实例挂 state：与 Bot 同构（各进程各自的连接，SQLite 短连接并发安全）
    db = Database(cfg.db_path)
    app.state.db = db
    app.state.pm = ProjectManager(db)
    app.state.telegram_token = cfg.telegram_token

    app.include_router(api_router)

    # 托管前端：dist 存在则挂静态 + SPA 回退到 index.html
    if _FRONTEND_DIST.is_dir():
        assets = _FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        index_file = _FRONTEND_DIST / "index.html"

        @app.get("/")
        def _index() -> FileResponse:
            return FileResponse(index_file)

        # 其余非 /api 路径回退到 index.html（前端路由预留）
        @app.get("/{full_path:path}")
        def _spa(full_path: str):
            candidate = _FRONTEND_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:
        @app.get("/")
        def _no_frontend() -> dict:
            return {
                "message": "前端还没构建。先 cd web/frontend && npm install && npm run build，"
                           "或开发期用 npm run dev（走 /api 代理）。",
                "api_docs": "/api/docs",
            }

    logger.info("Web 控制台已组装。前端产物: %s (存在=%s)",
                _FRONTEND_DIST, _FRONTEND_DIST.is_dir())
    return app


def run_web(cfg: Config, host: str, port: int) -> None:
    import uvicorn

    app = create_app(cfg)
    logger.info("启动 Web 控制台 http://%s:%d …", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
