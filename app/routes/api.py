"""FastAPI REST API 路由 - 提供 RESTful 接口"""
# routes/api.py
# 这个文件定义了系统的 REST API 接口
# 用户通过 HTTP 请求与系统交互: 上传文件、启动分析、查询状态、下载结果
#
# API 设计原则:
# 1. RESTful 风格——资源（文件、任务）通过 URL 路径标识
# 2. 异步非阻塞——文件上传和长时间分析都用 async/await
# 3. 任务队列模式——上传和启动立即返回 task_id，客户端轮询结果
# 4. 统一错误格式——所有错误都通过 ErrorResponse 模型返回
#
# 端点一览:
#   GET  /api/v1/agents           — 列出所有可用 Agent
#   GET  /api/v1/tools            — 列出所有可用 Tool
#   POST /api/v1/upload           — 上传文件
#   POST /api/v1/analyze          — 启动分析工作流
#   GET  /api/v1/tasks/{id}/status — 查询任务状态
#   GET  /api/v1/tasks/{id}/result — 获取任务结果
#   GET  /api/v1/output/{filename} — 下载输出文件
#   GET  /api/v1/tasks            — 列出所有任务

import os
# 操作系统接口——检查文件存在、创建目录等

import shutil
# 高级文件操作——但我们没有使用，保留以备将来可能需要复制/移动文件

import uuid
# 通用唯一标识符——生成 task_id 和 file_id
# uuid.uuid4().hex 生成 32 位十六进制字符串，如 "a1b2c3d4e5f6..."

import asyncio
# 异步 I/O 库——提供 asyncio.create_task() 用于后台执行工作流
# 这样 API 请求不会阻塞——用户提交任务后立即收到响应

from datetime import datetime
# 日期时间——给任务和文件打时间戳

from pathlib import Path
# 跨平台路径处理——比 os.path 更现代、更安全
# Path("/foo/bar") / "file.txt" — 自动处理路径分隔符

from typing import Optional
# 可选类型标注——FastAPI 自动处理 Optional 参数的校验

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
# APIRouter:     FastAPI 路由分组工具——可以在不同文件中定义路由，最后合并
# UploadFile:    FastAPI 的文件上传类型——异步读取文件内容
# File:          文件参数的依赖注入标记
# Form:          表单参数的依赖注入标记（analyze 接口的 request 和 file_ids 是表单字段）
# HTTPException: FastAPI 的 HTTP 错误响应——返回状态码和错误信息

from fastapi.responses import FileResponse
# FileResponse: FastAPI 的文件下载响应——自动设置 Content-Type 和 Content-Disposition

from app.config import UPLOAD_DIR, OUTPUT_DIR, SUPPORTED_EXTENSIONS, API_PREFIX
# UPLOAD_DIR:       上传文件的存储目录（配置为 "uploads/"）
# OUTPUT_DIR:       输出文件的存储目录（配置为 "output/"）
# SUPPORTED_EXTENSIONS: 支持的文件扩展名映射 {".pdf": "pdf", ".docx": "docx", ...}
# API_PREFIX:       API 路由前缀（配置为 "/api/v1"）

from app.models.state import FileInfo
# FileInfo: 文件信息模型（filename, file_path, file_type, size）
# 用于从上传的文件元数据构造 FileInfo 对象，传给工作流

from app.models.schemas import (
    AnalyzeResponse, TaskStatusResponse, TaskResultResponse,
    AgentInfo, ToolInfo, ErrorResponse,
)
# 所有 Pydantic 响应模型
# AnalyzeResponse:    启动分析后的立即响应（task_id, status, estimated_time）
# TaskStatusResponse: 任务状态查询响应（task_id, status, agent_history, progress, errors）
# TaskResultResponse: 任务结果响应（含 summary, analysis, report_path, xlsx_path 等）
# AgentInfo:          Agent 信息（name, description, tools）
# ToolInfo:           工具信息（name, description, parameters, agent）
# ErrorResponse:      错误格式

from app.orchestrator.workflow import run_workflow
# run_workflow: 异步函数，启动 LangGraph 工作流
# 接收 files, user_request, session_id → 返回完整结果字典

from app.tools.registry import registry
# registry: ToolRegistry 单例——可以列出所有已注册的工具
# 用于 GET /tools 接口

