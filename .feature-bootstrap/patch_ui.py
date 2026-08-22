from pathlib import Path
import re
p=Path(__file__).resolve().parents[1]/'webapp/src/Prototype.tsx'
t=p.read_text()
def rep(old,new,count=1):
 global t
 n=t.count(old)
 if n!=count: raise SystemExit(f'ui expected {count}, got {n}: {old[:90]}')
 t=t.replace(old,new,count)
def sub(pattern,new):
 global t
 t,n=re.subn(pattern,new,t,count=1,flags=re.S)
 if n!=1: raise SystemExit(f'ui regex miss: {pattern[:90]}')

rep('''  type Dashboard,
  type VenueId,''','''  type Dashboard,
  type SubscriptionTerm,
  type VenueId,''')
rep('import { LULU_LABELS, resolveLuluState } from "./lulu";','''import { resolveDashboardAvailability, resolveVenueDisplayState } from "./dashboard-state";
import { LULU_LABELS, resolveLuluState } from "./lulu";''')
rep('''];

function formatClock''','''];

const TERM_LABELS: Record<SubscriptionTerm, string> = {
  "7d": "7天", "8d": "8天", "9d": "9天", "10d": "10天",
  "11d": "11天", "12d": "12天", "13d": "13天", "14d": "14天 · 两周",
  "30d": "30天", "90d": "3个月", "180d": "半年", long_term: "长期",
};

function formatClock''')
rep('if (!value) return "等待首次巡检";','if (!value) return "暂无巡检记录";')
sub(r'    identity: receipt\n      \? \{.*?\n        \}\n      : initialDashboard\.identity,','''    identity: receipt
      ? { ...initialDashboard.identity, verified: true, maskedEmail: receipt.maskedEmail }
      : initialDashboard.identity,''')
rep('''  const [loading, setLoading] = useState(true);
  const [serviceOnline, setServiceOnline] = useState(true);''','''  const [loading, setLoading] = useState(true);
  const [serviceOnline, setServiceOnline] = useState(import.meta.env.DEV);
  const [hasSuccessfulDashboard, setHasSuccessfulDashboard] = useState(import.meta.env.DEV);
  const [refreshFailed, setRefreshFailed] = useState(false);''')
rep('''  const [endTime, setEndTime] = useState("22:00");
  const [durationDays, setDurationDays] = useState(7);''','''  const [endTime, setEndTime] = useState("22:00");
  const [subscriptionTerm, setSubscriptionTerm] = useState<SubscriptionTerm>("7d");''')
rep('''      setDashboard(next);
      setServiceOnline(true);''','''      setDashboard(next);
      setServiceOnline(true);
      setHasSuccessfulDashboard(true);
      setRefreshFailed(false);''')
sub(r'    \} catch \{\n      const unavailable = .*?\n      setServiceOnline\(import\.meta\.env\.DEV\);','''    } catch {
      setServiceOnline(import.meta.env.DEV);
      setRefreshFailed(true);''')
rep('''  useEffect(() => {
    if (!toast) return;''','''  useEffect(() => {
    const allowed = dashboard.subscriptionTerms[dashboard.identity.tier];
    if (!allowed.includes(subscriptionTerm)) setSubscriptionTerm("7d");
  }, [dashboard.identity.tier, dashboard.subscriptionTerms, subscriptionTerm]);

  useEffect(() => {
    if (!toast) return;''')
rep('''  const activeIdentity = dashboard.identity.verified
    ? dashboard.identity.maskedEmail
    : receipt?.maskedEmail;
  const luluState = resolveLuluState({
    serviceOnline,''','''  const activeIdentity = dashboard.identity.verified
    ? dashboard.identity.maskedEmail
    : receipt?.maskedEmail;
  const availability = resolveDashboardAvailability({ hasSuccessfulDashboard, loading, refreshFailed });
  const statusLabel = availability === "loading" ? "正在读取服务状态"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "刷新失败，显示上次数据" : "服务运行正常";
  const statusDetail = hasSuccessfulDashboard
    ? `更新于 ${formatUpdatedAt(dashboard.generatedAt)}`
    : loading ? "正在获取最新数据" : "请稍后点击刷新";
  const quotaPercent = dashboard.identity.dailyLimit > 0
    ? Math.min(100, Math.round(dashboard.identity.remindersToday / dashboard.identity.dailyLimit * 100)) : 0;
  const luluState = resolveLuluState({
    serviceOnline: serviceOnline && hasSuccessfulDashboard,''')
rep('''    setInviteCode("");
    setFormError("");''','''    setInviteCode("");
    setSubscriptionTerm("7d");
    setFormError("");''')
rep('''        endTime,
        durationDays,''','''        endTime,
        subscriptionTerm,''')
sub(r'          <div className="service-line" aria-live="polite">.*?<button\n              type="button"', '''          <div className={`service-line service-${availability}`} aria-live="polite">
            <span className={`live-dot ${availability === "ready" ? "" : availability}`} aria-hidden="true" />
            <strong>{statusLabel}</strong>
            <span>{statusDetail}</span>
            <button
              type="button"''')
rep('value={dashboard.metrics.activeSubscriptions}','value={hasSuccessfulDashboard ? dashboard.metrics.activeSubscriptions : "—"}')
rep('value={dashboard.metrics.remindersToday}','value={hasSuccessfulDashboard ? dashboard.metrics.remindersToday : "—"}')
rep('value={`${dashboard.metrics.healthyVenues}/${dashboard.metrics.totalVenues}`}','''value={hasSuccessfulDashboard
                ? `${dashboard.metrics.healthyVenues}/${dashboard.metrics.totalVenues}`
                : `—/${dashboard.metrics.totalVenues}`}''')
