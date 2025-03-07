#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/{logs,conf} /usr/local/openresty/lualib/resty /etc/nginx

# 安装依赖
apk update && apk add --no-cache git curl openssl openssh-client bash

# 配置LuaJIT库
if [ ! -d "/usr/local/openresty/luajit" ]; then
    mkdir -p /usr/local/openresty/luajit/lib
    ln -sf /usr/local/openresty/lualib/* /usr/local/openresty/luajit/lib/ 2>/dev/null || true
fi

# Git配置
cd /app
git config --global --add safe.directory /app

# 环境变量设置
[ -f /app/.env ] && export $(grep -v '^#' /app/.env | xargs)
export AIRFLOW_BASE_URL="${AIRFLOW_BASE_URL:-http://web:8080}"
export AIRFLOW_USERNAME="${AIRFLOW_USERNAME:-airflow}"
export AIRFLOW_PASSWORD="${AIRFLOW_PASSWORD:-airflow}"
export WX_MSG_WATCHER_DAG_ID="${WX_MSG_WATCHER_DAG_ID:-wx_msg_watcher}"

# 保存环境变量
cat > /usr/local/openresty/nginx/conf/nginx.env <<EOF
export AIRFLOW_BASE_URL="${AIRFLOW_BASE_URL}"
export AIRFLOW_USERNAME="${AIRFLOW_USERNAME}"
export AIRFLOW_PASSWORD="${AIRFLOW_PASSWORD}"
export WX_MSG_WATCHER_DAG_ID="${WX_MSG_WATCHER_DAG_ID}"
EOF

# 验证并启动Nginx
nginx -t && {
    source /usr/local/openresty/nginx/conf/nginx.env
    nginx -g "daemon off;"
} || exit 1 