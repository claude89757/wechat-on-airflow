#!/usr/bin/env bash
set -euo pipefail

python .feature/admin/write_backend_files.py
python .feature/admin/write_frontend_files.py
python .feature/admin/patch_backend.py
python .feature-bootstrap/patch_ui.py

python - <<'PY'
from pathlib import Path

path = Path("webapp/src/Prototype.tsx")
text = path.read_text(encoding="utf-8")

def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f"missing UI integration marker: {label}")
    text = text.replace(old, new, 1)

replace_once(
    'import { LULU_LABELS, resolveLuluState } from "./lulu";',
    'import { LULU_LABELS, resolveLuluState } from "./lulu";\nimport { AdminPanel, CommunityPanel } from "./OperationsPanel";',
    "operations imports",
)
replace_once(
    'type Panel = "create" | "help" | "subscriptions" | "priority" | null;',
    'type Panel = "create" | "help" | "subscriptions" | "priority" | "community" | "admin" | null;',
    "panel type",
)
replace_once(
    '    if (panel === "priority") return "提醒档位";\n    return receipt ? "创建订阅" : "验证邮箱";',
    '    if (panel === "priority") return "提醒档位";\n    if (panel === "community") return "用户社区";\n    if (panel === "admin") return "管理后台";\n    return receipt ? "创建订阅" : "验证邮箱";',
    "panel title",
)
subscriptions_block = '''          <button
            className="subscriptions-link"
            type="button"
            onClick={() => openPanel("subscriptions")}
          >
            <ListBulletsIcon size={24} weight="bold" />
            <span>我的订阅</span>
            <span aria-hidden="true">›</span>
          </button>'''
replace_once(
    subscriptions_block,
    subscriptions_block + '''

          {receipt ? (
            <button className="subscriptions-link" type="button" onClick={() => openPanel("community")}>
              <UsersThreeIcon size={24} weight="bold" />
              <span>用户社区</span><span aria-hidden="true">›</span>
            </button>
          ) : null}

          {receipt && dashboard.identity.isAdmin ? (
            <button className="subscriptions-link admin-entry" type="button" onClick={() => openPanel("admin")}>
              <ShieldCheckIcon size={24} weight="bold" />
              <span>管理后台</span><span aria-hidden="true">›</span>
            </button>
          ) : null}''',
    "operations entries",
)
replace_once(
    '        snap={panel === "create" ? 0.86 : panel === "priority" ? 0.82 : 0.72}',
    '        snap={panel === "create" ? 0.86 : panel === "priority" ? 0.82 : panel === "community" || panel === "admin" ? 0.94 : 0.72}',
    "operations panel snap",
)
replace_once(
    '        {panel === "priority" ? (',
    '''        {panel === "community" && receipt ? (
          <CommunityPanel receipt={receipt} />
        ) : null}

        {panel === "admin" && receipt && dashboard.identity.isAdmin ? (
          <AdminPanel receipt={receipt} />
        ) : null}

        {panel === "priority" ? (''',
    "operations panel render",
)
path.write_text(text, encoding="utf-8")

panel = Path("webapp/src/OperationsPanel.tsx")
text = panel.read_text(encoding="utf-8")
for unused in ("  CheckCircleIcon,\n", "  KeyIcon,\n"):
    text = text.replace(unused, "")
panel.write_text(text, encoding="utf-8")

index = Path("webapp/cloudflare/index.ts")
text = index.read_text(encoding="utf-8")
old = '''function base64UrlToBytes(value: string): Uint8Array {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}'''
new = '''function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}'''
if old not in text:
    raise SystemExit("missing base64 compatibility marker")
index.write_text(text.replace(old, new, 1), encoding="utf-8")

prototype = Path("webapp/src/Prototype.tsx")
text = prototype.read_text(encoding="utf-8")
text = text.replace(
    'const allowed = dashboard.subscriptionTerms[dashboard.identity.tier].includes(term);',
    'const allowed = dashboard.subscriptionTerms[dashboard.identity.tier].some((allowedTerm) => allowedTerm === term);',
)
text = text.replace(
    '''        endTime,
        subscriptionTerm,''',
    '''        endTime,
        termCode: subscriptionTerm,''',
)
text = text.replace(
    '<p>每天最多 {dashboard.identity.dailyLimit} 封 · 已用 {dashboard.identity.remindersToday} 封</p>',
    '<p>每天最多 {dashboard.identity.dailyLimit} 封 · 已提交 {dashboard.identity.submittedToday} 封 · 确认送达 {dashboard.identity.deliveredToday} 封 · 发送失败 {dashboard.identity.failedToday} 封</p>',
)
text = text.replace(
    '<span>{venueState === "unknown" ? "状态未知"\n                          : venue.lastNotificationAt ? "今日发送" : "今日未发送"}</span>',
    '<span>{venueState === "unknown" ? "状态未知"\n                          : venue.lastNotificationAt ? "确认送达" : "今日未确认送达"}</span>',
)
prototype.write_text(text, encoding="utf-8")

acceptance = Path("scripts/accept_webapp_admin.sh")
text = acceptance.read_text(encoding="utf-8")
old_accept = '''cleanup() {
  npx wrangler d1 execute zacks-tennis-alerts --remote \\
    --command "DELETE FROM verified_receipts WHERE token_hash='$token_hash';" >/dev/null 2>&1 || true
}
trap cleanup EXIT

npx wrangler d1 execute zacks-tennis-alerts --remote --command \\
  "INSERT OR REPLACE INTO verified_receipts (token_hash,email,masked_email,expires_at,last_used_at,created_at,revoked_at) VALUES ('$token_hash','claudexzt@gmail.com','cl*******@gmail.com',$expires_ms,$now_ms,$now_ms,NULL);" >/dev/null

npx wrangler d1 execute zacks-tennis-alerts --remote --json --command \\
  "SELECT email,role,revoked_at FROM user_roles WHERE email='claudexzt@gmail.com' AND role='admin';" \\
  > "$output_dir/d1-admin.json"'''
