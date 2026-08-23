# 个人每日简报

`personal_daily_briefing` DAG 每天调用 OpenAI Responses API 的 `web_search` 工具，检索最近 48 小时内与用户最相关的实质性变化，生成简体中文摘要，并复用现有 WeChat Sender 发送给一个受保护配置中的微信联系人。

## 默认行为

- 时区：`Asia/Shanghai`
- 计划：每天 `09:00`
- 检索窗口：最近 `48` 小时
- 条目上限：`8`
- 默认状态：关闭；部署代码本身不会发送任何消息
- 来源：优先官方公告、政府/学校/公司原始资料、GitHub 官方页面和高信誉媒体
- 低噪声：没有值得打扰的变化时会明确说明，不使用低价值内容凑数

默认主题覆盖：

1. OpenAI、ChatGPT、Codex、Anthropic、Claude、Cursor、MCP、智能体开发与 AI 原生产品；
2. `wechat-on-airflow`、agent-galaxy、pcapagent-studio、ioa-ssh-cli、netops-cli 等项目；
3. 嘉泉大学、韩国 D-2 留学签证、首尔租房和嘉泉大学通勤；
4. CourtVoice、网球语音/视频分析、ASR、Apple 平台和业余网球产品；
5. 会直接影响用户学习、出行、财务、产品或工作的国内外重大事件。

## Airflow Variables

| 名称 | 必需条件 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DAILY_BRIEFING_ENABLED` | 始终 | `false` | 只有设为 `true` 才生成和发送 |
| `DAILY_BRIEFING_OPENAI_API_KEY` | 启用时 | 空 | OpenAI API 密钥；敏感值 |
| `DAILY_BRIEFING_WECHAT_RECEIVER` | 启用时 | 空 | 微信联系人或群聊名称；敏感值，例如 `Tt` |
| `DAILY_BRIEFING_OPENAI_API_URL` | 否 | Responses API 地址 | 通常无需修改 |
| `DAILY_BRIEFING_MODEL` | 否 | `gpt-5.6` | 用于联网检索与摘要的模型 |
| `DAILY_BRIEFING_TOPICS` | 否 | 预置主题列表 | JSON 字符串数组；可覆盖默认关注范围 |
| `DAILY_BRIEFING_LOOKBACK_HOURS` | 否 | `48` | 检索时间窗口 |
| `DAILY_BRIEFING_REQUEST_TIMEOUT_SECONDS` | 否 | `300` | OpenAI 请求超时 |
| `DAILY_BRIEFING_MAX_ITEMS` | 否 | `8` | 最多 12 条，默认 8 条 |
| `DAILY_BRIEFING_STATE` | 应用管理 | `{}` | 当日草稿、发送状态和防重复信息 |

微信发送继续使用既有的 `WECHAT_SEND_*` Variables。不要把 API 密钥、收件人名称或发送端配置提交到仓库。

## 启用顺序

1. 先部署代码，保持 `DAILY_BRIEFING_ENABLED=false`。
2. 在受保护的 Airflow Variable 中写入 `DAILY_BRIEFING_OPENAI_API_KEY`。
3. 写入 `DAILY_BRIEFING_WECHAT_RECEIVER=Tt`，并按需调整主题、模型和检索窗口。
4. 确认 WeChat Sender `/readyz` 正常，且手机上的微信已登录。
5. 将 `DAILY_BRIEFING_ENABLED` 设为 `true`。下一次北京时间 09:00 会真实发送。

不要用单元测试、冒烟测试或 CI 触发真实消息。需要人工验证真实投递时，应使用受保护的生产流程并明确批准。

## 防重复与失败恢复

- 同一北京时间日期发送成功后，后续重跑会返回 `already_sent`，不会重复投递。
- OpenAI 生成成功后先把完整草稿保存到 `DAILY_BRIEFING_STATE`，再调用微信发送。
- 微信发送失败时，Airflow 重试复用同一份草稿，避免重复调用联网搜索和产生不一致内容。
- 当天确需重新发送时，先人工检查原因，再将 `DAILY_BRIEFING_STATE` 重置为 `{}` 后手动运行；这会产生真实消息。
- 每条微信文本按约 1,750 字符分段，并附带最多 8 个来源标题和原始链接。

## 验证

聚焦验证：

```bash
pytest -q tests/daily_briefing_test.py
```

仓库完整门禁：

```bash
make verify
```

测试覆盖检索窗口、来源解析、消息分段、默认关闭、同日幂等、失败草稿复用和请求契约。所有测试均替换外部调用，不会访问 OpenAI 或发送微信。
