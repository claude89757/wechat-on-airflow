#!/usr/bin/env bash
set -euo pipefail

APPLY=false
TARGET_COMMIT=""
REPOSITORY_URL="${WECHAT_SENDER_REPOSITORY_URL:-https://github.com/claude89757/wechat-on-airflow.git}"
INSTALL_DIR="${WECHAT_SENDER_INSTALL_DIR:-/opt/wechat-on-airflow}"
VENV_DIR="${WECHAT_SENDER_VENV_DIR:-/opt/wechat-sender-venv}"
CONFIG_FILE="${WECHAT_SENDER_CONFIG_FILE:-/etc/wechat-sender.env}"
SERVICE_NAME="wechat-sender.service"
APPIUM_SERVICE_NAME="appium-6002.service"
APPIUM_OVERRIDE_DIR="/etc/systemd/system/${APPIUM_SERVICE_NAME}.d"
APPIUM_OVERRIDE_FILE="${APPIUM_OVERRIDE_DIR}/wechat-sender.conf"

usage() {
  cat <<'EOF'
Usage: scripts/install_wechat_sender.sh --target-commit <full-sha> [--apply]

The command is read-only by default. Apply mode installs the exact Git commit,
creates a dedicated service user and virtual environment, and enables the
systemd service. The protected configuration file must already contain:

  WECHAT_ALLOWED_DEVICE_NAME=<device>
  WECHAT_APPIUM_URL=http://127.0.0.1:6002
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
[[ -f "$CONFIG_FILE" ]] || fail "missing protected configuration: $CONFIG_FILE"
[[ "$(stat -c '%a' "$CONFIG_FILE")" == "600" ]] || fail "$CONFIG_FILE must have mode 600"
grep -Eq '^WECHAT_ALLOWED_DEVICE_NAME=.+$' "$CONFIG_FILE" ||
  fail "$CONFIG_FILE is missing WECHAT_ALLOWED_DEVICE_NAME"
grep -Eq '^WECHAT_APPIUM_URL=http://(127\.0\.0\.1|localhost):6002/?$' "$CONFIG_FILE" ||
  fail "WECHAT_APPIUM_URL must use the local Appium service on port 6002"
DEVICE_NAME="$(sed -n 's/^WECHAT_ALLOWED_DEVICE_NAME=//p' "$CONFIG_FILE" | tail -n 1)"
[[ "$DEVICE_NAME" =~ ^[A-Za-z0-9._:-]+$ ]] ||
  fail "WECHAT_ALLOWED_DEVICE_NAME must be an adb-safe device serial"
for command in adb appium tesseract; do
  command -v "$command" >/dev/null || fail "required sender command is unavailable: $command"
done
tesseract --list-langs 2>/dev/null | grep -Fxq chi_sim ||
  fail "tesseract chi_sim language data is required"
python3 -c 'from PIL import Image; assert hasattr(Image, "Resampling")' 2>/dev/null ||
  fail "python3-pil with Image.Resampling support is required"
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

fetch_origin
git -C "$INSTALL_DIR" cat-file -e "${TARGET_COMMIT}^{commit}" ||
  fail "target commit is not available from the repository"
git -C "$INSTALL_DIR" checkout --detach "$TARGET_COMMIT"
[[ "$(git -C "$INSTALL_DIR" rev-parse HEAD)" == "$TARGET_COMMIT" ]] ||
  fail "checked-out commit does not match target"

next_venv="${VENV_DIR}.new"
previous_venv="${VENV_DIR}.previous"
rm -rf "$next_venv"
python3 -m venv --system-site-packages "$next_venv"
grep -v '^Pillow==' \
  "$INSTALL_DIR/docker/sender/requirements.lock" \
  >"$next_venv/requirements.lock"
"$next_venv/bin/python" -m pip install --disable-pip-version-check \
  --requirement "$next_venv/requirements.lock"
rm "$next_venv/requirements.lock"
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
