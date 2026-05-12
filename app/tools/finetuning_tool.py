"""
文件: tools/finetuning_tool.py | 微调数据分析工具集
职责: 从训练产出文件中提取关键指标

核心数据源:
  1. trainer_log.jsonl → 逐 step 训练日志 (loss/lr/step)，含收敛判断
  2. training_loss.png → 损失曲线图（自动检测展示）
  3. .json / .csv / .log / .txt → 辅助补充
"""

import json
import re
import os
from pathlib import Path


def extract_training_metrics(parsed_contents: dict) -> dict:
    """
    从解析内容中提取训练相关指标

    参数:
      parsed_contents: {filename: ParsedContent} — 来自 Parser 的输出

    返回:
      dict: 按文件类型分类的指标数据
    """
    result = {
        "json_files": {},       # 保存完整的 JSON 指标
        "jsonl_data": {},       # JSONL 逐 step 训练日志（核心数据）
        "csv_epochs": [],       # CSV 中的逐 epoch 数据
        "log_analysis": "",     # 日志关键信息
        "prediction_files": [],  # 预测结果文件
        "model_files": [],      # 模型权重文件
        "summary": {
            "best_eval_loss": None,
            "best_eval_accuracy": None,
            "best_eval_f1": None,
            "train_loss": None,
            "total_epochs": 0,
            "training_completed": False,
            "issues": [],
        },
        "files_classified": {
            "metrics_json": [], "jsonl": [], "logs": [], "csv": [],
            "predictions": [], "model_weights": [], "other": [],
        },
    }

    for filename, content in parsed_contents.items():
        ext = Path(filename).suffix.lower()
        text = content and content.text or ""

        if ext == ".json":
            # 尝试解析为训练指标 JSON
            parsed_json = _try_parse_json(text)
            if parsed_json:
                result["json_files"][filename] = parsed_json
                result["files_classified"]["metrics_json"].append(filename)
                _extract_json_metrics(parsed_json, result["summary"])
            else:
                result["files_classified"]["other"].append(filename)

        elif ext == ".jsonl":
            # JSONL 格式：每行一个 JSON 对象（LLaMA-Factory 标准输出）
            result["files_classified"]["jsonl"].append(filename)
            parsed = _parse_jsonl_metrics(text)
            result["jsonl_data"] = {
                "filename": filename,
                "rows": parsed.get("rows", []),
                "fields": parsed.get("fields", []),
                "available_metrics": parsed.get("available_metrics", []),
                "step_count": parsed.get("step_count", 0),
                "loss_field": parsed.get("loss_field"),
                "convergence": parsed.get("convergence", {}),
                "stats": parsed.get("stats", {}),
            }
            # 用 JSONL 数据更新 summary
            conv = parsed.get("convergence", {})
            if conv.get("min_loss") is not None:
                s = result["summary"]
                if s["best_eval_loss"] is None or conv["min_loss"] < s["best_eval_loss"]:
                    s["best_eval_loss"] = conv["min_loss"]
                if conv.get("final_loss") is not None:
                    s["train_loss"] = conv["final_loss"]
                s["total_epochs"] = max(s["total_epochs"], len(parsed.get("rows", [])))

        elif ext == ".csv":
            # 尝试从 CSV 文本中提取数值
            result["files_classified"]["csv"].append(filename)
            epochs = _parse_csv_metrics(text)
            result["csv_epochs"].extend(epochs)

        elif ext in (".log", ".out"):
            result["files_classified"]["logs"].append(filename)
            analysis = _analyze_log_text(text)
            result["log_analysis"] += f"\n=== {filename} ===\n" + analysis
            _extract_log_summary(analysis, result["summary"])

        elif ext == ".txt":
            result["files_classified"]["predictions"].append(filename)
            result["prediction_files"].append({
                "filename": filename,
                "preview": text[:1000],
            })

        elif ext in (".bin", ".safetensors"):
            result["files_classified"]["model_weights"].append(filename)
            result["model_files"].append(filename)

        else:
            result["files_classified"]["other"].append(filename)

    # 从 CSV epoch 数据中更新 summary
    if result["csv_epochs"]:
        values = [e for e in result["csv_epochs"] if e.get("eval_loss") is not None]
        if values:
            best = min(values, key=lambda x: x["eval_loss"])
            result["summary"]["best_eval_loss"] = best["eval_loss"]
            if best.get("eval_accuracy"):
                result["summary"]["best_eval_accuracy"] = best["eval_accuracy"]
        result["summary"]["total_epochs"] = len(result["csv_epochs"])

    return result


