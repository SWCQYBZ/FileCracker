"""
文件: tools/registry.py | 中央工具注册中心
核心模式: Registry Pattern（注册表模式）
设计目标:
  1. 所有工具集中注册，Agent 通过名称发现和调用
  2. 统一管理(注册/查询/调用/鉴权)，而非散落在各处
  3. 解耦工具提供者和工具消费者

比喻: 就像手机的应用商店——开发者(工具创建者)注册 App，
     用户(Agent)在商店里搜索安装使用，双方不直接打交道
"""

# ============================================================
# Python 类型标注
# Any: 任何类型，工具函数的返回值可以是任意 Python 对象
# Callable: 可调用对象(函数)，标记工具函数
# Optional: 可能为 None 的类型
# ============================================================
from typing import Any, Callable, Optional
from pydantic import BaseModel  # 结构化数据校验


class ToolResult(BaseModel):
    """
    工具调用的统一返回格式
    无论工具内部做什么，都包装成这个结构
    好处: Agent 不用关心调用是否成功，统一判断 .success
    """
    success: bool = True     # 是否调用成功
    data: Any = None         # 成功时的返回数据
    error: Optional[str] = None  # 失败时的错误信息
    metadata: dict = {}      # 额外元信息（预留）


class ToolDefinition(BaseModel):
    """
    工具的定义信息
    注册时填写，Agent 和 API 通过这个了解工具
    """
    name: str                # 工具名称，唯一标识
    description: str         # 功能描述，给 LLM 看
    parameters: dict         # 参数说明，给 LLM 知道传什么参数
    agent: str               # 所属 Agent 名
    fn: Any = None           # 实际的可调用函数对象


class ToolRegistry:
    """
    核心: 工具注册中心

    设计模式:
    - 单例(Singleton): 全局只有一个 registry 实例
    - 注册表(Registry): 通过名称 -> 工具定义 的映射

    为什么不直接用 import 调用函数?
    - 硬编码: Agent 得知道具体函数名和路径
    - 难扩展: 新增工具需改调用方代码
    - 难治理: 无法统一做日志/限流/鉴权
    """

    def __init__(self):
        # 核心数据结构: 字典，键是工具名，值是工具定义
        # 选择 dict 而非 list: O(1) 查找速度
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, fn: Callable, name: str, description: str,
                 parameters: dict, agent: str) -> ToolDefinition:
        """
        注册一个工具到注册中心

        参数:
          fn: 工具函数本身（可调用对象）
          name: 工具唯一名称
          description: 描述（给 LLM 看，用于决定何时调用）
          parameters: 参数描述（给 LLM 看）
          agent: 所属 Agent 名称，用于权限过滤

        返回值:
          ToolDefinition 对象

        关键设计:
        - 如果重名则抛出异常，防止无意中覆盖
        - 名称冲突说明设计有问题，应该暴露而不是静默处理
        """
        if name in self._tools:
            # 防御性编程: 重名注册是 bug，不应静默覆盖
            raise ValueError(f"工具 '{name}' 已注册")
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            agent=agent,
            fn=fn,  # 存储函数引用，而非调用结果
        )
        self._tools[name] = tool_def
        return tool_def

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """按名称获取工具定义（如果不存在返回 None）"""
        return self._tools.get(name)

    def get_tools_for(self, agent_name: str) -> list[ToolDefinition]:
        """
        获取指定 Agent 可用的所有工具
        这是"授权"的简单实现——Agent 只能看到自己的工具
        未来可以加更复杂的权限策略
        """
        return [t for t in self._tools.values() if t.agent == agent_name]

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有已注册的工具"""
        return list(self._tools.values())

    async def call_tool(self, name: str, **params) -> ToolResult:
        """
        统一工具调用入口

        设计要点:
        1. 异步方法(async)，支持同步和异步两种工具函数
        2. 统一的错误处理，调用方不需要 try/except
        3. 统一返回 ToolResult 结构

        为什么用 `hasattr(fn, '__call__')` 判断?
        - 普通函数和实现了 __call__ 的类都有这个属性
        - 用于区分同步函数和异步协程函数
        - 更严谨的做法是用 inspect.iscoroutinefunction
        """
        # 1. 查找工具是否存在
        tool_def = self._tools.get(name)
        if not tool_def:
            return ToolResult(success=False, error=f"工具 '{name}' 不存在")
        # 2. 检查函数是否绑定
        if tool_def.fn is None:
            return ToolResult(success=False, error=f"工具 '{name}' 未绑定函数")
        # 3. 执行函数
        try:
            if hasattr(tool_def.fn, '__call__'):
                # 同步函数: 直接调用
                result = tool_def.fn(**params)
            else:
                # 异步函数: await 等待
                result = await tool_def.fn(**params)
            return ToolResult(success=True, data=result)
        except Exception as e:
            # 所有异常都捕获，不抛给调用方
            return ToolResult(success=False, error=str(e))


# ============================================================
# 全局单例实例
# 所有工具通过这个实例注册和访问
# 为什么用模块级变量而非类变量: Python 模块天然是单例
# 如果用类变量，多实例会有状态不一致的风险
# ============================================================
registry = ToolRegistry()
