# 云函数部署说明

上传scf目录下的代码到云函数后，再云函数的控制台，执行下面2个命令，安装第三方依赖包

```shell
pip3.10 install pycryptodome -t .
pip3.10 install requests -t .
```


> 注意：配置云函数的环境变量！