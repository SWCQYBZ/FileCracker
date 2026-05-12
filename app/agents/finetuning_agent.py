"""
文件: agents/finetuning_agent.py | Finetuning Agent - 微调数据分析
职责: 分析微调训练产出的文件，提取关键指标并生成分析报告

核心分析依据:
  1. trainer_log.jsonl → 逐 step 训练日志 + 收敛判断
  2. training_loss.png → 损失曲线图（自动检测展示）
  3. .json/.csv/.log/.txt → 辅助补充
"""

import json
import os
import shutil
from pathlib import Path
from openai import OpenAI
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, OUTPUT_DIR
from app.tools.registry import registry
from app.tools.finetuning_tool import generate_training_charts
from .base import BaseAgent


# 训练图表文件名关键词（自动检测匹配的图片）
CHART_KEYWORDS = ["loss", "curve", "train", "eval", "metric", "chart", "lr", "acc", "result", "learning"]


class FinetuningAgent(BaseAgent):
    """微调训练数据分析 Agent"""

    name = "finetuning"
    description = "微调数据分析 — 分析训练指标、loss 曲线、评估结果"
    tools = ["extract_training_metrics", "write_markdown"]

    def __init__(self):
        self.client = None
        if DEEPSEEK_API_KEY:
            self.client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    async def execute(self, state, context=None) -> dict:
        """执行微调数据分析"""
        parsed = state.get("parsed_contents", {})
        user_request = state.get("user_request", "")
        all_files = state.get("files", [])

        if not parsed:
            return {"finetuning_result": None}

        # 步骤1: 检查是否有训练相关的文件（核心：优先 JSONL）
        training_exts = {".jsonl", ".json", ".log", ".out", ".csv", ".txt"}
        training_files = {
            fn for fn in parsed.keys()
            if "." + fn.rsplit(".", 1)[-1].lower() in training_exts
        }
        if not training_files:
            return {"finetuning_result": None}

        # 步骤2: 检测训练图表图片（loss 曲线图等）
        chart_images = self._find_chart_images(all_files)

        # 步骤3: 调用工具提取结构化指标
        metrics_result = await registry.call_tool(
            "extract_training_metrics",
            parsed_contents=parsed,
        )
        metrics = metrics_result.data if metrics_result.success else {}

        # 步骤3b: 从 JSONL 数据自动生成训练曲线图
        jsonl_data = metrics.get("jsonl_data", {})
        if jsonl_data and jsonl_data.get("rows"):
            generated = generate_training_charts(jsonl_data, OUTPUT_DIR)
            # 把生成的图放前面，优先展示
            chart_images = generated + chart_images

        # 步骤4: LLM 综合分析
        llm_analysis = ""
        if self.client and metrics:
            llm_analysis = await self._llm_analyze(metrics, user_request)

        # 步骤5: 组装最终结果
        finetuning_result = {
            "metrics": metrics,
            "llm_analysis": llm_analysis,
            "summary": self._generate_summary(metrics, llm_analysis),
            "chart_images": chart_images,
        }

        return {
            "finetuning_result": finetuning_result,
            "agent_history": ["finetuning"],
        }

    @staticmethod
    def _find_chart_images(files: list) -> list[dict]:
        """
        扫描上传文件中匹配训练图表的图片，复制到输出目录

        匹配规则: 文件名包含 loss/curve/train/eval/metric/chart/lr/acc 等关键词
        """
        img_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
        keyword_lower = [k.lower() for k in CHART_KEYWORDS]
        found = []

        os.makedirs(OUTPUT_DIR, exist_ok=True)

        for f in files:
            fpath = getattr(f, "file_path", None) or getattr(f, "path", None) or ""
            fname = getattr(f, "filename", None) or Path(fpath).name
            ext = Path(fname).suffix.lower()
            name_lower = Path(fname).stem.lower()

            if ext not in img_exts:
                continue
            if not any(kw in name_lower for kw in keyword_lower):
                continue

            src = Path(fpath) if fpath else None
            if src and src.exists():
                # 复制到输出目录，避免文件名冲突
                dst_name = f"ft_chart_{len(found)}_{src.name}"
                dst = OUTPUT_DIR / dst_name
                try:
                    shutil.copy2(str(src), str(dst))
                    found.append({
                        "filename": dst_name,
                        "original": src.name,
                        "url": f"/api/v1/output/{dst_name}",
                        "size": src.stat().st_size,
                    })
                except OSError:
                    pass

        return found

    async def _llm_analyze(self, metrics: dict, user_request: str) -> str:
        """用 LLM 对训练指标做综合分析"""
        # 构建分析上下文
        summary = metrics.get("summary", {})
        json_files = metrics.get("json_files", {})
        jsonl_data = metrics.get("jsonl_data", {})
        csv_epochs = metrics.get("csv_epochs", [])
        log_analysis = metrics.get("log_analysis", "")

        context_parts = []

        # JSONL 逐 step 数据（核心）
        if jsonl_data and jsonl_data.get("rows"):
            conv = jsonl_data.get("convergence", {})
            stats = jsonl_data.get("stats", {})
            rows = jsonl_data.get("rows", [])
            context_parts.append("【trainer_log.jsonl 逐 Step 训练日志】")
            context_parts.append(f"总步数: {jsonl_data.get('step_count', 0)}")
            context_parts.append(f"字段: {', '.join(jsonl_data.get('fields', []))}")
            context_parts.append(f"可用指标: {', '.join(jsonl_data.get('available_metrics', []))}")
            if conv:
                context_parts.append(f"收敛判断: {conv.get('verdict', '')}")
                context_parts.append(f"趋势: {conv.get('trend', '')} — {conv.get('description', '')}")
                if "initial_loss" in conv:
                    context_parts.append(f"初始 loss: {conv['initial_loss']} → 最终 loss: {conv['final_loss']} (最小: {conv['min_loss']})")
            if stats:
                context_parts.append("各字段统计:")
                for field, s in stats.items():
                    context_parts.append(f"  {field}: first={s['first']}, last={s['last']}, min={s['min']}, max={s['max']}")
            # 显示前 5 条和后 5 条
            context_parts.append("--- 前 5 步 ---")
            for r in rows[:5]:
                context_parts.append(json.dumps(r, ensure_ascii=False))
            if len(rows) > 10:
                context_parts.append("... (中间省略) ...")
                context_parts.append("--- 后 5 步 ---")
                for r in rows[-5:]:
                    context_parts.append(json.dumps(r, ensure_ascii=False))

        # CSV 逐 epoch 数据
        if csv_epochs:
            context_parts.append(f"【CSV 逐 Epoch 数据】共 {len(csv_epochs)} 条")
            # 显示头尾
            for e in csv_epochs[:5]:
                context_parts.append(str(e))
            if len(csv_epochs) > 10:
                context_parts.append("... (中间省略)")
                for e in csv_epochs[-3:]:
                    context_parts.append(str(e))

        # 日志
        if log_analysis:
            context_parts.append(f"【日志分析】\n{log_analysis[:2000]}")

        # 预测样本
        preds = metrics.get("prediction_files", [])
        if preds:
            context_parts.append(f"【预测样例】共 {len(preds)} 个文件")
            for p in preds[:2]:
                context_parts.append(f"--- {p['filename']} ---\n{p['preview'][:500]}")

        prompt = "\n\n".join(context_parts)

        try:
            resp = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=4096,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": (
                        "你是一位 AI 模型微调训练专家。分析以下训练数据，输出 JSON 格式的分析报告：\n"
                        "{\n"
                        '  "overall_assessment": "总体评价（一句话概括训练效果）",\n'
                        '  "best_metrics": {"best_eval_loss": 数字, "best_eval_accuracy": 数字或null},\n'
                        '  "convergence_analysis": "收敛情况分析（loss 是否下降、是否过拟合）",\n'
                        '  "issues_and_warnings": ["问题列表"],\n'
                        '  "recommendations": ["改进建议列表"]\n'
                        "}\n"
                        "注意：只输出 JSON，不要其他文字。"
                    )},
                    {"role": "user", "content": (
                        f"用户需求: {user_request[:500]}\n\n"
                        f"训练数据:\n{prompt[:12000]}"
                    )},
                ],
            )
            text = resp.choices[0].message.content
            # 提取 JSON
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                parsed = json.loads(text[start:end])
                return parsed
            except (json.JSONDecodeError, ValueError):
                return {"overall_assessment": "LLM 分析解析失败", "issues_and_warnings": []}
        except Exception:
            return {"overall_assessment": "LLM 分析不可用", "issues_and_warnings": []}

    def _generate_summary(self, metrics: dict, llm: str | dict) -> str:
        """生成简短的中文总结"""
        summary = metrics.get("summary", {})
        jsonl_data = metrics.get("jsonl_data", {})
        parts = []

        if isinstance(llm, dict) and llm.get("overall_assessment"):
            parts.append(llm["overall_assessment"])

        # JSONL 收敛信息（核心）
        conv = jsonl_data.get("convergence", {})
        if conv.get("verdict"):
            parts.append(conv["verdict"])
        if conv.get("trend"):
            parts.append(f"收敛趋势: {conv['trend']}")
        if "initial_loss" in conv:
            parts.append(f"loss: {conv['initial_loss']} → {conv['final_loss']} (min: {conv['min_loss']})")

        steps = jsonl_data.get("step_count", 0)
        if steps:
            parts.append(f"训练步数: {steps}")

        # 传统指标（补充）
        best_loss = summary.get("best_eval_loss")
        if best_loss is not None and not conv:
            parts.append(f"最佳 eval_loss: {best_loss:.4f}")

        best_acc = summary.get("best_eval_accuracy")
        if best_acc is not None:
            parts.append(f"最佳 eval_accuracy: {best_acc:.4f}")

        epochs = summary.get("total_epochs", 0)
        if epochs:
            parts.append(f"训练轮数: {epochs}")

        if summary.get("training_completed"):
            parts.append("训练已正常完成")
        elif not conv:
            parts.append("训练状态未知")

        issues = summary.get("issues", [])
        if issues:
            parts.append(f"⚠️ 需关注: {'; '.join(issues[:3])}")

        # 文件统计
        fc = metrics.get("files_classified", {})
        file_counts = []
        for k, v in fc.items():
            if v:
                file_counts.append(f"{k}: {len(v)}")
        if file_counts:
            parts.append(f"分析文件: {', '.join(file_counts)}")

        return " · ".join(parts) if parts else "未发现训练数据"

    @staticmethod
    def _to_markdown_table(data: list[dict], title: str = "") -> str:
        """将 [{k: v}] 列表渲染为 Markdown 表格"""
        if not data:
            return ""
        # 收集所有列（保留顺序，排除 _source 等内部字段）
        seen = {}
        cols = []
        for row in data:
            for k in row:
                if k.startswith("_"):
                    continue
                if k not in seen:
                    cols.append(k)
                    seen[k] = True
        if not cols:
            return ""
        # 表头
        lines = []
        if title:
            lines.append(f"**{title}**")
            lines.append("")
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in data:
            vals = []
            for c in cols:
                v = row.get(c, "")
                if isinstance(v, float):
                    vals.append(f"{v:.6g}")
                else:
                    vals.append(str(v))
            lines.append("| " + " | ".join(vals) + " |")
        lines.append("")
        return "\n".join(lines)

    def _format_report(self, result: dict) -> str:
        """格式化为 Markdown 报告（含可视化表格）"""
        metrics = result.get("metrics", {})
        summary = metrics.get("summary", {})
        llm = result.get("llm_analysis", {})
        csv_epochs = metrics.get("csv_epochs", [])
        json_files = metrics.get("json_files", {})

        lines = [
            "# 微调训练数据分析报告",
            "",
        ]

        # ===== 1. 总体摘要 =====
        lines.extend(["## 一、总体摘要", "", result.get("summary", "无数据"), ""])

        # ===== 2. 关键指标 =====
        lines.append("## 二、关键指标")
        lines.append("")
        best_loss = summary.get("best_eval_loss")
        best_acc = summary.get("best_eval_accuracy")
        best_f1 = summary.get("best_eval_f1")
        train_loss = summary.get("train_loss")
        if any([best_loss, best_acc, best_f1, train_loss]):
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

        # ===== 3. 逐 Epoch 训练指标表格 =====
        if csv_epochs:
            lines.append("## 三、逐 Epoch 训练指标")
            lines.append("")
            lines.append(self._to_markdown_table(csv_epochs))

        # ===== 4. JSON 评估指标 =====
        if json_files:
            lines.append("## 四、JSON 评估明细")
            lines.append("")
            for fname, data in json_files.items():
                lines.append(f"**{fname}**")
                lines.append("")
                if isinstance(data, dict):
                    # 渲染为键值表格
                    items = []
                    for k, v in data.items():
                        if not isinstance(v, (dict, list)):
                            val = f"{v:.6g}" if isinstance(v, float) else str(v)
                            items.append({"参数": k, "数值": val})
                    if items:
                        lines.append(self._to_markdown_table(items))
                    else:
                        lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```")
                        lines.append("")
                elif isinstance(data, list):
                    lines.append(f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```")
                    lines.append("")

        # ===== 5. AI 评估 =====
        if isinstance(llm, dict) and llm.get("overall_assessment"):
            lines.extend(["## 五、AI 评估", ""])
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

        # ===== 6. 训练曲线图 =====
        charts = result.get("chart_images", [])
        if charts:
            lines.append("## 六、训练曲线图")
            lines.append("")
            for img in charts:
                lines.append(f"![{img['original']}]({img['url']})")
                lines.append("")
            lines.append("")

        # ===== 7. 日志分析 =====
        log = metrics.get("log_analysis", "").strip()
        if log:
            lines.extend(["## 七、日志分析", "", log, ""])

        # ===== 8. 文件清单 =====
        fc = metrics.get("files_classified", {})
        lines.extend(["## 八、分析文件清单", ""])
        for category, label in [
            ("metrics_json", "📊 评估指标 JSON"),
            ("csv", "📋 逐 epoch 明细"),
            ("logs", "📝 训练日志"),
            ("predictions", "🔤 预测输出"),
            ("model_weights", "⚙️ 模型权重"),
        ]:
            files = fc.get(category, [])
            if files:
                lines.append(f"**{label}** ({len(files)} 个)")
                for f in files:
                    lines.append(f"- {f}")
                lines.append("")

        lines.extend([
            "---",
            "*报告由微调数据分析 Agent 自动生成*",
        ])

        return "\n".join(lines)
