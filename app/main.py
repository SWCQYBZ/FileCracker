"""FastAPI 应用入口 - 多智能体文件分析系统的主入口"""
# main.py
# 这个文件是系统的"大门"——启动 FastAPI 应用，配置中间件，注册路由
#
# 启动方式:
#   1. 直接运行: python -m app.main
#   2. uvicorn 运行: uvicorn app.main:app
#
# 加载顺序:
#   python app/main.py
#     → from app.config import ...    （加载配置）
#     → from app.routes.api import ...（加载路由——会触发 tools 注册）
#     → FastAPI()                     （创建应用实例）
#     → app.add_middleware(...)       （配置 CORS）
#     → app.include_router(...)       （注册路由）
#     → uvicorn.run(app, ...)        （启动 HTTP 服务器）

import os
import threading
import time
import shutil

import uvicorn
# ASGI 服务器——运行 FastAPI 应用
# uvicorn 是一个高性能的异步 HTTP 服务器
# 基于 uvloop 和 httptools（和 Node.js 的 libuv 类似）

from pathlib import Path
# 跨平台路径处理——用于路径拼接
# 虽然在 main.py 中没有直接使用，但 imports 保留了以备开发

from fastapi import FastAPI
# FastAPI: 高性能异步 Web 框架
# 基于 Starlette + Pydantic
# 特点:
#   1. 自动生成 OpenAPI 文档（/docs）
#   2. 请求/响应自动校验（通过 Pydantic）
#   3. 原生异步支持（async/await）

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
# CORS 中间件: 跨域资源共享
# 允许来自不同域名的前端页面访问这个 API
# 如果不配置 CORS，浏览器的同源策略会阻止前端 JS 调用 API
# 在本地开发或前后端分离时必须配置

from app.config import API_HOST, API_PORT, STATIC_DIR, UPLOAD_DIR
# API_HOST: 绑定的主机地址（默认 "0.0.0.0" — 所有网络接口）
# API_PORT: 绑定的端口（默认 8000）
# 从 config.py 读取，config.py 从环境变量或默认值获取

from app.routes.api import router
# 导入 API 路由
# 注意: 这个 import 会触发 tools/__init__.py 的加载
# 因为 routes/api.py 中 import 了 registry 和其他模块
# 而 tools/__init__.py 中 import 了所有工具模块（触发注册）
# 所以所有工具在 app 启动时就已经注册完毕

# ========= 创建 FastAPI 应用 =========
app = FastAPI(
    title="多智能体文件分析系统",
    # API 标题（显示在 /docs 页面上）

    description="Multi-Agent File Analysis System - 基于 LangGraph + Claude API",
    # API 描述（显示在 /docs 页面上）

    version="1.0.0",
    # 版本号
)
# app 是 FastAPI 应用实例（全局单例）
# 这个实例会被 uvicorn 加载: uvicorn app.main:app

# ========= 配置 CORS 中间件 =========
# CORS（跨域资源共享）允许前端页面从不同域名访问 API
# 在生产环境中应该限制 allow_origins 为特定的前端域名
app.add_middleware(
    CORSMiddleware,
    # Starlette 的 CORS 中间件

    allow_origins=["*"],
    # 允许的来源域名
    # ["*"] = 允许所有域名（开发环境方便）
    # 生产环境应该限制为具体域名，如 ["https://myapp.com"]
    # 安全风险: 如果设置 ["*"]，任何网站都可以通过浏览器调用这个 API

    allow_credentials=True,
    # 允许携带凭据（Cookie、Authorization 头等）

    allow_methods=["*"],
    # 允许的 HTTP 方法
    # ["*"] = 允许所有方法（GET, POST, PUT, DELETE, OPTIONS 等）

    allow_headers=["*"],
    # 允许的 HTTP 请求头
    # ["*"] = 允许所有请求头
)

# ========= 注册路由 =========
app.include_router(router)
# 将 api.py 中定义的所有路由注册到 FastAPI 应用
# router 的 prefix 是 "/api/v1"
# 所以所有路由都是 /api/v1/xxx
# 例如: GET /api/v1/agents, POST /api/v1/upload 等

# ========= 健康检查和欢迎页 =========

@app.get("/")
async def root():
    """Serve the SPA frontend"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {
        "service": "多智能体文件分析系统",
        "version": "1.0.0",
        "endpoints": {
            "agents": "/api/v1/agents",
            "tools": "/api/v1/tools",
            "upload": "/api/v1/upload",
            "analyze": "/api/v1/analyze",
            "tasks": "/api/v1/tasks",
        },
    }


@app.get("/health")
async def health():
    """健康检查端点 — 用于监控和负载均衡"""
    api_key_ok = bool(os.environ.get("DEEPSEEK_API_KEY", ""))
    return {
        "status": "healthy",
        "deepseek_api": "configured" if api_key_ok else "not configured",
    }


# ========= 定时清理上传文件 =========
def _start_cleanup_scheduler():
    """启动后台线程，每12小时清理一次 uploads 目录"""
    def cleanup_loop():
        while True:
            time.sleep(12 * 60 * 60)  # 12小时
            if UPLOAD_DIR.exists():
                shutil.rmtree(UPLOAD_DIR)
                UPLOAD_DIR.mkdir(exist_ok=True)
                print(f"[Cleanup] 上传目录已清理: {UPLOAD_DIR}")

    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    print(f"[Cleanup] 定时清理已启动，每12小时清理一次 uploads 目录")


_start_cleanup_scheduler()


def main():
    """启动服务"""
    # 直接运行 app/main.py 时的入口函数
    # 输出启动信息并启动 uvicorn 服务器

    print("=" * 60)
    # 输出分隔线（60 个等号）

    print("  [AI] 多智能体文件分析系统")
    # 服务名称

    print(f"  [HTTP] http://{API_HOST}:{API_PORT}")
    # 服务地址（用户通过这个地址访问 API）

    print(f"  [DOCS] http://{API_HOST}:{API_PORT}/docs")
    # API 文档地址（FastAPI 自动生成的 OpenAPI 文档）
    # 在浏览器中打开可以看到所有端点的详细说明

    print("=" * 60)
    # 分隔线

    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")
    # 启动 uvicorn 服务器
    # app: FastAPI 应用实例
    # host: 绑定的 IP（0.0.0.0 = 所有网卡）
    # port: 端口号
    # log_level: 日志级别（"info" = 记录请求信息和错误）
    #
    # uvicorn.run() 会阻塞当前线程，直到服务器停止


if __name__ == "__main__":
    # Python 标准惯用法:
    # 当直接运行 python app/main.py 时，__name__ == "__main__"
    # 当被 import 时（from app.main import app），__name__ != "__main__"
    # 所以 uvicorn.run() 只会在直接运行时执行
    # 如果通过 uvicorn app.main:app 启动，不会执行这里的代码

    main()
    # 调用 main 函数启动服务
