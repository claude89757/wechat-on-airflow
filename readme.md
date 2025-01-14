# AI-Chatbot-Airflow-DAGs

## 项目简介
基于Airflow的AI聊天机器人数据处理系统，用于管理和调度AI模型训练、数据处理等任务。系统采用Docker容器化部署，使用Redis作为缓存，PostgreSQL作为持久化存储。

## 技术栈
- Apache Airflow
- Docker & Docker Compose
- Redis
- PostgreSQL
- Python 3.8+

## 系统架构
```
AI-Chatbot-Airflow-DAGs/
├── dags/                    # Airflow DAG任务文件
│   ├── ai_chat.py          # AI聊天核心处理
│   ├── wx_msg_watcher.py   # 微信消息监控
│   └── tool_dags/          # 工具类DAG
│       └── db_cleanup.py   # 数据库清理任务
├── database/               # 数据库配置
│   ├── redis/             # Redis配置
│   └── postgresql/        # PostgreSQL配置
├── logs/                  # 系统日志
├── docker-compose.yml     # Docker服务编排
├── requirements.txt       # 项目依赖
├── webhook_server.py      # Webhook服务
├── .env                   # 环境变量配置
└── .gitignore            # Git忽略配置
```

## 快速开始

### 1. 环境准备
- Docker 20.10+
- Docker Compose 2.0+
- Python 3.8+

### 2. 部署步骤

1. 克隆项目
```bash
git clone https://github.com/your-username/AI-Chatbot-Airflow-DAGs.git
cd AI-Chatbot-Airflow-DAGs
```

2. 环境配置
```bash
cp .env.example .env
# 编辑.env文件，配置必要的环境变量
```

3. 启动服务
```bash
docker-compose up -d
```

### 3. 访问服务
- Airflow UI: http://localhost:8080
  - 用户名: airflow
  - 密码: airflow
- Redis: localhost:6379
- PostgreSQL: localhost:5432

## 核心功能

### DAG任务
1. **AI聊天处理** (ai_chat.py)
   - AI模型训练调度
   - 聊天数据处理

2. **消息监控** (wx_msg_watcher.py)
   - 微信消息监控
   - 消息队列处理

3. **系统维护** (db_cleanup.py)
   - 数据库定期清理
   - 系统性能优化

### 数据存储
- **Redis缓存**
  - 临时会话数据
  - 高频访问数据缓存

- **PostgreSQL数据库**
  - 用户数据持久化
  - 聊天历史记录
  - 系统配置信息

## 运维管理

### 日志管理
- 系统日志: `logs/`目录
- 任务日志: Airflow UI界面
- 容器日志查看:
```bash
docker-compose logs -f [service_name]
```

### 系统维护
1. 更新依赖
```bash
pip install -r requirements.txt --upgrade
```

2. 更新Docker服务
```bash
docker-compose pull
docker-compose up -d
```

## 故障排查

### 常见问题
1. **服务启动失败**
   - 检查Docker服务状态
   - 检查端口占用情况
   - 验证环境变量配置

2. **数据库连接异常**
   - 确认数据库容器运行状态
   - 检查数据库连接参数
   - 验证网络连通性

3. **任务执行失败**
   - 查看Airflow任务日志
   - 检查任务依赖配置
   - 验证资源使用情况

## 贡献指南
欢迎提交Issue和Pull Request来帮助改进项目。在提交代码前，请确保：
- 遵循项目代码规范
- 添加必要的测试用例
- 更新相关文档

## 许可证
[MIT License](LICENSE)

