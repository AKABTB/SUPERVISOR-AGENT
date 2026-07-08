# Supervisor Agent · 目标监督助手

一个用于个人目标监督与交付追踪的助手。它通过定时提醒与交付审查两项机制，帮助使用者推动目标从计划走向落地。设计上刻意保持"约束"而非"辅助"的定位——它不提供建议、不发散讨论，只做进度督促和遗漏检查。

## 核心能力

| 能力 | 说明 |
|---|---|
| **交付审查** | 提交产出时对照目标检查遗漏，明确指出缺失项，不提供额外建议或发散。能识别"进行中""快完成"等未实际交付的表述。 |
| **进度督促** | 按设定的频率定时提醒，以是否实际交付作为唯一判定标准。 |
| **目标设定** | 支持自然语言设目标（LLM 抽取标题/频率/截止），并可将大目标拆成有序子目标；只翻译使用者已说出口的内容，不确定则反问，不替使用者构思目标。 |

## 特性

- **双端不同定位**：同一使用者在两个入口下对应不同的交互模式。
  - **Telegram 端**（执行/交付场景）：聚焦交付督促，锁定后的目标不可在此修改。
  - **Web 控制台**（管理场景）：提供全局视图，可自由增删改目标、设定主攻目标与督促频率。
- **自然语言设目标**：一句人话即可设目标，无需固定格式——由 LLM 抽取标题、督促频率、截止时间。解析不确定时会反问确认，不擅自补全或发散（沿用"只翻译输入、不替你想目标"的定位）。
- **目标拆分（父子目标）**：大目标可拆成有序子目标/里程碑。督促与审查始终落在"当前活跃的子目标"上（督促文案形如「大目标 · 当前子目标」），交掉一步自动推进到下一步。
- **单一主攻目标**：全局至多一个"主攻目标"参与督促，其余排队；主攻目标完成后队列自动顶替。
- **跨进程自同步**：Bot 与 Web 是两个独立进程、共享同一个 SQLite。在 Web 端修改目标后，Bot 内的定时器会在约 20 秒内自动感知并重新调度，无需重启。

## 技术栈

- **后端**：Python 3.11 · [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) · FastAPI · SQLite
- **前端**：Vue 3 + Vite（极简终端风格）
- **LLM**：基于 OpenAI 兼容接口，可切换 DeepSeek / OpenAI 等（见 `config.yaml` 的 `llm.provider`）

## 架构（四层）

```
交互层     Telegram Bot  +  Web 控制台          ← 仅负责收发、身份识别、转调核心层
核心层     进度督促 + 交付审查 + 意图识别 + 调度   ← 全部业务判断集中于此
存储层     SQLite 单文件（goals / delivery_logs / nag_logs）
LLM 适配层  统一 LLMClient 接口，切换服务商只需替换实现
```

交互层只负责消息收发，业务判断全部集中在核心层——因此 Bot 与 Web 复用同一套核心逻辑；新增第三种交互入口（如企业微信）只需在交互层扩展，核心层不受影响。

```
supervisor/
  __main__.py            统一入口
  config.py              加载 config.yaml + .env
  core/                  进度督促 / 交付审查 / 意图识别 / 目标解析 / 调度
  storage/               数据模型 + SQLite 存取
  llm/                   LLMClient 抽象 + OpenAI 兼容实现 + 工厂
  interfaces/
    telegram_bot.py      Telegram 交互 + JobQueue 定时 + 自校看门狗
    web/                 FastAPI 路由 + 托管前端 dist
web/frontend/            Vue3 + Vite 前端
scripts/                 自测脚本
```

## 快速开始

**前置**：Python 3.11、Node.js（构建前端用）。

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 配置（复制两份模板后填入真实值）
cp .env.example .env
cp config.example.yaml config.yaml
#   .env 中：
#     TELEGRAM_BOT_TOKEN     —— 从 @BotFather 获取
#     TELEGRAM_OWNER_CHAT_ID —— 使用者的 chat id（仅服务单一使用者）
#     DEEPSEEK_API_KEY / OPENAI_API_KEY —— 按 config.yaml 中选定的 provider 填写
#   config.yaml 中：LLM provider/model、base_url、Telegram 代理、时区等

# 3. 构建前端
cd web/frontend && npm install && npm run build && cd ../..
```

启动：

| 命令 | 作用 |
|---|---|
| `python -m supervisor` | 启动 Telegram Bot |
| `python -m supervisor web` | 启动 Web 控制台（默认 http://127.0.0.1:8000） |
| `python -m supervisor selfcheck` | 仅运行骨架自检（建库、读配置） |
| `cd web/frontend && npm run dev` | 前端开发模式（:5173，`/api` 代理到 :8000） |

> 修改前端后需重新执行 `npm run build` 并重启 web，否则托管的仍是旧构建产物。
> 若部署环境无法直连 Telegram，可在 `config.yaml` 的 `telegram.proxy` 填写代理地址；部署到可直连的服务器时留空即可。

## 配置

- `config.yaml` — 可读配置：LLM provider/model、数据库路径、时区、Telegram 代理、Web host/port（**不含密钥**）。照 `config.example.yaml` 复制填写，不纳入版本库。
- `.env` — 密钥（Telegram token、chat id、各服务商 LLM key），照 `.env.example` 复制填写，不纳入版本库。

## 许可证

[GPL-3.0](LICENSE)
