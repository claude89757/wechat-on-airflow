#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_ACCOUNT_ID:?}"
: "${CLOUDFLARE_API_TOKEN:?}"
target_commit="${1:?target commit required}"
output_dir="${2:-.local/admin-acceptance}"
mkdir -p "$output_dir"

token="acceptance-$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
token_hash="$(python - "$token" <<'PY'
import hashlib,sys
print(hashlib.sha256(sys.argv[1].encode()).hexdigest())
PY
)"
now_ms="$(python - <<'PY'
import time
print(int(time.time()*1000))
PY
)"
expires_ms=$((now_ms + 3600000))

wrangler() {
  (cd webapp && npx wrangler "$@")
}

cleanup() {
  wrangler d1 execute zacks-tennis-alerts --remote \
    --command "DELETE FROM verified_receipts WHERE token_hash='$token_hash';" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wrangler d1 execute zacks-tennis-alerts --remote --command \
  "INSERT OR REPLACE INTO verified_receipts (token_hash,email,masked_email,expires_at,last_used_at,created_at,revoked_at) VALUES ('$token_hash','claudexzt@gmail.com','cl*******@gmail.com',$expires_ms,$now_ms,$now_ms,NULL);" >/dev/null

wrangler d1 execute zacks-tennis-alerts --remote --json --command \
  "SELECT email,role,revoked_at FROM user_roles WHERE email='claudexzt@gmail.com' AND role='admin';" \
  > "$output_dir/d1-admin.json"

base="https://zacks.claude89757.cc"
curl -fsS "$base/api/healthz" > "$output_dir/health.json"
curl -fsS -H "Authorization: Bearer $token" "$base/api/bootstrap" > "$output_dir/bootstrap.json"
curl -fsS -H "Authorization: Bearer $token" "$base/api/community/users" > "$output_dir/community.json"
curl -fsS -H "Authorization: Bearer $token" "$base/api/admin/users" > "$output_dir/admin-users.json"
curl -fsS -H "Authorization: Bearer $token" "$base/api/admin/invites" > "$output_dir/admin-invites.json"

community_status="$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/community/users")"
admin_status="$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/admin/users")"

python - "$target_commit" "$community_status" "$admin_status" "$output_dir" <<'PY'
import json, pathlib, sys
target, community_status, admin_status, output = sys.argv[1:]
root = pathlib.Path(output)
health = json.loads((root/'health.json').read_text())
bootstrap = json.loads((root/'bootstrap.json').read_text())
community = json.loads((root/'community.json').read_text())
users = json.loads((root/'admin-users.json').read_text())
invites = json.loads((root/'admin-invites.json').read_text())
assert health.get('ok') is True
deployed = health.get('deploymentCommit') or health.get('deployment_commit')
if deployed is not None:
    assert deployed == target, (deployed, target)
assert bootstrap['identity']['verified'] is True
assert bootstrap['identity']['isAdmin'] is True
assert isinstance(community.get('users'), list)
assert isinstance(users.get('users'), list)
assert isinstance(invites.get('invites'), list)
assert community_status == '401', community_status
assert admin_status == '401', admin_status
for item in community.get('users', []):
    assert '@' in item['email'] and '*' in item['email']
    assert item['email'] != 'claudexzt@gmail.com'
summary = {
    'ok': True,
    'targetCommit': target,
    'admin': bootstrap['identity']['maskedEmail'],
    'communityUsers': len(community.get('users', [])),
    'adminUsers': len(users.get('users', [])),
    'adminInvites': len(invites.get('invites', [])),
    'anonymousCommunityStatus': community_status,
    'anonymousAdminStatus': admin_status,
}
(root/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps(summary, ensure_ascii=False))
PY

html="$(curl -fsS "$base/")"
script_path="$(printf '%s' "$html" | grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' | head -1)"
test -n "$script_path"
curl -fsS "$base$script_path" > "$output_dir/app.js"
for phrase in '用户社区' '管理后台' '确认送达' '发送失败'; do
  grep -q "$phrase" "$output_dir/app.js"
done

if [ "${RUN_BROWSER_E2E:-true}" = true ]; then
  e2e_script="$output_dir/e2e.mjs"
  cat > "$e2e_script" <<'JS'
import { chromium } from 'playwright';
import fs from 'node:fs';
const [base, token, out] = process.argv.slice(2);
const browser = await chromium.launch({headless:true});
const context = await browser.newContext({viewport:{width:390,height:844}});
const page = await context.newPage();
const errors=[];
page.on('console', msg => { if(msg.type()==='error') errors.push(msg.text()); });
await page.addInitScript(({token}) => {
  localStorage.setItem('zacks-tennis-verified-emails-v1', JSON.stringify([{
    token,
    email:'claudexzt@gmail.com',
    maskedEmail:'cl*******@gmail.com',
    verifiedAt:new Date().toISOString(),
  }]));
}, {token});
await page.goto(base, {waitUntil:'networkidle'});
await page.getByRole('button', {name:/用户社区/}).waitFor();
await page.getByRole('button', {name:/管理后台/}).waitFor();
await page.getByRole('button', {name:/用户社区/}).click();
await page.getByText('社区用户').waitFor();
await page.keyboard.press('Escape');
await page.getByRole('button', {name:/管理后台/}).click();
await page.getByText('邀请码管理').waitFor();
await page.screenshot({path:`${out}/mobile.png`, fullPage:true});
fs.writeFileSync(`${out}/browser.json`, JSON.stringify({ok:errors.length===0,errors},null,2));
if(errors.length) throw new Error(errors.join('\n'));
await browser.close();
JS
  node "$e2e_script" "$base" "$token" "$output_dir"
  rm -f "$e2e_script"
fi
