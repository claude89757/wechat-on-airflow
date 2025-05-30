# debugger disable
```js
Function.prototype.constructor = function() { return () => {} }
```

# Configure jsrpc
Open JsEnv and copy-paste into website console (Note: You can inject the environment when the browser starts, don't inject during debugging breakpoints)

# Start connection

```js
demo = new Hlclient("ws://127.0.0.1:12080/ws?group=sign");
```

# Register JS function

```js
demo.regAction("aq", async function (resolve, param) {
    console.log("=== aq function call started ===");
    console.log("Received parameters:", param);
    
    try {
        // Check aq function status
        console.log("aq function type:", typeof aq);
        console.log("aq function content first 100 characters:", aq.toString().substring(0, 100));
        
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
            setTimeout(() => reject(new Error("aq function execution timeout")), 10000);
        });
        
        const aqPromise = aq(aU, aV, aW, aX, aY);
        console.log("aq function called, waiting for result...");
        
        const result = await Promise.race([aqPromise, timeoutPromise]);
        console.log("aq function execution completed, result:", result);
        
        resolve(result);
    } catch (error) {
        console.error("=== aq function execution error ===");
        console.error("Error type:", error.constructor.name);
        console.error("Error message:", error.message);
        console.error("Error stack:", error.stack);
        resolve({error: error.message, type: error.constructor.name});
    } finally {
        console.log("=== aq function call ended ===");
    }
});

console.log("Enhanced debug version of aq function has been re-registered");
```