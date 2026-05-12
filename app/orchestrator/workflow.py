"""LangGraph Workflow 构建 - 定义节点、边、执行入口"""
# orchestrator/workflow.py
# 这个文件是"工作流的建筑师"
# 它负责: 定义有哪些节点、节点之间的连接关系、怎么启动执行
#
# 类比: 如果把工作流比作一个工厂流水线
# - workflow.py = 工厂的布局图（机器放哪里、传送带怎么连）
# - nodes.py = 每个机器的操作手册（这台机器具体做什么）
#
# 核心 API:
#   create_workflow() → StateGraph（定义好的图结构，需要 compile 才能用）
#   run_workflow()    → dict（直接执行完整工作流并返回结果）
#
# 技术选型说明:
# 为什么用 StateGraph 而不是 FunctionGraph？
# - StateGraph: 所有节点共享一个全局状态（WorkflowState）
# - FunctionGraph: 每个节点有独立的输入/输出
# 选择 StateGraph 的原因:
#   1. 多 Agent 系统需要共享状态（解析结果→总结→分析）
#   2. 并行节点需要写入同一个状态的不同字段
#   3. 便于调试——任何时候可以查看完整的 State 快照

from langgraph.graph import StateGraph, START, END
# langgraph.graph 是 LangGraph 的核心模块
# StateGraph:   状态图构建器——所有节点共享一个全局状态
# START:        图的起始点（虚拟节点，不是真正的节点）
# END:          图的终止点（虚拟节点，图执行到此结束）

from langgraph.checkpoint.memory import MemorySaver
# MemorySaver: LangGraph 的检查点（Checkpointer）——在内存中保存状态快照
# 作用:
#   1. 支持"断点续传"——可以在某个节点暂停，然后恢复
#   2. 支持"回溯"——可以查看历史状态
#   3. 是 LangGraph 的"持久化"接口——可以用 SqliteSaver/PostgresSaver 替换
# 目前为什么用 MemorySaver？
#   分析流程通常很短（几十秒到几分钟），不需要持久化到数据库
#   未来如果支持"长时任务"（几小时的分析），可以换 PostgresSaver

from app.models.state import WorkflowState
# WorkflowState 是 TypedDict，定义了工作流中所有字段的类型
# 它被用作 StateGraph 的"状态模式"——LangGraph 根据它来:
#   1. 校验节点的返回值
#   2. 自动合并节点的输出到全局状态
#   3. 检查 State 中字段的 reducer 注解（如 Annotated[list, operator.add]）

from .nodes import (
    planner_node, parser_node, summary_node,
    analysis_node, finetuning_node, spreadsheet_node,
    document_node,
    sync_node, report_node,
    route_after_parser, route_after_summary, route_after_sync,
)
# 从 nodes.py 导入所有节点函数和路由函数
# 节点函数 (planner_node, parser_node, ...):
#   异步函数, (state) → dict, 实现了节点的具体逻辑
# 路由函数 (route_after_parser, ...):
#   同步函数, 决定条件边的走向


