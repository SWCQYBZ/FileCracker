"""
文件: agents/parser_agent.py | File Parser Agent - 文件解析
职责: 遍历所有上传文件，调用对应的解析工具提取内容

为什么 Parser 是 Agent 而不是直接调用工具?
- 集中处理所有文件类型的路由逻辑
- 统一错误处理（一个文件解析失败不影响其他文件）
- 统一格式转换（所有解析结果转为 ParsedContent）
"""

import os
from app.tools.file_reader import get_file_reader  # 获取文件类型对应的 reader 函数
from app.tools.registry import registry            # 工具注册中心
from app.tools.csv_processor import read_csv       # CSV 专用解析
from app.tools.ocr_tool import ocr_image           # OCR 工具
from app.models.state import ParsedContent         # 统一解析结果格式
from .base import BaseAgent


class ParserAgent(BaseAgent):
    """文件解析 Agent: 解析各种格式的文件"""

    name = "parser"
    description = "解析各种格式的文件，提取文本、表格和元数据"
    # 该 Agent 能调用的所有工具
    tools = ["read_pdf", "read_docx", "read_txt", "read_md", "read_json",
             "read_csv", "read_xml", "read_xlsx", "ocr_image"]

    async def execute(self, state, context=None) -> dict:
        """
        遍历所有文件并解析

        路由逻辑:
        - CSV 文件 → 通过 registry 调用 read_csv（返回结构化表格）
        - 图片文件 → 通过 registry 调用 ocr_image（OCR 识别）
        - 其他 → get_file_reader 获取 reader 函数直接调用

        为什么 CSV/图片走 registry.call_tool 而其他走 get_file_reader?
        - CSV/图片的处理有特殊逻辑，通过注册中心便于统一管理
        - 其他文件的 reader 是纯函数，直接调用更高效
        """
        parsed = {}
        files_to_parse = state.get("files", [])

        for file_info in files_to_parse:
            file_path = file_info.file_path
            file_type = file_info.file_type
            filename = file_info.filename

            # 文件可能被删除，跳过
            if not os.path.exists(file_path):
                continue

            # 根据文件类型选择解析方式
            if file_type == "csv":
                # CSV: 通过 registry 调用，获取结构化表格
                result = await registry.call_tool("read_csv", file_path=file_path)
            elif file_type == "xlsx":
                # XLSX: 通过 registry 调用 openpyxl 解析
                result = await registry.call_tool("read_xlsx", file_path=file_path)
            elif file_type == "image":
                # 图片: 通过 registry 调用 OCR
                result = await registry.call_tool("ocr_image", file_path=file_path)
            else:
                # 其他: 通过 file_reader 策略获取对应 reader
                reader = get_file_reader(file_type)
                try:
                    result_data = reader(file_path)
                    # 模拟 ToolResult 结构（保持接口一致）
                    result = type("R", (), {"success": True, "data": result_data})()
                except Exception as e:
                    result = type("R", (), {"success": False, "error": str(e)})()

            # 统一转换为 ParsedContent
            if result.success:
                content = result.data if isinstance(result.data, dict) else {"text": str(result.data)}
                parsed[filename] = ParsedContent(**content)
            else:
                parsed[filename] = ParsedContent(text=f"[解析失败] {result.error}")

        return {"parsed_contents": parsed, "status": "parsing_completed"}
