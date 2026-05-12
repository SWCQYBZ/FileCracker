"""
文件: agents/planner.py | Planner Agent - 任务规划
职责: 分析用户请求和上传的文件，生成结构化的任务计划
地位: 整个系统的"大脑"——决定做什么、谁做、什么顺序

两种工作模式:
1. LLM 模式(有 API Key): 让 Claude 理解需求，动态规划
2. 降级模式(无 API Key): 规则生成固定流程

为什么 Planner 如此重要?
在真正的多 Agent 系统中，Planner 的规划质量决定一切
当前是"半自动"——固定流程 + LLM 优化
未来可以进化到完全由 LLM 动态规划
"""

import json
import os
from openai import OpenAI  # OpenAI SDK（兼容 DeepSeek API）

from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, SUPPORTED_EXTENSIONS
from app.models.state import WorkflowPlan, FileInfo
from .base import BaseAgent


# ============================================================
# System Prompt: 给 Claude 的角色设定
# 这是 LLM 模式下 Planner 的行为准则
# 内容包括:
#   1. 角色定义(任务规划专家)
#   2. 可用 Agent 列表(谁可以用)
#   3. 可用工具列表(可以用什么)
#   4. 输出格式(JSON)
#
# 为什么写这么详细?
# LLM 需要明确的上下文才能做出合理决策
# "可用"信息不全 → LLM 会编造不存在的 Agent/工具
# ============================================================
SYSTEM_PROMPT = """你是一个任务规划专家。你的职责是分析用户上传的文件和需求，生成结构化的任务计划。

可用 Agent:
- parser: 文件解析 - 读取各种格式的文件内容
- summary: 内容总结 - 对解析结果进行总结，提取重点
- analysis: 数据分析 - 对数据进行统计分析、风险分析、趋势分析
- finetuning: 微调数据分析 - 分析训练日志、loss 曲线、评估指标
- document: 业务文档分析 - 分析工单、合同、报告等文档，提取结构化字段
- spreadsheet: 电子表格 - 提取结构化数据并生成 XLSX 文件

可用 Tool:
- read_pdf / read_docx / read_txt / read_md / read_json / read_xml: 解析对应格式文件
- read_csv / analyze_csv: CSV 处理
- read_xlsx / generate_xlsx: Excel 读取和生成
- ocr_image: 图片文字识别
- analyze_statistics / risk_analysis / trend_analysis: 数据分析
- extract_training_metrics: 提取训练指标
- write_markdown: 写入 Markdown

请输出 JSON 格式的计划，不要包含其他内容：
{
  "tasks": [
    {"agent": "parser", "tool": "read_pdf", "params": {"file_path": "..."}},
    {"agent": "summary", "tool": "", "params": {}},
    {"agent": "analysis", "tool": "analyze_statistics", "params": {}},
    {"agent": "finetuning", "tool": "extract_training_metrics", "params": {}},
    {"agent": "document", "tool": "", "params": {}},
    {"agent": "spreadsheet", "tool": "generate_xlsx", "params": {}}
  ],
  "parallel_groups": [["analysis", "finetuning", "document", "spreadsheet"]],
  "reasoning": "简要说明规划理由"
}
"""


class PlannerAgent(BaseAgent):
    """Planner Agent: 分析用户请求和文件，生成任务计划"""

    name = "planner"
    description = "分析用户请求和文件，生成任务计划"
    tools = []  # Planner 不直接使用工具，它只做规划

    def __init__(self):
        # 初始化 DeepSeek 客户端（兼容 OpenAI SDK）
        # 如果没配置 API Key，client 为 None
        # 后续执行时会自动降级为规则模式
        self.client = None
        if DEEPSEEK_API_KEY:
            self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def create_plan(self, files: list[FileInfo], user_request: str) -> WorkflowPlan:
        """
        根据文件列表和用户请求生成执行计划

        流程:
        1. 有 API Key → 调用 Claude → 解析 JSON 响应 → WorkflowPlan
        2. 无 API Key → 规则生成默认计划
        """
        # 无 API Key 时快速降级
        if not self.client:
            return self._default_plan(files)

        # 构造给 LLM 的文件描述
        file_descriptions = []
        for f in files:
            file_descriptions.append(
                f"  - {f.filename} (类型: {f.file_type}, 大小: {f.size} bytes)"
            )

        prompt = f"""用户请求: {user_request}

上传的文件:
{chr(10).join(file_descriptions)}

请根据文件类型和用户需求生成任务计划。"""

        try:
            # 调用 DeepSeek API
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=4096,
                temperature=0.3,        # 低温度 = 更确定性的输出
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},  # 角色设定
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content.strip()
            # 从响应中提取 JSON（处理 LLM 可能输出额外文字的情况）
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            return WorkflowPlan(**data)
        except Exception as e:
            # API 调用失败时降级到规则模式
            return self._default_plan(files)

    def _default_plan(self, files: list[FileInfo]) -> WorkflowPlan:
        """
        默认计划生成（降级方案）

        流程固定: 解析所有文件 → 总结 → 分析 → 生成表格
        虽然不如 LLM 灵活，但保证系统在无 API 时也能用
        """
        tasks = []
        # 第一步: 为每个文件创建解析任务
        for f in files:
            tasks.append({
                "agent": "parser",
                "tool": self._tool_for_type(f.file_type),
                "params": {"file_path": f.file_path},
            })
        # 后续固定步骤
        tasks.append({"agent": "summary", "tool": "", "params": {}})
        tasks.append({"agent": "analysis", "tool": "analyze_statistics", "params": {}})
        tasks.append({"agent": "spreadsheet", "tool": "generate_xlsx", "params": {}})

        return WorkflowPlan(
            tasks=tasks,
            parallel_groups=[["analysis", "spreadsheet"]],  # 分析 和 表格生成 可并行
            reasoning=f"共 {len(files)} 个文件，先解析再总结、分析、生成表格",
        )

    def _tool_for_type(self, file_type: str) -> str:
        """根据文件内部类型返回对应的解析工具名"""
        mapping = {
            "pdf": "read_pdf", "docx": "read_docx", "csv": "read_csv",
            "json": "read_json", "text": "read_txt", "markdown": "read_md",
            "xml": "read_xml", "yaml": "read_yaml",
            "image": "ocr_image",
        }
        # 不支持的类型也用 read_txt 保底
        return mapping.get(file_type, "read_txt")

    async def execute(self, state, context=None) -> dict:
        """Planner Agent 的执行入口"""
        plan = await self.create_plan(state["files"], state["user_request"])
        return {"plan": plan, "status": "planning_completed"}
