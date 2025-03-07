#!/bin/sh

# 创建日志目录并设置权限
mkdir -p /usr/local/openresty/nginx/logs
chmod 755 /usr/local/openresty/nginx/logs

# 安装git和其他依赖（如果未安装）
echo "正在安装必要的依赖..."
apk update && apk add --no-cache git curl openssl

# 确保git可以在/app目录下运行
cd /app
git config --global --add safe.directory /app

# 检查环境变量
if [ -f /app/.env ]; then
    echo "检测到.env文件，加载环境变量..."
    export $(grep -v '^#' /app/.env | xargs)
fi

# 设置Airflow访问环境变量（如果未设置）
if [ -z "$AIRFLOW_BASE_URL" ]; then
    echo "设置默认Airflow基础URL..."
    export AIRFLOW_BASE_URL="http://web:8080"
fi

if [ -z "$AIRFLOW_USERNAME" ]; then
    echo "设置默认Airflow用户名..."
    export AIRFLOW_USERNAME="airflow"
fi

if [ -z "$AIRFLOW_PASSWORD" ]; then
    echo "设置默认Airflow密码..."
    export AIRFLOW_PASSWORD="airflow"
fi

if [ -z "$WX_MSG_WATCHER_DAG_ID" ]; then
    echo "设置默认微信消息监控DAG ID..."
    export WX_MSG_WATCHER_DAG_ID="wx_msg_watcher"
fi

# 将环境变量传递给Nginx
echo "配置Nginx环境变量..."
cat > /usr/local/openresty/nginx/conf/nginx.env <<EOF
export AIRFLOW_BASE_URL="${AIRFLOW_BASE_URL}"
export AIRFLOW_USERNAME="${AIRFLOW_USERNAME}"
export AIRFLOW_PASSWORD="${AIRFLOW_PASSWORD}"
export WX_MSG_WATCHER_DAG_ID="${WX_MSG_WATCHER_DAG_ID}"
EOF

# 检查Nginx配置
echo "验证Nginx配置..."
nginx -t

# 如果配置检查通过，启动Nginx
if [ $? -eq 0 ]; then
    echo "Nginx配置检查通过，启动服务..."
    # 加载环境变量并使用前台模式启动Nginx
    source /usr/local/openresty/nginx/conf/nginx.env
    nginx -g "daemon off;"
else
    echo "Nginx配置检查失败，退出..."
    exit 1
fi 