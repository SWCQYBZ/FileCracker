"""
文件: agents/document_agent.py | Document Analysis Agent - 业务文档分析
职责: 分析工单、合同、报告等业务文档，提取结构化字段和关键发现

核心分析:
  1. 从 PDF/DOCX/TXT 等文档文本中提取结构化信息
  2. 识别单号、负责人、状态、截止日期、优先级、风险等关键字段
  3. 生成结构化 JSON 分析报告
"""

import json
from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from .base import BaseAgent


SYSTEM_PROMPT = """你是一位专业的业务文档分析专家。请分析以下文档内容，提取关键结构化信息。

请输出 JSON 格式的分析结果，不要包含其他内容：
{
  "document_type": "工单/合同/报告/其他",
  "summary": "文档内容摘要（2-3句话）",
  "structured_fields": {
    "ticket_number": "单号/合同号/编号（如无填null）",
    "responsible_person": "负责人/经办人（如无填null）",
    "status": "状态（如：待处理/进行中/已完成/已关闭/null）",
    "deadline": "截止日期（如无填null）",
    "priority": "优先级（高/中/低/null）",
    "department": "部门（如无填null）",
    "amount": "金额（数字，如无填null）",
    "risks": ["风险1", "风险2"]
  },
  "key_findings": [
    {"field": "发现项名称", "value": "具体内容", "importance": "high/medium/low"}
  ],
  "overall_analysis": "综合分析和对文档的整体判断"
}
"""


class DocumentAgent(BaseAgent):
    """业务文档分析 Agent"""

    name = "document"
    description = "业务文档分析 — 分析工单、合同、报告等文档，提取结构化字段和关键发现"
    tools = ["write_markdown"]

    def __init__(self):
        self.client = None
        if DEEPSEEK_API_KEY:
            self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def execute(self, state, context=None) -> dict:
        """执行业务文档分析"""
        parsed = state.get("parsed_contents", {})
        user_request = state.get("user_request", "")

        if not parsed:
            return {"document_result": None}

        # 步骤1: 从解析文件中筛选有实质文本内容的业务文档
        document_texts = {}
        for filename, content in parsed.items():
            text = getattr(content, "text", "")
            if text and len(text.strip()) > 50:
                document_texts[filename] = text[:5000]

        if not document_texts:
            return {"document_result": None}

        # 步骤2: LLM 分析（有 API Key）或规则降级
        if self.client:
            result = await self._llm_analyze(document_texts, user_request)
        else:
            result = self._rule_based_analysis(document_texts)

        return {
            "document_result": result,
            "agent_history": ["document"],
        }

    async def _llm_analyze(self, document_texts: dict, user_request: str) -> dict:
        """用 LLM 从文档中提取结构化信息"""
        context_parts = []
        for filename, text in document_texts.items():
            context_parts.append(f"--- {filename} ---\n{text}")

        prompt = "\n\n".join(context_parts)

        try:
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=4096,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"用户需求: {user_request[:500]}\n\n"
                        f"文档内容:\n{prompt[:15000]}"
                    )},
                ],
            )
            text = resp.choices[0].message.content
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                parsed = json.loads(text[start:end])
                return parsed
            except (json.JSONDecodeError, ValueError):
                return {
                    "document_type": "未知",
                    "summary": "LLM 分析解析失败",
                    "structured_fields": {},
                    "key_findings": [],
                    "overall_analysis": "LLM 返回的 JSON 格式不正确",
                }
        except Exception as e:
            return {
                "document_type": "未知",
                "summary": f"LLM 分析不可用: {str(e)}",
                "structured_fields": {},
                "key_findings": [],
                "overall_analysis": "",
            }

    def _rule_based_analysis(self, document_texts: dict) -> dict:
        """无 API Key 时的规则降级方案"""
        key_findings = []
        total_chars = 0
        for filename, text in document_texts.items():
            total_chars += len(text)
            key_findings.append({
                "field": "文件",
                "value": f"{filename} ({len(text)} 字符)",
                "importance": "medium",
            })

        return {
            "document_type": "文档",
            "summary": f"共分析 {len(document_texts)} 个文档文件，总计 {total_chars} 字符。"
                       "（规则模式：已扫描文件内容，详细分析需配置 API Key）",
            "structured_fields": {},
            "key_findings": key_findings,
            "overall_analysis": "规则模式分析完成。配置 DeepSeek API Key 可获得更深入的业务文档分析。",
        }
