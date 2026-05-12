"""Workflow Node 函数 - 每个 Node 是 (state) → partial_state_update"""
# orchestrator/nodes.py
# 这个文件定义了 LangGraph 工作流中的所有"节点"（Node）函数
#
# 什么是 Node？
# 在 LangGraph 中，Node 是工作流图中的一个执行步骤
# 每个 Node 是一个异步函数: (state) → dict
# - 输入: 当前的 WorkflowState（整个工作流的全部状态）
# - 输出: 一个 dict，会被合并（update）到全局状态中
# 注意: Node 不需要返回所有字段，只返回自己修改的部分
#       LangGraph 会自动将返回值 merge 到 State 中
#
# 为什么 Node 函数要放在单独的文件中？
# workflow.py 负责"搭图"（定义节点和边的关系）
# nodes.py 负责"实现"（每个节点具体做什么）
# 分离关注点，让图结构和节点逻辑可以独立修改

from typing import Literal
# Literal: Python 3.8+ 的类型标注，限制变量只能取特定值
# 例如: -> Literal["summary_node"] 表示返回值只能是 "summary_node"

from langgraph.types import Send
# Send: LangGraph 的条件路由工具
# 普通路由: 一个节点 → 另一个节点（node → next_node）
# Send 路由: 一个节点 → 多个节点并行执行（fan-out）
# 用法: Send("target_node", partial_state)
#   - "target_node": 目标节点名称
#   - partial_state: 发送给该节点的状态子集
# 注意: 使用 Send 时，LangGraph 自动处理结果的合并
#       但目标字段必须使用 Annotated[list, operator.add] 来支持并发写入

from app.models.state import WorkflowState
# 导入 WorkflowState 类型定义
# 虽然是 TypedDict，但可以用作函数参数的类型标注（静态检查）

from app.agents import (
    PlannerAgent, ParserAgent, SummaryAgent,
    AnalysisAgent, FinetuningAgent, SpreadsheetAgent,
    DocumentAgent,
)
# 导入所有 Agent 类
# 每个 Node 函数内部实例化对应的 Agent，然后调用 agent.execute()
# 为什么不把 Agent 实例化放在外面？
# - 每个 Agent 在 __init__ 中创建 LLM 客户端等资源
# - 按需实例化可以延迟资源创建，避免在定义图时就占用内存
# - 也方便测试时单独 mock 某个 Agent


async def planner_node(state: WorkflowState) -> dict:
    """Planner Node: 分析请求，生成任务计划"""
    # PlannerAgent 负责理解用户上传的文件和用户请求
    # 输出 WorkflowPlan（含任务列表和并行分组）
    agent = PlannerAgent()
    # 实例化 PlannerAgent
    # __init__ 中会尝试创建 LLM 客户端（如果有 API Key）
    # 如果没有 API Key，后续 create_plan 会降级到规则模式

    plan = await agent.create_plan(state["files"], state["user_request"])
    # create_plan 根据文件列表和用户请求生成 WorkflowPlan
    # 有 API Key: 调用 Claude 做智能分析，动态决定任务
    # 无 API Key: 规则固定流程（解析→总结→分析→生成表格）
    # state["files"]: list[FileInfo]，包含文件名、路径、类型、大小

    return {
        "plan": plan,
        # WorkflowPlan 对象，包含 tasks 和 parallel_groups
        # 后续节点的路由逻辑可能会根据 plan 中的信息做决策

        "current_task_index": 0,
        # 当前执行到第几个任务（0 表示刚开始）
        # 这是一个扩展性字段——未来支持"任务级"进度追踪

        "status": "planning_completed",
        # 标记 Planner 阶段完成
        # 这个状态会在整个工作流中流转，最终到 "completed"

        "agent_history": ["planner"],
        # agent_history 是 Annotated[list[str], operator.add] 类型
        # 每个节点把自己的名字追加到这个列表中
        # 这样即使有并行节点同时追加，也不会出现写入冲突
        # 最终效果: ["planner", "parser", "summary", "analysis", "spreadsheet", "sync", "reporter"]
    }


