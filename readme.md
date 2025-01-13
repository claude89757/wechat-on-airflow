# AI-Chatbot-Airflow-DAGs

## 项目说明

这是一个基于Airflow的AI聊天机器人数据处理系统，用于管理和调度AI模型的训练、数据处理等相关任务。系统采用Docker容器化部署，使用Redis作为缓存，PostgreSQL作为持久化存储。

## 目录结构

- [dags](./dags/readme.md) - 存放Airflow DAG任务文件
  - 包含AI聊天机器人相关的数据处理和训练任务
- [logs](./logs/readme.md) - 存放日志文件
  - 记录系统运行和任务执行的日志信息
- [requirements.txt](./requirements.txt) - 项目依赖包清单
  - 列出所有需要安装的Python包及其版本
- [docker-compose.yml](./docker-compose.yml) - Docker编排配置文件
  - 定义和配置项目所需的Docker服务
- [webhook_server.py](./webhook_server.py) - Webhook服务器
  - 处理外部系统的回调请求
- [database](./database) - 数据库相关配置
  - [redis](./database/redis/readme.md) - Redis缓存数据库
  - [postgresql](./database/postgresql/readme.md) - PostgreSQL关系型数据库
- [.env](./.env) - 环境变量配置文件
  - 存储项目所需的环境变量和密钥
- [.gitignore](./.gitignore) - Git忽略文件配置
  - 指定不需要纳入版本控制的文件和目录

## 使用说明

### 环境要求
- Docker 20.10+
- Docker Compose 2.0+
- Python 3.8+

### 快速开始

1. 克隆项目
   ```bash
   git clone https://github.com/your-username/AI-Chatbot-Airflow-DAGs.git
   cd AI-Chatbot-Airflow-DAGs
   ```

2. 配置环境变量
   ```bash
   cp .env.example .env
   # 编辑.env文件，填写必要的环境变量
   ```

3. 启动服务
   ```bash
   docker-compose up -d
   ```

4. 访问服务
   - Airflow Web界面: http://localhost:8080
   - 默认登录凭据:
     - 用户名: airflow
     - 密码: airflow

### DAG任务说明

系统包含以下主要DAG任务：

- `ai_chat.py`: AI聊天机器人的核心处理任务
- `wx_msg_watcher.py`: 微信消息监控任务
- `db_cleanup.py`: 数据库清理维护任务

### 数据库管理

- Redis缓存数据库
  - 端口: 6379
  - 主要用于存储临时会话数据

- PostgreSQL数据库
  - 端口: 5432
  - 用于存储持久化数据

### 日志查看

- 系统日志位于`logs`目录
- 可通过Airflow Web界面查看任务执行日志
- Docker容器日志可通过以下命令查看：
  ```bash
  docker-compose logs -f [service_name]
  ```

### 常见问题

1. 如果服务启动失败，请检查：
   - Docker服务是否正常运行
   - 端口是否被占用
   - 环境变量是否配置正确

2. 数据库连接问题：
   - 确认数据库容器是否正常运行
   - 检查数据库连接配置是否正确

### 维护与更新

1. 更新依赖包：
   ```bash
   pip install -r requirements.txt --upgrade
   ```

2. 更新Docker镜像：
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

