-- 导入所需模块
local cjson = require "cjson"

-- 日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[404 Not Found] ", msg)
end

-- 主处理函数
local function process_not_found()
    -- 获取请求路径
    local request_uri = ngx.var.request_uri
    log("收到未处理路径的请求: " .. request_uri)
    
    -- 设置响应头
    ngx.status = 404
    ngx.header.content_type = "application/json"
    
    -- 返回JSON格式的错误信息
    local error_response = {
        status = "error",
        code = 404,
        message = "未找到该路径",
        path = request_uri,
        detail = "该服务器只接受指定的API调用: /update, /wcf_callback, /health",
        timestamp = ngx.time()
    }
    
    ngx.say(cjson.encode(error_response))
    return ngx.exit(404)
end

-- 执行处理函数
process_not_found() 