#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty /etc/nginx

# 设置国内Alpine镜像源
sed -i 's/dl-cdn.alpinelinux.org/mirrors.cloud.tencent.com/g' /etc/apk/repositories

# 安装依赖
echo "正在安装依赖..."
apk update && apk add --no-cache curl luarocks

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

# 处理配置文件中的环境变量
echo "处理配置文件中的环境变量..."

# 备份原始配置文件
cp /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak

# 处理 WEB_UI_URL
if [ -z "$WEB_UI_URL" ]; then
    echo "WEB_UI_URL 为空，删除相关配置..."
    # 删除 upstream web_ui_backend {...} 块
    sed -i '/upstream web_ui_backend/,/}/d' /etc/nginx/conf.d/default.conf
    # 删除 location / {...} 块
    sed -i '/location \/ {/,/}/d' /etc/nginx/conf.d/default.conf
else
    echo "替换 WEB_UI_URL: $WEB_UI_URL"
    sed -i "s|\${WEB_UI_URL}|$WEB_UI_URL|g" /etc/nginx/conf.d/default.conf
fi

# 处理 AIRFLOW_BASE_URL
if [ -z "$AIRFLOW_BASE_URL" ]; then
    echo "AIRFLOW_BASE_URL 为空，删除相关配置..."
    # 删除 upstream airflow_backend {...} 块
    sed -i '/upstream airflow_backend/,/}/d' /etc/nginx/conf.d/default.conf
    # 删除 location /airflow {...} 块
    sed -i '/location \/airflow {/,/}/d' /etc/nginx/conf.d/default.conf
else
    echo "替换 AIRFLOW_BASE_URL: $AIRFLOW_BASE_URL"
    sed -i "s|\${AIRFLOW_BASE_URL}|$AIRFLOW_BASE_URL|g" /etc/nginx/conf.d/default.conf
fi

# 处理 DIFY_URL
if [ -z "$DIFY_URL" ]; then
    echo "DIFY_URL 为空，删除相关配置..."
    # 删除 upstream dify_backend {...} 块
    sed -i '/upstream dify_backend/,/}/d' /etc/nginx/conf.d/default.conf
    # 删除 location /dify {...} 块
    sed -i '/location \/dify {/,/}/d' /etc/nginx/conf.d/default.conf
else
    echo "替换 DIFY_URL: $DIFY_URL"
    sed -i "s|\${DIFY_URL}|$DIFY_URL|g" /etc/nginx/conf.d/default.conf
fi

# 打印当前的全部环境变量
echo "当前的全部环境变量:"
env

# 打印替换后的配置文件
echo "替换后的配置文件内容:"
cat /etc/nginx/conf.d/default.conf

# 启动Nginx
echo "启动Nginx服务..."
exec nginx -g "daemon off;" 
