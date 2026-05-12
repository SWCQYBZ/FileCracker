"""
文件: models/state.py | LangGraph Workflow State 定义
核心概念: State 是贯穿整个工作流的"数据总线"
        每个 Node 从 State 读数据，往 State 写数据
        LangGraph 确保 State 的一致性和并发安全
"""

# ============================================================
# 类型系统导入
# TypedDict: Python 的类型化字典，LangGraph 用它定义 State 结构
# Annotated: 带元数据的类型标注，用于告诉 LangGraph 如何合并字段
# operator: Python 操作符模块，提供 add 等函数用于字段合并策略
# ============================================================
from typing import TypedDict, Annotated, Optional, Any
import operator
from pydantic import BaseModel  # Pydantic 提供运行时数据校验


class FileInfo(BaseModel):
    """
    用户上传文件的元信息
    使用 BaseModel 而非 TypedDict: FastAPI 需要 Pydantic 模型做参数校验
    """
    filename: str     # 文件名（上传时的原始文件名）
    file_path: str    # 文件在服务器上的绝对路径
    file_type: str    # 内部类型标识（来自 config.py 的映射）
    size: int         # 文件大小（字节）


class ParsedContent(BaseModel):
    """
    文件解析结果的标准格式
    所有解析器无论输入格式(PDF/DOCX/CSV...)，都输出这个结构
    这就是"统一接口"模式——后续 Agent 不用关心源文件格式
    """
    text: str = ""          # 提取的纯文本内容
    tables: list = []       # 提取的表格数据，每项是二维数组 [[行1], [行2]]
    metadata: dict = {}     # 元数据（页数、作者、编码等）


class WorkflowPlan(BaseModel):
    """
    Planner Agent 输出的任务计划
    决定了: 谁(agent)用什么工具(tool)做什么(params)
    """
    tasks: list[dict] = []       # 任务列表，顺序执行
    parallel_groups: list[list[str]] = []  # 可并行的任务组
    reasoning: str = ""          # Planner 的推理过程（用于调试）


class TaskResult(BaseModel):
    """单个任务执行结果（预留，当前未使用）"""
    task_id: str = ""
    agent: str = ""
    tool: str = ""
    success: bool = False
    data: Any = None
    error: Optional[str] = None


class WorkflowState(TypedDict):
    """
    LangGraph StateGraph 的状态定义
    这是整个工作流的核心数据结构

    字段合并策略:
    - 普通字段: 后一个写覆盖前一个(只允顺序写入)
    - Annotated[list, operator.add]: 多个 Node 可以同时追加(支持并行写入)
    """
    # === 输入字段（由 API 层填充） ===
    session_id: str              # 工作流唯一标识
    files: list[FileInfo]        # 要处理的文件列表
    user_request: str            # 用户的自然语言需求

    # === Planner 输出 ===
    plan: Optional[WorkflowPlan]  # 任务计划
    current_task_index: int       # 当前执行索引（预留）
    task_results: Annotated[dict, {}]  # 任务结果累积（预留）

    # === 逐步累积的处理结果 ===
    parsed_contents: Annotated[dict[str, ParsedContent], {}]
    # 键: 文件名，值: 解析结果
    # Annotated 的 {} 是默认空 dict

    summary: Optional[str]         # 内容总结
    analysis_result: Optional[dict]  # 分析结果
    finetuning_result: Optional[dict]  # 微调分析结果
    document_result: Optional[dict]  # 业务文档分析结果
    xlsx_path: Optional[str]       # 生成的 Excel 路径
    report_path: Optional[str]     # 生成的报告路径

    # === 控制字段 ===
    errors: Annotated[list[str], operator.add]
    # 关键设计: operator.add 让多个并行 Node 都能追加错误
    # 如果不这样，并行写同一个字段会冲突

    agent_history: Annotated[list[str], operator.add]
    # Agent 执行历史，同样支持并行追加

    status: str  # running / planning_completed / parsing_completed /
                 # parallel_completed / completed / failed
