"""
文件: agents/base.py | Agent 抽象基类
作用: 定义所有 Agent 的统一接口
设计模式: 模板方法模式(Template Method) + 策略模式(Strategy)

为什么需要基类?
1. 保证所有 Agent 有相同的 execute 接口
2. 新增 Agent 只需继承 + 实现 execute
3. 类型系统可以检查是否遗漏必要方法
4. IDE 可以给出正确的方法提示
"""

# ============================================================
# ABC = Abstract Base Class，Python 抽象基类
# abstractmethod = 抽象方法装饰器，子类必须实现
# ============================================================
from abc import ABC, abstractmethod
from typing import Any
from app.models.state import WorkflowState  # Agent 通过 State 通信


class BaseAgent(ABC):
    """
    所有 Agent 的抽象基类

    每个 Agent 有三个基本信息:
    - name: 唯一标识符，用于路由和日志
    - description: 功能描述，给 Planner 决定何时调用
    - tools: 该 Agent 能使用的工具列表

    核心方法 execute:
      输入: 当前 WorkflowState
      输出: 要更新的 State 片段(dict)
      注意: 不要返回完整 State，只返回要改的字段
    """

    name: str = ""               # Agent 名称，如 "planner", "parser"
    description: str = ""        # 功能描述，给 Planner Agent 看的
    tools: list[str] = []        # 允许调用的工具名列表

    @abstractmethod
    async def execute(self, state: WorkflowState, context: dict = None) -> dict:
        """
        执行 Agent 任务

        参数:
          state: 当前工作流状态（只读）
          context: 额外的上下文信息（预留）

        返回:
          要更新的状态字段 dict
          如: {"plan": plan, "status": "planning_completed"}

        设计原则:
        - 不要修改传入的 state（不可变）
        - 只返回要变更的字段（最小更新原则）
        - 如果出错，通过返回的 errors 字段传递而非抛异常
        """
        ...  # Ellipsis 表示由子类实现

    def get_tool_list(self) -> list[str]:
        """获取该 Agent 可用的工具列表"""
        return self.tools
