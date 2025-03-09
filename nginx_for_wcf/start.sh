#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty

# 设置国内Alpine镜像源
sed -i 's/dl-cdn.alpinelinux.org/mirrors.cloud.tencent.com/g' /etc/apk/repositories

# 安装依赖
echo "正在安装依赖..."
apk update && apk add --no-cache curl luarocks

# 安装Lua库
luarocks install lua-resty-http
luarocks install lua-resty-openssl
luarocks install lua-cjson

# 配置LuaJIT库
if [ ! -d "/usr/local/openresty/luajit" ]; then
    mkdir -p /usr/local/openresty/luajit/lib
    ln -sf /usr/local/openresty/lualib/* /usr/local/openresty/luajit/lib/ 2>/dev/null || true
fi

# 处理配置模板
if [ -f "/etc/nginx/templates/nginx.conf.template" ]; then
    echo "处理nginx.conf模板..."
    cp /etc/nginx/templates/nginx.conf.template /usr/local/openresty/nginx/conf/nginx.conf
fi

# 检查配置并启动Nginx
nginx -t && exec nginx -g "daemon off;" 