# ========= 创建路由 =========
router = APIRouter(prefix=API_PREFIX)
# 创建一个路由实例，所有端点的路径都会自动添加 API_PREFIX 前缀
# 例如: 定义 @router.get("/agents") → 实际路径是 /api/v1/agents
# 这样做的优点:
#   1. 版本控制——/api/v1/ 表示这是 API 的第一版
#   2. 路由分组——方便统一修改前缀
#   3. 与 main.py 解耦——prefix 定义在 config.py 中

# ========= 内存任务存储 =========
# task_id -> {state, result, ...}
_task_store: dict = {}
# 内存中的任务字典（任务数据库）
# 为什么不使用真正的数据库？
#   1. 本地工具场景，没有多用户并发访问
#   2. 任务信息时短暂的——完成后用户很快就会获取结果
#   3. 简化部署——不需要配置数据库
# 这是在 简单性 和 可靠性 之间的权衡
# 如果服务器重启，内存中的任务信息会丢失
# 生产环境可以用 Redis 或 SQLite 替代

# ========= Agent 注册信息 =========
# 用于 GET /agents 接口
# 这个列表是静态定义的（不是从 Agent 代码中动态检测的）
# 这样做的好处:
#   1. 可以在描述中提供更友好的中文解释
#   2. 可以在不修改 Agent 代码的情况下调整描述
#   3. 稳定可靠——不会因为 import 错误导致 Agent 列表为空
# 坏处: 新增 Agent 时需要同时更新这个列表
_agent_registry = [
    {
        "name": "planner",
        "description": "分析请求并规划任务分配",
        "tools": [],
        # Planner 不直接使用工具，它只做规划
    },
    {
        "name": "parser",
        "description": "解析各种文件格式（PDF、DOCX、TXT、CSV、图片等）",
        "tools": [t.name for t in registry.get_tools_for("parser")],
        # 从 ToolRegistry 中查询 parser 可以使用的工具列表
        # 包括: read_pdf, read_docx, read_txt, read_md, read_csv, read_json, read_xml, ocr_image
    },
    {
        "name": "summary",
        "description": "总结文件内容并生成 Markdown 摘要",
        "tools": [t.name for t in registry.get_tools_for("summary")],
        # summary 只使用 write_markdown 工具
    },
    {
        "name": "analysis",
        "description": "数据统计、风险、趋势分析",
        "tools": [t.name for t in registry.get_tools_for("analysis")],
        # analysis 使用 analyze_statistics, risk_analysis, trend_analysis, write_markdown
    },
    {
        "name": "spreadsheet",
        "description": "提取结构化数据并生成 XLSX",
        "tools": [t.name for t in registry.get_tools_for("spreadsheet")],
        # spreadsheet 只使用 generate_xlsx 工具
    },
    {
        "name": "finetuning",
        "description": "微调数据分析 — 分析训练指标、loss、评估结果",
        "tools": [t.name for t in registry.get_tools_for("finetuning")],
        # finetuning 使用 extract_training_metrics, write_markdown
    },
    {
        "name": "document",
        "description": "业务文档分析 — 分析工单、合同、报告等，提取结构化字段和关键发现",
        "tools": [t.name for t in registry.get_tools_for("document")],
        # document 使用 write_markdown
    },
]


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents():
    """列出所有可用 Agent"""
    # 返回系统中的所有 Agent 信息
    # 用户通过这个端点了解系统有哪些能力
    # 也可以用于前端动态展示 Agent 列表
    return _agent_registry
    # FastAPI 自动将列表转换为 JSON 数组
    # 每个元素符合 AgentInfo schema


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools():
    """列出所有可用 Tool"""
    # 返回系统中所有已注册的工具信息
    # 注意: 工具必须通过 tools/__init__.py 的导入触发注册
    # 如果某些工具没有 import，它们不会出现在列表中

    tools = registry.list_tools()
    # registry.list_tools() 返回 list[ToolDefinition]
    # ToolDefinition 包含: name, description, parameters, agent, function

    return [
        ToolInfo(
            name=t.name,
            # 工具名，如 "read_pdf"、"generate_xlsx"

            description=t.description,
            # 工具功能描述

            parameters=t.parameters,
            # 参数模式（JSON Schema 格式）
            # 用于自动生成 API 文档和参数校验

            agent=t.agent,
            # 所属 Agent 名称
        )
        for t in tools
    ]
    # 将 ToolDefinition 转换为 ToolInfo（Pydantic 模型）
    # FastAPI 自动进行 JSON 序列化和 schema 验证


