#!/bin/bash

# 刷新证书
echo "刷新证书"
/usr/bin/certbot renew --force-renewal

# 复制最新的 fullchain 和 privkey 文件
echo "复制最新的 fullchain 和 privkey 文件"
cp $(ls -t /etc/letsencrypt/archive/tiantian-tennis.ai/fullchain*.pem | head -n 1) /root/dify/docker/nginx/ssl/fullchain.pem
cp $(ls -t /etc/letsencrypt/archive/tiantian-tennis.ai/privkey*.pem | head -n 1)  /root/dify/docker/nginx/ssl/privkey.pem

# dify的环境变量.env设置
echo "更新dify环境变量配置"
sed -i 's/^NGINX_SSL_CERT_FILENAME=.*/NGINX_SSL_CERT_FILENAME=fullchain.pem/' /root/dify/docker/.env
sed -i 's/^NGINX_SSL_CERT_KEY_FILENAME=.*/NGINX_SSL_CERT_KEY_FILENAME=privkey.pem/' /root/dify/docker/.env
sed -i 's/^NGINX_HTTPS_ENABLED=.*/NGINX_HTTPS_ENABLED=true/' /root/dify/docker/.env

# 设置文件权限  
echo "设置文件权限"
chmod 644 /root/dify/docker/nginx/ssl/fullchain.pem
chmod 644 /root/dify/docker/nginx/ssl/privkey.pem

# 重启 nginx容器
echo "重启 nginx容器"
/usr/bin/docker restart docker-nginx-1

echo "完成"


# crontab -e 每3个月执行一次，凌晨1点执行 
# 0 0 1 */3 * /root/renew_dify_ssl.sh