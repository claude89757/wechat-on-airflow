--[[
微信消息回调处理模块
功能：接收微信消息回调，处理ID精度问题，并转发到Airflow进行后续处理
作者：Claude AI
日期：2025/03/22
]]--

-- =====================================================
-- 模块导入与配置
-- =====================================================
local cjson = require "cjson"
local cjson_safe = require "cjson.safe"
local http = require "resty.http"

-- 设置cjson配置，确保大整数精度
cjson.encode_number_precision(16)  -- 设置为最大允许精度16
cjson_safe.encode_number_precision(16)  -- 同样设置安全模式的精度

-- 使用cjson_safe库以避免精度问题
local safe_decode = cjson_safe.decode
local safe_encode = cjson_safe.encode

-- =====================================================
-- 工具函数
-- =====================================================

-- 日志函数 - 统一日志格式
local function log(msg, level)
    level = level or ngx.INFO
    ngx.log(level, "[WCF Callback] ", msg)
end

-- 预处理函数：将ID字段转为字符串以保留精度
local function preserve_id_as_string(json_str)
    -- 匹配JSON中的ID字段，将其数值改为字符串形式
    local processed = json_str:gsub('"id":(%d+)', '"id":"%1"')
    return processed
end

-- 获取环境变量并验证其存在
local function get_required_env(name)
    local value = os.getenv(name)
    if not value or value == "" then
        error("错误: 必需的环境变量 " .. name .. " 未设置")
    end
    return value
end

-- =====================================================
-- 业务逻辑函数
-- =====================================================

-- 初始化配置信息
local function init_config()
    local config = {
        AIRFLOW_BASE_URL = get_required_env("AIRFLOW_BASE_URL"),
        AIRFLOW_USERNAME = get_required_env("AIRFLOW_USERNAME"),
        AIRFLOW_PASSWORD = get_required_env("AIRFLOW_PASSWORD"),
        WX_MSG_WATCHER_DAG_ID = get_required_env("WX_MSG_WATCHER_DAG_ID")
    }
    return config
end

-- 处理请求体，解析JSON并预处理ID
local function process_request()
    -- 获取请求体数据
    ngx.req.read_body()
    local request_body = ngx.req.get_body_data()
    
    -- 记录原始请求体(使用WARN级别确保显示)
    if request_body then
        log("收到原始请求体: " .. request_body, ngx.WARN)
    end
    
    if not request_body then
        log("请求体为空", ngx.ERR)
        return nil, "请求体为空"
    end
    
    -- 预处理JSON字符串，将ID字段转为字符串格式
    local processed_body = preserve_id_as_string(request_body)
    log("预处理后的请求体: " .. processed_body, ngx.WARN)
    
    -- 解析JSON请求体
    local callback_data, err = safe_decode(processed_body)
    if not callback_data then
        log("解析请求体失败: " .. (err or "未知错误"), ngx.ERR)
        return nil, "解析JSON失败: " .. (err or "未知错误")
    end
    
    -- 记录解析后的回调数据
    log("解析后的回调数据: " .. safe_encode(callback_data), ngx.WARN)
    
    -- 添加客户端IP
    local client_ip = ngx.var.remote_addr
    callback_data["source_ip"] = client_ip
    
    return callback_data
end

-- 创建唯一的dag_run_id
local function create_dag_run_id(callback_data)
    local formatted_roomid = string.gsub(tostring(callback_data["roomid"] or ""), "[^a-zA-Z0-9]", "")
    local msg_id = tostring(callback_data["id"] or "")
    local source_ip = tostring(callback_data["source_ip"] or "")
    local msg_timestamp = tostring(callback_data["ts"] or "")
    local dag_run_id = source_ip .. "_" .. formatted_roomid .. "_" .. msg_id .. "_" .. msg_timestamp
    
    log("生成的dag_run_id: " .. dag_run_id, ngx.INFO)
    return dag_run_id
end

