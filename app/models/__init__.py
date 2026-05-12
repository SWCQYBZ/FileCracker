"""Models 包 - 数据模型定义"""
# models/__init__.py
# 集中导出所有数据模型，外部只需 from app.models import XXX
# 这样做的好处:
#   1. 调用方无需关心模型具体在哪个文件中定义
#   2. 可以在不修改调用方代码的情况下重构模型文件结构
#   3. __all__ 明确了公开 API 边界

from .state import FileInfo, ParsedContent, WorkflowPlan, TaskResult, WorkflowState
# state.py 定义了工作流相关的内部模型
# FileInfo:       上传文件的基本信息（文件名、路径、类型、大小）
# ParsedContent:  文件解析结果的统一格式（text + tables + metadata）
# WorkflowPlan:   Planner 输出的任务计划
# TaskResult:     单个任务的执行结果
# WorkflowState:  LangGraph State 的类型定义（TypedDict）

from .schemas import (
    AnalyzeRequest, AnalyzeResponse,
    TaskStatusResponse, TaskResultResponse,
    AgentInfo, ToolInfo, ErrorResponse,
)
# schemas.py 定义了 FastAPI 接口的请求/响应模型（Pydantic）
# AnalyzeRequest/Response:    上传+分析的请求和响应格式
# TaskStatusResponse:         任务状态查询的响应
# TaskResultResponse:         任务结果的响应（含总结、分析、文件路径）
# AgentInfo/ToolInfo:         Agent/Tool 列表的响应格式
# ErrorResponse:              统一错误格式

__all__ = [
    "FileInfo", "ParsedContent", "WorkflowPlan", "TaskResult", "WorkflowState",
    "AnalyzeRequest", "AnalyzeResponse",
    "TaskStatusResponse", "TaskResultResponse",
    "AgentInfo", "ToolInfo", "ErrorResponse",
]
# 显式列出所有公开导出的模型名称
# 不加 __all__ 也可以工作，但显式声明可以让开发者一目了然
