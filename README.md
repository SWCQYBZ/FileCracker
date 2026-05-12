<p align="center">
  <samp>
    <strong>FileCracker</strong>
    <br>
    多智能体文件分析系统
    <br>
    Multi-Agent File Analysis System
  </samp>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/LangGraph-0.4%2B-orange">
  <img src="https://img.shields.io/badge/FastAPI-0.115%2B-green">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey">
</p>

---

## 概述

**FileCracker** 是一个基于 **LangGraph** 的多智能体协作文件分析系统。用户上传文件并输入分析需求，系统会自动调度多个 AI Agent 协同工作——解析文件、总结内容、数据分析、微调训练分析、业务文档分析等，最终生成一份完整的 Markdown 分析报告。

> 如果把传统文件分析比作"一个人用一把刀切菜"，那 FileCracker 就是"一个后厨团队——有人洗菜、有人切菜、有人掌勺、有人摆盘"。

## 核心特性

| 特性 | 说明 |
|------|------|
| **多智能体协作** | 7 个 Agent 各司其职，通过 LangGraph 工作流编排并行执行 |
| **多格式支持** | PDF、DOCX、XLSX、CSV、JSON、XML、Markdown、TXT、图片（OCR）等多种文件格式 |
| **LLM 驱动** | 集成 DeepSeek API（兼容 OpenAI），无 API Key 时自动降级为规则引擎 |
| **业务文档分析** | 从工单、合同、报告中提取结构化字段（单号、状态、截止日期、风险等） |
| **微调训练分析** | 分析 JSONL 训练日志，检测收敛趋势，可视化 loss 曲线 |
| **数据分析** | 统计分析、风险检测，支持表格数据提取与 Excel 导出 |
| **会话管理** | 类 ChatGPT 侧边栏，历史对话自动保存，随时回溯 |
| **一键部署** | 单文件启动，无外部数据库依赖，可部署至阿里云等 VPS |

## 系统架构

```
用户请求 + 文件
     │
     ▼
┌──────────────────────────────────────────────────────┐
│                   Planner Agent                      │
│    分析用户需求，生成任务计划（LLM / 规则降级）        │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│                   Parser Agent                       │
│    解析所有文件（PDF/DOCX/CSV/JSON/图片/Excel...）    │
└────────────────────┬─────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────────┐
│                  Summary Agent                       │
│    汇总解析结果，按用户需求生成 Markdown 摘要          │
└────────────────────┬─────────────────────────────────┘
                     │
         ┌───────────┼───────────┬───────────┐
         ▼           ▼           ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
   │Analysis  │ │Finetune │ │Document │ │Spreadsheet   │
   │数据分析  │ │微调分析  │ │文档分析  │ │表格导出 XLSX │
   └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘
        └────────────┼────────────┼───────────────┘
                     ▼
            ┌──────────────────┐
            │    Sync Node     │
            │   等待并行完成    │
            └────────┬─────────┘
                     ▼
            ┌──────────────────┐
            │   Report Node    │
            │ 生成最终分析报告  │
            └──────────────────┘
```

### Agent 职责

| Agent | 职责 | 触发条件 |
|-------|------|----------|
| **Planner** | 分析用户需求，规划任务流程 | 每次分析启动时 |
| **Parser** | 根据文件类型调用对应解析工具 | Planner 完成后 |
| **Summary** | 汇总解析结果为 Markdown 摘要 | 所有文件解析完毕 |
| **Analysis** | 统计分析、风险检测、LLM 洞察（并行） | Summary 完成后 |
| **Finetuning** | 分析训练日志，检测收敛趋势（并行） | Summary 完成后 |
| **Document** | 提取业务文档结构化字段（并行） | Summary 完成后 |
| **Spreadsheet** | 提取表格数据生成 Excel（并行） | Summary 完成后 |
| **Sync** | 同步点，等待所有并行分支完成 | 并行分支全部完成 |
| **Report** | 整合所有结果，生成完整报告 | 同步完成 |

## 快速开始

### 环境要求

- Python 3.10+
- （可选）DeepSeek API Key

### 安装

```bash
# 克隆仓库
git clone https://github.com/SWCQYBZ/FileCracker.git
cd FileCracker

# 安装依赖
pip install -r requirements.txt

# 配置 API Key（可选，不配置则使用规则降级模式）
set DEEPSEEK_API_KEY=your_api_key_here
```

### 启动

```bash
python -m app.main
```

访问 [http://localhost:8000](http://localhost:8000) 即可使用。

### 使用流程

1. 在对话框中输入分析需求（如"分析这份合同的风险点"）
2. 上传文件（支持拖拽或点击上传）
3. 点击发送，系统自动调度 Agent 开始分析
4. 实时查看各 Agent 执行进度
5. 获取完整的 Markdown 分析报告

## 配置说明

通过环境变量配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（不配置则使用规则降级） | 无 |
| `DEEPSEEK_BASE_URL` | API 端点地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `API_HOST` | 服务监听地址 | `0.0.0.0` |
| `API_PORT` | 服务端口 | `8000` |

## 技术栈

- **LangGraph** — 有向图工作流引擎，编排多 Agent 协作
- **FastAPI** — 高性能异步 Web 框架
- **DeepSeek API** — LLM 驱动智能分析（兼容 OpenAI SDK）
- **openpyxl** — Excel 读写
- **PyMuPDF** — PDF 解析
- **python-docx** — Word 文档解析
- **Pandas** — 数据处理与统计分析
- **Tesseract OCR** — 图片文字识别

## 项目结构

```
FileCracker/
├── app/
│   ├── agents/          # AI Agent 定义
│   │   ├── planner.py       # 任务规划
│   │   ├── parser_agent.py  # 文件解析
│   │   ├── summary_agent.py # 内容总结
│   │   ├── analysis_agent.py# 数据分析
│   │   ├── finetuning_agent.py # 微调分析
│   │   ├── document_agent.py   # 文档分析
│   │   └── spreadsheet_agent.py# 表格导出
│   ├── models/          # 数据模型
│   │   ├── state.py         # LangGraph 状态定义
│   │   └── schemas.py       # API 响应模型
│   ├── orchestrator/    # 工作流编排
│   │   ├── workflow.py      # LangGraph 图构建
│   │   └── nodes.py         # 节点函数 + 路由
│   ├── routes/          # API 路由
│   │   └── api.py           # REST API 端点
│   ├── tools/           # 工具函数
│   │   ├── file_reader.py   # 文件读取
│   │   ├── csv_processor.py # CSV 处理
│   │   ├── data_analyzer.py # 数据分析
│   │   ├── finetuning_tool.py # 微调工具
│   │   ├── xlsx_generator.py  # Excel 生成
│   │   ├── ocr_tool.py      # OCR 识别
│   │   └── registry.py      # 工具注册中心
│   ├── config.py        # 配置
│   └── main.py          # 应用入口
├── static/
│   └── index.html       # 前端 SPA
├── uploads/             # 上传文件（自动清理）
├── output/              # 分析报告输出
└── requirements.txt     # 依赖清单
```

## 许可证

MIT License