def _try_parse_json(text: str) -> dict | None:
    """尝试将文本解析为 JSON，支持 training_stats.json 常见格式"""
    if not text or not text.strip():
        return None
    text = text.strip()
    # 如果文本不是以 { 或 [ 开头，不处理
    if not (text.startswith("{") or text.startswith("[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_json_metrics(data: dict | list, summary: dict):
    """从解析后的 JSON 中递归查找训练指标"""
    if isinstance(data, dict):
        # 直接查找常见指标名
        key_map = {
            "eval_loss": "best_eval_loss",
            "eval_accuracy": "best_eval_accuracy",
            "eval_f1": "best_eval_f1",
            "eval_f1_score": "best_eval_f1",
            "train_loss": "train_loss",
        }
        for key, summary_key in key_map.items():
            if key in data and isinstance(data[key], (int, float)):
                val = data[key]
                if summary[summary_key] is None or (
                    summary_key == "best_eval_loss" and val < summary[summary_key]
                ):
                    summary[summary_key] = val

        # 检查训练状态
        if data.get("training_completed") or data.get("complete"):
            summary["training_completed"] = True
        if data.get("epoch"):
            summary["total_epochs"] = max(summary["total_epochs"], int(data["epoch"]))

        # 递归查找嵌套字典
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_json_metrics(v, summary)

    elif isinstance(data, list):
        for item in data:
            _extract_json_metrics(item, summary)


def _parse_csv_metrics(text: str) -> list[dict]:
    """
    从 CSV 文本中解析逐 epoch 指标

    期望表头含: epoch, train_loss, eval_loss, eval_accuracy, learning_rate 等
    """
    if not text:
        return []
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return []

    headers = [h.strip().lower().replace('"', "") for h in lines[0].split(",")]
    epochs = []

    for line in lines[1:]:
        if not line.strip():
            continue
        values = [v.strip().replace('"', "") for v in line.split(",")]
        if len(values) != len(headers):
            continue
        row = {}
        for i, h in enumerate(headers):
            if i < len(values):
                try:
                    row[h] = float(values[i])
                except ValueError:
                    row[h] = values[i]
        if row.get("epoch") is not None or row.get("eval_loss") is not None:
            epochs.append(row)

    return epochs


def _analyze_log_text(text: str) -> str:
    """从训练日志中提取关键信息"""
    if not text:
        return "（空日志）"

    parts = []

    # 检查训练是否完成
    if re.search(r"(training\s*complete|finished|done|成功|完成)", text, re.I):
        parts.append("✅ 训练已完成")

    # 检查错误
    errors = re.findall(r"(?i)(error|exception|traceback|失败|报错)", text)
    if errors:
        # 提取错误行上下文
        error_lines = []
        for i, line in enumerate(text.split("\n")):
            if re.search(r"(?i)(error|exception|traceback)", line):
                ctx = "\n".join(text.split("\n")[max(0, i - 1):i + 3])
                error_lines.append(ctx[:300])
        parts.append(f"⚠️ 发现 {len(errors)} 个错误/警告:\n" + "\n---\n".join(error_lines[:5]))
    else:
        parts.append("✅ 日志中未发现错误")

    # 检查 loss 趋势（取最后的部分）
    loss_pattern = re.findall(r"(?i)(loss[:\s]*=?)\s*([\d.]+)", text)
    if loss_pattern:
        losses = [float(l[1]) for l in loss_pattern[-20:]]
        if len(losses) >= 2:
            first, last = losses[0], losses[-1]
            if last < first:
                parts.append(f"📉 Loss 呈下降趋势: {first:.4f} → {last:.4f}（收敛良好）")
            else:
                parts.append(f"📈 Loss 未下降: {first:.4f} → {last:.4f}（需关注）")

    # 提取 step 信息
    steps = re.findall(r"(?i)(step|steps|iteration)[:\s]*(\d+)", text)
    if steps:
        total_steps = max(int(s[1]) for s in steps)
        parts.append(f"📊 总训练步数: {total_steps}")

    return "\n".join(parts)


def _parse_jsonl_metrics(text: str) -> dict:
    """
    解析 trainer_log.jsonl 格式（每行一个 JSON 对象）

    LLaMA-Factory 等框架训练时逐 step 输出的结构:
      {"loss": 3.21, "learning_rate": 5e-5, "step": 10, "epoch": 0.1, "grad_norm": 1.2}

    返回:
      rows:       所有行数据（用于 LLM 分析和表格渲染）
      fields:     出现的所有字段名
      step_count: 总步数
      summary:    统计摘要 + 收敛判断
    """
    if not text or not text.strip():
        return {"rows": [], "fields": [], "step_count": 0, "summary": {}}

    lines = text.strip().split("\n")
    rows = []
    field_set = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
                for k in obj:
                    field_set[k] = True
        except json.JSONDecodeError:
            continue

    if not rows:
        return {"rows": [], "fields": [], "step_count": 0, "summary": {}}

    fields = sorted(field_set.keys())

    # 识别数值型训练指标
    known_metrics = {
        "loss", "train_loss", "eval_loss", "learning_rate", "lr",
        "current_lr", "step", "global_step", "epoch", "grad_norm",
        "gradient_norm", "accuracy", "eval_accuracy", "eval_f1",
    }
    available = [f for f in fields if f in known_metrics]

    # 识别 loss 字段（优先级: loss > train_loss > eval_loss）
    loss_field = next((c for c in ["loss", "train_loss", "eval_loss"] if c in field_set), None)

    # 提取 loss 序列
    loss_values = []
    for row in rows:
        if loss_field and loss_field in row and isinstance(row[loss_field], (int, float)):
            loss_values.append(row[loss_field])

    # === 收敛分析 ===
    convergence = {}
    if len(loss_values) >= 3:
        initial = loss_values[0]
        final = loss_values[-1]
        min_val = min(loss_values)
        min_idx = loss_values.index(min_val)

        convergence["initial_loss"] = round(initial, 6)
        convergence["final_loss"] = round(final, 6)
        convergence["min_loss"] = round(min_val, 6)
        convergence["min_loss_at_step"] = min_idx + 1  # 1-based step

        # 看最后 20% 步数的趋势（至少 5 步）
        tail_count = max(len(loss_values) // 5, 5)
        tail = loss_values[-tail_count:]
        half = len(tail) // 2
        first_half_avg = sum(tail[:half]) / half
        second_half_avg = sum(tail[-half:]) / half
        delta = second_half_avg - first_half_avg
        threshold = 0.01 * max(abs(first_half_avg), 0.001)

        if delta < -threshold:
            convergence["trend"] = "下降中"
            convergence["description"] = "loss 仍在下降，继续训练可能进一步优化"
        elif delta < threshold:
            convergence["trend"] = "已平稳"
            convergence["description"] = "loss 已趋于平稳，模型基本收敛"
        else:
            convergence["trend"] = "上升中"
            convergence["description"] = "loss 有上升趋势，可能存在过拟合"

        # 总体判断
        if final < initial * 0.3:
            convergence["verdict"] = "✅ 训练有效，loss 显著下降"
        elif final < initial * 0.7:
            convergence["verdict"] = "✅ 训练有效，loss 明显下降"
        elif final < initial * 0.9:
            convergence["verdict"] = "⚠️ 训练效果一般，loss 略有下降"
        else:
            convergence["verdict"] = "❌ 训练效果不佳，loss 未明显下降"
    else:
        convergence["trend"] = "数据不足"
        convergence["description"] = "loss 数据点少于 3 条，无法分析收敛"

    # 各字段统计
    stats = {}
    for field in available:
        values = []
        for row in rows:
            v = row.get(field)
            if isinstance(v, (int, float)):
                values.append(v)
        if values:
            entry = {
                "first": round(values[0], 6) if isinstance(values[0], float) else values[0],
                "last": round(values[-1], 6) if isinstance(values[-1], float) else values[-1],
                "min": round(min(values), 6) if isinstance(min(values), float) else min(values),
                "max": round(max(values), 6) if isinstance(max(values), float) else max(values),
            }
            # loss 才需要平均值
            if field in ("loss", "train_loss", "eval_loss"):
                entry["avg"] = round(sum(values) / len(values), 6)
            stats[field] = entry

    return {
        "rows": rows,
        "fields": fields,
        "available_metrics": available,
        "step_count": len(rows),
        "loss_field": loss_field,
        "convergence": convergence,
        "stats": stats,
    }


def _extract_log_summary(analysis: str, summary: dict):
    """从日志分析中提取摘要信息"""
    if "训练已完成" in analysis:
        summary["training_completed"] = True
    if "⚠️" in analysis:
        summary["issues"].append("训练日志中存在错误/警告")


def generate_training_charts(jsonl_data: dict, output_dir: Path) -> list[dict]:
    """
    根据 JSONL 数据绘制训练曲线图

    自动生成：
      - loss 曲线（含最低点标注）
      - learning_rate 曲线（如果数据中包含 lr 字段）

    返回：chart_images 列表，与 _find_chart_images 格式一致
    """
    rows = jsonl_data.get("rows", [])
    if not rows:
        return []

    # 提取 loss 数据
    loss_field = jsonl_data.get("loss_field")
    if not loss_field:
        return []

    step_field = next((f for f in ["step", "global_step"]
                       if f in jsonl_data.get("fields", [])), "step")

    steps, losses = [], []
    for row in rows:
        s = row.get(step_field, len(steps) + 1)
        l = row.get(loss_field)
        if isinstance(s, (int, float)) and isinstance(l, (int, float)):
            steps.append(s)
            losses.append(l)

    if not steps or not losses:
        return []

    # 检测是否有 lr 数据
    lr_field = next((f for f in ["learning_rate", "lr", "current_lr"]
                     if f in jsonl_data.get("fields", [])), None)
    lr_values = []
    if lr_field:
        for row in rows:
            lr = row.get(lr_field)
            if isinstance(lr, (int, float)):
                lr_values.append(lr)

    results = []

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        # 设置中文字体
        plt.rcParams['axes.unicode_minus'] = False
        try:
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei',
                                                'WenQuanYi Micro Hei', 'DejaVu Sans']
        except Exception:
            pass

        min_loss = min(losses)
        min_idx = losses.index(min_loss)

        if lr_values:
            # 双图模式：Loss + LR
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
            ax1.plot(steps, losses, 'b-o', markersize=3, linewidth=1.5, label='Loss')
            ax1.axhline(y=min_loss, color='r', linestyle='--', alpha=0.5)
            ax1.annotate(f'Min Loss: {min_loss:.4f}',
                         xy=(steps[min_idx], min_loss),
                         xytext=(steps[min_idx], min_loss * 1.1),
                         arrowprops=dict(arrowstyle='->', color='r'),
                         fontsize=10, color='r')
            ax1.set_xlabel('Step')
            ax1.set_ylabel('Loss')
            ax1.set_title('Training Loss')
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            ax2.plot(steps[:len(lr_values)], lr_values,
                     'g-o', markersize=3, linewidth=1.5, label='LR')
            ax2.set_xlabel('Step')
            ax2.set_ylabel('Learning Rate')
            ax2.set_title('Learning Rate Schedule')
            ax2.legend()
            ax2.grid(True, alpha=0.3)

            fig.suptitle('Training Process Overview', fontsize=14, fontweight='bold')
            plt.tight_layout()
        else:
            # 单图模式
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(steps, losses, 'b-o', markersize=3, linewidth=1.5, label='Loss')
            ax.axhline(y=min_loss, color='r', linestyle='--', alpha=0.5)
            ax.annotate(f'Min Loss: {min_loss:.4f}',
                        xy=(steps[min_idx], min_loss),
                        xytext=(steps[min_idx], min_loss * 1.1),
                        arrowprops=dict(arrowstyle='->', color='r'),
                        fontsize=10, color='r')
            ax.set_xlabel('Step')
            ax.set_ylabel('Loss')
            ax.set_title('Training Loss Curve')
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()

        # 保存
        os.makedirs(str(output_dir), exist_ok=True)
        chart_filename = "ft_chart_generated_loss.png"
        chart_path = Path(str(output_dir)) / chart_filename
        fig.savefig(str(chart_path), dpi=150, bbox_inches='tight')
        plt.close(fig)

        results.append({
            "filename": chart_filename,
            "original": "auto_generated_loss_chart.png",
            "url": f"/api/v1/output/{chart_filename}",
            "size": chart_path.stat().st_size,
        })

    except ImportError:
        pass
    except Exception:
        import traceback
        traceback.print_exc()

    return results


# === 注册 ===
from .registry import registry

registry.register(
    extract_training_metrics, "extract_training_metrics",
    "从微调训练输出文件中提取关键指标（loss、accuracy、epoch 等）",
    {"parsed_contents": "解析后的文件内容字典 {filename: ParsedContent}"},
    agent="finetuning",
)
