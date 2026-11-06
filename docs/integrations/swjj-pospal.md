# 深湾竞界网匹中心 PosPal 场地查询接入

## 来源与边界

该门店的微信小程序 `wx309ade03a6eb6cc3` 是银豹 / PosPal 代管的通用预约前端。
它的 `ext` 配置声明了 `storeId=6149033` 与
`serverBase=https://wxservice-stg48.pospal.cn/`，与泛思博特链、FFTENNIS 前海
使用同一台预约服务器。

接入只复用**无需登录、无需支付、不会创建订单**的只读查询：

1. `Store/GetStoreDataFast`：确认门店身份与营业状态。
2. `AppointmentVenue/LoadClassroomProjectList`：发现门店预约项目。
3. `AppointmentVenue/AppointmentVenueConfig`：读取预约开放天数等配置。
4. `AppointmentVenue/LoadValidClassRoomApptSettingV2`：按日期查询场地时段。

登录、会员、支付、锁场和下单接口（`SaveVenueAppointmentV2` 等）均不进入
Airflow 或 Web。小程序里的任何 Token、Cookie、openid 或 session key 都不得
写入代码、日志或运行时配置；查询接口本身也不需要它们。

## 运行时标识

| 字段 | 值 |
| --- | --- |
| `store_id` | `6149033` |
| `project_uid` | `1793192927642251816`（项目「网球」） |
| 请求头 | `STOREID`、`PSPLVISITORAUTO=API`、`APPTYPE=1`、`VERSIONINFO=NC\|2026.10.28` |
| Body | `dateTime`、`projectUid`、`userId` |

门店还有「匹克球」项目（`1793192931485890101`），由 `projectUid` 天然隔离，
不会被网球场巡检读取。

## 2026-11-06 只读验证

- 门店名称精确返回 `深湾竞界网匹中心`，地址为深圳南山通港街。
- 项目列表返回 `网球` 与 `匹克球` 两个项目。
- 2026-11-07 至 2026-11-12 均返回 `success`，每天 136 个时段、8 片场地。
- 场地为：网球标准场 1/2/3/7 号、VIP 网球风雨场 4/5/6 号、网球单打场 8 号。
- 可预约窗口为「今天 + 7 天」，第 8 天起 `validClassRooms` 与 `slots` 均为空。
- 时段为 07:00–23:59，每格 60 分钟；`apptInfo.canApptOrNot` 为唯一可约判据。
- 价格：标准场 125 / 185 / 145，单打场 80 / 120 / 90，VIP 风雨场 180 / 268 / 180
  （工作日日间 / 晚间与周末日间 / 深夜三档）。

这些数字只证明接口和响应结构在验证时可用，不作为长期余量承诺。

## 筛选与通知安全

只发布 7 片标准场与 VIP 风雨场。`网球单打场8号` 按用户决策排除：
门店把场地编号写在名称尾部（`网球标准场1号`），共享的「前缀编号」白名单
无法表达这组场地，因此使用 `单打` 排除词，而不是 `allowed_court_numbers`。

门店在 4 个场地名尾部填充了制表符（`'网球标准场2号\t'`）。适配器在解析阶段
统一 `strip()`，避免制表符进入 Web 观测键或微信消息文本。

PosPal 对未知 `projectUid` 或错配 `STOREID` 仍返回 `successed: true` 且
`validClassRooms` 为空。本场地为此启用 `require_rooms_when_in_window`：
窗口内没有教室时抛出 `PosPalEmptyInventoryError`，把「配置失效」从
「健康空结果」中区分出来。其他 PosPal 场地保持既有语义不变。

首次完整成功巡检会先发布 Web 原始观测、写入微信通知去重缓存并建立
`SWJJ_NOTIFICATION_BASELINE` 初始化标记，该轮不发送微信，避免把上线时的
全部现有余量误报为新增。

## 七天窗口与去重容量

该门店一次巡检覆盖今天起 7 天，而共享默认是 3 天。两个共享常量因此变成
按场地可配：

- `lookahead_days`：默认 3，本场地为 7。
- `max_cached_messages`：默认 100，本场地为 400。去重缓存必须容纳一次
  完整扫描可能产生的全部消息；一旦旧消息被挤出缓存，仍然空闲的场地会
  被再次提醒。7 天 × 7 片 × 每日最多 6 个晚间时段约 294 条，400 留有余量。

七天窗口也放大了 Web 观测的写入量：每轮最多约 950 条 `current_availability`
记录，是三天窗口的 2.3 倍。`observed_slots` 使用 `event_key` 去重，因此长期
表只随真实时段增长。上线后需要观察 Host Core 的写入延迟与 `venue_status`。

## 通知链接

微信提醒附带的订场入口是 `#小程序://深湾竞界智享订场/sPHQZElfQM9p8ie`，
由 `VENUE_BOOKING_PROGRAMS["swjj"]` 在投递阶段追加，沿用共享的每群每程序
两小时冷却。
