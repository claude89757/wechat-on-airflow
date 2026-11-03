#!/usr/bin/env bash
set -euo pipefail

APPLY=false
TARGET_COMMIT=""
WHEELHOUSE=""
REPOSITORY_URL="${WECHAT_SENDER_REPOSITORY_URL:-https://github.com/claude89757/wechat-on-airflow.git}"
INSTALL_DIR="${WECHAT_SENDER_INSTALL_DIR:-/opt/wechat-on-airflow}"
VENV_DIR="${WECHAT_SENDER_VENV_DIR:-/opt/wechat-sender-venv}"
CREDENTIAL_DIR="${WECHAT_SENDER_CREDENTIAL_DIR:-/etc/wechat-sender/credentials}"
SERVICE_NAME="wechat-sender.service"
APPIUM_SERVICE_NAME="appium-6002.service"
APPIUM_OVERRIDE_DIR="/etc/systemd/system/${APPIUM_SERVICE_NAME}.d"
APPIUM_OVERRIDE_FILE="${APPIUM_OVERRIDE_DIR}/wechat-sender.conf"

usage() {
  cat <<'EOF'
Usage: scripts/install_wechat_sender.sh --target-commit <full-sha> [--wheelhouse <staged-file>] [--apply]

The command is read-only by default. Apply mode installs the exact Git commit,
creates a dedicated service user and virtual environment, and enables the
systemd service. The protected credential directory must already contain:

  wechat_allowed_device_name
  wechat_appium_url
EOF
}

fail() {
  printf 'wechat-sender deploy: %s\n' "$*" >&2
  exit 1
}

fetch_origin() {
  local attempt
  for attempt in 1 2 3; do
    if git -C "$INSTALL_DIR" fetch --force origin '+refs/heads/*:refs/remotes/origin/*'; then
      return 0
    fi
    if [[ "$attempt" != 3 ]]; then
      sleep "$((attempt * 5))"
    fi
  done
  fail "Git fetch failed after 3 attempts"
}

