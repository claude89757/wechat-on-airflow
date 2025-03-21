# 企业微信云函数部署说明

上传scf目录下的代码到云函数后，在云函数的控制台，执行下面2个命令，安装第三方依赖包

```shell
pip3.10 install pycryptodome -t .
pip3.10 install requests -t .
```

> 注意：配置云函数的环境变量！
> - WX_WORK_TOKEN：企业微信应用配置的Token
> - WX_WORK_ENCODING_AES_KEY：企业微信应用配置的EncodingAESKey
> - WX_WORK_CORPID：企业微信的企业ID
> - AIRFLOW_BASE_URL：Airflow的基础URL
> - AIRFLOW_USERNAME：Airflow的用户名
> - AIRFLOW_PASSWORD：Airflow的密码
> - AIRFLOW_DAG_ID：触发的Airflow DAG ID，默认为"wx_work_msg_watcher" 