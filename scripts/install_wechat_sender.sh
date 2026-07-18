#!/usr/bin/env bash
set -euo pipefail

APPLY=false
TARGET_COMMIT=""
REPOSITORY_URL="${WECHAT_SENDER_REPOSITORY_URL:-https://github.com/claude89757/wechat-on-airflow.git}"
INSTALL_DIR="${WECHAT_SENDER_INSTALL_DIR:-/opt/wechat-on-airflow}"
VENV_DIR="${WECHAT_SENDER_VENV_DIR:-/opt/wechat-sender-venv}"
CONFIG_FILE="${WECHAT_SENDER_CONFIG_FILE:-/etc/wechat-sender.env}"
SERVICE_NAME="wechat-sender.service"

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
python3 -m venv "$next_venv"
"$next_venv/bin/python" -m pip install --disable-pip-version-check \
  --requirement "$INSTALL_DIR/docker/sender/requirements.lock"
rm -rf "$previous_venv"
if [[ -d "$VENV_DIR" ]]; then
  mv "$VENV_DIR" "$previous_venv"
fi
mv "$next_venv" "$VENV_DIR"

install -o root -g root -m 0644 \
  "$INSTALL_DIR/deploy/systemd/wechat-sender.service" \
  "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:7001/readyz >/dev/null; then
    systemctl is-enabled --quiet "$SERVICE_NAME"
    systemctl is-active --quiet "$SERVICE_NAME"
    printf 'wechat-sender deploy: apply and readiness verification succeeded\n'
    exit 0
  fi
  sleep 2
done

systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
fail "service did not become ready"
