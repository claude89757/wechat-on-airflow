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

-- 从/tmp/env.txt文件中读取环境变量
local function get_env_var(name, default_value, description)
    -- 首先尝试从OS环境变量获取
    local value = os.getenv(name)
    
    -- 如果OS环境变量中没有，尝试从/tmp/env.txt文件中读取
    if not value or value == "" then
        local env_file = io.open("/tmp/env.txt", "r")
        if env_file then
            for line in env_file:lines() do
                local env_name, env_value = line:match("^([^=]+)=(.*)$")
                if env_name and env_name == name then
                    value = env_value
                    break
                end
            end
            env_file:close()
        end
    end
    
    -- 如果仍然没有找到，使用默认值
    if not value or value == "" then
        log("警告: 环境变量 " .. name .. " 未设置，将使用默认值: " .. default_value, ngx.WARN)
        return default_value
    else
        return value
    end
end

-- 配置信息 - 使用增强的环境变量获取函数
local AIRFLOW_BASE_URL = get_env_var("AIRFLOW_BASE_URL", "http://web:8080", "Airflow Web UI URL")
local AIRFLOW_USERNAME = get_env_var("AIRFLOW_USERNAME", "airflow", "Airflow 用户名")
local AIRFLOW_PASSWORD = get_env_var("AIRFLOW_PASSWORD", "airflow", "Airflow 密码")
local WX_MSG_WATCHER_DAG_ID = get_env_var("WX_MSG_WATCHER_DAG_ID", "wx_msg_watcher", "处理微信消息的DAG ID")

-- 主处理函数
local function process_wcf_callback()
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
    
    -- 将源IP添加到callback_data中
    callback_data["source_ip"] = client_ip
    
    -- 记录接收到的消息
    log("接收到微信消息: " .. request_body, ngx.INFO)
    
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
    
    -- 记录触发Airflow的参数
    log("触发Airflow参数: " .. cjson.encode(airflow_payload), ngx.INFO)
    
    -- 使用HTTP客户端触发Airflow DAG
    local httpc = http.new()
    
    -- 设置超时
    httpc:set_timeout(10000)  -- 10秒超时
    
    -- 构建API URL
    local airflow_api_url = AIRFLOW_BASE_URL .. "/api/v1/dags/" .. WX_MSG_WATCHER_DAG_ID .. "/dagRuns"
    
    -- 尝试进行错误捕获
    local ok, res_or_err = pcall(function()
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
    
    -- 记录触发结果
    if res.status == 200 or res.status == 201 then
        log("触发结果: 成功 - DAG: " .. WX_MSG_WATCHER_DAG_ID .. ", dag_run_id: " .. dag_run_id, ngx.INFO)
        ngx.status = 200
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "DAG触发成功", 
            dag_run_id = dag_run_id
        }))
    else
        log("触发结果: 失败 - 状态码: " .. res.status .. " - 错误: " .. res.body, ngx.ERR)
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