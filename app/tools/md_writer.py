"""
文件: tools/md_writer.py | Markdown 文件写入工具
职责: 将 Markdown 内容写入文件

为什么需要这么简单的工具?
- 保持工具调用的一致性: 所有输出操作都通过 ToolRegistry
- 未来扩展点: 可以加模板渲染、语法检查、自动目录生成
"""

import os
from datetime import datetime
from app.config import OUTPUT_DIR
from .registry import registry


def write_markdown(content: str, filename: str = "", output_path: str = "") -> str:
    """
    将 Markdown 内容写入文件

    参数:
      content: Markdown 文本内容
      filename: 文件名（可选，不含路径）
      output_path: 完整输出路径（可选，优先级高于 filename）

    返回:
      文件绝对路径

    如果 output_path 和 filename 都没给:
      自动生成时间戳文件名: report_20240101_120000.md
    """
    if not output_path:
        # 确保输出目录存在
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        # 时间戳保证文件名唯一
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = filename or f"report_{ts}"
        if not name.endswith(".md"):
            name += ".md"                           # 确保扩展名正确
        output_path = str(OUTPUT_DIR / name)
    else:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 始终用 UTF-8 写入，保证中文不乱码
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


# === 注册工具 ===
registry.register(
    write_markdown, "write_markdown",
    "将内容写入 Markdown 文件",
    {"content": "Markdown 内容", "filename": "文件名（可选）", "output_path": "输出路径（可选）"},
    agent="summary",
)
