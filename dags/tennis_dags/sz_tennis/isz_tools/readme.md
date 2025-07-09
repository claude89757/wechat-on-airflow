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
# debug mode
mitmproxy -p 8888 -s ~/csp_patch.py

# 后
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
demo.regAction("a8", async function (resolve, param) {
    console.log("=== a8 function call started ===");
    console.log("Received parameters:", param);
    
    try {
        // Check a8 function status
        console.log("a8 function type:", typeof a8);
        console.log("a8 function content first 100 characters:", a8.toString().substring(0, 100));
        
        const {ar, as, at, au, av} = param;
        console.log("Parsed parameters:");
        console.log("ar:", ar);
        console.log("as:", as);
        console.log("at:", at);
        console.log("au:", au);
        console.log("av:", av);
        
        console.log("Preparing to call a8 function...");
        
        // Set timeout protection
        const timeoutPromise = new Promise((_, reject) => {
            setTimeout(() => reject(new Error("a8 function execution timeout")), 10000);
        });
        
        const a8Promise = a8(ar, as, at, au, av);
        console.log("a8 function called, waiting for result...");
        
        const result = await Promise.race([a8Promise, timeoutPromise]);
        console.log("a8 function execution completed, result:", result);
        
        resolve(result);
    } catch (error) {
        console.error("=== a8 function execution error ===");
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        console.error("Error stack:", error.stack);
        resolve({error: error.message, type: error.constructor.name});
    } finally {
        console.log("=== a8 function call ended ===");
    }
});

console.log("Enhanced debug version of a8 function has been re-registered");
```