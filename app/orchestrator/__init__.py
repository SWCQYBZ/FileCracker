"""Orchestrator 包 - 工作流编排"""
# orchestrator/__init__.py
# 将 orchestrator 目录标记为 Python 包
# 对外暴露两个核心函数: create_workflow 和 run_workflow
# 包外部使用时:
#   from app.orchestrator import create_workflow, run_workflow

from .workflow import create_workflow, run_workflow
# 从 workflow 模块导入工作流构建和运行函数
# create_workflow: 构建 LangGraph StateGraph（定义节点和边的拓扑）
# run_workflow:   创建图 + 注入初始状态 + 调用 ainvoke 执行

__all__ = ["create_workflow", "run_workflow"]
# 定义 from orchestrator import * 时的导出列表
# 只暴露工作流的创建和运行入口，隐藏内部 node 实现细节
