"""
文件: agents/summary_agent.py | Summary Agent - 内容总结
职责: 将所有文件的解析结果汇总为 Markdown 格式的摘要

两种模式:
1. LLM 模式: Claude 生成段落式总结（有深度、有洞察）
2. 降级模式: 规则生成统计摘要（字符数、表格数）

为什么总结 Agent 如此重要?
用户不关心每个文件的原始内容
用户关心的是"这些文件整体上在说什么"——这就是总结的价值
"""

import json
from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.tools.registry import registry
from .base import BaseAgent


class SummaryAgent(BaseAgent):
    """总结 Agent: 汇总解析结果，生成 Markdown 摘要"""

    name = "summary"
    description = "总结文件内容，提取重点，生成 Markdown 摘要"
    tools = ["write_markdown"]     # 只需要写入文件的工具

    def __init__(self):
        # 初始化 DeepSeek 客户端（兼容 OpenAI SDK）
        self.client = None
        if DEEPSEEK_API_KEY:
            self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def summarize(self, parsed_contents: dict, user_request: str = "") -> str:
        """
        将所有解析结果汇总为 Markdown 摘要

        策略:
        1. 如果配置了 API Key → 让 Claude 根据用户需求生成针对性总结
        2. 否则 → 规则生成基础统计摘要

        参数:
          parsed_contents: {文件名: ParsedContent}
          user_request: 用户在对话框中输入的原始需求
        返回:
          Markdown 格式的字符串
        """
        if not parsed_contents:
            return "无文件内容"

        # 提取每个文件的内容片段（限制长度，避免超出 Token 限制）
        sections = []
        for filename, content in parsed_contents.items():
            # 获取元数据
            metadata = getattr(content, 'metadata', {})
            image_count = metadata.get('image_count', 0)
            paragraph_count = metadata.get('paragraph_count', 0)
            table_count = metadata.get('table_count', 0)
            
            # 构建文件信息
            file_info = []
            file_info.append(f"## 📄 {filename}")
            file_info.append("")
            
            # 添加元数据信息
            meta_lines = []
            if paragraph_count > 0:
                meta_lines.append(f"- 段落数: {paragraph_count}")
            if table_count > 0:
                meta_lines.append(f"- 表格数: {table_count}")
            if image_count > 0:
                meta_lines.append(f"- 图片数: {image_count}")
            
            if meta_lines:
                file_info.append("**文件信息:**")
                file_info.extend(meta_lines)
                file_info.append("")
            
            # 添加内容
            text_content = content.text[:3000] if content.text else "（无文本内容）"
            file_info.append("**内容预览:**")
            file_info.append(text_content)
            file_info.append("")
            file_info.append("---")
            file_info.append("")
            
            sections.extend(file_info)

        if self.client:
            # LLM 模式: 让 Claude 根据用户需求做针对性总结
            req_section = f"\n用户需求:\n{user_request[:500]}\n\n" if user_request else "\n"
            prompt = f"""请根据用户的特定需求分析以下文件内容，输出 Markdown 总结报告。{req_section}
要求：
1. 仔细理解用户的需求，针对性分析和总结
2. 文件概览（几个文件、类型分布等）
3. 每个文件的要点总结
4. 围绕用户需求提取核心发现

注意：如果文件包含图片但没有文本，请说明这一点并建议使用 OCR。

文件内容：
{chr(10).join(sections)[:8000]}
"""
            try:
                resp = self.client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    max_tokens=4096,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content
            except Exception:
                # API 失败时降级
                pass

        # 降级模式: 规则生成统计摘要
        lines = ["# 文件分析摘要", "", f"**文件数量**: {len(parsed_contents)} 个\n"]
        for fn, content in parsed_contents.items():
            metadata = getattr(content, 'metadata', {})
            lines.extend([
                f"## {fn}",
                f"- 字符数: {len(content.text)}",
                f"- 表格数: {len(content.tables)}",
            ])
            image_count = metadata.get('image_count', 0)
            if image_count > 0:
                lines.append(f"- 图片数: {image_count}")
            lines.append("")
        return "\n".join(lines)

    async def execute(self, state, context=None) -> dict:
        """执行总结任务"""
        parsed = state.get("parsed_contents", {})
        user_request = state.get("user_request", "")
        summary = await self.summarize(parsed, user_request)

        # 自动将摘要写入 Markdown 文件
        # 通过 ToolRegistry 调用，而非直接写文件
        # 这样保持了"所有输出操作都走工具"的一致性
        result = await registry.call_tool(
            "write_markdown",
            content=summary,
            filename="summary_report.md",
        )
        if result.success:
            return {"summary": summary, "report_path": result.data}
        return {"summary": summary}
