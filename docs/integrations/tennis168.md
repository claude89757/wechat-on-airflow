# Tennis168 场地查询接口文档

## 接口概述

- **接口地址**: `https://sysh.tennis168.vip/api/sports/space/date_list`
- **请求方式**: GET
- **功能说明**: 查询指定日期的网球场地预约情况

---

## 请求参数

### URL 参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| date | string | 是 | 查询日期，格式：`YYYY-MM-DD` |
| store_id | int | 是 | 门店 ID，如 `117` |

### 请求 Headers

| Header 名 | 必填 | 说明 |
|-----------|------|------|
| Host | 是 | `sysh.tennis168.vip` |
| store-id | **是** | 门店 ID（必须与 URL 参数一致） |
| content-type | 否 | `application/json` |
| form-type | 否 | `routine` |
| authori-zation | 否 | Bearer Token（实际未校验，见注意事项） |

---

## 请求示例

```bash
curl -k \
  -H "Host: sysh.tennis168.vip" \
  -H "store-id: 117" \
  -H "content-type: application/json" \
  "https://sysh.tennis168.vip/api/sports/space/date_list?date=2026-01-24&store_id=117"
```

---

## 返回数据格式

### 成功响应

```json
{
  "status": 200,
  "msg": "ok",
  "data": {
    "date": "2026-01-24",
    "min_key": 6,
    "max_key": 24,
    "current_key": 21,
    "children": [
      {
        "time": "6:00~7:00",
        "full_time": "6:00~7:00",
        "timeKey": 6,
        "children": [
          {
            "space_id": 172,
            "name": "1号场",
            "space_type_name": "室外",
            "price": "120.00",
            "active": "1",
            "status_text": "120.00",
            "spec_type": 1,
            "status": 1,
            "flag": "697388277395d",
            "detail_id": 0
          }
        ]
      }
    ]
  }
}
```

### 字段说明

#### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| status | int | 状态码，200 表示成功 |
| msg | string | 状态信息 |
| data | object | 数据主体 |

#### data 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 查询日期 |
| min_key | int | 最早可预约时段（如 6 表示 6:00） |
| max_key | int | 最晚可预约时段（如 24 表示 24:00） |
| current_key | int | 当前时段 |
| children | array | 各时段场地列表 |

#### 时段对象（children 数组元素）

| 字段 | 类型 | 说明 |
|------|------|------|
| time | string | 时段简写，如 `6:00~7:00` |
| full_time | string | 时段完整格式 |
| timeKey | int | 时段标识（小时数） |
| children | array | 该时段各场地信息 |

#### 场地对象

| 字段 | 类型 | 说明 |
|------|------|------|
| space_id | int | 场地 ID |
| name | string | 场地名称，如 `1号场` |
| space_type_name | string | 场地类型，如 `室外` |
| price | string | 价格（元），空字符串表示不可预约 |
| **active** | string | **可预约状态：`"1"` 可预约，`"0"` 不可预约** |
| status_text | string | 状态文本，如 `120.00` 或 `已预约` |
| spec_type | int | 规格类型 |
| status | int | 状态码 |
| flag | string | 唯一标识符 |
| detail_id | int | 详情 ID |

### 错误响应

```json
{
  "status": 400,
  "msg": "缺少store_id"
}
```

---

## 场地信息（store_id=117）

| 场地 ID | 名称 | 类型 | 单价 |
|---------|------|------|------|
| 172 | 1号场 | 室外 | 120 元/小时 |
| 173 | 2号场 | 室外 | 120 元/小时 |
| 174 | 3号场 | 室外 | 120 元/小时 |
| 176 | 4号场 | 室外 | 120 元/小时 |
| 177 | 5号场 | 室外 | 120 元/小时 |
| 178 | 6号场 | 室外 | 120 元/小时 |

- **营业时间**: 6:00 ~ 24:00（共 18 个时段）
- **每日总时段数**: 108 个（6 个场地 × 18 个小时）

---

## 可查询日期范围

| 范围 | 说明 |
|------|------|
| 最近日期 | 今天及以后 |
| 最远日期 | 至少支持未来 14 天 |

- 越接近当天，已被预约的时段越多
- 越远的日期，可预约时段越多（未来 14 天几乎全部可预约）

---

## 注意事项

### 1. 鉴权说明

> **重要**: 此查询接口实际上**不需要鉴权**

- `authori-zation` Header（注意非标准拼写）**未被服务端验证**
- 不带 Token、带错误 Token、带随机字符串均可正常返回数据
- 仅 `store-id` Header 为必填项

### 2. SSL 证书问题

服务器 SSL 证书链不完整，调用时需要：
- curl 添加 `-k` 参数跳过证书验证
- 或在代码中配置忽略 SSL 验证

### 3. Header 必填项

| Header | 是否必须 | 缺失时返回 |
|--------|----------|-----------|
| store-id | **必须** | `{"status":400,"msg":"缺少store_id"}` |
| authori-zation | 可选 | 正常返回数据 |
| form-type | 可选 | 正常返回数据 |

### 4. 判断场地可预约逻辑

```javascript
// 判断某个场地是否可预约
function isAvailable(space) {
  return space.active === "1";
}

// 获取可预约场地列表
function getAvailableSpaces(data) {
  const available = [];
  data.children.forEach(timeSlot => {
    timeSlot.children.forEach(space => {
      if (space.active === "1") {
        available.push({
          time: timeSlot.time,
          name: space.name,
          space_id: space.space_id,
          price: space.price
        });
      }
    });
  });
  return available;
}
```

---

## 调用示例代码

### Python

```python
import requests

def get_tennis_schedule(date, store_id=117):
    url = f"https://sysh.tennis168.vip/api/sports/space/date_list"
    headers = {
        "Host": "sysh.tennis168.vip",
        "store-id": str(store_id),
        "content-type": "application/json"
    }
    params = {
        "date": date,
        "store_id": store_id
    }

    # 注意：需要关闭 SSL 验证
    response = requests.get(url, headers=headers, params=params, verify=False)
    return response.json()

# 使用示例
result = get_tennis_schedule("2026-01-24")
if result["status"] == 200:
    for time_slot in result["data"]["children"]:
        for space in time_slot["children"]:
            if space["active"] == "1":
                print(f"{time_slot['time']} {space['name']}: {space['price']}元")
```

### Node.js

```javascript
const https = require('https');

async function getTennisSchedule(date, storeId = 117) {
  const options = {
    hostname: 'sysh.tennis168.vip',
    path: `/api/sports/space/date_list?date=${date}&store_id=${storeId}`,
    method: 'GET',
    headers: {
      'Host': 'sysh.tennis168.vip',
      'store-id': storeId.toString(),
      'content-type': 'application/json'
    },
    rejectUnauthorized: false  // 跳过 SSL 验证
  };

  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(JSON.parse(data)));
    });
    req.on('error', reject);
    req.end();
  });
}

// 使用示例
getTennisSchedule('2026-01-24').then(result => {
  console.log(result);
});
```

---

## 更新记录

| 日期 | 说明 |
|------|------|
| 2026-01-23 | 初始版本，完成接口测试与文档编写 |
