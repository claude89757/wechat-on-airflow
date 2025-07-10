#!/bin/bash

echo "🧹 开始清理服务器磁盘空间..."

# 设置颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 函数：显示磁盘使用情况
show_disk_usage() {
    echo -e "${YELLOW}=== 当前磁盘使用情况 ===${NC}"
    df -h /
    echo ""
}

# 函数：清理日志文件
cleanup_logs() {
    echo -e "${YELLOW}=== 清理Airflow日志文件 ===${NC}"
    
    # 清理7天前的日志文件
    if [ -d "/root/wechat-on-airflow/logs" ]; then
        echo "清理7天前的Airflow日志文件..."
        find /root/wechat-on-airflow/logs -type f -name "*.log" -mtime +7 -delete 2>/dev/null
        find /root/wechat-on-airflow/logs -type f -name "*.log.*" -mtime +7 -delete 2>/dev/null
        
        echo "清理空目录..."
        find /root/wechat-on-airflow/logs -type d -empty -delete 2>/dev/null
        
        echo "压缩大于10MB的日志文件..."
        find /root/wechat-on-airflow/logs -type f -name "*.log" -size +10M -exec gzip {} \; 2>/dev/null
        
        echo -e "${GREEN}✅ Airflow日志清理完成${NC}"
    else
        echo -e "${RED}❌ 未找到logs目录${NC}"
    fi
    echo ""
}

# 函数：清理Docker资源
cleanup_docker() {
    echo -e "${YELLOW}=== 清理Docker资源 ===${NC}"
    
    # 停止并删除已停止的容器
    echo "清理已停止的容器..."
    docker container prune -f
    
    # 清理未使用的镜像
    echo "清理未使用的镜像..."
    docker image prune -a -f
    
    # 清理未使用的卷
    echo "清理未使用的卷..."
    docker volume prune -f
    
    # 清理未使用的网络
    echo "清理未使用的网络..."
    docker network prune -f
    
    # 清理构建缓存
    echo "清理构建缓存..."
    docker builder prune -a -f
    
    echo -e "${GREEN}✅ Docker资源清理完成${NC}"
    echo ""
}

# 函数：清理系统日志
cleanup_system_logs() {
    echo -e "${YELLOW}=== 清理系统日志 ===${NC}"
    
    # 清理journal日志，只保留最近3天
    echo "清理systemd journal日志..."
    journalctl --vacuum-time=3d 2>/dev/null
    
    # 清理/var/log下的大日志文件
    echo "清理系统日志文件..."
    find /var/log -type f -name "*.log" -size +100M -mtime +7 -delete 2>/dev/null
    find /var/log -type f -name "*.log.*" -size +50M -mtime +3 -delete 2>/dev/null
    
    # 清理btmp和wtmp文件
    echo "清理登录日志..."
    > /var/log/btmp
    > /var/log/wtmp
    
    echo -e "${GREEN}✅ 系统日志清理完成${NC}"
    echo ""
}

# 函数：清理临时文件
cleanup_temp_files() {
    echo -e "${YELLOW}=== 清理临时文件 ===${NC}"
    
    # 清理/tmp目录
    echo "清理/tmp目录..."
    find /tmp -type f -mtime +7 -delete 2>/dev/null
    
    # 清理/var/tmp目录
    echo "清理/var/tmp目录..."
    find /var/tmp -type f -mtime +7 -delete 2>/dev/null
    
    echo -e "${GREEN}✅ 临时文件清理完成${NC}"
    echo ""
}

# 函数：清理package缓存
cleanup_package_cache() {
    echo -e "${YELLOW}=== 清理包管理器缓存 ===${NC}"
    
    # 清理yum缓存
    if command -v yum &> /dev/null; then
        echo "清理yum缓存..."
        yum clean all 2>/dev/null
    fi
    
    # 清理apt缓存
    if command -v apt &> /dev/null; then
        echo "清理apt缓存..."
        apt clean 2>/dev/null
        apt autoremove -y 2>/dev/null
    fi
    
    echo -e "${GREEN}✅ 包缓存清理完成${NC}"
    echo ""
}

# 主执行流程
main() {
    echo -e "${GREEN}🚀 开始磁盘清理程序${NC}"
    echo ""
    
    # 显示清理前的磁盘使用情况
    echo -e "${YELLOW}清理前:${NC}"
    show_disk_usage
    
    # 执行各种清理操作
    cleanup_logs
    cleanup_docker
    cleanup_system_logs
    cleanup_temp_files
    cleanup_package_cache
    
    # 显示清理后的磁盘使用情况
    echo -e "${YELLOW}清理后:${NC}"
    show_disk_usage
    
    echo -e "${GREEN}🎉 磁盘清理完成！${NC}"
    echo ""
    echo -e "${YELLOW}建议：${NC}"
    echo "1. 更新docker-compose.yml文件以防止将来日志过大"
    echo "2. 定期运行此脚本或设置cron任务"
    echo "3. 监控磁盘使用情况：df -h"
}

# 检查是否为root用户
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}此脚本需要root权限运行${NC}" 
   exit 1
fi

# 执行主函数
main 