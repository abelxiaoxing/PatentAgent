# 专利撰写助手 (Patent Drafting Assistant)

一个基于大语言模型的智能专利撰写工具，帮助专利代理师高效完成专利申请文件的撰写工作。

## ✨ 功能特性

- **智能生成专利纲要**：根据核心技术构思自动生成符合中国专利法要求的详细纲要
- **分章节撰写**：支持按章节生成和编辑专利文档内容
- **多模型支持**：支持 OpenAI 兼容 API 和 Google Gemini 模型
- **代理配置**：支持通过代理服务器访问 API
- **响应式界面**：基于 Streamlit 构建的直观易用的 Web 界面

## 🚀 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (推荐) 或 pip
- 有效的 API Key（OpenAI 或 Google Gemini）

### 安装步骤

1. 克隆仓库：
   ```bash
   git clone https://github.com/yourusername/PatentAgent.git
   cd PatentAgent
   ```

2. 使用 uv 同步依赖：
   ```bash
   # 安装 uv (如果尚未安装)
   curl -sSf https://astral.sh/uv/install.sh | sh
   
   # 同步依赖并创建虚拟环境
   uv sync
   ```



## 🖥️ 使用说明

1. 启动应用：
   ```bash
   uv run streamlit run app.py
   ```

2. 在左侧边栏配置 API 密钥和模型参数
3. 在文本框中输入核心技术构思，点击对应按钮即可生成
4. 审阅并修改自动生成的纲要
5. 逐章生成和编辑专利文档内容

## 📂 项目结构

```
PatentAgent/
├── main.py            # 主应用入口
├── .env               # 环境变量文件
├── pyproject.toml     # Python 依赖包
└── README.md          # 项目说明文档
```
## ⚙️ 配置说明

`.env` 文件记录了以下参数，注意保管您的api key：

```ini
# 选择模型提供商 (openai 或 google)
PROVIDER=openai

# OpenAI 兼容 API 配置
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_BASE=https://api.mistral.ai/v1  # 可替换为其他兼容API地址
OPENAI_MODEL=mistral-medium-latest

# Google Gemini 配置
GOOGLE_API_KEY=your_google_api_key
GOOGLE_MODEL=gemini-2.5-flash-preview-04-17

# 代理配置（可选）
PROXY_URL=http://127.0.0.1:7890
```
