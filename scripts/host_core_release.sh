#!/usr/bin/env bash
# Protected GitHub runner entry. Production credentials never leave the Environment.
set -Eeuo pipefail
umask 077
: "${TARGET_COMMIT:?}" "${OPERATION:?}" "${AIRFLOW_SSH_HOST:?}" "${AIRFLOW_REPOSITORY_PATH:?}"
[[ "$TARGET_COMMIT" =~ ^[0-9a-f]{40}$ ]]
SSH_OPTIONS=(-n -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=20
  -o ServerAliveInterval=15 -o ServerAliveCountMax=120 -o TCPKeepAlive=yes -p "$AIRFLOW_SSH_PORT")
SCP_OPTIONS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=20
  -o ServerAliveInterval=15 -o ServerAliveCountMax=120 -P "$AIRFLOW_SSH_PORT")
remote() {
  local quoted=() argument escaped
  for argument in "$@"; do printf -v escaped '%q' "$argument"; quoted+=("$escaped"); done
  ssh "${SSH_OPTIONS[@]}" "$AIRFLOW_SSH_USER@$AIRFLOW_SSH_HOST" \
    "set -euo pipefail; cd '$AIRFLOW_REPOSITORY_PATH'; DEPLOYMENT_COMMIT='$TARGET_COMMIT' \
     python3 scripts/host_core_command_with_heartbeat.py ${quoted[*]} --target-commit '$TARGET_COMMIT'"
}
checkpoint() {
  ssh "${SSH_OPTIONS[@]}" "$AIRFLOW_SSH_USER@$AIRFLOW_SSH_HOST" \
    "set -euo pipefail; cd '$AIRFLOW_REPOSITORY_PATH'; \
     DEPLOYMENT_COMMIT='$TARGET_COMMIT' AIRFLOW_IMAGE_NAME='wechat-on-airflow:host-$TARGET_COMMIT' \
     docker compose exec -T zacks-api python -m wechat_airflow.host_core.release_checkpoint \
       --expected-commit '$TARGET_COMMIT'"
}
deploy_edge() {
  local kind="$1"
  node - "$kind" <<'JS'
const fs=require('node:fs');
const kind=process.argv[2];
const config=JSON.parse(fs.readFileSync(kind==='maintenance'?'wrangler.migration.jsonc':'wrangler.jsonc','utf8'));
config.vars={...(config.vars||{}),DEPLOYMENT_COMMIT:process.env.TARGET_COMMIT};
config.triggers={crons:[]};
fs.writeFileSync('.wrangler-host-core-runtime.json',JSON.stringify(config));
JS
  npx wrangler deploy --config .wrangler-host-core-runtime.json
  rm -f .wrangler-host-core-runtime.json
}
export_snapshot() {
  local sql="/tmp/zacks-source-${GITHUB_RUN_ID}.sql" log="/tmp/zacks-source-${GITHUB_RUN_ID}.log"
  if ! npx wrangler d1 export zacks-tennis-alerts --config wrangler.migration.jsonc \
      --remote --output "$sql" --skip-confirmation >"$log" 2>&1; then
    echo 'D1 control-plane export failed; private export output was not published' >&2
    return 1
  fi
  test -s "$sql"
  gzip -9 "$sql"
  local sha path
  sha="$(sha256sum "$sql.gz" | cut -d' ' -f1)"
  path="$AIRFLOW_REPOSITORY_PATH/.local/host-core-migration/final-${sha}.sql.gz"
  ssh "${SSH_OPTIONS[@]}" "$AIRFLOW_SSH_USER@$AIRFLOW_SSH_HOST" \
    "install -d -m 0700 '$AIRFLOW_REPOSITORY_PATH/.local/host-core-migration'"
  scp "${SCP_OPTIONS[@]}" "$sql.gz" "$AIRFLOW_SSH_USER@$AIRFLOW_SSH_HOST:$path"
  ssh "${SSH_OPTIONS[@]}" "$AIRFLOW_SSH_USER@$AIRFLOW_SSH_HOST" "chmod 0600 '$path'"
  rm -f "$sql.gz" "$log"
  remote migrate-sql --sql-export "$path" --snapshot-sha256 "$sha"
}
changed=false
recover() {
  local status=$?
  trap - EXIT INT TERM HUP
  set +e
  if [[ "$status" != 0 && "$changed" == true ]]; then
    remote pause-host-delivery
    echo '{"event":"release_failed","recovery":"host_paused_no_legacy_fallback","legacyRuntime":false}' >&2
  fi
  exit "$status"
}
trap recover EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
case "$OPERATION" in
  preflight) remote preflight ;;
  full-cutover)
    changed=true
    remote prepare-runtime | tee /tmp/host-core-prepare.log
    checkpoint | tee /tmp/host-core-checkpoint.json
    migration_complete="$(jq -er 'if (.migrationComplete | type) == "boolean" then (.migrationComplete | tostring) else error("missing migration checkpoint") end' /tmp/host-core-checkpoint.json)"
    if [[ "$migration_complete" == false ]]; then
      # Refuse to overwrite host-side writes when a previous attempt already
      # exposed the pure edge but has lost its migration evidence.
      edge="$(curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
        https://zacks.claude89757.cc/api/edge-healthz)"
      if [[ "$(printf '%s' "$edge" | jq -r '.cutover // false')" == true ]]; then
        echo 'Pure edge already active without a verified checkpoint; refusing D1 re-import' >&2
        exit 1
      fi
      # Freeze the old owner before exporting. This is an explicit maintenance
      # interval, not a compatibility backend or a second delivery owner.
      deploy_edge maintenance
      sleep 300
      remote sync-secrets
      export_snapshot
    else
      echo '{"event":"resume_verified_migration","d1Reimport":false,"secretRotation":false}'
    fi
    remote prepare-routing
    deploy_edge production
    remote cutover
    PYTHONPATH=../scripts python ../scripts/webapp_production_health.py --expected-commit "$TARGET_COMMIT" --format json
    ;;
  activate-workers) changed=true; remote activate-workers ;;
  health) remote health --include-public | tee /tmp/host-core-business-health.log ;;
  acceptance)
    remote acceptance --include-public --wait-seconds 1800 | tee /tmp/host-core-business-health.log
    tail -n 1 /tmp/host-core-business-health.log > /tmp/host-core-acceptance.json
    jq -e '.complete == true and .ok == true and .success == true' /tmp/host-core-acceptance.json >/dev/null
    ;;
  pause) remote pause-host-delivery ;;
  *) echo "Unsupported Host Core operation" >&2; exit 2 ;;
esac
changed=false