-- 触发Airflow DAG
local function trigger_airflow_dag(config, callback_data, dag_run_id)
    -- 准备Airflow API载荷
    local airflow_payload = {
        conf = callback_data,
        dag_run_id = dag_run_id,
        note = "Triggered by WCF callback via Nginx"
    }
    
    -- 详细记录转发到Airflow的消息内容
    log("转发到Airflow的完整消息: " .. safe_encode(airflow_payload), ngx.WARN)
    
    -- 记录Airflow API目标信息
    log("Airflow API 目标: " .. config.AIRFLOW_BASE_URL .. "/api/v1/dags/" .. config.WX_MSG_WATCHER_DAG_ID .. "/dagRuns", ngx.WARN)
    
    -- 使用HTTP客户端触发Airflow DAG
    local httpc = http.new()
    
    -- 设置超时
    httpc:set_timeout(10000)  -- 10秒超时
    
    -- 构建API URL
    local airflow_api_url = config.AIRFLOW_BASE_URL .. "/api/v1/dags/" .. config.WX_MSG_WATCHER_DAG_ID .. "/dagRuns"
    
    -- 发送HTTP请求
    local res, err = httpc:request_uri(airflow_api_url, {
        method = "POST",
        body = safe_encode(airflow_payload),
        headers = {
            ["Content-Type"] = "application/json",
            ["Authorization"] = "Basic " .. ngx.encode_base64(config.AIRFLOW_USERNAME .. ":" .. config.AIRFLOW_PASSWORD)
        }
    })
    
    if not res then
        log("连接错误详情: " .. (err or "未知错误"), ngx.ERR)
        return nil, err
    end
    
    -- 记录API响应
    log("收到Airflow API响应: 状态码=" .. res.status .. ", 响应体=" .. (res.body or "空"), ngx.WARN)
    
    return res
end

-- 处理HTTP响应
local function handle_response(res, dag_run_id)
    if res.status == 200 or res.status == 201 then
        log("DAG触发成功: dag_run_id=" .. dag_run_id, ngx.WARN)
        ngx.status = 200
        ngx.header.content_type = "application/json"
        ngx.say(safe_encode({
            message = "DAG触发成功", 
            dag_run_id = dag_run_id
        }))
    else
        log("触发结果: 失败 - 状态码: " .. res.status .. " - 错误: " .. res.body, ngx.ERR)
        ngx.status = res.status
        ngx.header.content_type = "application/json"
        ngx.say(safe_encode({
            message = "DAG触发失败", 
            status = res.status,
            error = res.body
        }))
    end
end

-- 错误响应函数
local function error_response(status, message, error_details)
    ngx.status = status
    ngx.header.content_type = "application/json"
    ngx.say(safe_encode({
        message = message, 
        error = error_details
    }))
    return ngx.exit(status)
end

-- =====================================================
-- 主流程函数
-- =====================================================
local function main()
    -- 1. 初始化配置
    local config = init_config()
    
    -- 2. 处理请求并获取回调数据
    local callback_data, err = process_request()
    if not callback_data then
        return error_response(400, "无效的数据", err)
    end
    
    -- 3. 创建唯一的dag_run_id
    local dag_run_id = create_dag_run_id(callback_data)
    
    -- 4. 触发Airflow DAG
    local ok, res_or_err = pcall(function()
        return trigger_airflow_dag(config, callback_data, dag_run_id)
    end)
    
    -- 5. 处理错误情况
    if not ok then
        log("调用Airflow API发生Lua错误: " .. tostring(res_or_err), ngx.ERR)
        return error_response(500, "Airflow API请求过程中发生Lua错误", tostring(res_or_err))
    end
    
    -- 6. 处理正常结果
    local res, err = res_or_err, nil
    if type(res_or_err) == "string" then
        res, err = nil, res_or_err
    end
    
    if not res then
        log("调用Airflow API失败: " .. (err or "未知错误"), ngx.ERR)
        return error_response(500, "Airflow API请求失败", err or "未知错误")
    end
    
    -- 7. 处理响应
    handle_response(res, dag_run_id)
end

-- =====================================================
-- 错误处理和程序入口
-- =====================================================
local function error_handler()
    local ok, err = pcall(main)
    if not ok then
        log("处理WCF回调时发生错误: " .. tostring(err), ngx.ERR)
        ngx.status = 500
        ngx.header.content_type = "application/json"
        ngx.say(safe_encode({
            message = "处理请求时发生错误", 
            error = tostring(err)
        }))
    end
end

-- 执行处理函数
error_handler() 