async def parser_node(state: WorkflowState) -> dict:
    """Parser Node: 解析所有文件"""
    # ParserAgent 遍历所有上传文件，根据文件类型调用对应的解析工具
    # 支持: PDF、DOCX、TXT、CSV、JSON、XML、Markdown、图片（OCR）
    agent = ParserAgent()

    result = await agent.execute(state)
    # ParserAgent.execute() 接收整个 state
    # 从中读取 state["files"]（上传的文件列表）
    # 返回 {"parsed_contents": {...}, "status": "parsing_completed"}
    # 文件不存在时自动跳过，单个文件失败不影响其他文件（错误隔离）
    # CSV 通过 registry.call_tool("read_csv") 调用
    # 图片通过 registry.call_tool("ocr_image") 调用
    # 其他文件通过 get_file_reader() 查找对应的 reader 函数

    return {
        "parsed_contents": result.get("parsed_contents", {}),
        # 解析结果: {filename: ParsedContent}
        # ParsedContent 包含 text（文本内容）、tables（表格）、metadata（元数据）
        # 解析失败的文件的 text 为 "[解析失败] 错误信息"

        "agent_history": ["parser"],
        # 追加执行记录
        # operator.add 会把这个元素追加到 agent_history 列表中
    }


async def summary_node(state: WorkflowState) -> dict:
    """Summary Node: 总结文件内容"""
    # SummaryAgent 将解析结果汇总为 Markdown 格式的摘要
    # 有 API Key: Claude 生成段落式总结（有深度、有洞察）
    # 无 API Key: 规则生成统计摘要（字符数、表格数）
    agent = SummaryAgent()

    result = await agent.execute(state)
    # SummaryAgent.execute() 从 state 中读取 parsed_contents
    # 提取每个文件的内容片段（限制 3000 字符避免 Token 超限）
    # 调用 Claude 或规则引擎生成 Markdown 字符串
    # 通过 registry.call_tool("write_markdown") 自动写入文件
    # 返回 {"summary": markdown_string, "report_path": "output/summary_report.md"}

    return {
        "summary": result.get("summary", ""),
        # Markdown 格式的总结文本
        # 会被 report_node 使用，嵌入到最终报告中

        "report_path": result.get("report_path", ""),
        # summary_report.md 的文件路径
        # 如果 write_markdown 调用失败，report_path 为空字符串

        "agent_history": ["summary"],
    }


async def analysis_node(state: WorkflowState) -> dict:
    """Analysis Node: 数据分析"""
    # AnalysisAgent 对结构化数据做三层分析
    agent = AnalysisAgent()

    result = await agent.execute(state)
    # AnalysisAgent.execute() 从 state 读取 parsed_contents
    # 提取表格数据，转为 [{header: value}] 格式
    # 执行三层分析:
    #   1. analyze_statistics: 数值统计（均值、中位数、标准差等）
    #   2. risk_analysis: 风险检测（异常值、空值率等）
    #   3. LLM 分析: Claude 做语义理解（商业洞察）
    # 返回 {"analysis_result": {statistics, risk, trend, llm_analysis}}

    return {
        "analysis_result": result.get("analysis_result", {}),
        # 分析结果字典，包含:
        # - statistics: 统计结果（各字段的数值指标）
        # - risk: 风险分析结果（风险等级、异常项列表）
        # - trend: 趋势分析（暂为框架，未来扩展）
        # - llm_analysis: Claude 的分析 JSON（由 report_node 渲染）

        "agent_history": ["analysis"],
    }


async def finetuning_node(state: WorkflowState) -> dict:
    """Finetuning Node: 微调训练数据分析"""
    agent = FinetuningAgent()
    result = await agent.execute(state)
    return {
        "finetuning_result": result.get("finetuning_result"),
        "agent_history": ["finetuning"],
    }


async def document_node(state: WorkflowState) -> dict:
    """Document Node: 业务文档分析（工单、合同、报告等）"""
    agent = DocumentAgent()
    result = await agent.execute(state)
    return {
        "document_result": result.get("document_result"),
        "agent_history": ["document"],
    }


