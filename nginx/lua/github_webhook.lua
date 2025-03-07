-- 导入所需模块
local ngx_pipe = require "ngx.pipe"

-- 简单日志函数
local function log(msg)
    ngx.log(ngx.INFO, "[GitHub Webhook] " .. msg)
    print("[GitHub Webhook] " .. msg)
end

-- 检查环境变量
local function check_env()
    local env_file = io.open("/tmp/env.txt", "r")
    if not env_file then
        log("无法读取环境变量文件")
        return
    end
    
    local env_content = env_file:read("*all")
    env_file:close()
    
    log("环境变量内容:")
    for line in env_content:gmatch("[^\r\n]+") do
        -- 隐藏密码信息
        if not line:match("PASSWORD") then
            log("  " .. line)
        end
    end
end

-- 执行命令函数
local function execute_cmd(cmd)
    local command = "cd /app && " .. cmd
    log("执行命令: " .. command)
    
    -- 创建进程
    local proc, err = ngx_pipe.spawn({"sh", "-c", command})
    if not proc then
        log("创建进程失败: " .. (err or "未知错误"))
        return false
    end
    
    -- 设置超时时间为60秒
    proc:set_timeouts(60000, 60000, 60000)  -- 设置读取、写入和等待超时（毫秒）
    
    -- 记录开始时间
    local start_time = ngx.now()
    
    -- 读取标准输出和标准错误
    local stdout, stderr, reason, status = proc:stdout_read_all()
    
    -- 记录结束时间和耗时
    local end_time = ngx.now()
    local duration = end_time - start_time
    log("命令执行耗时: " .. duration .. " 秒")
    
    -- 检查是否超时
    if reason == "timeout" then
        log("命令执行超时: " .. command)
        log("可能原因: 网络连接问题、Git仓库过大或权限问题")
        proc:kill(9)  -- 强制终止进程
        return false
    end
    
    -- 等待进程结束
    local ok, wait_reason, wait_status = proc:wait()
    if not ok then
        log("等待进程结束失败: " .. (wait_reason or "未知错误"))
    end
    
    -- 检查命令执行状态
    if status ~= 0 then
        log("命令执行失败: " .. (stderr or reason or "未知错误"))
        log("状态码: " .. (status or "未知"))
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
    
    -- 检查环境变量
    check_env()
    
    -- 检查Git配置
    if not execute_cmd("git config --list | grep proxy") then
        log("未检测到Git代理配置")
    end
    
    -- 检查Git是否可用
    if not execute_cmd("which git") then
        log("Git命令不可用")
        ngx.status = 500
        ngx.say("Git命令不可用")
        return ngx.exit(500)
    end
    
    -- 检查目录权限
    if not execute_cmd("ls -la /app") then
        log("/app目录权限问题")
        ngx.status = 500
        ngx.say("/app目录权限问题")
        return ngx.exit(500)
    end
    
    -- 检查Git仓库状态
    if not execute_cmd("git status") then
        log("Git仓库状态异常")
        ngx.status = 500
        ngx.say("Git仓库状态异常")
        return ngx.exit(500)
    end
    
    -- 使用--depth=1参数减少下载数据量
    log("开始获取远程代码，可能需要一些时间...")
    if not execute_cmd("GIT_TRACE=1 git fetch --depth=1 --all") then
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
        -- 设置超时时间为5秒
        proc:set_timeouts(5000, 5000, 5000)
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