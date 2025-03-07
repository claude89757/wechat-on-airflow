#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty /etc/nginx

# 设置国内Alpine镜像源
sed -i 's/dl-cdn.alpinelinux.org/mirrors.cloud.tencent.com/g' /etc/apk/repositories

# 安装依赖
echo "正在安装依赖..."
apk update && apk add --no-cache git curl luarocks

# 验证git安装
echo "验证git安装..."
which git
if [ $? -ne 0 ]; then
    echo "Git安装失败，尝试重新安装..."
    apk add --no-cache --update git
    which git || echo "Git安装仍然失败!"
else
    echo "Git安装成功: $(git --version)"
fi

# 安装lua-resty-http库
luarocks install lua-resty-http
# 安装lua-resty-openssl库 (解决mTLS支持问题)
luarocks install lua-resty-openssl
# 安装cjson库 (JSON处理)
luarocks install lua-cjson

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
echo "PROXY_URL: ${PROXY_URL}"

# 将环境变量导出到一个临时文件，供Nginx使用
# 使用更明确的方式导出关键环境变量
echo "AIRFLOW_BASE_URL=$AIRFLOW_BASE_URL" > /tmp/env.txt
echo "AIRFLOW_USERNAME=$AIRFLOW_USERNAME" >> /tmp/env.txt
echo "AIRFLOW_PASSWORD=$AIRFLOW_PASSWORD" >> /tmp/env.txt
echo "WX_MSG_WATCHER_DAG_ID=$WX_MSG_WATCHER_DAG_ID" >> /tmp/env.txt
echo "PROXY_URL=$PROXY_URL" >> /tmp/env.txt

# 显示导出的环境变量内容进行验证
echo "已导出以下环境变量到/tmp/env.txt文件:"
cat /tmp/env.txt

# 检查/app目录
echo "检查/app目录..."
ls -la /app
if [ ! -d "/app/.git" ]; then
    echo "警告: /app目录下没有.git目录，可能不是有效的Git仓库"
fi

# Git配置
cd /app
echo "配置Git..."
git config --global --add safe.directory /app

# 如果存在PROXY_URL环境变量，则配置Git代理
if [ ! -z "$PROXY_URL" ]; then
    echo "检测到代理环境变量，配置Git使用代理: $PROXY_URL"
    git config --global http.proxy "$PROXY_URL"
    git config --global https.proxy "$PROXY_URL"
else
    echo "未检测到代理环境变量，Git将直接连接"
fi

# 测试Git连接
echo "测试Git连接..."
git status
if [ $? -ne 0 ]; then
    echo "Git仓库状态异常，请检查权限和配置"
else
    echo "Git仓库状态正常"
fi

# 启动Nginx
echo "启动Nginx服务..."
exec nginx -g "daemon off;" 
