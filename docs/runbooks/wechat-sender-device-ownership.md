# Shared phone ownership

The reader and HTTP Sender share `/run/wechat-device/device-<serial>.lock` using
Linux `flock`. Every phone mutation, Appium create/reset and retained warm session
must own that lock. The systemd Sender creates a setgid runtime directory owned
by `wechat-sender`; a reader must have that supplementary group and set
`ZACKS_DEVICE_LOCK_DIR=/run/wechat-device`. Never delete a held lock file.

The Sender retains a warm session for at most five idle seconds by default
(`WECHAT_WARM_IDLE_SECONDS`, clamped to 0.1–30 seconds). Its expiry callback takes
the same in-process mutex as requests and checks a generation number before
closing, so an old timer cannot terminate a new send. Busy acquisition returns
409 before claiming the durable message ledger. Unknown submissions are never
retried as a side effect of device recovery.

Deploy through the protected Sender workflow. Install the reader configuration
only after the runtime directory exists. Observe natural sends and reader sweeps;
never use the send endpoint for an unapproved synthetic notification.
