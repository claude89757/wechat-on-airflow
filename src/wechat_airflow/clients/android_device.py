from __future__ import annotations

import logging
import re
import shlex
import time

import paramiko

LOGGER = logging.getLogger(__name__)
SSH_TIMEOUT_SECONDS = 30


def exec_cmd_by_ssh_with_status(
    host: str,
    port: int,
    username: str,
    password: str,
    cmd: str,
) -> tuple[str | None, str | None, int | None]:
    """Execute one bounded command on the Android host."""
    ssh: paramiko.SSHClient | None = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=SSH_TIMEOUT_SECONDS,
            auth_timeout=SSH_TIMEOUT_SECONDS,
            banner_timeout=SSH_TIMEOUT_SECONDS,
        )
        _, stdout, stderr = ssh.exec_command(cmd, timeout=SSH_TIMEOUT_SECONDS)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        if exit_status != 0 and not error:
            error = f"command exited with status {exit_status}"
        return output, error, exit_status
    except Exception as exc:
        LOGGER.exception("android_host_ssh_failed host=%s port=%s", host, port)
        return None, str(exc), None
    finally:
        if ssh is not None:
            ssh.close()


def exec_cmd_by_ssh(
    host: str,
    port: int,
    username: str,
    password: str,
    cmd: str,
) -> tuple[str | None, str | None]:
    output, error, _ = exec_cmd_by_ssh_with_status(host, port, username, password, cmd)
    return output, error


def build_login_shell_adb_command(adb_command: str) -> str:
    """Run adb through the remote login shell that owns its PATH."""
    return f"bash -l -c {shlex.quote(f'adb {adb_command}')}"


def parse_adb_devices_output(output: str, device_serial: str) -> bool:
    """Return whether the target is present in the online device state."""
    for line in output.splitlines():
        if "List of devices attached" in line:
            continue
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 2 and parts[0] == device_serial and parts[1] == "device":
            return True
    return False


def get_device_id_by_adb(
    host: str,
    port: int,
    username: str,
    password: str,
) -> list[str]:
    """Return online adb device serials from the remote Android host."""
    output, _ = exec_cmd_by_ssh(
        host,
        port,
        username,
        password,
        build_login_shell_adb_command("devices"),
    )
    if not output:
        return []

    device_ids = []
    for line in output.splitlines():
        if "List of devices attached" in line:
            continue
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 2 and parts[1] == "device":
            device_ids.append(parts[0])
    return device_ids


def is_boot_completed_output(output: str) -> bool:
    return output.strip() == "1"


def reboot_device_via_ssh_adb(
    device_ip: str,
    username: str,
    password: str,
    device_serial: str,
    port: int = 22,
) -> bool:
    """Request an Android reboot through adb on the remote host."""
    output, error, exit_status = exec_cmd_by_ssh_with_status(
        device_ip,
        port,
        username,
        password,
        build_login_shell_adb_command(f"-s {device_serial} reboot"),
    )
    if exit_status != 0:
        LOGGER.error(
            "android_reboot_failed device=%s exit_status=%s error=%s",
            device_serial,
            exit_status,
            error,
        )
        return False
    if error:
        LOGGER.warning("android_reboot_warning device=%s error=%s", device_serial, error)
    LOGGER.info(
        "android_reboot_requested device=%s output_present=%s",
        device_serial,
        bool(output),
    )
    return True


def is_device_online_via_ssh_adb(
    device_ip: str,
    username: str,
    password: str,
    device_serial: str,
    port: int = 22,
) -> bool:
    output, error, exit_status = exec_cmd_by_ssh_with_status(
        device_ip,
        port,
        username,
        password,
        build_login_shell_adb_command("devices"),
    )
    if exit_status != 0 or output is None:
        LOGGER.warning(
            "android_online_check_failed device=%s exit_status=%s error=%s",
            device_serial,
            exit_status,
            error,
        )
        return False
    return parse_adb_devices_output(output, device_serial)


def wait_for_device_boot_completed(
    device_ip: str,
    username: str,
    password: str,
    device_serial: str,
    port: int = 22,
    timeout: int = 300,
    interval: int = 10,
) -> bool:
    """Wait until adb reports the target online and Android reports boot complete."""
    deadline = time.monotonic() + timeout
    boot_command = build_login_shell_adb_command(
        f"-s {device_serial} shell getprop sys.boot_completed"
    )

    while time.monotonic() < deadline:
        if not is_device_online_via_ssh_adb(
            device_ip,
            username,
            password,
            device_serial,
            port=port,
        ):
            time.sleep(interval)
            continue

        output, error, exit_status = exec_cmd_by_ssh_with_status(
            device_ip,
            port,
            username,
            password,
            boot_command,
        )
        if exit_status == 0 and output is not None and is_boot_completed_output(output):
            LOGGER.info("android_boot_completed device=%s", device_serial)
            return True
        LOGGER.info(
            "android_boot_pending device=%s exit_status=%s error=%s",
            device_serial,
            exit_status,
            error,
        )
        time.sleep(interval)

    LOGGER.error("android_boot_timeout device=%s timeout=%s", device_serial, timeout)
    return False
