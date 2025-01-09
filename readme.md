# AI-Chatbot-Airflow-DAGs

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

## 项目说明

这是一个基于Airflow的AI聊天机器人数据处理系统，用于管理和调度AI模型的训练、数据处理等相关任务。系统采用Docker容器化部署，使用Redis作为缓存，PostgreSQL作为持久化存储。
