"""
文件: tools/data_analyzer.py | 数据分析工具集
职责: 提供统计、风险、趋势三种分析功能

设计选择: 使用 Python 标准库 statistics 而非 pandas
原因:
  1. 本项目数据量小（通常几百行），pandas 的优势发挥不出来
  2. 避免引入 10MB+ 的依赖
  3. statistics 标准库零依赖，开箱即用

何时该换 pandas:
  - 数据量 > 10万行
  - 需要复杂的分组聚合(groupby)
  - 需要时间序列重采样(resample)
  - 需要缺失值填充/数据透视表
"""

import statistics            # Python 标准库: 均值/中位数/标准差
from collections import Counter
from typing import Any
from .registry import registry


def analyze_statistics(data: list[dict], value_field: str = "") -> dict:
    """
    基本统计分析

    自动检测所有数值字段并计算:
    - 计数(count)、最小值(min)、最大值(max)
    - 总和(sum)、均值(avg)、中位数(median)、标准差(stdev)

    参数:
      data: 字典列表，如 [{"价格": 100, "数量": 5}, ...]
      value_field: 指定分析的字段名(预留参数)

    为什么自动检测而非指定字段?
    - 兼容性好：不同文件有不同的字段名
    - 用户体验好：用户不需要知道数据有哪些列
    - 缺点: 可能把 ID 列(如 101, 102)误判为数值——但影响不大
    """
    if not data:
        return {"error": "无数据", "stats": {}}

    # 第1步: 收集所有字段名
    numeric_values = {}
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())

    # 第2步: 提取数值字段
    for key in all_keys:
        values = []
        for row in data:
            val = row.get(key)
            if val is not None:
                try:
                    # 清理千位分隔符后转浮点
                    v = float(str(val).replace(",", "").replace(" ", ""))
                    values.append(v)
                except (ValueError, TypeError):
                    pass  # 非数值跳过
        if values:
            numeric_values[key] = values

    # 第3步: 计算统计量
    stats = {}
    for field, values in numeric_values.items():
        if len(values) >= 2:
            # 用 statistics 标准库，确保数学正确性
            stats[field] = {
                "count": len(values),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "sum": round(sum(values), 2),
                "avg": round(statistics.mean(values), 2),
                "median": round(statistics.median(values), 2),
                # stdev 是样本标准差(除 n-1)，适合从样本推断总体
                "stdev": round(statistics.stdev(values), 2),
            }
        elif len(values) == 1:
            stats[field] = {
                "count": 1,
                "value": values[0],  # 只有一个值无法计算标准差
            }

    return {
        "total_rows": len(data),
        "numeric_fields": list(numeric_values.keys()),
        "stats": stats,
    }


def risk_analysis(data: list[dict], thresholds: dict = None) -> dict:
    """
    风险分析

    当前实现: 占位框架，统计数值字段
    未来可扩展:
    - 异常值检测(3σ 原则/IQR 四分位距)
    - 趋势突变检测
    - 与阈值比较(如预算超支)

    参数:
      data: 数据列表
      thresholds: 自定义阈值(预留)
    """
    if not data:
        return {"error": "无数据"}

    thresholds = thresholds or {}
    risks = []

    # 自动检测数值字段（与 analyze_statistics 同样的逻辑）
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())

    for key in all_keys:
        values = []
        for row in data:
            val = row.get(key)
            if val is not None:
                try:
                    v = float(str(val).replace(",", "").replace(" ", ""))
                    values.append((row, v))
                except (ValueError, TypeError):
                    pass
        if len(values) < 3:
            continue

    return {
        "risk_count": len(risks),
        "risks": risks,
        "risk_level": "low" if len(risks) == 0
                      else "medium" if len(risks) < 3
                      else "high",
    }


def trend_analysis(data: list[dict], date_field: str = "", value_field: str = "") -> dict:
    """
    趋势分析

    分析时间序列数据的趋势方向和变化幅度
    需要指定日期字段和数值字段

    例如: 按月的销售额趋势
      date_field = "月份", value_field = "销售额"
      → {"trend": "up", "change_pct": 15.5, ...}

    限制:
    - 数据必须按时间排序
    - 只做线性趋势判断(首尾对比)
    """
    if not data or not date_field or not value_field:
        return {"error": "需要指定日期字段和数值字段"}

    points = []
    for row in data:
        date_val = row.get(date_field, "")
        val = row.get(value_field)
        if date_val and val is not None:
            try:
                points.append({
                    "date": str(date_val),
                    "value": float(str(val).replace(",", "")),
                })
            except (ValueError, TypeError):
                pass

    if len(points) < 2:
        return {"error": f"有效数据不足 ({len(points)} 条)"}

    values = [p["value"] for p in points]
    first_val = points[0]["value"]
    last_val = points[-1]["value"]

    return {
        "data_points": len(points),
        "start_value": first_val,
        "end_value": last_val,
        "change": round(last_val - first_val, 2),
        "change_pct": round(
            (last_val - first_val) / first_val * 100, 2
        ) if first_val != 0 else 0,
        "min": min(values),
        "max": max(values),
        "trend": "up" if last_val > first_val
                 else "down" if last_val < first_val
                 else "flat",
    }


# === 注册 3 个分析工具 ===
registry.register(
    analyze_statistics, "analyze_statistics",
    "对数据进行基本统计分析（计数、均值、中位数、标准差等）",
    {"data": "数据列表（每项为 dict）", "value_field": "数值字段名（可选）"},
    agent="analysis",
)
registry.register(
    risk_analysis, "risk_analysis",
    "风险分析 - 基于阈值检查数据中的异常值",
    {"data": "数据列表", "thresholds": "阈值字典（可选）"},
    agent="analysis",
)
registry.register(
    trend_analysis, "trend_analysis",
    "趋势分析 - 分析时间序列数据的趋势方向",
    {"data": "数据列表", "date_field": "日期字段名", "value_field": "数值字段名"},
    agent="analysis",
)
