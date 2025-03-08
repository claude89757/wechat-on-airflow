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

# 验证必需的环境变量
echo "验证环境变量配置..."

# 检查必需的环境变量
check_env_var() {
    if [ -z "${!1}" ]; then
        echo "错误: 必需的环境变量 $1 未设置"
        exit 1
    else
        if [ "$1" = "AIRFLOW_PASSWORD" ]; then
            echo "$1: ******"
        else
            echo "$1: ${!1}"
        fi
    fi
}

# 验证所有必需的环境变量
check_env_var AIRFLOW_BASE_URL
check_env_var AIRFLOW_USERNAME
check_env_var AIRFLOW_PASSWORD
check_env_var WX_MSG_WATCHER_DAG_ID


# 启动Nginx
echo "启动Nginx服务..."
exec nginx -g "daemon off;" 
