"""Agents 包 - 所有 Agent 的注册入口"""
# agents/__init__.py
# 集中导入并导出所有 Agent 类
# 外部使用时只需: from app.agents import PlannerAgent, ParserAgent, ...

from .base import BaseAgent
# BaseAgent 是抽象基类，定义了所有 Agent 的通用接口
# name:        Agent 的唯一标识符（如 "planner"、"parser"）
# description: Agent 的功能描述，用于 Planner 的 LLM Prompt
# tools:       该 Agent 能调用的工具名列表
# execute():   抽象方法，每个 Agent 必须实现

from .planner import PlannerAgent
# PlannerAgent: 任务规划 Agent——分析用户请求和文件，生成 WorkflowPlan
# 工作模式:
#   - LLM 模式（有 API Key）：让 Claude 分析需求，动态生成任务列表
#   - 降级模式（无 API Key）：规则生成固定流程（解析→总结→分析→生成表格）

from .parser_agent import ParserAgent
# ParserAgent: 文件解析 Agent——遍历所有上传文件，调用对应解析工具
# 支持格式: PDF、DOCX、TXT、Markdown、CSV、JSON、XML、YAML、图片（OCR）
# 路由策略: CSV→registry.call_tool()，图片→registry.call_tool()，其他→file_reader

from .summary_agent import SummaryAgent
# SummaryAgent: 内容总结 Agent——将所有解析结果汇总为 Markdown 摘要
# 两种模式:
#   - LLM 模式: Claude 生成有深度的段落式总结
#   - 降级模式: 规则生成统计摘要（字符数、表格数等基本信息）

from .analysis_agent import AnalysisAgent
from .finetuning_agent import FinetuningAgent
# AnalysisAgent: 数据分析 Agent——对结构化数据进行多层分析
# 三层分析:
#   1. 统计分析: 自动识别数值字段，计算均值/中位数/标准差等
#   2. 风险分析: 检测异常值和高风险字段
#   3. LLM 分析: Claude 理解数据的商业含义，生成洞察和建议

from .spreadsheet_agent import SpreadsheetAgent
# SpreadsheetAgent: 电子表格 Agent——从解析结果中提取结构化数据生成 XLSX
# 表格来源:
#   1. 原生表格: 解析器直接提取的表格（如 DOCX 中的表格）
#   2. 管道符表格: 从 Markdown/文本中检测 | A | B | C | 格式并提取
#   3. 未来: LLM 从非结构化文本中提取的表格

from .document_agent import DocumentAgent
# DocumentAgent: 业务文档分析 Agent——分析工单、合同、报告等文档
# 用 LLM 提取结构化字段（单号、负责人、状态、截止日期、优先级、风险等）

__all__ = [
    "BaseAgent",
    "PlannerAgent",
    "ParserAgent",
    "SummaryAgent",
    "AnalysisAgent",
    "FinetuningAgent",
    "SpreadsheetAgent",
    "DocumentAgent",
]
# 显式导出所有 Agent 类，明确包的公开 API
# 新增 Agent 时需要同时在此处添加导出
