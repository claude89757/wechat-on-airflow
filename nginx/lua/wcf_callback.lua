-- 导入所需模块
local cjson = require "cjson"
local http = require "resty.http"

-- 配置信息
local AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL") or "http://web:8080"
local AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME") or "airflow"
local AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD") or "airflow"
local WX_MSG_WATCHER_DAG_ID = os.getenv("WX_MSG_WATCHER_DAG_ID") or "wx_msg_watcher"

-- 日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[WCF Callback] ", msg)
end

-- 主处理函数
local function process_wcf_callback()
    -- 获取请求体数据
    ngx.req.read_body()
    local request_body = ngx.req.get_body_data()
    
    if not request_body then
        log("请求体为空")
        ngx.status = 400
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({message = "无效的数据"}))
        return ngx.exit(400)
    end
    
    -- 解析JSON请求体
    local success, callback_data = pcall(cjson.decode, request_body)
    if not success then
        log("解析请求体失败: " .. callback_data)
        ngx.status = 400
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({message = "无效的JSON数据"}))
        return ngx.exit(400)
    end
    
    -- 获取客户端IP
    local client_ip = ngx.var.remote_addr
    log("接收到来自 " .. client_ip .. " 的WCF回调数据")
    
    -- 将源IP添加到callback_data中
    callback_data["source_ip"] = client_ip
    
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
    
    -- 使用HTTP客户端触发Airflow DAG
    local httpc = http.new()
    
    -- 设置超时
    httpc:set_timeout(10000)  -- 10秒超时
    
    -- 构建API URL
    local airflow_api_url = AIRFLOW_BASE_URL .. "/api/v1/dags/" .. WX_MSG_WATCHER_DAG_ID .. "/dagRuns"
    
    -- 发送请求到Airflow API
    local res, err = httpc:request_uri(airflow_api_url, {
        method = "POST",
        body = cjson.encode(airflow_payload),
        headers = {
            ["Content-Type"] = "application/json",
            ["Authorization"] = "Basic " .. ngx.encode_base64(AIRFLOW_USERNAME .. ":" .. AIRFLOW_PASSWORD)
        }
    })
    
    if not res then
        log("调用Airflow API失败: " .. (err or "未知错误"))
        ngx.status = 500
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "Airflow API请求失败", 
            error = err or "未知错误"
        }))
        return ngx.exit(500)
    end
    
    -- 检查响应状态
    if res.status == 200 or res.status == 201 then
        log("成功触发Airflow DAG: " .. WX_MSG_WATCHER_DAG_ID .. ", dag_run_id: " .. dag_run_id)
        ngx.status = 200
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "DAG触发成功", 
            dag_run_id = dag_run_id
        }))
    else
        log("触发Airflow DAG失败: " .. res.status .. " - " .. res.body)
        ngx.status = res.status
        ngx.header.content_type = "application/json"
        ngx.say(cjson.encode({
            message = "DAG触发失败", 
            status = res.status,
            error = res.body
        }))
    end
end

-- 执行处理函数
process_wcf_callback() 