while (($#)); do
  case "$1" in
    --apply)
      APPLY=true
      shift
      ;;
    --target-commit)
      (($# >= 2)) || fail "--target-commit requires a value"
      TARGET_COMMIT="$2"
      shift 2
      ;;
    --wheelhouse)
      (($# >= 2)) || fail "--wheelhouse requires a value"
      WHEELHOUSE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$TARGET_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "target commit must be a full lowercase SHA"
[[ -d "$CREDENTIAL_DIR" ]] || fail "missing protected credentials: $CREDENTIAL_DIR"
[[ "$(stat -c '%a' "$CREDENTIAL_DIR")" == "700" ]] || fail "$CREDENTIAL_DIR must have mode 700"
for credential in wechat_allowed_device_name wechat_appium_url; do
  [[ -s "$CREDENTIAL_DIR/$credential" ]] || fail "missing credential: $credential"
  [[ "$(stat -c '%a' "$CREDENTIAL_DIR/$credential")" == "600" ]] ||
    fail "$credential must have mode 600"
done
grep -Eq '^http://(127\.0\.0\.1|localhost):6002/?$' "$CREDENTIAL_DIR/wechat_appium_url" ||
  fail "WECHAT_APPIUM_URL must use the local Appium service on port 6002"
DEVICE_NAME="$(tr -d '\r\n' <"$CREDENTIAL_DIR/wechat_allowed_device_name")"
[[ "$DEVICE_NAME" =~ ^[A-Za-z0-9._:-]+$ ]] ||
  fail "WECHAT_ALLOWED_DEVICE_NAME must be an adb-safe device serial"
for command in adb appium tesseract; do
  command -v "$command" >/dev/null || fail "required sender command is unavailable: $command"
done
tesseract --list-langs 2>/dev/null | grep -Fxq chi_sim ||
  fail "tesseract chi_sim language data is required"
# Preserve the established service interpreter/minor version for an upgrade.
# A new standalone installation may use the documented Python 3.12 baseline.
SENDER_PYTHON="$VENV_DIR/bin/python"
if [[ ! -e "$VENV_DIR" && ! -L "$VENV_DIR" ]]; then
  SENDER_PYTHON=python3.12
fi
"$SENDER_PYTHON" -c 'import sys, venv; assert sys.version_info[:2] in {(3, 11), (3, 12)}' 2>/dev/null ||
  fail "Sender Python 3.11 or 3.12 with venv support is required"
[[ "$(adb -s "$DEVICE_NAME" get-state 2>/dev/null)" == "device" ]] ||
  fail "configured Android device is not online in adb"
adb -s "$DEVICE_NAME" shell pm path com.tencent.mm 2>/dev/null | grep -q '^package:' ||
  fail "WeChat is not installed on the configured Android device"
systemctl cat "$APPIUM_SERVICE_NAME" >/dev/null 2>&1 ||
  fail "$APPIUM_SERVICE_NAME is not installed"

printf 'wechat-sender deploy: target=%s apply=%s\n' "$TARGET_COMMIT" "$APPLY"
printf 'wechat-sender deploy: install_dir=%s service=%s\n' "$INSTALL_DIR" "$SERVICE_NAME"

if [[ "$APPLY" != true ]]; then
  printf 'wechat-sender deploy: preflight ok; no changes applied\n'
  exit 0
fi

[[ "$(id -u)" == "0" ]] || fail "--apply must run as root"
for command in curl git python3 systemctl; do
  command -v "$command" >/dev/null || fail "required command is unavailable: $command"
done

if ! id wechat-sender >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin wechat-sender
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  git clone --filter=blob:none --no-checkout "$REPOSITORY_URL" "$INSTALL_DIR"
else
  [[ -z "$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=no)" ]] ||
    fail "$INSTALL_DIR has tracked changes"
  git -C "$INSTALL_DIR" remote set-url origin "$REPOSITORY_URL"
fi

if ! git -C "$INSTALL_DIR" cat-file -e "${TARGET_COMMIT}^{commit}" 2>/dev/null; then
  fetch_origin
fi
git -C "$INSTALL_DIR" cat-file -e "${TARGET_COMMIT}^{commit}" ||
  fail "target commit is not available from the repository"
git -C "$INSTALL_DIR" checkout --detach "$TARGET_COMMIT"
[[ "$(git -C "$INSTALL_DIR" rev-parse HEAD)" == "$TARGET_COMMIT" ]] ||
  fail "checked-out commit does not match target"

next_venv="${VENV_DIR}.new"
previous_venv="${VENV_DIR}.previous"
rm -rf "$next_venv"
# Do not inherit distribution Pillow: its version is outside our release lock.
"$SENDER_PYTHON" -m venv "$next_venv"
wheelhouse_stage="$(mktemp -d "${VENV_DIR}.wheelhouse.XXXXXXXX")"
cleanup_wheelhouse_stage() {
  rm -rf -- "$wheelhouse_stage"
}
trap cleanup_wheelhouse_stage EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# Independently validate the complete archive using the replacement interpreter.
wheelhouse_verified="$("$next_venv/bin/python" "$INSTALL_DIR/scripts/sender_wheelhouse.py" \
  --lock "$INSTALL_DIR/docker/sender/requirements.lock" \
  --manifest "$INSTALL_DIR/config/sender-arm32-wheelhouse.json" --artifact "$WHEELHOUSE" \
  --directory "$wheelhouse_stage/wheels")" || fail "staged wheelhouse verification failed"
if [[ "$wheelhouse_verified" == true ]]; then
  "$next_venv/bin/python" - "$INSTALL_DIR/docker/sender/requirements.lock" "$wheelhouse_stage/wheels" <<'OFFLINE_INSTALL_PY'
import os
import sys

environment = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
environment["PIP_CONFIG_FILE"] = os.devnull
# Replace this process so normal termination and timeout ownership stay with pip.
os.execve(sys.executable, [sys.executable, "-m", "pip", "--isolated", "install", "--disable-pip-version-check", "--no-cache-dir", "--only-binary=:all:", "--no-index", "--find-links", sys.argv[2], "--requirement", sys.argv[1]], environment)
OFFLINE_INSTALL_PY
elif [[ "$wheelhouse_verified" == false ]]; then
  "$next_venv/bin/python" -m pip install --disable-pip-version-check \
    --only-binary=Pillow --requirement "$INSTALL_DIR/docker/sender/requirements.lock"
else
  fail "staged wheelhouse returned invalid evidence"
fi
"$next_venv/bin/python" "$INSTALL_DIR/sender_agent/verify_dependencies.py" \
  "$INSTALL_DIR/docker/sender/requirements.lock"
cleanup_wheelhouse_stage
trap - EXIT HUP INT TERM
# Validate before replacing the active environment or restarting any service.
rm -rf "$previous_venv"
if [[ -d "$VENV_DIR" ]]; then
  mv "$VENV_DIR" "$previous_venv"
fi
mv "$next_venv" "$VENV_DIR"

install -o root -g root -m 0644 \
  "$INSTALL_DIR/deploy/systemd/wechat-sender.service" \
  "/etc/systemd/system/$SERVICE_NAME"
install -d -o root -g root -m 0755 "$APPIUM_OVERRIDE_DIR"
install -o root -g root -m 0644 \
  "$INSTALL_DIR/deploy/systemd/appium-6002.override.conf" \
  "$APPIUM_OVERRIDE_FILE"

adb -s "$DEVICE_NAME" shell svc power stayon usb
adb -s "$DEVICE_NAME" shell settings put global window_animation_scale 0
adb -s "$DEVICE_NAME" shell settings put global transition_animation_scale 0
adb -s "$DEVICE_NAME" shell settings put global animator_duration_scale 0
adb -s "$DEVICE_NAME" shell dumpsys deviceidle whitelist +com.tencent.mm >/dev/null || true

printf 'DEPLOYMENT_COMMIT=%s\n' "$TARGET_COMMIT" >/etc/wechat-sender/release.env
chmod 0644 /etc/wechat-sender/release.env
systemctl daemon-reload
systemctl enable "$APPIUM_SERVICE_NAME"
systemctl restart "$APPIUM_SERVICE_NAME"
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:7001/readyz >/dev/null; then
    systemctl is-enabled --quiet "$SERVICE_NAME"
    systemctl is-active --quiet "$SERVICE_NAME"
    systemctl is-enabled --quiet "$APPIUM_SERVICE_NAME"
    systemctl is-active --quiet "$APPIUM_SERVICE_NAME"
    printf 'wechat-sender deploy: apply and readiness verification succeeded\n'
    exit 0
  fi
  sleep 2
done

systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
fail "service did not become ready"
