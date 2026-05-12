"""Tools 包 - 导入所有工具模块以触发注册"""
# tools/__init__.py
# 这个文件是整个工具系统的关键——它确保所有工具模块的注册代码被执行
#
# 设计思路:
# 每个工具模块（如 file_reader.py）在模块级别调用 registry.register()
# 但 Python 的模块级代码只在 import 时执行一次
# 所以在包入口统一 import 所有工具模块，确保注册发生
#
# 如果不这样做:
#   1. 工具模块永远不会被 import → 注册不会发生
#   2. Agent 调用 registry.call_tool("read_pdf") → 报错"工具不存在"
# 这是之前的 Bug 原因，修复方案就是在这里统一导入

from .registry import ToolRegistry, ToolDefinition, ToolResult
# 从 registry 模块导入核心类
# ToolRegistry:   工具注册中心（单例模式），管理所有工具的注册和调用
# ToolDefinition: 工具元数据定义（名称、描述、参数模式、所属 Agent）
# ToolResult:     工具调用结果的标准格式（success + data + error + metadata）

# 导入所有工具模块（触发模块级 registry.register()）
# 每个 import 都会执行被导入模块的顶层代码
# 每个模块的模块级代码中包含了 registry.register() 调用
# 这些注册调用把工具函数包装为 ToolDefinition 并存入注册中心
from . import file_reader     # 注册 read_pdf, read_docx, read_txt, read_md
from . import csv_processor   # 注册 read_csv, analyze_csv
from . import xlsx_generator  # 注册 generate_xlsx
from . import md_writer       # 注册 write_markdown
from . import ocr_tool        # 注册 ocr_image
from . import data_analyzer   # 注册 analyze_statistics, risk_analysis, trend_analysis
from . import finetuning_tool # 注册 extract_training_metrics

__all__ = ["ToolRegistry", "ToolDefinition", "ToolResult"]
# 公开导出三个核心类
# 工具模块本身不导出（外部通过 registry 调用工具，不直接 import 工具模块）
