# 已暂停网球场 DAG 归档

从 `dags/` 移出，避免被 Airflow 扫描加载。

## 归档原因

线上对应 DAG 均为 `is_paused=true`，且近 7 天无运行；按「暂停网球场 DAG 一律当死代码」策略归档。

## 原路径 → 归档路径

| 原 DAG / 模块 | 原路径 |
|---|---|
| isz_*（香蜜/黄木岗/网羽/简上/华侨城） | `dags/tennis_dags/sz_tennis/isz_watcher.py` + `isz_tools/` |
| I深圳网球场信息监控 | `dags/tennis_dags/sz_tennis/ydmap_watcher.py` |
| 宝安网球中心信息监控 | `dags/tennis_dags/sz_tennis/bawtt_ydmap_watcher.py` |
| 粤海街道网球场巡检 | `dags/tennis_dags/sz_tennis/yhjd_watcher.py` |
| 深圳蛇口网球场巡检 | `dags/tennis_dags/sz_tennis/sk_watcher.py` |
| 深圳地铁深云文体公园网球场巡检 | `dags/tennis_dags/sz_tennis/sy_watcher.py` |
| 上海卢湾网球场巡检 | `dags/tennis_dags/sh_tennis/sh_001_watcher.py` |
| 上海徐汇网球场巡检 | `dags/tennis_dags/sh_tennis/sh_003_watcher.py` |

## 仍保留在 dags/ 的网球场巡检（线上开启）

- `TOPS科技园网球场巡检`
- `上越沙河网球场巡检`
- `深圳湾网球场巡检`
- `深圳金地网球场巡检`
- `深圳市体育中心网球场巡检`

如需恢复某个归档 DAG，将其移回 `dags/` 对应目录并在 Airflow 中 unpause。