@router.post("/upload", status_code=201)
async def upload_files(files: list[UploadFile] = File(...)):
    """上传文件（支持多文件）"""
    # 用户上传一个或多个文件
    # 文件被保存到 UPLOAD_DIR 目录，返回文件元信息
    # 客户端拿到返回的 file_id，然后在 /analyze 接口中使用

    # 确保上传目录存在
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # exist_ok=True: 如果目录已存在，不报错
    # 如果目录不存在，自动创建（包括父目录）

    uploaded = []
    # 成功上传的文件列表

    errors = []
    # 上传失败的文件列表（含错误原因）

    for file in files:
        # 遍历每个上传文件
        ext = Path(file.filename).suffix.lower()
        # 获取文件扩展名（小写）
        # Path("报告.pdf").suffix → ".pdf"
        # Path("Data.CSV").suffix → ".csv"（注意小写转换）

        if ext not in SUPPORTED_EXTENSIONS:
            # 检查扩展名是否在支持列表中
            # SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx", ".csv": "csv", ...}
            errors.append({"filename": file.filename, "error": f"不支持的文件类型: {ext}"})
            continue
            # 不支持的类型跳过，不中断整个上传

        file_id = f"{uuid.uuid4().hex}{ext}"
        # 生成唯一文件名
        # 使用 uuid 避免文件名冲突
        # 保留原始扩展名（如 ".pdf"）
        # 示例: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.pdf"

        save_path = UPLOAD_DIR / file_id
        # 完整的保存路径
        # UPLOAD_DIR = Path("uploads")
        # pathlib 的 / 运算符: Path("uploads") / "a1b2...pdf" → Path("uploads/a1b2...pdf")

        try:
            content = await file.read()
            # 异步读取上传文件内容到内存
            # 对于大文件，这可能会消耗较多内存
            # 生产环境应该用流式写入或分块读取

            with open(save_path, "wb") as f:
                f.write(content)
            # 以二进制写入模式打开文件
            # 所有文件类型都以二进制写入（包括文本文件）——避免编码问题

            uploaded.append({
                "filename": file.filename,
                # 原始文件名（用户上传时显示的名称）
                # 在 result 接口的 files 列表中会用到

                "file_id": file_id,
                # 由 uuid 生成的文件唯一标识
                # 客户端在 /analyze 接口中通过 file_ids 参数引用这个文件

                "file_path": str(save_path),
                # 文件在服务器上的实际路径

                "file_type": SUPPORTED_EXTENSIONS[ext],
                # 文件内部类型（'pdf', 'docx', 'csv' 等）
                # 用于 Parser 选择对应的解析工具

                "size": len(content),
                # 文件大小（字节）
            })
        except Exception as e:
            # 捕获所有可能的异常（磁盘满、权限不足等）
            errors.append({"filename": file.filename, "error": str(e)})

    return {"uploaded": uploaded, "errors": errors, "count": len(uploaded)}
    # 返回上传结果
    # uploaded: 成功列表
    # errors: 失败列表
    # count: 成功数量


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_files(
    request: str = Form("请分析这些文件，总结内容并提取数据"),
    # 用户的分析需求，从表单字段获取
    # 默认值: "请分析这些文件，总结内容并提取数据"
    # 可选参数——不传时使用默认值

    file_ids: str = Form(""),
    # 文件的 UUID 标识（上传时返回的 file_id），逗号分隔
    # 例如: "a1b2c3d4.pdf,e5f6a7b8.csv"
    # 从表单字段获取（不是 JSON body）
):
    """启动分析工作流（需要先上传文件获取 file_ids）"""
    # 用户上传文件后，调用这个接口启动分析

    if not file_ids:
        # 没有提供 file_ids → 400 错误
        raise HTTPException(status_code=400, detail="请提供 file_ids（逗号分隔的上传文件 ID）")

    ids = [f.strip() for f in file_ids.split(",") if f.strip()]
    # 将逗号分隔的字符串拆分为列表
    # 同时过滤掉空字符串（两个逗号之间的空内容）
    # 例如: "a.pdf,,b.csv" → ["a.pdf", "b.csv"]

    files = []
    for fid in ids:
        # 根据 file_id 从上传目录查找文件
        fpath = UPLOAD_DIR / fid
        if not fpath.exists():
            # 文件未找到 → 404 错误
            raise HTTPException(status_code=404, detail=f"文件未找到: {fid}")

        ext = fpath.suffix.lower()
        # 获取文件扩展名

        files.append(FileInfo(
            filename=fid,
            # 注意: 这里 filename 存的是 file_id（uuid 生成的文件名）
            # 原始文件名在 upload 的返回值中
            # 这是一个设计上的妥协——为了在 result 接口中能找到文件

            file_path=str(fpath),
            # 文件在服务器上的绝对路径

            file_type=SUPPORTED_EXTENSIONS.get(ext, "text"),
            # 根据扩展名映射文件类型
            # get() 的默认值是 "text"——未知类型作为纯文本处理

            size=fpath.stat().st_size,
            # 文件大小（字节）
            # st_size 是 os.stat 返回的文件大小字段
        ))

    task_id = uuid.uuid4().hex
    # 生成唯一的任务 ID
    # 客户端通过这个 ID 查询任务状态和结果

    now = datetime.now().isoformat()
    # 记录任务创建时间
    # isoformat() → "2026-05-11T12:34:56.789"

    _task_store[task_id] = {
        "status": "queued",
        # 初始状态: 队列中等待执行

        "created_at": now,
        # 创建时间

        "files": files,
        # 要分析的文件列表

        "user_request": request,
        # 用户的分析需求

        "result": None,
        # 结果（工作流执行完成后填充）
    }

    # 异步启动工作流
    asyncio.create_task(_run_workflow_background(task_id, files, request))
    # asyncio.create_task() 创建一个后台协程任务
    # 这个任务会在事件循环中运行，不阻塞当前请求
    # 效果: 用户立即收到 202 响应，工作流在后台执行
    #
    # 为什么不直接 await run_workflow()？
    # 如果直接 await，HTTP 请求会一直挂起到工作流完成
    # 对于长时间运行的任务（几十秒），HTTP 连接会超时
    # 所以采用"立即返回 task_id，客户端轮询"的模式
    #
    # 潜在问题:
    # 如果工作流内发生未捕获异常，asyncio.create_task 会静默吞掉异常
    # 需要确保节点函数内部的异常都被捕获并写入 state["errors"]

    return AnalyzeResponse(
        task_id=task_id,
        status="queued",
        estimated_time="30s",
        # 预估执行时间（硬编码）
        # 实际时间取决于文件数量、大小、网络请求速度等

        created_at=now,
    )
    # 返回任务信息，客户端立即收到响应


