-- 导入所需模块
local cjson = require "cjson"
local shell = require "resty.shell"

-- 日志级别常量
local LOG_LEVELS = {
    DEBUG = ngx.DEBUG,
    INFO = ngx.INFO,
    WARN = ngx.WARN,
    ERROR = ngx.ERR
}

-- Docker友好的日志函数
local function log(level, msg, details)
    local log_level = LOG_LEVELS[level] or LOG_LEVELS.INFO
    
    -- 使用ISO 8601格式的时间戳，更适合日志解析
    local timestamp = os.date("!%Y-%m-%dT%H:%M:%SZ")
    
    -- 创建结构化日志对象，适合Docker日志收集
    local log_data = {
        timestamp = timestamp,
        level = level,
        service = "github-webhook",
        message = msg
    }
    
    -- 添加详情到日志对象
    if details then
        if type(details) == "table" then
            for k, v in pairs(details) do
                log_data[k] = v
            end
        else
            log_data["details"] = tostring(details)
        end
    end
    
    -- 序列化为JSON格式，适合Docker日志处理
    local success, json_log = pcall(cjson.encode, log_data)
    local log_msg
    
    if success then
        -- 使用JSON格式输出，便于日志聚合工具处理
        log_msg = json_log
    else
        -- 回退到简单格式
        log_msg = string.format("[%s][%s][GitHub Webhook] %s", timestamp, level, msg)
        if details then
            if type(details) == "table" then
                log_msg = log_msg .. " - 详情: [复杂数据结构]"
            else
                log_msg = log_msg .. " - 详情: " .. tostring(details)
            end
        end
    end
    
    -- 输出到标准输出/错误，确保被Docker日志驱动捕获
    if level == "ERROR" or level == "WARN" then
        io.stderr:write(log_msg .. "\n")
        io.stderr:flush()
    else
        io.stdout:write(log_msg .. "\n")
        io.stdout:flush()
    end
    
    -- 同时保留原有的ngx.log输出，便于在Nginx日志中也能看到
    ngx.log(log_level, log_msg)
end

-- 执行Git命令函数
local function execute_git_command(cmd, repo_path)
    local command = "cd " .. repo_path .. " && " .. cmd
    log("INFO", "准备执行Git命令", {command = command, repo_path = repo_path})
    
    local start_time = ngx.now()
    local status, output, err = shell.execute(command)
    local execution_time = ngx.now() - start_time
    
    if status ~= 0 then
        log("ERROR", "Git命令执行失败", {
            command = command,
            status = status,
            error = err or "未知错误",
            execution_time = string.format("%.3f", execution_time)
        })
        return false, err or "未知错误"
    end
    
    log("INFO", "Git命令执行成功", {
        command = command,
        output_length = #output,
        output_preview = string.sub(output, 1, 200) .. (string.len(output) > 200 and "..." or ""),
        execution_time = string.format("%.3f", execution_time)
    })
    return true, output
end

-- 主处理函数
local function process_webhook()
    local start_time = ngx.now()
    local request_id = ngx.var.request_id or ngx.req.get_headers()["X-Request-ID"] or string.format("%d.%d", ngx.time(), ngx.worker.pid())
    
    log("INFO", "收到GitHub Webhook请求", {
        request_id = request_id,
        method = ngx.req.get_method(),
        uri = ngx.var.request_uri,
        client_ip = ngx.var.remote_addr,
        user_agent = ngx.req.get_headers()["User-Agent"]
    })
    
    -- 设置响应类型
    ngx.header.content_type = "text/plain"
    
    -- 获取请求体
    ngx.req.read_body()
    local request_body = ngx.req.get_body_data()
    if not request_body then
        log("ERROR", "请求体为空", {request_id = request_id})
        ngx.status = 400
        ngx.say("请求体为空")
        return ngx.exit(400)
    end
    
    log("DEBUG", "收到请求体", {request_id = request_id, size = #request_body})
    
    -- 解析JSON格式的请求体
    local success, payload = pcall(cjson.decode, request_body)
    if not success then
        log("WARN", "解析请求体失败", {request_id = request_id, error = payload})
        -- 即使解析失败也继续执行，因为我们主要关注的是git操作
    else
        -- 提取有用的webhook信息
        local event_info = {
            request_id = request_id,
            event_type = ngx.req.get_headers()["X-GitHub-Event"],
            delivery_id = ngx.req.get_headers()["X-GitHub-Delivery"]
        }
        
        if payload.repository then
            event_info.repository = payload.repository.full_name
            event_info.repository_id = payload.repository.id
        end
        
        if payload.sender then
            event_info.sender = payload.sender.login
            event_info.sender_id = payload.sender.id
        end
        
        if payload.ref then
            event_info.ref = payload.ref
        end
        
        if payload.after then
            event_info.commit_id = payload.after
        end
        
        log("INFO", "解析Webhook事件信息", event_info)
    end
    
    -- 仓库路径
    local repo_path = "/app"
    log("INFO", "使用仓库路径", {request_id = request_id, path = repo_path})
    
    -- 执行git fetch
    log("INFO", "开始执行git fetch操作", {request_id = request_id})
    local fetch_success, fetch_result = execute_git_command("git fetch --all", repo_path)
    if not fetch_success then
        log("ERROR", "Git fetch操作失败", {request_id = request_id, result = fetch_result})
        ngx.status = 500
        ngx.say("Git fetch失败: " .. fetch_result)
        return ngx.exit(500)
    end
    
    -- 执行git reset
    log("INFO", "开始执行git reset操作", {request_id = request_id})
    local reset_success, reset_result = execute_git_command("git reset --hard origin/main", repo_path)
    if not reset_success then
        log("ERROR", "Git reset操作失败", {request_id = request_id, result = reset_result})
        ngx.status = 500
        ngx.say("Git reset失败: " .. reset_result)
        return ngx.exit(500)
    end
    
    -- 记录当前Git状态
    log("INFO", "获取当前Git状态", {request_id = request_id})
    local _, git_status = execute_git_command("git status -s", repo_path)
    local _, git_log = execute_git_command("git log -1 --pretty=format:'%h - %an, %ar : %s'", repo_path)
    local _, git_diff = execute_git_command("git diff --name-status HEAD@{1} HEAD", repo_path)
    
    -- 返回成功响应
    local total_time = ngx.now() - start_time
    log("INFO", "Webhook处理完成", {
        request_id = request_id,
        execution_time = string.format("%.3f", total_time),
        current_commit = git_log,
        changed_files = git_diff
    })
    
    ngx.status = 200
    ngx.say("更新成功")
    return ngx.exit(200)
end

-- 执行主处理函数
process_webhook() 