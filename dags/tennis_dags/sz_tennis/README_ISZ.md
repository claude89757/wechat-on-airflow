# 爱深圳场地监控DAG说明

## 概述
这个脚本能够为不同的爱深圳场地自动创建独立的Airflow DAG，实现多场地的网球场监控功能。

## 支持的场地

| 场地名称 | 场地ID | DAG ID | 调度时间 | 营业时间 | 监控天数 |
|---------|--------|--------|----------|----------|----------|
| 香蜜体育中心 | 100341 | isz_xiangmi_tennis_watcher | 每小时2,10,18,26,34,42,50,58分 | 07:00-22:30 | 2天 |
| 黄木岗体育中心 | 100344 | isz_huangmugang_tennis_watcher | 每小时4,12,20,28,36,44,52分 | 07:00-22:30 | 2天 |
| 网羽中心 | 100704 | isz_wangyu_tennis_watcher | 每小时6,14,22,30,38,46,54分 | 07:00-23:00 | 2天 |
| 华侨城体育中心 | 105143 | isz_huaqiaocheng_tennis_watcher | 每小时8,16,24,32,40,48,56分 | 07:00-22:00 | 3天 |

## 功能特性

1. **动态DAG创建**: 自动为每个场地创建独立的DAG
2. **错开执行时间**: 避免多个场地同时查询，减少服务器压力
3. **智能时间过滤**: 
   - 工作日关注18-21点的场地
   - 周末关注15-21点的场地
   - 自动过滤场地营业时间外的时段
4. **微信通知**: 发现空场后自动发送微信通知
5. **防重复通知**: 已发送的通知会被缓存，避免重复发送
6. **配置驱动**: 使用config.py中的静态配置，包括时间范围和活跃天数
7. **🚀 优化的代理支持**: 
   - 智能代理格式验证
   - 自动直连备选机制
   - 详细的错误日志记录
   - 超时和连接错误处理
   - 代理轮询重试机制
   - 响应格式验证

## 文件结构

```
isz_watcher.py          # 主要的DAG生成脚本
isz_tools/
├── get_isz_data.py     # 数据获取模块
├── sign_url_utls.py    # URL签名工具
└── config.py           # 配置文件
```

## 配置说明

### Airflow Variables
需要在Airflow中配置以下变量：

- `PROXY_URL`: 代理服务器URL（可选）
- `SZ_TENNIS_CHATROOMS`: 微信群名称列表，每行一个
- `ZACKS_UP_FOR_SEND_MSG_LIST`: 微信消息发送队列

### 代理配置详解
系统使用强制代理策略，确保所有请求都通过代理：

1. **系统代理**: 通过`PROXY_URL`变量配置的固定代理（优先级最高）
2. **动态代理池**: 从GitHub自动获取的免费代理列表

**代理使用流程**:
```
1. 优先使用系统代理（如果配置）
2. 轮询动态代理池中的代理
3. 每个代理失败后等待1秒再试下一个
4. 如果所有代理都失败，返回错误
5. 详细记录每次尝试的结果
```

**重要**: 系统不支持直连模式，必须配置可用的代理才能正常工作。

**代理格式验证**:
- 自动验证IP:PORT格式
- 过滤无效的代理条目
- 支持HTTP/HTTPS代理协议

### 场地配置
在`VENUE_CONFIGS`字典中可以添加新的场地：

```python
"场地名称": {
    "sales_item_id": "场地ID",
    "venue_name": "显示名称",
    "dag_id": "dag的唯一标识",
    "description": "DAG描述",
    "schedule_interval": "cron表达式",
    "time_range": {"start_time": "HH:MM", "end_time": "HH:MM"},
    "active_days": 监控天数
}
```

## 监控范围

- 根据场地配置检查未来N天的场地情况（香蜜体育、黄木岗、网羽中心：2天；华侨城：3天）
- 过滤特定时间段的空场（工作日18-21点，周末15-21点）
- 自动遵循各场地的营业时间限制
- 🚀 **强制代理访问**: 所有请求必须通过代理，确保网络安全性
- 智能代理切换和重试机制

## 部署说明

1. 确保所有依赖模块都在Python路径中
2. 将文件放在Airflow的dags目录下
3. 在Airflow UI中启用相应的DAG
4. 配置必要的Airflow Variables
5. **网络配置**: 确保能访问GitHub获取代理列表（可选）

**重要**: 本版本已修复Airflow导入问题，使用绝对导入路径确保稳定性。

## 注意事项

- 每个DAG有15分钟的超时限制
- 0点到8点之间不执行巡检
- 错误会被记录但不会中断执行
- 消息缓存最多保留100条
- **⚠️ 重要**: 系统要求强制使用代理，必须确保有可用的代理配置
- **代理要求**: 至少配置`PROXY_URL`或确保能访问GitHub获取动态代理列表

## 故障排除

### 导入错误
如果遇到`ImportError: attempted relative import with no known parent package`错误：
- ✅ 本版本已修复此问题
- 使用绝对导入路径：`from tennis_dags.sz_tennis.isz_tools.xxx import xxx`
- 确保所有包目录都有`__init__.py`文件