async def spreadsheet_node(state: WorkflowState) -> dict:
    """Spreadsheet Node: 生成 XLSX"""
    # SpreadsheetAgent 从解析结果中提取结构化表格，生成 Excel 文件
    agent = SpreadsheetAgent()

    result = await agent.execute(state)
    # SpreadsheetAgent.execute() 从 state 读取 parsed_contents
    # 执行两步表格提取:
    #   1. 原生表格: 从 ParsedContent.tables 中直接获取
    #   2. 管道符表格: 从文本中扫描 | 分隔的数据格式
    # 调用 registry.call_tool("generate_xlsx") 生成格式化的 .xlsx 文件
    # 返回 {"xlsx_path": "output/extracted_data.xlsx"}

    return {
        "xlsx_path": result.get("xlsx_path"),
        # 生成的 Excel 文件路径
        # 如果没有表格数据，值为 None
        # report_node 会检查这个值来决定是否在报告中添加"数据表格"章节

        "agent_history": ["spreadsheet"],
    }


async def sync_node(state: WorkflowState) -> dict:
    """Synchronizer Node: 等待并行任务完成，合并结果"""
    # 这个节点不做任何实际工作
    # 它的作用是在图结构中提供一个"汇合点"
    #
    # LangGraph 的并行分支是这样的:
    # summary_node → [analysis_node, spreadsheet_node] → sync_node
    #
    # 为什么需要 sync_node？
    # LangGraph 的并行是"fork-join"模式:
    #   1. summary_node 完成 → route_after_summary 通过 Send() 同时启动 analysis 和 spreadsheet
    #   2. LangGraph 并行执行 analysis_node 和 spreadsheet_node
    #   3. 两个节点都完成后，才会进入 sync_node
    # sync_node 就是那个"join"点，它确保两个并行分支都完成了
    # 才继续到 report_node（因为 report_node 需要 analysis 和 xlsx 的结果）
    return {
        "status": "parallel_completed",
        # 标记并行阶段完成
        # 虽然实际等待是由 LangGraph 引擎完成的
        # 但显式标记状态可以让调用方和日志系统了解进度

        "agent_history": ["sync"],
        # 追加执行记录
    }


