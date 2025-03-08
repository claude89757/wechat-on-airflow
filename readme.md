# wechat-on-airflow

## 项目简介

wechat-on-airflow 是一个基于 Apache Airflow 的项目，用于管理和编排 AI 驱动的微信聊天机器人工作流，实现自动回复消息、定时发送通知、自动更新菜单以及与微信 API 集成等自动化任务，提升微信机器人的响应效率和运营优化。

## 整体架构

```
+-----------------------------------------------------------------------------------------+         +-----------+
|                      🌐 WEB UI  （前端： 多账号管理、智能客服管理等）                         | -[内网]->| 🔐 nacos  |
+-----------------------------------------------------------------------------------------+         +-----------+
      |                                        |                             |
查询聊天记录(触发式）             发送消息\查询状态数据(触发式+定时任务）        知识库接口(触发式)       
      ↓                                        ↓                             ↓   
+---------+       +---------+       +------------------------+         +-------------------+       +-------------+
| ☁️ 云函数 | <---> | 💾 Mysql | <--->| ⭐️ Airflow （开源项目）   |-[跨境]->| 🤖 Dify （开源项目） | ----> | 🧠 大模型服务 |
+---------+       +---------+  |<-> +------------------------+         +-------------------+       +-------------+
                               |            ↑              |
                               |    +------------------+   |
     |--------------------------    | 🔌 Webhook (自研) |  WCF API
     |              |               +------------------+   |
     |              |                       ↑              |
  新消息上报    发送消息\查询数据      [内网]上报新消息(触发式)  [内网]发送消息\查询数据(触发式+定时任务）
     |              |                       |              ↓
+---------+         |               +----------------------------+
| ☁️ 云函数 |         |               | 🔄 WCF (开源项目, Windows)   |
+---------+         |               +----------------------------+
     ↑              |                       ↑                |
     |              |                       |                |
  新消息上报     官方API接口               第三方Hook       第三方Hook
     |              ↓                       |                ↓
+----------------------------+      +---------------------------+
|       📢 微信公众号          |      | 💬 微信客户端 （Windows）    |
+----------------------------+      +---------------------------+


备注：
- WEB UI: 多账号管理的前端页面
- 个人微信客户端： 使用 wcf-client-rust 项目， 基于 wcf 协议， 实现微信客户端功能
- Webhook： 自研， 基于 HTTP API 实现
- Airflow： 开源项目， 用于管理和编排工作流
- Dify： 开源项目， 用于智能客服管理
- 大模型服务： 基于大模型 API 实现
- 云函数：使用腾讯云云函数，实现部分中转功能
- 微信公众号：官方提供的API接口
- Mysql: 购买腾讯云数据库，存储比较重要的聊天记录等数据
```

## 个人微信功能列表

- [x] 接收文字消息
- [ ] 接收图片消息
- [ ] 接收视频消息
- [ ] 接收文件消息
- [x] 发送文字消息
- [ ] 发送图片消息
- [ ] 发送视频消息
- [ ] 发送文件消息

## 微信公众号功能列表

- [x] 接收文字消息
- [ ] 接收图片消息
- [ ] 接收视频消息
- [ ] 接收文件消息
- [ ] 发送文字消息
- [ ] 发送图片消息
- [ ] 发送视频消息
- [ ] 发送文件消息


## 关联项目

- [前端UI](https://github.com/YuChanGongzhu/ai-agent)
- [airflow](https://github.com/apache/airflow)
- [wcf-client-rust](https://github.com/lich0821/wcf-client-rust)
- [dify](https://github.com/langgenius/dify)

---

**Contributors**

<a href="https://github.com/claude89757/wechat-on-airflow/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=claude89757/wechat-on-airflow" />
</a>

# Git Webhook 服务器

这是一个简单的 Git Webhook 服务器，用于自动更新代码仓库。当 GitHub 发送 webhook 请求时，服务器会自动拉取最新代码。

## 功能特点

- 使用 Flask 框架构建，代码简洁易维护
- 详细的日志记录（同时输出到控制台和日志文件）
- 轻量级，易于部署

## 安装

1. 确保已安装 Python 3.6+
2. 安装依赖：

```bash
pip install flask
```

## 配置

在 `git_webhook_server.py` 中可以配置以下参数：

- `PORT`：服务器监听端口（默认：5000）
- `LOG_FILE`：日志文件路径（默认：与脚本同目录下的 git_webhook.log）

## 使用方法

### 启动服务器

```bash
python git_webhook_server.py
```

### 后台运行

```bash
nohup python git_webhook_server.py &
```

### 查看日志

```bash
tail -f git_webhook.log
```

### 查看运行状态

```bash
ps aux | grep git_webhook_server.py
```

### 停止服务器

```bash
pkill -f git_webhook_server.py
```

## 在 GitHub 上配置 Webhook

1. 在 GitHub 仓库中，进入 Settings > Webhooks > Add webhook
2. 设置 Payload URL 为 `http://你的服务器IP:5000/update`
3. 选择 Content type 为 `application/json`
4. 选择触发事件（通常是 `push` 事件）
5. 点击 Add webhook 保存