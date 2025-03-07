#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty /etc/nginx

# 设置国内Alpine镜像源
sed -i 's/dl-cdn.alpinelinux.org/mirrors.cloud.tencent.com/g' /etc/apk/repositories

# 安装依赖
apk update && apk add --no-cache git curl luarocks

# 安装lua-resty-http库
luarocks install lua-resty-http
# 安装lua-resty-openssl库 (解决mTLS支持问题)
luarocks install lua-resty-openssl
# 安装luasocket库 (URL解析和网络功能)
luarocks install luasocket

# 配置LuaJIT库
if [ ! -d "/usr/local/openresty/luajit" ]; then
    mkdir -p /usr/local/openresty/luajit/lib
    ln -sf /usr/local/openresty/lualib/* /usr/local/openresty/luajit/lib/ 2>/dev/null || true
fi

# 设置和验证Airflow相关环境变量
echo "AIRFLOW_BASE_URL: ${AIRFLOW_BASE_URL}"
echo "AIRFLOW_USERNAME: ${AIRFLOW_USERNAME}"
echo "AIRFLOW_PASSWORD: ${AIRFLOW_PASSWORD}"
echo "WX_MSG_WATCHER_DAG_ID: ${WX_MSG_WATCHER_DAG_ID}"

# 将环境变量导出到一个临时文件，供Nginx使用
# 使用更明确的方式导出关键环境变量
echo "AIRFLOW_BASE_URL=$AIRFLOW_BASE_URL" > /tmp/env.txt
echo "AIRFLOW_USERNAME=$AIRFLOW_USERNAME" >> /tmp/env.txt
echo "AIRFLOW_PASSWORD=$AIRFLOW_PASSWORD" >> /tmp/env.txt
echo "WX_MSG_WATCHER_DAG_ID=$WX_MSG_WATCHER_DAG_ID" >> /tmp/env.txt

# 显示导出的环境变量内容进行验证
echo "已导出以下环境变量到/tmp/env.txt文件:"
cat /tmp/env.txt

# Git配置
cd /app
git config --global --add safe.directory /app

# 启动Nginx
echo "启动Nginx服务..."
exec nginx -g "daemon off;" 
