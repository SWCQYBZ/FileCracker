"""
文件: tools/csv_processor.py | CSV 处理工具
职责: 解析 CSV 文件并分析其统计信息

CSV 的特殊性:
  虽然 CSV 是文本文件，但它是"结构化文本"
  按纯文本读就丢失了行列结构
  所以独立处理，保留表格数据结构
"""

import csv          # Python 内置 CSV 解析器，标准库无需安装
import io           # 内存中的文件流，用于从字符串模拟文件读取
import os
import chardet      # 编码检测库（与 read_txt 同样的编码问题）
from .registry import registry


def read_csv(file_path: str) -> dict:
    """
    解析 CSV 文件，返回文本和结构化数据

    返回两个视图:
    1. text: 原始的 CSV 内容（给 LLM 看）
    2. tables: 解析后的行列结构（给分析工具用）

    编码处理:
    CSV 文件常由 Excel 生成，Windows 下默认 GBK 编码
    直接用 UTF-8 读必现乱码，所以必须做编码检测
    """
    # 二进制读取 + 编码检测（与 read_txt 同一策略）
    with open(file_path, "rb") as f:
        raw = f.read()
    detected = chardet.detect(raw)
    encoding = detected.get("encoding", "utf-8") or "utf-8"

    # 用检测到的编码解码
    content = raw.decode(encoding, errors="replace")

    # 解析 CSV 行
    rows = []
    try:
        # StringIO: 把字符串包装成文件对象，满足 csv.reader 的输入要求
        reader = csv.reader(io.StringIO(content))
        for row in reader:
            # 过滤全空行（跳过 CSV 中的空行）
            if any(cell.strip() for cell in row):
                rows.append([cell.strip() for cell in row])
    except Exception:
        # CSV 格式错误时静默处理，返回原始文本
        pass

    return {
        "text": content,
        # 关键: 将整个 CSV 作为一张表，包在列表中
        # 因为 ParsedContent.tables 是 list[list[list]]
        # 每个元素是一张完整的表(二维数组)
        "tables": [rows] if len(rows) >= 2 else [],
        "metadata": {
            "encoding": encoding,           # 检测到的编码
            "rows": len(rows) - 1 if rows else 0,  # 数据行数(不含表头)
            "columns": rows[0] if rows else [],     # 列名
        },
    }


def analyze_csv(file_path: str) -> dict:
    """
    分析 CSV 数据统计信息

    自动识别数值列，计算基本统计量
    Excel 导出的 CSV 常含千位分隔符(1,234)，需要清理

    为何不直接用 pandas?
    - pandas 对这个简单任务过重
    - 安装 pandas(~10MB) 只为算平均值是过度杀伤
    - 但当数据量 >10万行时，应该换成 pandas
    """
    result = read_csv(file_path)
    rows = result.get("tables", [])  # 取解析后的表格数据

    # 至少需要表头+1行数据
    if len(rows) < 2:
        return {"error": "数据不足", "summary": result["text"]}

    headers = rows[0]      # 第一行是表头
    data = rows[1:]         # 后续行是数据

    summary = {
        "total_rows": len(data),
        "columns": len(headers),
        "column_names": headers,
        "column_stats": {},
    }

    # 逐列分析
    for col_idx, header in enumerate(headers):
        values = []
        for row in data:
            if col_idx < len(row):          # 防止行列不对齐
                val = row[col_idx]
                try:
                    # 清理千位分隔符后转数字
                    values.append(float(val.replace(",", "")))
                except (ValueError, AttributeError):
                    pass  # 非数值列跳过
        if values:
            summary["column_stats"][header] = {
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "count": len(values),
            }

    return summary


# === 注册两个工具到 Registry ===
registry.register(
    read_csv, "read_csv",
    "解析 CSV 文件，提取文本和结构化表格数据",
    {"file_path": "CSV 文件路径"},
    agent="parser",
)
registry.register(
    analyze_csv, "analyze_csv",
    "分析 CSV 数据，计算每列的基本统计信息",
    {"file_path": "CSV 文件路径"},
    agent="analysis",
)
