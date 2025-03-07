# Nginx + OpenResty 配置

本配置实现了三个主要功能：
1. 处理微信回调请求，并通过Airflow API触发相应的DAG
2. 提供健康检查端点

## 目录结构

```
nginx/
├── conf.d/            # Nginx配置文件目录
│   ├── default.conf   # 默认站点配置
│   └── nginx.conf     # 主Nginx配置文件
├── lua/               # Lua脚本目录
│   ├── github_webhook.lua  # GitHub Webhook处理脚本
│   └── wcf_callback.lua    # 微信回调处理脚本
├── logs/              # 日志目录
└── start.sh           # 容器启动脚本
```

## 配置说明

### 访问控制策略

- 本服务只开放三个特定的API端点:
  - `/wcf_callback`: 微信回调处理
  - `/health`: 健康检查端点
- 所有其他未明确定义的路径请求将返回404错误
- 不转发任何其他流量到Airflow后端


### 微信回调处理

- `/wcf_callback` 路径专门用于接收微信回调请求
- 使用Lua脚本处理请求并触发Airflow DAG
- 处理流程：
  1. 接收和验证微信回调JSON数据
  2. 记录客户端IP地址并添加到回调数据中
  3. 生成唯一的DAG运行ID
  4. 使用Airflow API触发指定的DAG，传递所有必要参数
  5. 包含完整的鉴权和错误处理

## 鉴权设置

Nginx容器会处理和Airflow的鉴权，通过以下方式：

1. 从环境变量获取Airflow凭据（用户名和密码）
2. 使用Basic认证方式调用Airflow API
3. 提供了.env文件挂载，支持从文件加载环境变量

需要设置的环境变量：
- `AIRFLOW_BASE_URL`: Airflow API基础URL（默认: http://web:8080）
- `AIRFLOW_USERNAME`: Airflow用户名
- `AIRFLOW_PASSWORD`: Airflow密码
- `WX_MSG_WATCHER_DAG_ID`: 要触发的DAG ID（默认: wx_msg_watcher）

## 权限处理

为确保有足够的权限执行git命令，我们：

1. 使用`root`用户运行Nginx容器
2. 在启动脚本中设置git全局安全目录
3. 将整个应用目录挂载到容器内的`/app`路径

## 测试 API

### 测试微信回调

```bash
curl -X POST http://your-server/wcf_callback \
  -H "Content-Type: application/json" \
  -d '{"roomid":"test-room","id":"123456","ts":"1621234567","content":"测试消息"}'
```

### 测试健康检查

```bash
curl http://your-server/health
```

## 故障排查

检查Nginx日志：

```bash
docker-compose logs nginx
```

或直接查看日志文件：

```bash
cat nginx/logs/error.log
``` 