new_accept = '''wrangler() {
  (cd webapp && npx wrangler "$@")
}

cleanup() {
  wrangler d1 execute zacks-tennis-alerts --remote \\
    --command "DELETE FROM verified_receipts WHERE token_hash='$token_hash';" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wrangler d1 execute zacks-tennis-alerts --remote --command \\
  "INSERT OR REPLACE INTO verified_receipts (token_hash,email,masked_email,expires_at,last_used_at,created_at,revoked_at) VALUES ('$token_hash','claudexzt@gmail.com','cl*******@gmail.com',$expires_ms,$now_ms,$now_ms,NULL);" >/dev/null

wrangler d1 execute zacks-tennis-alerts --remote --json --command \\
  "SELECT email,role,revoked_at FROM user_roles WHERE email='claudexzt@gmail.com' AND role='admin';" \\
  > "../$output_dir/d1-admin.json"'''
if old_accept in text:
    text = text.replace(old_accept, new_accept, 1)
text = text.replace(
    '''cat > "$output_dir/e2e.mjs" <<'JS'
import { chromium } from 'playwright';''',
    '''e2e_script="webapp/.admin-acceptance-e2e.mjs"
cat > "$e2e_script" <<'JS'
import { chromium } from 'playwright';''',
)
text = text.replace(
    '''node "$output_dir/e2e.mjs" "$base" "$token" "$output_dir"''',
    '''node "$e2e_script" "$base" "$token" "$output_dir"
rm -f "$e2e_script"''',
)
acceptance.write_text(text, encoding="utf-8")
PY

cat >> webapp/src/prototype.css <<'CSS'

/* Extended subscription, delivery lifecycle, community and admin surfaces */
.service-loading .live-dot,.live-dot.loading,.live-dot.unknown{background:#aab5b3}.service-stale .live-dot,.live-dot.stale{background:#e2a93b}.venue-health strong.unknown{color:#8a9795}
.quota-card{display:grid;gap:8px;margin-top:10px;padding:14px 16px;border:1px solid rgba(20,150,137,.16);border-radius:18px;background:linear-gradient(145deg,#f6fbfa,#eef8f6)}.quota-card>div{display:flex;align-items:baseline;justify-content:space-between;gap:12px}.quota-card span,.quota-card p{margin:0;color:#697a77;font-size:12px}.quota-card strong{color:#136f65;font-size:15px}.quota-track{display:block;height:6px;overflow:hidden;border-radius:999px;background:rgba(20,150,137,.12)}.quota-track i{display:block;height:100%;border-radius:inherit;background:currentColor}
.term-choices button{min-width:76px}.term-choices button.locked{opacity:.58}.term-note{margin:10px 0 0;color:#667875;font-size:12px;line-height:1.55}.admin-entry{color:#7b5718}
.ops-panel{display:grid;gap:14px;padding-bottom:18px}.ops-loading{padding:30px 12px;color:#6b7b78;text-align:center}.ops-intro{display:flex;align-items:center;gap:12px;padding:16px;border-radius:18px;background:#f1f8f6;color:#176f65}.ops-intro>div{min-width:0}.ops-intro strong{color:#1d4742;font-size:17px}.ops-intro p,.ops-card p{margin:4px 0 0;color:#71807e;font-size:12px;line-height:1.5}.admin-intro{background:linear-gradient(145deg,#fff9ea,#f3f9f6);color:#a16a12}.ops-list{display:grid;gap:10px}.ops-card{display:grid;gap:10px;padding:14px;border:1px solid rgba(42,112,105,.12);border-radius:16px;background:#fff}.ops-card-title{display:flex;align-items:center;justify-content:space-between;gap:10px}.ops-card-title strong{min-width:0;overflow:hidden;color:#244d48;font-size:14px;text-overflow:ellipsis;white-space:nowrap}.ops-card-title span{flex:0 0 auto;padding:4px 8px;border-radius:999px;background:#edf7f5;color:#29766d;font-size:10px;font-weight:700}.ops-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.ops-grid span{display:grid;gap:2px;padding:8px;border-radius:12px;background:#f7faf9;color:#71807d;font-size:10px}.ops-grid b{color:#24504a;font-size:13px}.ops-tabs{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;padding:4px;border-radius:14px;background:#eef4f2}.ops-tabs button{padding:10px;border:0;border-radius:11px;background:transparent;color:#667875;font-weight:700}.ops-tabs button.selected{background:#fff;color:#176f65;box-shadow:0 2px 8px rgba(20,80,72,.08)}
.invite-create-card{display:grid;gap:10px;padding:14px;border-radius:16px;background:#f7faf9}.invite-create-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.invite-create-row label,.admin-user-times{display:grid;gap:5px;color:#697a77;font-size:11px}.invite-create-row input,.invite-create-card .field input{width:100%;box-sizing:border-box;padding:10px 11px;border:1px solid rgba(42,112,105,.16);border-radius:11px;background:#fff;color:#234d48}.invite-meta,.admin-user-times{display:flex;flex-wrap:wrap;gap:6px 12px;color:#758481;font-size:10px}.invite-actions{display:flex;flex-wrap:wrap;gap:7px}.invite-actions button{display:inline-flex;align-items:center;gap:4px;padding:7px 10px;border:1px solid rgba(42,112,105,.14);border-radius:10px;background:#f7fbfa;color:#2a6d65;font-size:11px;font-weight:700}.invite-actions button.danger{color:#b45249}.admin-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
CSS
