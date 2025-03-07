-- 导入所需模块
-- 不再使用 resty.shell，改用 os.execute
-- local shell = require "resty.shell"

-- 简单日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[GitHub Webhook] " .. msg)
    print("[GitHub Webhook] " .. msg)
end

-- 执行命令函数
local function execute_cmd(cmd)
    local command = "cd /app && " .. cmd
    log("执行命令: " .. command)
    
    local status = os.execute(command)
    
    if status ~= 0 then
        log("命令执行失败: 返回状态码 " .. tostring(status))
        return false
    end
    
    log("命令执行成功")
    return true
end

-- 主处理函数
local function process_webhook()
    log("收到GitHub Webhook请求，开始更新代码")
    
    -- 设置响应类型
    ngx.header.content_type = "text/plain"
    
    -- 强制获取最新代码并重置本地修改
    if not execute_cmd("git fetch --all") then
        ngx.status = 500
        ngx.say("获取远程代码失败")
        return ngx.exit(500)
    end
    
    -- 强制重置为远程main分支，丢弃所有本地修改和冲突
    if not execute_cmd("git reset --hard origin/main") then
        ngx.status = 500
        ngx.say("重置代码失败")
        return ngx.exit(500)
    end
    
    -- 清理未跟踪的文件和目录
    execute_cmd("git clean -fd")
    
    -- 获取当前提交信息
    local handle = io.popen("cd /app && git log -1 --pretty=format:'%h - %an, %ar : %s'")
    local commit_info = handle:read("*a")
    handle:close()
    
    if commit_info and commit_info ~= "" then
        log("当前代码版本: " .. commit_info)
    end
    
    -- 返回成功响应
    ngx.status = 200
    ngx.say("代码更新成功")
    return ngx.exit(200)
end

-- 执行主处理函数
process_webhook() 