# wechat-on-airflow

## 项目简介

wechat-on-airflow 是一个基于 Apache Airflow 的项目，用于管理和编排 AI 驱动的微信聊天机器人工作流，实现自动回复消息、定时发送通知、自动更新菜单以及与微信 API 集成等自动化任务，提升微信机器人的响应效率和运营优化。

## 整体架构

```
                                        👤 👤 👤 👤 👤
                    +-------------------------------------------------+ 
                    |            🌐 Nginx (开源组件)(公网)              | 
                    +-------------------------------------------------+ 
                                              ↓
+-----------------------------------------------------------------------------------------+ 
|                      📊 WEB UI  （前端： 多账号管理、智能客服管理等）                         | 
+-----------------------------------------------------------------------------------------+ 
                                               ↓       
+-----------------------------------------------------------------------------------------+         +-----------+
|                                    ⚖️ Nginx (开源组件)(内网)                               | -[内网]->| 🔐 nacos  |  
+-----------------------------------------------------------------------------------------+         +-----------+
      |                                        |                             |
[内网]查询聊天记录(触发式）      [内网]发送消息\查询状态数据(触发式+定时任务）    [公网]知识库接口(触发式)       
      ↓                                        ↓                             ↓   
+---------+       +---------+       +------------------------+         +-------------------+       +-------------+
| ☁️ 云函数 | <---> | 💾 Mysql | <--->| ⭐️ Airflow （开源项目）   |-[跨境]->| 🤖 Dify （开源项目） | ----> | 🧠 大模型服务 |
+---------+       +---------+   <-> +------------------------+         +-------------------+       +-------------+
                               |            ↑              |
                               |    +-------------------+  |
     |--------------------------    | 🔌 Nginx (开源组件) |  WCF API
     |              |               +-------------------+  |
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
- Nginx: 主要负责负载均衡、转发流量等
```

## 个人微信功能列表

- [x] 接收文字消息
- [x] 接收图片消息
- [x] 接收视频消息
- [ ] 接收文件消息
- [x] 发送文字消息
- [x] 发送图片消息
- [x] 发送视频消息
- [ ] 发送文件消息

## 微信公众号功能列表

- [x] 接收文字消息
- [x] 接收图片消息
- [x] 接收视频消息
- [ ] 接收文件消息
- [x] 发送文字消息
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
