# FFTENNIS前海国际网球中心 PosPal 场地查询接入

## 来源与边界

归档 `miniprogram-wxb8ec04a1ebd1866b-2026.07.25.zip` 对应的小程序使用
PosPal / 银豹预约接口。接入仅复用无需登录、无需支付、不会创建订单的只读查询；
登录、会员、支付、锁场和下单接口均不进入 Airflow 或 Web。归档中的任何短期
Token、Cookie、openid 或 session key 均不得写入代码、日志或运行时配置。

## 只读查询链路

1. `Store/GetStoreDataFast`：确认门店身份与营业状态。
2. `AppointmentVenue/LoadClassroomProjectList`：发现门店预约项目。
3. `AppointmentVenue/AppointmentVenueConfig`：读取预约开放天数等配置。
4. `AppointmentVenue/LoadValidClassRoomApptSettingV2`：按日期查询场地时段。

运行时使用公开门店标识 `5934657`、项目标识 `1756717886546691955`，以及
`dateTime`、`projectUid`、`userId` 三个查询字段。请求头使用小程序公开约定的
`STOREID`、`PSPLVISITORAUTO=API`、`APPTYPE=1` 和
`VERSIONINFO=NC|2026.07.25`。适配器默认进行 TLS 校验并优先直连；仅在直连
失败时使用现有公开 HTTPS 代理池。DAG 遵循新场地默认一分钟巡检粒度。

## 2026-08-30 只读验证

隔离 GitHub Actions 运行器在标准 TLS 校验下连续查询三天：

- 门店名称精确返回 `FFTENNIS前海国际网球中心`，门店状态正常且未停业。
- 项目列表返回 `网球场` 项目，项目标识与归档调用一致。
- 2026-08-30、2026-08-31、2026-09-01 均返回 `success`。
- 每天返回 159 个时段和 10 个场地；可订时段分别为 70、123、130。
- 场地名称为 1–6号双打场、7–8号非标单打场、9–10号发球机场。

这些数字只证明接口和响应结构在验证时可用，不作为长期余量承诺。

## 筛选与通知安全

Web 与微信只接收 1–6号双打场。名称包含 `非标`、`发球机`、`小场`、`匹克`
或 `练习` 的场地在解析阶段即被剔除。首次完整成功巡检会先发布 Web 原始观测、
写入微信通知去重缓存并建立初始化标记，该轮不发送微信，避免把上线时的全部
现有余量误报为新增。测试和验收不得发送真实邮件或微信消息。
