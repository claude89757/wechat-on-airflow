-- 导入所需模块
local cjson = require "cjson"
local shell = require "resty.shell"

-- 日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[GitHub Webhook] ", msg)
end

-- 执行Git命令函数
local function execute_git_command(cmd, repo_path)
    local command = "cd " .. repo_path .. " && " .. cmd
    log("执行命令: " .. command)
    
    local status, output, err = shell.execute(command)
    if status ~= 0 then
        log("命令执行失败: " .. (err or "未知错误"))
        return false, err or "未知错误"
    end
    
    log("命令执行成功: " .. output)
    return true, output
end

-- 主处理函数
local function process_webhook()
    -- 设置响应类型
    ngx.header.content_type = "text/plain"
    
    -- 获取请求体
    local request_body = ngx.req.get_body_data()
    if not request_body then
        log("请求体为空")
        ngx.status = 400
        ngx.say("请求体为空")
        return ngx.exit(400)
    end
    
    -- 解析JSON格式的请求体（可选，取决于您如何处理webhook）
    local success, payload = pcall(cjson.decode, request_body)
    if not success then
        log("解析请求体失败: " .. payload)
        -- 即使解析失败也继续执行，因为我们主要关注的是git操作
    end
    
    -- 仓库路径
    local repo_path = "/app"
    
    -- 执行git fetch
    local fetch_success, fetch_result = execute_git_command("git fetch --all", repo_path)
    if not fetch_success then
        ngx.status = 500
        ngx.say("Git fetch失败: " .. fetch_result)
        return ngx.exit(500)
    end
    
    -- 执行git reset
    local reset_success, reset_result = execute_git_command("git reset --hard origin/main", repo_path)
    if not reset_success then
        ngx.status = 500
        ngx.say("Git reset失败: " .. reset_result)
        return ngx.exit(500)
    end
    
    -- 返回成功响应
    ngx.status = 200
    ngx.say("更新成功")
    return ngx.exit(200)
end

-- 执行主处理函数
process_webhook() 