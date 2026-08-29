# 小程序构建产物归档：wxb8ec04a1ebd1866b

归档一份微信小程序（appid `wxb8ec04a1ebd1866b`）的编译产物，用于接口与页面结构
分析。该产物为第三方小程序，仓库不包含其源码，也不依赖它运行任何 DAG 或服务。

## 归档物

| 项目 | 值 |
|------|-----|
| 文件 | `miniprogram-wxb8ec04a1ebd1866b-2026.07.25.zip` |
| AppID | `wxb8ec04a1ebd1866b` |
| 应用版本 | `2026.07.25`（来自 `config.js` 的 `appVersion`） |
| 入口页 | `pages/index/index` |
| 未压缩体积 | 16 MB |
| 归档体积 | 2.1 MB |
| 文件数 | 3,375 个文件 / 988 个目录 |
| SHA-256 | `4b24f41a0ba2db47e49d6c0f167acebb40c80b165d82d908796f0033a8b9746f` |

## 来源

压缩包来自微信客户端缓存的小程序编译包目录（`.../applet/packages/<appid>/7/OUTPUT/<appid>`），
打包命令：

```bash
cd <OUTPUT 目录>
zip -r -X wxb8ec04a1ebd1866b-2026.07.25.zip wxb8ec04a1ebd1866b
```

`-X` 用于剔除 macOS 扩展属性与 `__MACOSX` 元数据，避免归档噪声。

## 结构

产物是已编译的小程序包，顶层包含 `app.js`、`app.json`、`app.wxss`、`app-config.json`
以及 `pages/`、`subPages/`、`components/`、`modules/`、`utils/`、`styles/` 等目录，
另有分包目录 `accountSubpages/`、`aestheticSubpages/`、`clockInActivitySubpages/`、
`invoiceSubpages/`、`livePackage/`、`marketingSubpages/`、`trainingSubpages/`、
`mpxPackages/`。

主包页面按业务分组：`index`、`shopping`（门店与商品）、`order`（订单与开票）、
`account`（登录与反馈）、`college`、`customize`、`template`、`notice`、`web` 等。

`modules/` 下含 `client/`、`server/`、`services/`、`store/`、`cache/`、`utils/`、
`weui/`，是请求层与状态管理所在，是分析接口调用的主要入口。

## 用途与边界

- 用途：离线检视该小程序的页面路由、分包划分与接口调用方式。
- 边界：仅作只读归档参考，不被 `src/wechat_airflow` 引用，也不参与构建、测试或部署。
- 注意：归档内可能含有第三方接口域名与配置，引用前请确认是否涉及敏感信息；
  仓库约定不提交密钥与生产凭据，新增分析结论时应只摘录必要的接口形状。

## 校验

```bash
shasum -a 256 miniprogram-wxb8ec04a1ebd1866b-2026.07.25.zip
# 4b24f41a0ba2db47e49d6c0f167acebb40c80b165d82d908796f0033a8b9746f

unzip -t miniprogram-wxb8ec04a1ebd1866b-2026.07.25.zip
# No errors detected in compressed data
```
