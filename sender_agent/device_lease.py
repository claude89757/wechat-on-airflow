"""Cross-process phone ownership. Hold this lease for the entire Appium session."""

import fcntl
import os
import re
import time
from pathlib import Path


class DeviceLease:
    def __init__(self, device_name: str):
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", device_name):
            raise ValueError("invalid device name")
        directory = Path(os.environ.get("WECHAT_DEVICE_LOCK_DIR", "/run/wechat-device"))
        self.path = directory / f"device-{device_name}.lock"
        self.fd: int | None = None

    def acquire(self, timeout: float = 0) -> bool:
        if self.fd is not None:
            return True
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o660)
        if os.fstat(fd).st_uid == os.getuid():
            os.fchmod(fd, 0o660)
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        os.close(fd)
                        return False
                    time.sleep(0.1)
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()} owner=wechat-sender".encode())
            self.fd = fd
            return True
        except BaseException:
            os.close(fd)
            raise

    def release(self) -> None:
        fd, self.fd = self.fd, None
        if fd is not None:
            os.close(fd)
