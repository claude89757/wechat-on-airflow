from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_RESPONSES_API_URL = "https://api.openai.com/v1/responses"
DEFAULT_LOOKBACK_HOURS = 48
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300
DEFAULT_MAX_ITEMS = 8
DEFAULT_MAX_SOURCE_LINKS = 8
DEFAULT_MAX_WECHAT_MESSAGE_CHARS = 1750

DAILY_BRIEFING_ENABLED_VAR = "DAILY_BRIEFING_ENABLED"
DAILY_BRIEFING_OPENAI_API_KEY_VAR = "DAILY_BRIEFING_OPENAI_API_KEY"
DAILY_BRIEFING_OPENAI_API_URL_VAR = "DAILY_BRIEFING_OPENAI_API_URL"
DAILY_BRIEFING_MODEL_VAR = "DAILY_BRIEFING_MODEL"
DAILY_BRIEFING_WECHAT_RECEIVER_VAR = "DAILY_BRIEFING_WECHAT_RECEIVER"
DAILY_BRIEFING_TOPICS_VAR = "DAILY_BRIEFING_TOPICS"
DAILY_BRIEFING_LOOKBACK_HOURS_VAR = "DAILY_BRIEFING_LOOKBACK_HOURS"
DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS_VAR = "DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS"
DAILY_BRIEFING_MAX_ITEMS_VAR = "DAILY_BRIEFING_MAX_ITEMS"
DAILY_BRIEFING_STATE_VAR = "DAILY_BRIEFING_STATE"

DEFAULT_TOPICS = [
    (
        "核心人物动态：黄仁勋/NVIDIA、Sam Altman/OpenAI、埃隆·马斯克/"
        "xAI、Tesla、SpaceX、X；只收录会影响 AI、商业、产品或投资判断的实质变化"
    ),
    (
        "AI 与开发者工具：OpenAI/ChatGPT/Codex、Anthropic/Claude、Cursor、MCP、"
        "智能体开发、AI 原生产品、账号访问、iOS 登录、退款及数据导出变化"
    ),
    (
        "开源与产品项目：claude89757/wechat-on-airflow、agent-galaxy、"
        "pcapagent-studio、ioa-ssh-cli、netops-cli、codebuddy 工具及网络智能运维"
    ),
    (
        "韩国留学与生活：嘉泉大学研究生院/教育行政、D-2 留学签证广州领区、"
        "首尔租房及到嘉泉大学通勤的重要政策、期限和机会"
    ),
    (
        "网球与 CourtVoice：网球语音/视频分析、ASR、Apple 平台、业余网球产品、"
        "真正影响训练、比赛或产品机会的重要动态"
    ),
    "国内外重大事件：只收录会直接影响学习、出行、财务、产品或工作决策的事项",
]