async def _run_workflow_background(task_id: str, files: list[FileInfo], request: str):
    """后台运行工作流"""
    # 这是 asyncio.create_task 的目标函数
    # 在后台执行工作流，完成后更新 _task_store
    #
    # 注意: 函数名以下划线开头，表示"内部函数，外部不应直接调用"
    # 类型注解: task_id 是 str，files 是 FileInfo 列表，request 是 str

    task = _task_store[task_id]
    # 获取任务记录（引用，不是副本）
    # 后续的修改会直接反映到 _task_store 中

    try:
        task["status"] = "running"
        # 更新状态为"运行中"
        # 客户端可以通过 GET /tasks/{id}/status 看到这个状态变化

        result = await run_workflow(files, request, task_id)
        # 调用 workflow.py 的 run_workflow 函数
        # 这会在 LangGraph 引擎中执行完整工作流（7 个节点）
        # 这是一个长时间的异步操作（可能是几十秒）
        #
        # run_workflow 内部:
        #   1. create_workflow() — 构建 StateGraph
        #   2. 构造初始状态
        #   3. graph.ainvoke(initial_state) — 执行整个图
        #   4. 返回最终状态（含所有结果）

        task["status"] = "completed"
        # 工作流完成 → 更新状态

        task["result"] = result
        # 保存完整的工作流执行结果
        # 包括 parsed_contents, summary, analysis_result, report_path, xlsx_path 等

    except Exception as e:
        # 工作流执行过程中发生未捕获异常
        # 所有节点函数内部的异常应该已经在节点中被捕获
        # 这里的异常通常是图结构问题或系统级错误

        task["status"] = "failed"
        # 更新状态为"失败"

        task["result"] = {"errors": [str(e)]}
        # 保存错误信息
        # 客户端通过 GET /tasks/{id}/result 可以看到错误详情


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态"""
    # 客户端轮询这个端点来检查任务进度
    # 轮询频率建议: 每 2-3 秒一次
    #
    # 返回:
    #   - task_id: 任务 ID
    #   - status: queued / running / completed / failed
    #   - agent_history: 已执行的 Agent 列表
    #   - progress: 进度（0.0 ~ 1.0）
    #   - errors: 错误列表

    task = _task_store.get(task_id)
    # 从内存任务字典中查找
    # .get() 返回 None 如果 task_id 不存在

    if not task:
        # 任务不存在 → 404
        raise HTTPException(status_code=404, detail="任务不存在")

    result = task.get("result") or {}
    # 获取任务结果（可能还没完成，结果为 None）
    # 如果 result 为 None，使用空字典

    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        # 当前状态: queued / running / completed / failed

        agent_history=result.get("agent_history", []),
        # 已执行的 Agent 历史
        # 例如: ["planner", "parser", "summary", "analysis"]
        # 仅在结果已生成时可用

        progress=(
            0.5 if task["status"] == "running"
            else (1.0 if task["status"] == "completed" else 0.0)
        ),
        # 进度估算:
        #   queued:    0.0（尚未开始）
        #   running:   0.5（已经开始了，粗略估计）
        #   completed: 1.0（全部完成）
        #   failed:    0.0（失败）
        # 注意: 这是一个粗略估算，没有精确到具体节点
        # 更精确的做法: 根据 agent_history 的长度 / 总节点数

        errors=result.get("errors", []),
        # 错误列表（如果有）
    )


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(task_id: str):
    """获取分析结果"""
    # 在任务状态变为 completed 后，调用这个端点获取完整结果
    # 如果任务尚未完成，返回 400 错误

    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] != "completed":
        # 任务尚未完成，不允许获取结果
        raise HTTPException(
            status_code=400,
            detail=f"任务尚未完成，当前状态: {task['status']}"
        )
        # 客户端应该先轮询 status 端点，等状态为 completed 后再获取结果

    result = task.get("result") or {}
    # 获取工作流执行结果

    parsed = result.get("parsed_contents", {})
    # 获取解析内容——用于构造 files 信息列表
    # parsed 是 {filename: ParsedContent} 格式

    files_info = [
        {
            "filename": fn,
            # 文件名

            "char_count": len(c.text) if hasattr(c, "text") else 0,
            # 文本长度（字符数）
            # 用 hasattr 检查（兼容可能的非标准对象）

            "tables": len(c.tables) if hasattr(c, "tables") else 0,
            # 表格数量
        }
        for fn, c in parsed.items()
    ]
    # 生成每个文件的摘要信息
    # 不返回完整文本内容（可能很大），只返回统计

    return TaskResultResponse(
        task_id=task_id,
        status="completed",

        summary=result.get("summary", ""),
        # Markdown 格式的总结文本

        analysis=result.get("analysis_result", {}),
        # 分析结果（统计分析 + 风险分析 + LLM 分析）

        finetuning=result.get("finetuning_result"),
        # 微调分析结果（训练指标 + LLM 评估）

        document=result.get("document_result"),
        # 业务文档分析结果（结构化字段 + 关键发现）

        report_path=result.get("report_path", ""),
        # 最终报告的文件路径
        # 客户端可以用这个路径调用 GET /output/{filename}

        xlsx_path=result.get("xlsx_path"),
        # Excel 文件路径（如果没有表格数据，为 None）

        files=files_info,
        # 文件摘要信息列表

        errors=result.get("errors", []),
        # 错误列表

        duration=task.get("duration"),
        # 执行耗时（秒）
        # 注意: _task_store 中目前没有设置 duration 字段
        # 这是一个"可扩展"字段，未来可以记录
    )


@router.get("/output/{filename}")
async def download_output(filename: str):
    """下载输出文件"""
    # 用户可以通过这个端点下载生成的报告或 Excel 文件
    # 文件路径: OUTPUT_DIR / filename
    # 例如: GET /api/v1/output/final_report.md

    file_path = OUTPUT_DIR / filename
    # 使用 pathlib 拼接路径
    # OUTPUT_DIR = Path("output")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
        # 文件不存在（可能是被删除或未生成）

    return FileResponse(str(file_path), filename=filename)
    # FileResponse: FastAPI 提供的文件下载响应
    # 自动设置:
    #   - Content-Type: 根据文件扩展名（text/markdown, application/vnd.openxmlformats...）
    #   - Content-Disposition: attachment（触发浏览器下载）
    #   - Content-Length: 文件大小


@router.get("/tasks")
async def list_tasks():
    """列出所有任务"""
    # 返回所有任务的基本信息（不包含结果的详细信息）
    # 这相当于"任务列表"视图

    return [
        {
            "task_id": tid,
            # 任务 ID

            "status": t["status"],
            # 任务状态

            "created_at": t["created_at"],
            # 创建时间

            "file_count": len(t.get("files", [])),
            # 文件数量
        }
        for tid, t in _task_store.items()
    ]
    # 遍历 _task_store 中的所有任务
    # 每个任务只返回基本信息，不返回完整的 result
