#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty /etc/nginx

# 设置国内Alpine镜像源
sed -i 's/dl-cdn.alpinelinux.org/mirrors.cloud.tencent.com/g' /etc/apk/repositories

# 安装依赖
apk update && apk add --no-cache git curl luarocks

# 安装lua-resty-http库
luarocks install lua-resty-http

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

# 启动Nginx
nginx -g "daemon off;" 