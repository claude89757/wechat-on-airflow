// ==UserScript==
// @name         Debugger Blocker Script
// @namespace    http://tampermonkey.net/
// @version      2.8
// @description  拦截调试工具调用，阻止动态函数创建
// @author       claude89757 by cursor
// @match        *://*/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function() {
    'use strict';
    console.log('[Debugger Blocker] Starting in Tampermonkey context...');

    const code = `
    (function(){
        console.log('[Debugger Blocker] Script execution started');

        // 保存原始函数
        const _Function = window.Function;
        const _eval = window.eval;
        const _setInterval = window.setInterval;

        // 解码十六进制字符串
        const decodeHexString = (str) => {
            return str.replace(/\\x([0-9a-f]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
        };

        // 检测可疑的字符串
        const isSuspiciousString = (str) => {
            if (typeof str !== 'string') return false;

            // 检查十六进制编码
            if (/\\x[0-9a-f]{2}/i.test(str)) {
                const decoded = decodeHexString(str);
                return decoded.includes('debugger');
            }

            // 检查模板字符串和多行字符串
            const cleanStr = str.replace(/\\n/g, '\\n')
                               .replace(/\\s+/g, ' ')
                               .toLowerCase();

            return cleanStr.includes('debugger') ||
                   cleanStr.includes('禁止调试') ||
                   cleanStr.includes('array.from') && cleanStr.includes('fill');
        };

        // 检查是否是框架代码
        const isFrameworkCode = (stack) => {
            return stack.includes('chunk-vendors') ||
                   stack.includes('webpack') ||
                   stack.includes('jquery');
        };

        // 拦截 setInterval
        try {
            window.setInterval = function(callback, delay, ...args) {
                if (typeof callback === 'function') {
                    const fnStr = callback.toString();
                    if (isSuspiciousString(fnStr)) {
                        return -1;
                    }
                } else if (typeof callback === 'string' && isSuspiciousString(callback)) {
                    return -1;
                }
                return _setInterval.call(window, callback, delay, ...args);
            };
        } catch(e) {
            console.error('[Debugger Blocker] SetInterval protection error:', e);
        }

        // 拦截 Function.prototype.constructor
        try {
            const originalDescriptor = Object.getOwnPropertyDescriptor(Function.prototype, 'constructor');
            const safeConstructor = Function.prototype.constructor;

            Object.defineProperty(Function.prototype, 'constructor', {
                get() {
                    const stack = new Error().stack || '';

                    if (isFrameworkCode(stack)) {
                        return safeConstructor;
                    }

                    return function(...args) {
                        const code = args.join('');
                        if (isSuspiciousString(code)) {
                            return function() { return {}; };
                        }
                        return safeConstructor.apply(this, args);
                    };
                },
                set(value) {
                    const stack = new Error().stack || '';
                    if (isFrameworkCode(stack)) {
                        Object.defineProperty(this, 'constructor', {
                            value: value,
                            writable: true,
                            configurable: true
                        });
                    }
                },
                configurable: true
            });
        } catch(e) {
            console.error('[Debugger Blocker] Constructor protection error:', e);
        }

        // 拦截eval
        try {
            window.eval = function(code) {
                if (typeof code === 'string' && isSuspiciousString(code)) {
                    return null;
                }
                return _eval.call(window, code);
            };
        } catch(e) {
            console.error('[Debugger Blocker] Eval protection error:', e);
        }

        // 拦截Function构造器
        try {
            window.Function = function(...args) {
                const code = args.join('');
                if (isSuspiciousString(code)) {
                    return function() { return {}; };
                }
                return _Function.apply(this, args);
            };
            window.Function.prototype = _Function.prototype;
        } catch(e) {
            console.error('[Debugger Blocker] Function protection error:', e);
        }

        console.log('[Debugger Blocker] Initialization complete');

        // 导出状态对象
        window._debuggerBlocker = {
            version: '2.8',
            isActive: true
        };
    })();
    `;

    try {
        const script = document.createElement('script');
        script.textContent = code;
        (document.head || document.documentElement).appendChild(script);
        script.remove();
    } catch (e) {
        console.error('[Debugger Blocker] Injection error:', e);
    }
})();