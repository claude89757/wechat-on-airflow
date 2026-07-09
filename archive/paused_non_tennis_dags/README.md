# 已暂停 / 非开启 DAG 归档

从 `dags/` 移出，避免被 Airflow 扫描加载。仅保留线上 **未暂停且在跑** 的 DAG 相关代码。

## 仍保留在 dags/ 的开启 DAG

| DAG | 文件 |
|---|---|
| `airflow_db_cleanup` | `tool_dags/db_cleanup.py` |
| `appium_wx_msg_watcher_for_zacks` | `tennis_dags/wx_msg_watcher_for_zacks.py` |
| `HTTPS可用代理巡检` | `tennis_dags/proxy_tools/https_proxy_watcher.py` |
| `HTTPS可用代理巡检_ydmap` | `tennis_dags/proxy_tools/ydmap_https_proxy_watcher.py` |
| `TOPS科技园网球场巡检` | `tennis_dags/sz_tennis/tops_watcher.py` |
| `zacks_phone_daily_reboot` | `tennis_dags/zacks_phone_reboot_dag.py` |
| `上越沙河网球场巡检` | `tennis_dags/sz_tennis/sysh_watcher.py` |
| `深圳市体育中心网球场巡检` | `tennis_dags/sz_tennis/tyzx_watcher.py` |
| `深圳湾网球场巡检` | `tennis_dags/sz_tennis/szw_watcher.py` |
| `深圳金地网球场巡检` | `tennis_dags/sz_tennis/jdwx_watcher.py` |

依赖保留：`dags/utils/*`（发送/Appium/Dify）、`dags/appium_wx_dags/common/mysql_tools.py`、`dags/tennis_dags/utils/tencent_ses|sms.py`。

## 本目录归档内容

- `appium_wx_dags/`：除 mysql_tools 外的暂停微信 DAG
- `wx_mp_dags/`、`wx_work_dags/`
- `ai_tennis_dags/`
- `github_watcher.py`、`news_watcher.py`、`tool_news_watcher.py`
- `tests/demo_*`
- 重复/未引用 utils 副本

网球场暂停 DAG 见 `../paused_tennis_dags/`。

如需恢复，移回 `dags/` 对应路径并在 Airflow unpause。