async def report_node(state: WorkflowState) -> dict:
    """Report Node: 汇总所有结果生成最终 Markdown 报告"""
    # 这是工作流的最后一个节点
    # 它收集之前所有节点的输出，整合为一份完成的分析报告

    # 步骤1: 从 state 中读取所有节点产生的结果
    parsed = state.get("parsed_contents", {})
    # 解析结果 {filename: ParsedContent}
    # 来自 parser_node

    summary = state.get("summary", "")
    # 总结内容（Markdown 字符串）
    # 来自 summary_node

    analysis = state.get("analysis_result", {})
    # 分析结果（字典，含 statistics / risk / llm_analysis）
    # 来自 analysis_node

    xlsx = state.get("xlsx_path")
    # Excel 文件路径（可能为 None）
    # 来自 spreadsheet_node

    # 步骤2: 组装报告内容
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 生成时间戳，用于报告标题

    lines = [
        "# [REPORT] 多智能体文件分析报告",
        "",
        f"**生成时间**: {ts}",
        f"**文件数量**: {len(parsed)} 个",
        "",
        "---",
        "",
        "## 一、文件总结",
        "",
        summary,
        "",
    ]
    # 报告的头部区域：标题、时间戳、文件数量、总结
    # summary_node 的输出直接嵌入这里

    if analysis:
        # 如果有分析结果，添加"数据分析"章节
        lines.extend([
            "---",
            "",
            "## 二、数据分析",
            "",
        ])

        # 2a. 统计分析结果
        stats = analysis.get("statistics", {})
        # statistics 字典结构: {"stats": {"字段名": {"mean": ..., "median": ..., ...}}}
        if stats and stats.get("stats"):
            lines.append("### [图表] 统计分析")
            lines.append("")
            for field, stat in stats["stats"].items():
                lines.append(f"- **{field}**: {stat}")
            lines.append("")
            # 遍历每个字段的统计结果，格式化为 Markdown 列表

        # 2b. 风险分析结果
        risk = analysis.get("risk", {})
        # risk 字典结构: {"risk_level": "low|medium|high", "risk_count": N, ...}
        if risk:
            lines.append("### [警告] 风险分析")
            lines.append(f"- 风险等级: {risk.get('risk_level', 'N/A')}")
            lines.append(f"- 风险项: {risk.get('risk_count', 0)} 个")
            lines.append("")

        # 2c. LLM 分析结果（AI 生成的商业洞察）
        llm = analysis.get("llm_analysis", {})
        # llm 是 Claude 返回的 JSON，结构: {summary, key_insights, risks, recommendations}
        if isinstance(llm, dict):
            if llm.get("summary"):
                lines.append("### [AI] AI 分析")
                lines.append("")
                lines.append(llm["summary"])
                lines.append("")
            if llm.get("key_insights"):
                lines.append("**关键洞察**:")
                for ins in llm["key_insights"]:
                    lines.append(f"- {ins}")
                lines.append("")
            if llm.get("recommendations"):
                lines.append("**建议**:")
                for rec in llm["recommendations"]:
                    lines.append(f"- {rec}")
                lines.append("")

    # 3. 业务文档分析章节
    document = state.get("document_result")
    if document and document.get("summary"):
        lines.extend([
            "---",
            "",
            "## 三、业务文档分析",
            "",
        ])
        doc_type = document.get("document_type", "文档")
        lines.append(f"**文档类型**: {doc_type}")
        lines.append("")
        lines.append(document.get("summary", ""))
        lines.append("")

        fields = document.get("structured_fields", {})
        if fields:
            non_null = {k: v for k, v in fields.items() if v is not None and v != ""}
            if non_null:
                lines.append("**结构化字段**:")
                lines.append("")
                lines.append("| 字段 | 值 |")
                lines.append("| --- | --- |")
                for k, v in non_null.items():
                    if isinstance(v, list):
                        lines.append(f"| {k} | {', '.join(str(x) for x in v)} |")
                    else:
                        lines.append(f"| {k} | {v} |")
                lines.append("")

        findings = document.get("key_findings", [])
        if findings:
            lines.append("**关键发现**:")
            lines.append("")
            for f in findings:
                icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.get("importance", "medium"), "⚪")
                lines.append(f"- {icon} **{f.get('field', '')}**: {f.get('value', '')}")
            lines.append("")

        overall = document.get("overall_analysis", "")
        if overall:
            lines.append("**综合分析**:")
            lines.append("")
            lines.append(overall)
            lines.append("")

    # 4. 微调数据分析章节（完整嵌入）
    finetuning = state.get("finetuning_result")
    if finetuning and finetuning.get("summary"):
        metrics = finetuning.get("metrics", {})
        summary_meta = metrics.get("summary", {})
        llm = finetuning.get("llm_analysis", {})
        jsonl_data = metrics.get("jsonl_data", {})
        csv_epochs = metrics.get("csv_epochs", [])
        json_files = metrics.get("json_files", {})
        charts = finetuning.get("chart_images", [])

        lines.extend(["---", "", "## 四、微调训练分析", ""])

        # 4a. 总体摘要
        lines.extend(["### 1. 总体摘要", "", finetuning["summary"], ""])

        # 3b. JSONL 逐 step 收敛分析（核心）
        if jsonl_data and jsonl_data.get("rows"):
            conv = jsonl_data.get("convergence", {})
            stats = jsonl_data.get("stats", {})
            steps = jsonl_data.get("step_count", 0)
            lines.append("### 2. 训练过程分析（trainer_log.jsonl）")
            lines.append("")
            lines.append(f"- **总步数**: {steps}")
            lines.append(f"- **可用指标**: {', '.join(jsonl_data.get('available_metrics', []))}")
            lines.append("")
            if conv:
                lines.append(f"**收敛判断**: {conv.get('verdict', '')}")
                lines.append("")
                if "initial_loss" in conv:
                    lines.append("| 指标 | 数值 |")
                    lines.append("| --- | --- |")
                    lines.append(f"| 初始 loss | {conv['initial_loss']} |")
                    lines.append(f"| 最终 loss | {conv['final_loss']} |")
                    lines.append(f"| 最小 loss | {conv['min_loss']} |")
                    lines.append(f"| 趋势 | {conv['trend']} |")
                    lines.append("")
                if conv.get("description"):
                    lines.append(f"> {conv['description']}")
                    lines.append("")
            if stats:
                lines.append("**各字段统计**:")
                lines.append("")
                stat_fields = list(stats.keys())
                lines.append("| 字段 | 初值 | 终值 | 最小值 | 最大值 |")
                lines.append("| --- | --- | --- | --- | --- |")
                for sf in stat_fields:
                    s = stats[sf]
                    lines.append(f"| {sf} | {s.get('first', '-')} | {s.get('last', '-')} | {s.get('min', '-')} | {s.get('max', '-')} |")
                lines.append("")
            # 逐 step 数据表格（采样展示）
            rows = jsonl_data.get("rows", [])
            if rows:
                lines.append("**逐 Step 数据（首尾采样）**:")
                lines.append("")
                display_cols = jsonl_data.get("fields", [])
                # Build table with first 5 and last 5 rows
                if display_cols:
                    lines.append("| " + " | ".join(display_cols) + " |")
                    lines.append("| " + " | ".join("---" for _ in display_cols) + " |")
                    for r in rows[:5]:
                        vals = []
                        for c in display_cols:
                            v = r.get(c, "")
                            if isinstance(v, float):
                                vals.append(f"{v:.6g}")
                            else:
                                vals.append(str(v))
                        lines.append("| " + " | ".join(vals) + " |")
                    if len(rows) > 10:
                        lines.append("| " + " | ".join("..." for _ in display_cols) + " |")
                        for r in rows[-5:]:
                            vals = []
                            for c in display_cols:
                                v = r.get(c, "")
                                if isinstance(v, float):
                                    vals.append(f"{v:.6g}")
                                else:
                                    vals.append(str(v))
                            lines.append("| " + " | ".join(vals) + " |")
                    lines.append("")

        # 3c. 关键指标（补充，从其他文件提取）
        best_loss = summary_meta.get("best_eval_loss")
        best_acc = summary_meta.get("best_eval_accuracy")
        best_f1 = summary_meta.get("best_eval_f1")
        train_loss = summary_meta.get("train_loss")
        sec_n = 3 if jsonl_data and jsonl_data.get("rows") else 2
        if any([best_loss, best_acc, best_f1, train_loss]):
            lines.append(f"### {sec_n}. 关键指标")
            lines.append("")
            lines.append("| 指标 | 数值 |")
            lines.append("| --- | --- |")
            if best_loss is not None:
                lines.append(f"| 最佳 eval_loss | {best_loss:.6g} |")
            if best_acc is not None:
                lines.append(f"| 最佳 eval_accuracy | {best_acc:.6g} |")
            if best_f1 is not None:
                lines.append(f"| 最佳 eval_f1 | {best_f1:.6g} |")
            if train_loss is not None:
                lines.append(f"| train_loss | {train_loss:.6g} |")
            lines.append("")
            sec_n += 1

        # 3d. 逐 Epoch 表格
        if csv_epochs:
            lines.append(f"### {sec_n}. 逐 Epoch 训练指标")
            lines.append("")
            seen_c = {}
            cols = []
            for row in csv_epochs:
                for k in row:
                    if k.startswith("_"):
                        continue
                    if k not in seen_c:
                        cols.append(k)
                        seen_c[k] = True
            if cols:
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("| " + " | ".join("---" for _ in cols) + " |")
                for row in csv_epochs:
                    vals = []
                    for c in cols:
                        v = row.get(c, "")
                        if isinstance(v, float):
                            vals.append(f"{v:.6g}")
                        else:
                            vals.append(str(v))
                    lines.append("| " + " | ".join(vals) + " |")
                lines.append("")
            sec_n += 1

        # 3e. JSON 评估
        if json_files:
            lines.append(f"### {sec_n}. JSON 评估明细")
            lines.append("")
            import json
            for fname, data in json_files.items():
                lines.append(f"**{fname}**")
                lines.append("")
                if isinstance(data, dict):
                    items = []
                    for k, v in data.items():
                        if not isinstance(v, (dict, list)):
                            val = f"{v:.6g}" if isinstance(v, float) else str(v)
                            items.append({"参数": k, "数值": val})
                    if items:
                        lines.append("| 参数 | 数值 |")
                        lines.append("| --- | --- |")
                        for item in items:
                            lines.append(f"| {item['参数']} | {item['数值']} |")
                        lines.append("")
                    else:
                        lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```\n")
                elif isinstance(data, list):
                    lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```\n")
            sec_n += 1

        # 3f. AI 评估
        if isinstance(llm, dict) and llm.get("overall_assessment"):
            lines.append(f"### {sec_n}. AI 评估")
            lines.append("")
            lines.append(f"**总体评价**: {llm['overall_assessment']}")
            lines.append("")
            if llm.get("convergence_analysis"):
                lines.append(f"**收敛分析**: {llm['convergence_analysis']}")
                lines.append("")
            if llm.get("issues_and_warnings"):
                lines.extend(["**问题与警告**:", ""])
                for issue in llm["issues_and_warnings"]:
                    lines.append(f"- ⚠️ {issue}")
                lines.append("")
            if llm.get("recommendations"):
                lines.extend(["**改进建议**:", ""])
                for rec in llm["recommendations"]:
                    lines.append(f"- 💡 {rec}")
                lines.append("")
            sec_n += 1

        # 3g. 训练曲线图
        if charts:
            lines.append(f"### {sec_n}. 训练曲线图")
            lines.append("")
            import base64
            from pathlib import Path
            from app.config import OUTPUT_DIR
            for img in charts:
                img_file = Path(str(OUTPUT_DIR)) / img["filename"]
                try:
                    b64 = base64.b64encode(img_file.read_bytes()).decode("ascii")
                    lines.append(f"![{img['original']}](data:image/png;base64,{b64})")
                except Exception:
                    lines.append(f"![{img['original']}]({img['filename']})")
                lines.append("")
            sec_n += 1

        # 3h. 日志分析
        log = metrics.get("log_analysis", "").strip()
        if log:
            lines.append(f"### {sec_n}. 日志分析")
            lines.append("")
            lines.append(log)
            lines.append("")
            sec_n += 1

        # 3i. 文件清单
        fc = metrics.get("files_classified", {})
        lines.append(f"### {sec_n}. 分析文件清单")
        lines.append("")
        for category, label in [
            ("jsonl", "📈 trainer_log.jsonl"),
            ("metrics_json", "📊 评估指标 JSON"),
            ("csv", "📋 逐 epoch 明细"),
            ("logs", "📝 训练日志"),
            ("predictions", "🔤 预测输出"),
            ("model_weights", "⚙️ 模型权重"),
        ]:
            flist = fc.get(category, [])
            if flist:
                lines.append(f"**{label}** ({len(flist)} 个)")
                for f in flist:
                    lines.append(f"- {f}")
                lines.append("")

    # 4. 数据表格章节（如果有生成的 Excel 文件）
    if xlsx:
        lines.extend([
            "---",
            "",
            "## 五、数据表格",
            "",
            f"结构化数据已导出至 Excel 文件:",
            f"- `{xlsx}`",
            "",
        ])

    # 4. 报告尾部
    lines.extend([
        "",
        "---",
        "*报告由多智能体文件分析系统自动生成*",
    ])

    report_content = "\n".join(lines)
    # 将行列表合并为完整的 Markdown 字符串

    # 步骤3: 通过 ToolRegistry 写入文件
    from app.tools.registry import registry
    # 直接引入 registry 单例（虽然模块顶部已有导入，但函数内导入避免循环依赖问题）
    result = await registry.call_tool(
        "write_markdown",
        content=report_content,
        filename="final_report.md",
    )
    # registry.call_tool("write_markdown", ...) 会:
    # 1. 查找名为 "write_markdown" 的工具定义
    # 2. 调用对应的工具函数 (save_to_file)
    # 3. 返回 ToolResult(success=True, data=file_path) 或带 error
    # 文件名: final_report.md，写入到 OUTPUT_DIR

    return {
        "report_path": result.data if result.success else "",
        # 如果写入成功，result.data 包含文件完整路径
        # 如果写入失败，返回空字符串

        "status": "completed",
        # 标记整个工作流完成
        # 调用方（API 层）通过检查这个字段判断任务是否结束

        "agent_history": ["reporter"],
    }