rep('<span><CalendarDotsIcon size={18} weight="bold" />7–14天</span>','''<span><CalendarDotsIcon size={18} weight="bold" />
                    {dashboard.identity.tier === "priority" ? "支持长期" : "7–14天"}
                  </span>''')
sub(r'            \{activeIdentity \? \(\n              <div className=\{`tier-row.*?\n            \) : null\}', '''            {activeIdentity && hasSuccessfulDashboard ? (
              <>
                <div className={`tier-row tier-${dashboard.identity.tier}`}>
                  <span className="tier-summary"><StarIcon size={20} weight="fill" /><span>
                    <strong>{dashboard.identity.tier === "priority" ? "优先用户" : "普通用户"}</strong>
                    <small>同时可保留 {dashboard.identity.activeSubscriptionLimit} 个有效订阅</small>
                  </span></span>
                  <button type="button" className={dashboard.identity.tier === "priority" ? "tier-enabled" : undefined}
                    onClick={() => openPanel("priority")}>
                    {dashboard.identity.tier === "priority" ? "查看规则" : "输入邀请码"}
                  </button>
                </div>
                <div className="quota-card" aria-label="今日邮件额度">
                  <div><span>今日邮件额度</span><strong>还可接收 {dashboard.identity.remainingToday} 封</strong></div>
                  <p>每天最多 {dashboard.identity.dailyLimit} 封 · 已用 {dashboard.identity.remindersToday} 封</p>
                  <span className="quota-track" aria-hidden="true"><i style={{ width: `${quotaPercent}%` }} /></span>
                </div>
              </>
            ) : null}''')
rep('''                  const VenueIcon = VENUE_ICONS[venue.id];
                  return (''','''                  const VenueIcon = VENUE_ICONS[venue.id];
                  const venueState = resolveVenueDisplayState(availability, venue.healthy);
                  return (''')
sub(r'                        <strong className=\{venue\.healthy \? "healthy" : "unhealthy"\}>.*?<span>\{formatRelative\(venue\.lastInspectionAt\)\}</span>', '''                        <strong className={venueState}><CheckCircleIcon size={16} weight="fill" />
                          {venueState === "unknown" ? (availability === "loading" ? "正在读取" : "状态未知")
                            : venueState === "healthy" ? "巡检正常" : "巡检异常"}
                        </strong>
                        <span>{venueState === "unknown" ? (availability === "loading" ? "请稍候" : "点击刷新重试")
                          : formatRelative(venue.lastInspectionAt)}</span>''')
rep('{formatClock(venue.lastNotificationAt)}','{venueState === "unknown" ? "—" : formatClock(venue.lastNotificationAt)}')
rep('<span>{venue.lastNotificationAt ? "今日发送" : "今日未发送"}</span>','''<span>{venueState === "unknown" ? "状态未知"
                          : venue.lastNotificationAt ? "今日发送" : "今日未发送"}</span>''')
rep('<div><strong>选择提醒条件</strong><p>设置场地、每日时间段和 7–14 天有效期。</p></div>','''<div><strong>选择提醒条件</strong><p>普通用户可选 7–14 天；优先用户还可选 30 天、3 个月、半年或长期。</p></div>''')
rep('<span>有效至 {subscription.activeUntil.slice(0, 10)}</span>','''<span>{!subscription.eligible ? "优先资格已失效，长期订阅已暂停"
                    : subscription.autoRenew ? "长期有效 · 自动续期"
                    : `有效至 ${subscription.activeUntil.slice(0, 10)}`}</span>''')
rep('<p>使用一次性趣味口令升级，全局邮件额度紧张时优先处理。</p>','<p>使用一次性趣味口令升级，并解锁 30 天、3 个月、半年和长期订阅。</p>')
rep('<li><strong>不计额度：</strong>邮箱验证码和微信消息不受档位限制。</li>','''<li><strong>不计额度：</strong>邮箱验证码和微信消息不受档位限制。</li>
              <li><strong>长期订阅：</strong>优先资格有效期间自动续期，直到主动取消。</li>''')
sub(r'              <fieldset>\n                <legend>订阅有效期.*?</fieldset>', '''              <fieldset>
                <legend>订阅有效期 <span>{dashboard.identity.tier === "priority" ? "优先用户支持长期" : "默认 7 天，最长 14 天"}</span></legend>
                <div className="day-choices term-choices">
                  {dashboard.subscriptionTerms.priority.map((term) => {
                    const allowed = dashboard.subscriptionTerms[dashboard.identity.tier].includes(term);
                    return <button type="button" key={term}
                      className={`${subscriptionTerm === term ? "selected" : ""} ${allowed ? "" : "locked"}`.trim()}
                      aria-pressed={subscriptionTerm === term}
                      onClick={() => allowed ? setSubscriptionTerm(term) : setPanel("priority")}>
                      {!allowed ? <KeyIcon size={14} weight="fill" /> : null}{TERM_LABELS[term]}
                    </button>;
                  })}
                </div>
                {subscriptionTerm === "long_term" ? <p className="term-note">
                  长期订阅会在优先资格有效期间自动续期，直到你主动取消；每日邮件额度和天气规则仍然适用。
                </p> : null}
              </fieldset>''')
p.write_text(t)
print('ui patched')