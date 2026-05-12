"""
文件: models/schemas.py | FastAPI 请求/响应模型
作用: 为 FastAPI 提供类型化接口定义，自动生成 OpenAPI 文档
      Pydantic 的 BaseModel 提供运行时数据校验
"""

# ============================================================
# Pydantic 是 FastAPI 的"心脏"——提供类型校验和序列化
# datetime 用于时间戳字段
# ============================================================
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class AnalyzeRequest(BaseModel):
    """
    分析请求体（当前未使用，分析参数通过 Form 传）
    预留用于未来支持更复杂的分析参数
    """
    request: str = "请分析这些文件，总结内容并提取数据"


class AnalyzeResponse(BaseModel):
    """POST /analyze 的响应——异步任务启动确认"""
    task_id: str                    # 任务唯一标识，用于后续查询
    status: str                     # 初始状态："queued"
    estimated_time: str = "30s"     # 预估时间，给用户体验预期
    created_at: str                 # 创建时间 ISO 格式


class TaskStatusResponse(BaseModel):
    """GET /tasks/{id}/status 的响应——用于轮询"""
    task_id: str
    status: str                     # queued/running/completed/failed
    agent_history: list[str] = []   # 已执行的 Agent 列表
    progress: float = 0.0           # 0.0 ~ 1.0 进度值
    errors: list[str] = []          # 错误信息


class TaskResultResponse(BaseModel):
    """GET /tasks/{id}/result 的响应——最终结果"""
    task_id: str
    status: str                     # completed/failed
    summary: Optional[str] = None                # Markdown 总结
    analysis: Optional[dict] = None              # 分析结果
    finetuning: Optional[dict] = None            # 微调分析结果
    document: Optional[dict] = None              # 业务文档分析结果
    report_path: Optional[str] = None            # 报告文件路径
    xlsx_path: Optional[str] = None              # Excel 文件路径
    files: list[dict] = []                       # 文件处理详情
    errors: list[str] = []                       # 错误列表
    duration: Optional[float] = None             # 耗时(秒)


class AgentInfo(BaseModel):
    """GET /agents 的响应——Agent 元信息"""
    name: str               # Agent 名称
    description: str        # 功能描述
    tools: list[str]        # 可用工具列表


class ToolInfo(BaseModel):
    """GET /tools 的响应——工具元信息"""
    name: str               # 工具名称
    description: str        # 功能描述
    parameters: dict        # 参数描述
    agent: str              # 所属 Agent


class ErrorResponse(BaseModel):
    """统一错误响应格式"""
    error: str
    detail: Optional[str] = None
