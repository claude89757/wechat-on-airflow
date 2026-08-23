import {
  ClipboardTextIcon,
  ShieldCheckIcon,
  TrashIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import {
  createAdminInvites,
  deleteAdminInvite,
  getAdminInvites,
  getAdminUsers,
  getCommunityUsers,
  updateAdminInvite,
  type AdminInvite,
  type AdminUser,
  type CommunityUser,
  type VerificationReceipt,
} from "./api";

function formatDate(value: string | null): string {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

export function CommunityPanel({ receipt }: { receipt: VerificationReceipt }) {
  const [users, setUsers] = useState<CommunityUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void getCommunityUsers(receipt)
      .then((result) => { if (active) setUsers(result.users); })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "读取失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [receipt]);

  if (loading) return <div className="ops-loading">正在读取社区用户…</div>;
  if (error) return <p className="form-error" role="alert">{error}</p>;
  return (
    <div className="ops-panel">
      <div className="ops-intro">
        <UsersThreeIcon size={30} weight="duotone" />
        <div>
          <strong>社区用户</strong>
          <p>仅展示脱敏邮箱和基础运营数据，完整信息只对管理员可见。</p>
        </div>
      </div>
      <div className="ops-list">
        {users.map((user) => (
          <article className="ops-card" key={user.email}>
            <div className="ops-card-title">
              <strong>{user.email}</strong>
              <span>{user.tier === "priority" ? "优先用户" : "普通用户"}</span>
            </div>
            <div className="ops-grid">
              <span><b>{user.activeSubscriptions}</b>有效订阅</span>
              <span><b>{user.deliveredVolume}</b>提醒送达</span>
              <span><b>{user.activity}</b>最近活跃</span>
            </div>
          </article>
        ))}
        {!users.length ? <div className="empty-state"><strong>暂无社区用户</strong></div> : null}
      </div>
    </div>
  );
}

export function AdminPanel({ receipt }: { receipt: VerificationReceipt }) {
  const [tab, setTab] = useState<"invites" | "users">("invites");
  const [invites, setInvites] = useState<AdminInvite[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [count, setCount] = useState(1);
  const [expiresInDays, setExpiresInDays] = useState(90);
  const [note, setNote] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [inviteResult, userResult] = await Promise.all([
        getAdminInvites(receipt),
        getAdminUsers(receipt),
      ]);
      setInvites(inviteResult.invites);
      setUsers(userResult.users);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "管理数据读取失败");
    } finally {
      setLoading(false);
    }
  }, [receipt]);

  useEffect(() => { void refresh(); }, [refresh]);

  const createInvites = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await createAdminInvites(receipt, { count, expiresInDays, note });
      setInvites((current) => [...result.invites, ...current]);
      setNote("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "邀请码创建失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleInvite = async (invite: AdminInvite) => {
    setBusy(true);
    try {
      await updateAdminInvite(receipt, invite.id, { active: !invite.active });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "邀请码更新失败");
    } finally {
      setBusy(false);
    }
  };

  const removeInvite = async (invite: AdminInvite) => {
    setBusy(true);
    try {
      await deleteAdminInvite(receipt, invite.id);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "邀请码删除失败");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div className="ops-loading">正在读取管理数据…</div>;
  return (
    <div className="ops-panel admin-panel">
      <div className="ops-intro admin-intro">
        <ShieldCheckIcon size={30} weight="duotone" />
        <div><strong>管理后台</strong><p>管理邀请码、用户活跃、订阅和邮件生命周期。</p></div>
      </div>
      <div className="ops-tabs">
        <button type="button" className={tab === "invites" ? "selected" : ""} onClick={() => setTab("invites")}>邀请码管理</button>
        <button type="button" className={tab === "users" ? "selected" : ""} onClick={() => setTab("users")}>用户运营</button>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}

      {tab === "invites" ? (
        <>
          <div className="invite-create-card">
            <div className="invite-create-row">
              <label><span>数量</span><input type="number" min={1} max={20} value={count} onChange={(event) => setCount(Math.max(1, Math.min(20, Number(event.target.value) || 1)))} /></label>
              <label><span>有效天数</span><input type="number" min={1} max={365} value={expiresInDays} onChange={(event) => setExpiresInDays(Math.max(1, Math.min(365, Number(event.target.value) || 1)))} /></label>
            </div>
            <label className="field"><span>备注</span><input value={note} maxLength={120} placeholder="例如：内部测试" onChange={(event) => setNote(event.target.value)} /></label>
            <button className="sheet-primary" type="button" disabled={busy} onClick={() => void createInvites()}>{busy ? "处理中…" : "创建邀请码"}</button>
          </div>
          <div className="ops-list">
            {invites.map((invite) => (
              <article className="ops-card invite-card" key={invite.id}>
                <div className="ops-card-title">
                  <strong>{invite.code ?? invite.codeHint ?? "历史口令不可恢复"}</strong>
                  <span>{invite.status}</span>
                </div>
                <p>{invite.note || "无备注"}</p>
                <div className="invite-meta">
                  <span>有效至 {formatDate(invite.expiresAt)}</span>
                  <span>{invite.redeemedBy ? `绑定 ${invite.redeemedBy}` : "尚未使用"}</span>
                  {invite.redeemedAt ? <span>兑换于 {formatDate(invite.redeemedAt)}</span> : null}
                </div>
                <div className="invite-actions">
                  {invite.code ? (
                    <button type="button" onClick={() => void navigator.clipboard.writeText(invite.code || "")}><ClipboardTextIcon size={17} />复制</button>
                  ) : null}
                  {!invite.redeemedBy && invite.status !== "deleted" ? (
                    <button type="button" disabled={busy} onClick={() => void toggleInvite(invite)}>{invite.active ? "停用" : "启用"}</button>
                  ) : null}
                  {invite.status !== "deleted" ? (
                    <button type="button" className="danger" disabled={busy} onClick={() => void removeInvite(invite)}><TrashIcon size={17} />删除</button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="ops-list">
          {users.map((user) => (
            <article className="ops-card admin-user-card" key={user.email}>
              <div className="ops-card-title"><strong>{user.email}</strong><span>{user.isAdmin ? "管理员" : user.tier === "priority" ? "优先用户" : "普通用户"}</span></div>
              <div className="admin-user-times">
                <span>首次验证 {formatDate(user.firstVerifiedAt)}</span>
                <span>最近登录 {formatDate(user.lastLoginAt)}</span>
                <span>最近活跃 {formatDate(user.lastActiveAt)}</span>
              </div>
              <div className="ops-grid admin-metrics">
                <span><b>{user.activeSubscriptions}</b>有效订阅</span>
                <span><b>{user.submittedToday}</b>今日提交</span>
                <span><b>{user.deliveredToday}</b>确认送达</span>
                <span><b>{user.failedToday}</b>发送失败</span>
                <span><b>{user.deliveredAllTime}</b>累计送达</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
