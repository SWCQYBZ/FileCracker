"""
文件: agents/spreadsheet_agent.py | Spreadsheet Agent - Excel 生成
职责: 从解析结果中提取结构化数据，生成格式化的 .xlsx 文件

表格来源:
1. 原生表格: CSV 文件、Word 文档中的表格
2. 管道符表格: Markdown/文本中的 | A | B | C | 格式
3. 未来: LLM 从非结构化文本中提取的表格
"""

from app.tools.registry import registry
from .base import BaseAgent


class SpreadsheetAgent(BaseAgent):
    """电子表格生成 Agent"""

    name = "spreadsheet"
    description = "从解析内容中提取结构化数据并生成 XLSX 文件"
    tools = ["generate_xlsx"]

    def _tables_from_parsed(self, parsed_contents: dict) -> list[dict]:
        """
        从解析结果中提取表格数据

        两步提取:
        1. 原生表格: 直接从 ParsedContent.tables 中拿
        2. 管道符表格: 从文本中提取 | 分隔的数据

        为什么需要两步?
        有些 Markdown 文件中的表格没被解析器识别
        需要二次扫描从文本中提取
        """
        tables = []
        for filename, content in parsed_contents.items():
            # 第1步: 获取原生表格
            for i, table in enumerate(content.tables):
                if len(table) >= 2:      # 至少表头+数据
                    tables.append({
                        "name": f"{filename}_table_{i + 1}",
                        "headers": table[0],
                        "rows": table[1:],
                    })
            # 第2步: 文本中提取管道符表格
            # 只在没有原生表格时尝试，避免重复
            if not content.tables and content.text:
                extracted = self._extract_pipe_tables(content.text, filename)
                tables.extend(extracted)
        return tables

    def _extract_pipe_tables(self, text: str, filename: str) -> list[dict]:
        """
        从文本中提取管道符表格

        识别模式:
        | 列1 | 列2 | 列3 |
        |-----|-----|-----|
        | 值1 | 值2 | 值3 |

        原理:
        - 扫描包含 | 符号的行
        - 连续的行组成一张表格
        - 空行或非 | 行结束当前表格
        """
        tables = []
        lines = text.split("\n")
        table_lines = []   # 当前正在收集的表格行

        for line in lines:
            # 包含至少2个 | 符号 → 可能是表格行
            if "|" in line and line.count("|") >= 2:
                # 提取 | 之间的内容
                table_lines.append(
                    [c.strip() for c in line.split("|") if c.strip()]
                )
            elif table_lines:
                # 非表格行结束当前表格
                if len(table_lines) >= 2:   # 至少2行才构成表格
                    tables.append({
                        "name": f"{filename}_extracted",
                        "headers": table_lines[0],
                        "rows": table_lines[1:],
                    })
                table_lines = []  # 重置

        # 处理文件末尾的表格
        if len(table_lines) >= 2:
            tables.append({
                "name": f"{filename}_extracted",
                "headers": table_lines[0],
                "rows": table_lines[1:],
            })

        return tables

    async def execute(self, state, context=None) -> dict:
        """生成 Excel 文件"""
        parsed = state.get("parsed_contents", {})
        tables = self._tables_from_parsed(parsed)

        # 没有数据时返回 None
        if not tables:
            return {"xlsx_path": None}

        # 通过 ToolRegistry 调用 Excel 生成工具
        result = await registry.call_tool("generate_xlsx", tables=tables)
        if result.success:
            return {"xlsx_path": result.data}
        return {"xlsx_path": None, "errors": [result.error]}
