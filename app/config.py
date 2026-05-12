"""
文件: config.py | 全局配置中心
作用: 统一管理所有模块共享的配置项，一处修改全局生效
设计: 所有硬编码集中在此，业务代码只引用变量，不出现魔数
"""

# ============================================================
# 标准库导入
# ============================================================
import os  # 操作系统接口，用于读取环境变量和路径操作
from pathlib import Path  # 路径对象，比 os.path 更现代、跨平台兼容更好
from dotenv import load_dotenv  # 从 .env 文件加载环境变量

# ============================================================
# 项目根目录定位
# 原理: __file__ 是当前文件(config.py)的绝对路径
#       os.path.dirname 取目录 → 得到 app/
#       .parent 再取父目录 → 得到项目根目录
# 为什么不用相对路径: 脚本可能从任何目录执行，相对路径会错
# ============================================================
ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent

# 加载项目根目录下的 .env 文件（如果存在），优先级低于已设置的环境变量
load_dotenv(ROOT_DIR / ".env")

# ============================================================
# 目录配置
# UPLOAD_DIR - 用户上传文件的存放目录
# OUTPUT_DIR - 系统生成文件(报告/Excel)的输出目录
# 为什么分开: 上传的源文件和生成的产物生命周期不同
#             (源文件可删、产物要保留给用户下载)
# ============================================================
UPLOAD_DIR = ROOT_DIR / "uploads"  # ROOT_DIR/uploads/
OUTPUT_DIR = ROOT_DIR / "output"   # ROOT_DIR/output/
STATIC_DIR = ROOT_DIR / "static"   # ROOT_DIR/static/ 前端静态文件

# ============================================================
# DeepSeek API 配置（驱动 LLM 智能分析的核心配置）
# ============================================================
# 从环境变量读取 API Key，绝不硬编码在代码中
# 原因: 防泄露、环境隔离(开发/生产用不同 Key)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
# DeepSeek API 地址（兼容 OpenAI 接口格式）
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# 使用的大模型版本
DEEPSEEK_MODEL = "deepseek-v4-flash"

# ============================================================
# FastAPI 服务配置
# ============================================================
API_HOST = os.environ.get("API_HOST", "0.0.0.0")    # 监听所有网络接口，允许外部访问
API_PORT = int(os.environ.get("API_PORT", "8000"))   # 默认端口 8000，可环境变量覆盖
API_PREFIX = "/api/v1"                               # API 版本前缀，便于版本演进

# ============================================================
# LangGraph 工作流配置
# ============================================================
MAX_ITERATIONS = 10     # 最大迭代次数，防止 Agent 陷入无限循环
WORKFLOW_TIMEOUT = 300  # 单个工作流超时时间(秒)，5分钟

# ============================================================
# 支持的文件类型映射表
# 键: 文件扩展名(小写)
# 值: 内部类型标识符(用于路由到对应的解析器)
# 为什么用 dict 而非 if-else: 新增类型只需加一行，不改逻辑代码
# ============================================================
SUPPORTED_EXTENSIONS = {
    # 文档类
    ".pdf": "pdf",          # Adobe PDF，用 pymupdf 解析
    ".docx": "docx",        # Word 文档，用 python-docx 解析
    ".doc": "docx",         # 旧版 Word，兼容处理
    ".xlsx": "xlsx",        # Excel 2007+，用 openpyxl 解析
    ".xls": "xlsx",         # 旧版 Excel，兼容
    # 数据类
    ".csv": "csv",          # 逗号分隔值，用 csv 模块解析
    ".json": "json",        # JSON 数据，用 json 模块解析
    ".jsonl": "jsonl",      # JSON Lines，行分隔 JSON（常用于训练数据）
    # 标记类
    ".md": "markdown",      # Markdown，按文本处理
    ".txt": "text",         # 纯文本，自动检测编码
    ".xml": "xml",          # XML 标记语言
    ".yaml": "yaml",        # YAML 配置格式
    ".yml": "yaml",         # YAML 的短扩展名
    ".jinja": "text",       # Jinja 模板文件
    ".log": "text",         # 日志文件（含训练日志）
    ".out": "text",         # 输出日志
    # 图片类（用于 OCR）
    ".png": "image",        # PNG 格式图片
    ".jpg": "image",        # JPEG 格式图片
    ".jpeg": "image",       # JPEG 完整扩展名
    ".gif": "image",        # GIF 格式
    ".bmp": "image",        # BMP 位图
    ".tiff": "image",       # TIFF 多页图片
    ".webp": "image",       # WebP 格式
}
