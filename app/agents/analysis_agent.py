"""
文件: agents/analysis_agent.py | Analysis Agent - 数据分析/风险分析
职责: 对解析结果中的结构化数据进行深度分析

三层分析:
1. 统计分析 → 通过 analyze_statistics 工具（数值计算）
2. 风险分析 → 通过 risk_analysis 工具（异常检测）
3. LLM 分析 → 通过 Claude API（语义理解 + 商业洞察）

为什么需要 LLM 分析？
规则分析只能做数值计算
LLM 可以理解"这些数字在商业上意味着什么"
比如:"Q2 销售额下降但客户数上升，说明客单价在降"
"""

import json
from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.tools.registry import registry
from .base import BaseAgent


class AnalysisAgent(BaseAgent):
    """数据分析 Agent"""

    name = "analysis"
    description = "对数据进行统计分析、风险分析、趋势分析"
    tools = ["analyze_statistics", "risk_analysis", "trend_analysis", "write_markdown"]

    def __init__(self):
        self.client = None
        if DEEPSEEK_API_KEY:
            self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def _extract_tabular_data(self, parsed_contents: dict) -> list[dict]:
        """
        从解析内容中提取表格数据

        将多张表格的行数据合并为统一的字典列表
        每个字典的键是表头，值是对应的数据

        例如:
        表格: [["姓名", "年龄"], ["张三", "30"], ["李四", "25"]]
        输出: [{"姓名": "张三", "年龄": "30"}, {"姓名": "李四", "年龄": "25"}]
        """
        all_rows = []
        for filename, content in parsed_contents.items():
            # content.tables 是 list[list[list]] 结构
            # 每项是一张完整的表格(二维数组)
            for table in content.tables:
                if len(table) >= 2:                    # 至少表头+1行数据
                    headers = table[0]
                    for row in table[1:]:
                        row_dict = {}
                        for ci, h in enumerate(headers):
                            if ci < len(row):
                                row_dict[h] = row[ci]
                        if row_dict:
                            row_dict["_source"] = filename  # 标记数据来源
                            all_rows.append(row_dict)
        return all_rows

    async def execute(self, state, context=None) -> dict:
        """执行数据分析"""
        parsed = state.get("parsed_contents", {})
        user_request = state.get("user_request", "")
        data = await self._extract_tabular_data(parsed)

        analysis = {
            "statistics": {},
            "risk": {},
            "trend": {},
            "llm_analysis": "",
        }

        # 1. 规则分析（只要有数据就执行）
        if data:
            # 统计分析
            result = await registry.call_tool("analyze_statistics", data=data)
            if result.success:
                analysis["statistics"] = result.data

            # 风险分析
            result = await registry.call_tool("risk_analysis", data=data)
            if result.success:
                analysis["risk"] = result.data

        # 2. LLM 综合分析（增强规则分析）
        if self.client:
            files_text = "\n\n".join([
                f"### {fn}\n{content.text[:2000]}"
                for fn, content in parsed.items()
            ])
            try:
                resp = self.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    max_tokens=4096,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": (
                            "你是一位数据分析专家。请根据用户的具体需求分析以下文件内容，输出 JSON："
                            '{"summary": "总体分析（针对用户需求）", "key_insights": [...], '
                            '"risks": [...], "recommendations": [...]}'
                        )},
                        {"role": "user", "content": (
                            f"用户需求: {user_request[:500]}\n\n"
                            f"文件内容:\n{files_text[:7500]}"
                        )},
                    ],
                )
                text = resp.choices[0].message.content
                # 提取 JSON
                start = text.index("{")
                end = text.rindex("}") + 1
                analysis["llm_analysis"] = json.loads(text[start:end])
            except Exception:
                analysis["llm_analysis"] = {"summary": "LLM 分析不可用"}

        return {"analysis_result": analysis}