def create_workflow() -> StateGraph:
    """构建完整的 LangGraph StateGraph"""
    # 这个函数定义了工作流的拓扑结构
    # 调用一次 create_workflow() 得到一个编译好的 StateGraph
    # 可以多次调用（每次得到一个新的图实例）

    builder = StateGraph(WorkflowState)
    # 创建 StateGraph 构建器
    # WorkflowState 作为类型参数告诉 LangGraph 状态的结构
    # builder 是一个"图构建器"——它提供了 add_node、add_edge 等方法
    # 调用 compile() 之前可以任意修改图结构
    # compile() 之后图就不可变了

    # ========== 注册节点 ==========
    # add_node(name, function) 向图中添加一个节点
    # - name: 节点名称（字符串），在其他地方通过名称引用这个节点
    # - function: 节点执行函数（async def，接收 state 返回 dict）
    # 注意: 节点名称必须唯一，不能重复

    builder.add_node("planner_node", planner_node)
    # Planner: 分析请求，生成任务计划
    # 这是工作流的起点，输出 WorkflowPlan

    builder.add_node("parser_node", parser_node)
    # Parser: 解析所有上传文件
    # 依赖 Planner 完成后才能执行（但实际不依赖 Plan，是固定顺序）

    builder.add_node("summary_node", summary_node)
    # Summary: 总结解析结果
    # 必须在 Parser 之后，因为需要 parsed_contents

    builder.add_node("analysis_node", analysis_node)
    # Analysis: 数据分析
    # 在 Summary 之后（但分析本身只依赖 parsed_contents，不依赖 summary）

    builder.add_node("finetuning_node", finetuning_node)
    # Finetuning: 微调训练数据分析
    # 与 Analysis / Spreadsheet 并行——只依赖 parsed_contents

    builder.add_node("spreadsheet_node", spreadsheet_node)
    # Spreadsheet: 生成 Excel
    # 与 Analysis 并行——只依赖 parsed_contents

    builder.add_node("document_node", document_node)
    # Document: 业务文档分析
    # 与 Analysis / Finetuning / Spreadsheet 并行——只依赖 parsed_contents

    builder.add_node("sync_node", sync_node)
    # Sync: 同步点，等待 analysis 和 spreadsheet 都完成
    # 这是 fork-join 模式的 join 点

    builder.add_node("report_node", report_node)
    # Report: 汇总所有结果，生成最终 Markdown 报告
    # 必须在所有节点之后（因为需要所有节点的输出）

    # ========== 定义边 ==========
    # add_edge(from, to) 添加一条普通边（固定路由）
    # add_conditional_edges(from, router_fn, destinations) 添加条件边（动态路由）

    builder.add_edge(START, "planner_node")
    # 从 START 到 planner_node
    # START 是虚拟起点——工作流从这里开始执行
    # 相当于: "工作流启动后，首先运行 planner_node"

    builder.add_edge("planner_node", "parser_node")
    # Planner → Parser（串行）
    # Planner 完成后立即执行 Parser

    builder.add_edge("parser_node", "summary_node")
    # Parser → Summary（串行）
    # 所有文件解析完成后，开始总结

    # Summary → 并行 Analysis + Finetuning + Document + Spreadsheet
    builder.add_conditional_edges("summary_node", route_after_summary, [
        "analysis_node",
        "finetuning_node",
        "document_node",
        "spreadsheet_node",
    ])
    # 条件边: summary_node 完成后，调用 route_after_summary 决定去向
    # route_after_summary 返回 list[Send] → 启动三个并行分支
    # 第三个参数 [analysis_node, spreadsheet_node] 是"可能的目标节点列表"
    # 这个列表帮助 LangGraph 做静态验证——确保 Send 的目标都在这个列表中
    #
    # 执行流程:
    # 1. summary_node 完成
    # 2. LangGraph 调用 route_after_summary(state)
    # 3. 收到两个 Send → 并行执行 analysis 和 spreadsheet
    # 4. LangGraph 引擎等待两个分支都完成

    # 并行节点 → Sync
    builder.add_edge("analysis_node", "sync_node")
    # Analysis → Sync
    # analysis_node 完成后进入 sync_node
    # 但 LangGraph 会等待 spreadsheet_node 和 finetuning_node 也完成才执行 sync_node

    builder.add_edge("spreadsheet_node", "sync_node")
    # Spreadsheet → Sync
    # spreadsheet_node 完成后也进入 sync_node

    builder.add_edge("document_node", "sync_node")
    # Document → Sync
    # document_node 完成后也进入 sync_node

    builder.add_edge("finetuning_node", "sync_node")
    # Finetuning → Sync
    # 四条边指向同一个 sync_node → LangGraph 会等待四条边的源节点都完成
    # 这是 fork-join 模式的实现方式

    # Sync → Report → END
    builder.add_edge("sync_node", "report_node")
    # Sync → Report（串行）
    # 同步完成后，开始生成最终报告

    builder.add_edge("report_node", END)
    # Report → END
    # END 是虚拟终点——图执行到此为止
    # 报告生成完成，工作流结束

    # ========== 编译 ==========
    graph = builder.compile(checkpointer=MemorySaver())
    # compile() 将图定义"编译"为可执行的图
    # 在 compile 之前，图可以任意修改；compile 之后图是只读的
    # checkpointer=MemorySaver(): 启用内存检查点
    # 有了 checkpointer，可以:
    #   - 在任意节点暂停/恢复执行
    #   - 查看执行到某一步时的状态快照
    #   - 支持 thread_id 隔离（不同 session_id 独立执行）

    return graph
    # 返回编译好的 StateGraph 实例
    # 调用方（run_workflow）用这个实例的 ainvoke() 方法执行工作流


async def run_workflow(files: list, user_request: str, session_id: str) -> dict:
    """运行完整工作流"""
    # 这是外部调用的统一入口
    # API 层（routes/api.py）调用这个函数来启动分析流程
    #
    # 参数:
    #   files: list[FileInfo] — 要分析的文件列表
    #   user_request: str — 用户的分析请求
    #   session_id: str — 会话 ID（用于隔离不同任务）
    #
    # 返回:
    #   dict — 工作流执行结果（即最终状态 WorkflowState）

    graph = create_workflow()
    # 创建并编译一个新的 StateGraph
    # 每次调用都创建新图实例，避免状态污染
    # 但 repeated 创建有性能开销——高频场景可以缓存编译好的图

    initial_state = {
        # 工作流的初始状态
        # 这些字段会填充到 WorkflowState 中

        "session_id": session_id,
        # 会话 ID，用于日志追踪

        "files": files,
        # 文件列表

        "user_request": user_request,
        # 用户请求

        "plan": None,
        # 任务计划（Planner 生成，初始为 None）

        "current_task_index": 0,
        # 当前任务索引

        "task_results": {},
        # 任务结果字典

        "parsed_contents": {},
        # 解析结果（初始为空）

        "summary": None,
        # 总结内容（初始为空）

        "analysis_result": None,

        "finetuning_result": None,
        # 微调分析结果（初始为空）

        "document_result": None,
        # 业务文档分析结果（初始为空）

        "xlsx_path": None,
        # Excel 文件路径（初始为 None）

        "report_path": None,
        # 报告文件路径（初始为 None）

        "errors": [],
        # 错误列表

        "status": "running",
        # 状态标记

        "agent_history": [],
        # Agent 执行历史
    }

    config = {"configurable": {"thread_id": session_id}}
    # LangGraph 的执行配置
    # thread_id: 线程 ID，LangGraph 用它来区分不同的执行实例
    # 同一个 thread_id 可以继续执行（断点续传）
    # 不同 thread_id 的执行完全隔离

    result = await graph.ainvoke(initial_state, config)
    # ainvoke: LangGraph 的异步执行方法
    # 参数1: initial_state — 初始状态字典
    # 参数2: config — 执行配置（含 thread_id）
    #
    # 执行过程:
    # 1. LangGraph 从 START 开始
    # 2. 按边走，每到一个节点就调用节点函数
    # 3. 节点函数的返回值 merge 到状态中
    # 4. 到达 END 后，返回最终状态
    #
    # 返回: 最终状态的字典（即所有节点执行完毕后的 WorkflowState）

    return result
    # 返回完整的工作流执行结果
    # 包含: parsed_contents, summary, analysis_result, xlsx_path, report_path, errors, status 等
