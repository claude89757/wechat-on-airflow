#!/bin/sh

# 创建必要目录
mkdir -p /usr/local/openresty/nginx/conf /usr/local/openresty/lualib/resty /etc/nginx/conf.d

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

# 打印环境变量
echo "当前的环境变量:"
env

# 处理配置模板
echo "开始处理配置模板..."

# 渲染 default.conf 模板
echo "渲染 default.conf 模板..."
if [ -f "/etc/nginx/templates/default.conf.template" ]; then
    # 替换模板中的变量（使用处理后的无协议URL）
    sed -e "s#\${WEB_UI_URL}#$WEB_UI_URL#g" \
        -e "s#\${AIRFLOW_BASE_URL}#$AIRFLOW_BASE_URL#g" \
        -e "s#\${DIFY_URL}#$DIFY_URL#g" \
        /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
    
    echo "default.conf 模板渲染完成"
    echo "default.conf 模板内容:"
    cat /etc/nginx/conf.d/default.conf
else
    echo "警告: default.conf 模板文件不存在!"
fi

# 渲染 nginx.conf 模板
echo "渲染 nginx.conf 模板..."
if [ -f "/etc/nginx/templates/nginx.conf.template" ]; then
    cp /etc/nginx/templates/nginx.conf.template /usr/local/openresty/nginx/conf/nginx.conf
    echo "nginx.conf 模板渲染完成"
    echo "nginx.conf 模板内容:"
    cat /usr/local/openresty/nginx/conf/nginx.conf
else
    echo "警告: nginx.conf 模板文件不存在!"
fi

# 渲染 proxy_settings.conf 模板
echo "渲染 proxy_settings.conf 模板..."
if [ -f "/etc/nginx/templates/proxy_settings.conf.template" ]; then
    cp /etc/nginx/templates/proxy_settings.conf.template /etc/nginx/conf.d/proxy_settings.conf
    echo "proxy_settings.conf 模板渲染完成"
    echo "proxy_settings.conf 模板内容:"
    cat /etc/nginx/conf.d/proxy_settings.conf
else
    echo "警告: proxy_settings.conf 模板文件不存在!"
fi

# 检查配置文件是否有效
echo "检查Nginx配置是否有效..."
nginx -t

# 启动Nginx
echo "启动Nginx服务..."
exec nginx -g "daemon off;" 
