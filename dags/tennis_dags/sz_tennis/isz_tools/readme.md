# For disable Content-Security-Policy

```python
# csp_patch.py
from mitmproxy import http
import re

TARGET = "wxsports.ydmap.cn"

def response(flow: http.HTTPFlow):
    if TARGET in flow.request.host:
        h = flow.response.headers
        if "Content-Security-Policy" in h:
            print("del Content-Security-Policy")
            del h["Content-Security-Policy"]
```

# Start mitmproxy in pi
```shell
# 调试模式
mitmproxy -p 8888 -s ~/csp_patch.py

# 后台运行
nohup mitmdump -p 8888 -s ~/csp_patch.py >/dev/null 2>&1 & 
```


# debugger disable
```js
Function.prototype.constructor = function() { return () => {} }
```
or use other way.


# Configure jsrpc
Open JsEnv and copy-paste into website console (Note: You can inject the environment when the browser starts, don't inject during debugging breakpoints)

# Start connection (must inject during debugging breakpoints)

```js
demo = new Hlclient("ws://127.0.0.1:12080/ws?group=sign");
```

# Register JS function (must inject during debugging breakpoints)

```js
demo.regAction("ap", async function (resolve, param) {
    console.log("=== ap function call started ===");
    console.log("Received parameters:", param);
    
    try {
        // Check ap function status
        console.log("ap function type:", typeof aq);
        console.log("ap function content first 100 characters:", ap.toString().substring(0, 100));
        
        const {aU, aV, aW, aX, aY} = param;
        console.log("Parsed parameters:");
        console.log("aU:", aU);
        console.log("aV:", aV);
        console.log("aW:", aW);
        console.log("aX:", aX);
        console.log("aY:", aY);
        
        console.log("Preparing to call aq function...");
        
        // Set timeout protection
        const timeoutPromise = new Promise((_, reject) => {
            setTimeout(() => reject(new Error("ap function execution timeout")), 10000);
        });
        
        const aqPromise = ap(aU, aV, aW, aX, aY);
        console.log("ap function called, waiting for result...");
        
        const result = await Promise.race([aqPromise, timeoutPromise]);
        console.log("ap function execution completed, result:", result);
        
        resolve(result);
    } catch (error) {
        console.error("=== ap function execution error ===");
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        console.error("Error stack:", error.stack);
        resolve({error: error.message, type: error.constructor.name});
    } finally {
        console.log("=== ap function call ended ===");
    }
});

console.log("Enhanced debug version of ap function has been re-registered");
```