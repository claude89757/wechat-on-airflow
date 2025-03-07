-- 导入所需模块
local cjson = require "cjson"
local http = require "resty.http"
local socket = require "socket"

-- 日志函数
local function log(msg, level)
    level = level or ngx.INFO
    ngx.log(level, "[WCF Callback] ", msg)
end

-- 调试日志函数，输出更详细的信息
local function debug_log(msg, obj)
    log(msg, ngx.DEBUG)
    if obj then
        local success, json_str = pcall(cjson.encode, obj)
        if success then
            log("详细数据: " .. json_str, ngx.DEBUG)
        else
            log("无法序列化详细数据: " .. tostring(obj), ngx.DEBUG)
        end
    end
end

-- 读取环境变量并提供更详细的日志
local function get_env_var(name, default_value, description)
    local value = os.getenv(name)
    
    if not value or value == "" then
        log("警告: 环境变量 " .. name .. " 未设置，将使用默认值: " .. default_value, ngx.WARN)
        return default_value
    else
        log("成功加载环境变量 " .. name .. ": " .. value, ngx.INFO)
        return value
    end
end

-- 配置信息 - 使用增强的环境变量获取函数
local AIRFLOW_BASE_URL = get_env_var("AIRFLOW_BASE_URL", "http://web:8080", "Airflow Web UI URL")
local AIRFLOW_USERNAME = get_env_var("AIRFLOW_USERNAME", "airflow", "Airflow 用户名")
local AIRFLOW_PASSWORD = get_env_var("AIRFLOW_PASSWORD", "airflow", "Airflow 密码")
local WX_MSG_WATCHER_DAG_ID = get_env_var("WX_MSG_WATCHER_DAG_ID", "wx_msg_watcher", "处理微信消息的DAG ID")

-- 打印环境变量值，用于调试
log("当前环境变量设置:", ngx.INFO)
log("AIRFLOW_BASE_URL = " .. AIRFLOW_BASE_URL, ngx.INFO)
log("AIRFLOW_USERNAME = " .. AIRFLOW_USERNAME, ngx.INFO)
log("WX_MSG_WATCHER_DAG_ID = " .. WX_MSG_WATCHER_DAG_ID, ngx.INFO)

-- 测试到Airflow的网络连接
local function test_airflow_connection()
    local url_module = require("socket.url")
    local parsed_url = url_module.parse(AIRFLOW_BASE_URL)
    if not parsed_url then
        log("无法解析Airflow URL: " .. AIRFLOW_BASE_URL, ngx.ERR)
        return false
    end
    
    local host = parsed_url.host
    local port = parsed_url.port or (parsed_url.scheme == "https" and 443 or 80)
    
    log("测试网络连接到Airflow服务: " .. host .. ":" .. port, ngx.INFO)
    
    -- 尝试TCP连接
    local tcp = socket.tcp()
    tcp:settimeout(5000)  -- 5秒超时
    local ok, err = tcp:connect(host, port)
    
    if not ok then
        log("无法连接到Airflow服务: " .. host .. ":" .. port .. " - " .. (err or "未知错误"), ngx.ERR)
        return false, err
    end
    
    log("成功连接到Airflow服务: " .. host .. ":" .. port, ngx.INFO)
    tcp:close()
    return true
end

-- 在脚本加载时测试连接
local connection_ok, connection_err = test_airflow_connection()
if not connection_ok then
    log("启动时Airflow连接测试失败: " .. (connection_err or "未知错误"), ngx.WARN)
end

