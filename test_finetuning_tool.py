#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试微调分析工具
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from app.tools.finetuning_tool import extract_training_metrics


def test_finetuning_tool():
    """测试微调分析工具"""
    print("=" * 60)
    print("测试微调分析工具")
    print("=" * 60)
    print()

    # 测试文件列表
    test_files = [
        "test_files/training_stats.json",
        "test_files/train_log.log",
        "test_files/epoch_metrics.csv",
    ]

    parsed_contents = {}

    # 读取并解析文件
    print("[1/3] 读取测试文件...")
    for filepath in test_files:
        full_path = root_dir / filepath
        if full_path.exists():
            print(f"  读取: {filepath}")
            # 简单读取文件内容
            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()
            # 构造 ParsedContent 格式 - 用字典
            parsed_contents[Path(filepath).name] = {
                "text": text,
                "tables": [],
                "metadata": {}
            }
        else:
            print(f"  警告: 文件不存在 {filepath}")

    print()
    print("[2/3] 调用微调分析工具...")
    print()

    # 调用微调分析工具 - 把字典转成简单对象
    parsed_objs = {}
    for fname, content in parsed_contents.items():
        obj = type('', (), {})()
        obj.text = content["text"]
        obj.tables = content["tables"]
        obj.metadata = content["metadata"]
        parsed_objs[fname] = obj

    result = extract_training_metrics(parsed_objs)

    # 打印结果
    print("=" * 60)
    print("分析结果")
    print("=" * 60)
    print()

    # 摘要
    summary = result.get("summary", {})
    print("摘要信息:")
    print(f"  best_eval_loss: {summary.get('best_eval_loss')}")
    print(f"  best_eval_accuracy: {summary.get('best_eval_accuracy')}")
    print(f"  best_eval_f1: {summary.get('best_eval_f1')}")
    print(f"  total_epochs: {summary.get('total_epochs')}")
    print(f"  training_completed: {summary.get('training_completed')}")
    print(f"  issues: {summary.get('issues')}")
    print()

    # 文件分类
    print("文件分类:")
    file_class = result.get("files_classified", {})
    for category, files in file_class.items():
        if files:
            print(f"  {category}: {files}")
    print()

    # JSON 文件
    if result.get("json_files"):
        print("JSON 指标:")
        for fname, data in result["json_files"].items():
            print(f"  {fname}: {data}")
        print()

    # CSV Epochs
    if result.get("csv_epochs"):
        print("逐 Epoch 数据:")
        for epoch in result["csv_epochs"][:5]:  # 只显示前5个
            print(f"  {epoch}")
        if len(result["csv_epochs"]) > 5:
            print(f"  ... 还有 {len(result['csv_epochs']) - 5} 条")
        print()

    # 日志分析
    if result.get("log_analysis"):
        print("日志分析:")
        # 替换特殊字符避免编码问题
        log_text = result["log_analysis"].replace("✅", "[OK]").replace("⚠️", "[WARN]").replace("📊", "").replace("📈", "").replace("📉", "")
        print(log_text)
        print()

    print("[3/3] 测试完成！")


if __name__ == "__main__":
    test_finetuning_tool()
