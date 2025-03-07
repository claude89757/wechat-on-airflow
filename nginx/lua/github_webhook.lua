-- 导入所需模块
local ngx_pipe = require "ngx.pipe"

-- 简单日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[GitHub Webhook] " .. msg)
    print("[GitHub Webhook] " .. msg)
end

-- 执行命令函数
local function execute_cmd(cmd)
    local command = "cd /app && " .. cmd
    log("执行命令: " .. command)
    
    local proc = ngx_pipe.spawn({"sh", "-c", command})
    if not proc then
        log("创建进程失败")
        return false
    end
    
    local stdout, stderr, reason, status = proc:stdout_read_all()
    proc:wait()
    
    if status ~= 0 then
        log("命令执行失败: " .. (stderr or reason or "未知错误"))
        return false
    end
    
    log("命令执行成功: " .. (stdout or ""))
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
    local proc = ngx_pipe.spawn({"sh", "-c", "cd /app && git log -1 --pretty=format:'%h - %an, %ar : %s'"})
    local commit_info = ""
    if proc then
        commit_info = proc:stdout_read_all() or ""
        proc:wait()
    end
    
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