-- 主处理函数
local function process_wcf_callback()
    -- 记录开始处理请求
    log("开始处理微信回调请求", ngx.INFO)
    
    -- 获取请求体数据
    ngx.req.read_body()
    local request_body = ngx.req.get_body_data()
    
    if not request_body then
        log("请求体为空", ngx.ERR)
        ngx.status = 400
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({message = "无效的数据"}))
        return ngx.exit(400)
    end
    
    -- 记录原始请求体用于调试
    debug_log("收到原始请求体", {body = request_body})
    
    -- 解析JSON请求体
    local success, callback_data = pcall(cjson.decode, request_body)
    if not success then
        log("解析请求体失败: " .. callback_data, ngx.ERR)
        ngx.status = 400
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({message = "无效的JSON数据", error = callback_data}))
        return ngx.exit(400)
    end
    
    -- 获取客户端IP
    local client_ip = ngx.var.remote_addr
    log("接收到来自 " .. client_ip .. " 的WCF回调数据")
    
    -- 将源IP添加到callback_data中
    callback_data["source_ip"] = client_ip
    
    -- 记录解析后的请求数据
    debug_log("解析后的请求数据", callback_data)
    
    -- 创建唯一的dag_run_id
    local formatted_roomid = string.gsub(tostring(callback_data["roomid"] or ""), "[^a-zA-Z0-9]", "")
    local msg_id = tostring(callback_data["id"] or "")
    local source_ip = tostring(callback_data["source_ip"] or "")
    local msg_timestamp = tostring(callback_data["ts"] or "")
    local dag_run_id = source_ip .. "_" .. formatted_roomid .. "_" .. msg_id .. "_" .. msg_timestamp
    
    -- 准备Airflow API载荷
    local airflow_payload = {
        conf = callback_data,
        dag_run_id = dag_run_id,
        note = "Triggered by WCF callback via Nginx"
    }
    
    log("准备触发Airflow DAG, dag_run_id: " .. dag_run_id)
    debug_log("Airflow API载荷", airflow_payload)
    debug_log("Airflow连接信息", {url = AIRFLOW_BASE_URL, username = AIRFLOW_USERNAME, dag_id = WX_MSG_WATCHER_DAG_ID})
    
    -- 使用HTTP客户端触发Airflow DAG
    local httpc = http.new()
    
    -- 设置超时
    httpc:set_timeout(10000)  -- 10秒超时
    
    -- 构建API URL
    local airflow_api_url = AIRFLOW_BASE_URL .. "/api/v1/dags/" .. WX_MSG_WATCHER_DAG_ID .. "/dagRuns"
    log("调用Airflow API URL: " .. airflow_api_url, ngx.INFO)
    
    -- 发送请求到Airflow API之前记录
    log("开始发送请求到Airflow API", ngx.INFO)
    
    -- 尝试进行错误捕获
    local ok, res_or_err = pcall(function()
        -- 先尝试解析主机名
        local parsed_url, err = require("socket.url").parse(airflow_api_url)
        if not parsed_url then
            return nil, "无法解析URL: " .. (err or "未知错误")
        end
        
        log("尝试连接到 " .. parsed_url.host .. ":" .. (parsed_url.port or "80"), ngx.INFO)
        
        -- 使用更详细的错误处理进行连接
        local res, err = httpc:request_uri(airflow_api_url, {
            method = "POST",
            body = cjson.encode(airflow_payload),
            headers = {
                ["Content-Type"] = "application/json",
                ["Authorization"] = "Basic " .. ngx.encode_base64(AIRFLOW_USERNAME .. ":" .. AIRFLOW_PASSWORD)
            }
        })
        
        if not res then
            log("连接错误详情: " .. (err or "未知错误"), ngx.ERR)
            return nil, err
        end
        
        return res
    end)
    
    -- 检查pcall结果
    if not ok then
        log("调用Airflow API发生Lua错误: " .. tostring(res_or_err), ngx.ERR)
        ngx.status = 500
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "Airflow API请求过程中发生Lua错误", 
            error = tostring(res_or_err)
        }))
        return ngx.exit(500)
    end
    
    -- 正常处理HTTP请求结果
    local res, err = res_or_err, nil
    if type(res_or_err) == "string" then
        res, err = nil, res_or_err
    end
    
    if not res then
        log("调用Airflow API失败: " .. (err or "未知错误"), ngx.ERR)
        ngx.status = 500
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "Airflow API请求失败", 
            error = err or "未知错误"
        }))
        return ngx.exit(500)
    end
    
    -- 检查响应状态
    log("收到Airflow API响应, 状态码: " .. res.status, ngx.INFO)
    debug_log("Airflow API响应详情", {status = res.status, body = res.body, headers = res.headers})
    
    if res.status == 200 or res.status == 201 then
        log("成功触发Airflow DAG: " .. WX_MSG_WATCHER_DAG_ID .. ", dag_run_id: " .. dag_run_id)
        ngx.status = 200
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "DAG触发成功", 
            dag_run_id = dag_run_id
        }))
    else
        log("触发Airflow DAG失败: " .. res.status .. " - " .. res.body, ngx.ERR)
        ngx.status = res.status
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "DAG触发失败", 
            status = res.status,
            error = res.body
        }))
    end
end

-- 错误处理包装器
local function error_handler()
    local ok, err = pcall(process_wcf_callback)
    if not ok then
        log("处理WCF回调时发生未捕获的错误: " .. tostring(err), ngx.ERR)
        ngx.status = 500
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "处理请求时发生内部服务器错误", 
            error = tostring(err)
        }))
    end
end

-- 执行处理函数
error_handler() 