# ---- Router Functions ----
# 路由函数是 LangGraph 中的"边"（Edge）逻辑
# 普通边: builder.add_edge("node_a", "node_b") — 固定路线
# 条件边: builder.add_conditional_edges(source, router_fn, destinations)
#   - router_fn 接收 state，返回目标节点名称
#   - 可以根据 state 中的动态数据决定走哪条路


def route_after_parser(state: WorkflowState) -> str:
    """解析完成后路由到 summary"""
    # 这是最简单的路由——解析完成后总是去 summary
    # 虽然目前是固定路由，但用条件边的形式实现了扩展性
    # 未来可以在这里加判断:
    #   - 如果解析全部失败 → 不去 summary，直接去 error_handler
    #   - 如果有特定文件类型 → 先做预处理
    #   - 如果文件过大 → 分段处理
    return "summary_node"
    # 直接返回目标节点名称（常量路由）
    # 类型标注 Literal["summary_node"] 让静态检查更严格


def route_after_summary(state: WorkflowState) -> list[Send]:
    """总结完成后并行路由到 analysis + spreadsheet"""
    # 这是 LangGraph 的 fan-out（扇出）模式
    # summary 完成后，analysis 和 spreadsheet 可以并行执行
    # 因为它们之间没有数据依赖:
    #   - analysis 只需要 parsed_contents（来自 parser）
    #   - spreadsheet 只需要 parsed_contents（来自 parser）
    # 两者互不依赖，并行执行可以缩短整体耗时

    # 构造要给并行节点传递的状态子集
    # 注意: 这里只传分析/表格生成需要的字段，不传整个 state
    # Send() 的第二个参数是"发送给目标节点的状态"
    # LangGraph 会把它 merge 到目标节点的 state 中
    state_updates = {
        "session_id": state.get("session_id", ""),
        # 会话 ID，用于日志追踪和检查点恢复

        "files": state.get("files", []),
        # 文件列表（analysis 和 spreadsheet 可能不需要，但保持完整）

        "user_request": state.get("user_request", ""),
        # 用户的原始请求

        "parsed_contents": state.get("parsed_contents", {}),
        # 解析结果——analysis 和 spreadsheet 都需要

        "summary": state.get("summary", ""),
        # 总结内容（spreadsheet 不需要，传过去也没问题）
    }

    return [
        Send("analysis_node", state_updates),
        # 数据分析分支：统计/风险/趋势分析
        # 写入 state["analysis_result"]

        Send("finetuning_node", state_updates),
        # 微调数据分析分支：检测训练指标文件并分析
        # 写入 state["finetuning_result"]

        Send("document_node", state_updates),
        # 业务文档分析分支：分析工单/合同/报告等
        # 写入 state["document_result"]

        Send("spreadsheet_node", state_updates),
        # 电子表格分支：提取表格生成 Excel
        # 写入 state["xlsx_path"]

        # 注意: 四个 Send 使用的是同一份 state_updates
        # 但各自独立修改自己的字段，不会产生写入冲突
    ]
    # 返回 list[Send] 触发 LangGraph 的并行执行


def route_after_sync(state: WorkflowState) -> str:
    """同步完成后路由到 report"""
    # 同步完成后总是去 report_node
    # 类似 route_after_parser，使用条件边形式保持代码一致性
    # 未来可以加判断: 如果分析失败，是否仍然生成报告？还是只生成部分报告？
    return "report_node"
    # 固定路由到报告生成节点
