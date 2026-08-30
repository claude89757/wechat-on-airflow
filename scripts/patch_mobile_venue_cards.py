from pathlib import Path
import re

def replace_once(source: str, before: str, after: str, label: str) -> str:
    count = source.count(before)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    return source.replace(before, after, 1)

def replace_regex(source: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected one regex match, found {count}")
    return updated

prototype_path = Path("webapp/src/Prototype.tsx")
source = prototype_path.read_text(encoding="utf-8")

format_relative = '''function formatRelative(value: string | null): string {
  if (!value) return "暂无巡检记录";
  const then = new Date(value).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${Math.max(seconds, 1)} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  return `${Math.floor(seconds / 3600)} 小时前`;
}
'''
format_relative_after = format_relative + '''
function formatCompactRelative(value: string | null): string {
  if (!value) return "暂无";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "暂无";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${Math.max(seconds, 1)}秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟前`;
  return `${Math.floor(seconds / 3600)}小时前`;
}

function formatCardNotification(
  value: string | null,
  venueState: "healthy" | "unhealthy" | "unknown",
  weatherSuppressed: boolean,
): string {
  if (venueState === "unknown") return "状态未知";
  if (value) return formatClock(value);
  if (weatherSuppressed) return "邮件暂停";
  return "今日无送达";
}

function sameSelection(
  left: readonly (string | number)[],
  right: readonly (string | number)[],
): boolean {
  if (left.length !== right.length) return false;
  return left.map(String).sort().join("|") === right.map(String).sort().join("|");
}
'''
source = replace_once(source, format_relative, format_relative_after, "format helpers")

source = replace_once(
    source,
    '''  const [venueIds, setVenueIds] = useState<VenueId[]>(["szw", "tops"]);
  const [weekdays, setWeekdays] = useState<Weekday[]>([...WEEKDAYS]);
''',
    '''  const [venueIds, setVenueIds] = useState<VenueId[]>(["szw", "tops"]);
  const [quickVenueId, setQuickVenueId] = useState<VenueId | null>(null);
  const [highlightedVenueId, setHighlightedVenueId] = useState<VenueId | null>(null);
  const [weekdays, setWeekdays] = useState<Weekday[]>([...WEEKDAYS]);
''',
    "quick venue state",
)

source = replace_once(
    source,
    '''  useEffect(() => {
    previousReminderCount.current = null;
    setNotificationBurst(false);
  }, [receipt?.token]);
  ''',
    '''  useEffect(() => {
    if (!highlightedVenueId) return;
    const timer = window.setTimeout(() => setHighlightedVenueId(null), 1800);
    return () => window.clearTimeout(timer);
  }, [highlightedVenueId]);

  useEffect(() => {
    previousReminderCount.current = null;
    setNotificationBurst(false);
  }, [receipt?.token]);
  ''',
    "card highlight effect",
)

source = replace_once(
    source,
    '''  const popularVenues = useMemo(() => [...dashboard.venues].sort((left, right) =>
  right.subscriberCount - left.subscriberCount
    || left.name.localeCompare(right.name, "zh-CN")
    || left.id.localeCompare(right.id)
), [dashboard.venues]);
  const selectedVenueNames = useMemo(() => popularVenues
    .filter((venue) => venueIds.includes(venue.id))
    .map((venue) => venue.name), [popularVenues, venueIds]);
  const subscriptionFormReady = venueIds.length > 0
    && weekdays.length > 0
    && startTime < endTime;
  const subscriptionSummary = `${venueIds.length} 个场地 · ${formatWeekdays(weekdays)} · ${startTime}–${endTime} · ${TERM_LABELS[subscriptionTerm]}`;
''',
    '''  const popularVenues = useMemo(() => [...dashboard.venues].sort((left, right) =>
  right.subscriberCount - left.subscriberCount
    || left.name.localeCompare(right.name, "zh-CN")
    || left.id.localeCompare(right.id)
), [dashboard.venues]);
  const selectedVenueNames = useMemo(() => popularVenues
    .filter((venue) => venueIds.includes(venue.id))
    .map((venue) => venue.name), [popularVenues, venueIds]);
  const quickVenue = useMemo(() => quickVenueId
    ? popularVenues.find((venue) => venue.id === quickVenueId) ?? null
    : null, [popularVenues, quickVenueId]);
  const QuickVenueIcon = quickVenue ? VENUE_ICONS[quickVenue.id] : TennisBallIcon;
  const activeVenueSubscriptionCounts = useMemo(() => {
    const counts = new Map<VenueId, number>();
    for (const subscription of dashboard.subscriptions) {
      if (!subscription.active || !subscription.eligible) continue;
      for (const venueId of subscription.venueIds) {
        counts.set(venueId, (counts.get(venueId) ?? 0) + 1);
      }
    }
    return counts;
  }, [dashboard.subscriptions]);
  const quickVenueSubscriptions = useMemo(() => quickVenue
    ? dashboard.subscriptions.filter((subscription) =>
        subscription.active
        && subscription.eligible
        && subscription.venueIds.includes(quickVenue.id))
    : [], [dashboard.subscriptions, quickVenue]);
  const duplicateSubscription = useMemo(() => dashboard.subscriptions.some((subscription) =>
    subscription.active
      && subscription.eligible
      && sameSelection(subscription.venueIds, venueIds)
      && sameSelection(subscription.weekdays, weekdays)
      && subscription.startTime === startTime
      && subscription.endTime === endTime
      && subscription.termCode === subscriptionTerm
  ), [dashboard.subscriptions, endTime, startTime, subscriptionTerm, venueIds, weekdays]);
  const subscriptionLimitReached = Boolean(
    receipt && hasSuccessfulDashboard && dashboard.identity.remainingSubscriptions <= 0,
  );
  const subscriptionFormReady = venueIds.length > 0
    && weekdays.length > 0
    && startTime < endTime
    && !duplicateSubscription
    && !subscriptionLimitReached;
  const subscriptionSummary = `${venueIds.length} 个场地 · ${formatWeekdays(weekdays)} · ${startTime}–${endTime} · ${TERM_LABELS[subscriptionTerm]}`;
''',
    "derived quick create state",
)

open_panel = '''  const openPanel = (nextPanel: Exclude<Panel, null>) => {
  keyboard.hide();
  setFormError("");
  if (nextPanel === "coffee") resetCoffeeFlow();
  setPanel(nextPanel);
};
'''
source = replace_once(
    source,
    open_panel,
    open_panel + '''
const openCreatePanel = (venueId?: VenueId) => {
  keyboard.hide();
  setFormError("");
  if (venueId) {
    setVenueIds([venueId]);
    setQuickVenueId(venueId);
  } else {
    setQuickVenueId(null);
  }
  setPanel("create");
};
''',
    "open quick create",
)

source = replace_once(
    source,
    '''      resetCoffeeFlow();
      setToast("请先验证邮箱，再回来领取彩蛋");
      setPanel("create");
      return;
''',
    '''      resetCoffeeFlow();
      setToast("请先验证邮箱，再回来领取彩蛋");
      openCreatePanel();
      return;
''',
    "coffee verification handoff",
)

source = replace_once(
    source,
    '''    if (startTime >= endTime) {
      setFormError("结束时间必须晚于开始时间");
      return;
    }

    setFormBusy(true);
''',
    '''    if (startTime >= endTime) {
      setFormError("结束时间必须晚于开始时间");
      return;
    }
    if (subscriptionLimitReached) {
      setFormError(`有效订阅已达到 ${dashboard.identity.activeSubscriptionLimit} 个上限`);
      return;
    }
    if (duplicateSubscription) {
      setFormError("已存在完全相同的提醒，无需重复创建");
      return;
    }

    setFormBusy(true);
''',
    "subscription guards",
)

source = replace_once(
    source,
    '''      setPanel(null);
      celebrationCounter.current += 1;
      setCelebrationId(celebrationCounter.current);
      setToast(`订阅已创建：${subscriptionSummary}`);
      await refresh();
''',
    '''      const createdQuickVenue = quickVenue;
      setPanel(null);
      setQuickVenueId(null);
      if (createdQuickVenue) setHighlightedVenueId(createdQuickVenue.id);
      celebrationCounter.current += 1;
      setCelebrationId(celebrationCounter.current);
      setToast(createdQuickVenue
        ? `${createdQuickVenue.name}提醒已创建 · ${formatWeekdays(weekdays)} · ${startTime}–${endTime} · ${TERM_LABELS[subscriptionTerm]}`
        : `订阅已创建：${subscriptionSummary}`);
      await refresh();
''',
    "quick create success",
)

source = replace_once(
    source,
    '''  const panelTitle = useMemo(() => {
      if (panel === "help") return "提醒如何工作";
      if (panel === "subscriptions") return "我的订阅";
      if (panel === "priority") return "提醒档位";
      if (panel === "community") return "用户社区";
      if (panel === "admin") return "管理后台";
      if (panel === "coffee") return "支持 Zacks";
      return receipt ? "创建订阅" : "验证邮箱";
    }, [panel, receipt]);
''',
    '''  const panelTitle = useMemo(() => {
      if (panel === "help") return "提醒如何工作";
      if (panel === "subscriptions") return "我的订阅";
      if (panel === "priority") return "提醒档位";
      if (panel === "community") return "用户社区";
      if (panel === "admin") return "管理后台";
      if (panel === "coffee") return "支持 Zacks";
      if (panel === "create" && quickVenue) {
        return receipt ? `创建${quickVenue.name}提醒` : `订阅${quickVenue.name}`;
      }
      return receipt ? "创建订阅" : "验证邮箱";
    }, [panel, quickVenue, receipt]);
''',
    "dynamic panel title",
)

source = replace_once(
    source,
    '''            <button className="primary-button" type="button" onClick={() => openPanel("create")}>
''',
    '''            <button className="primary-button" type="button" onClick={() => openCreatePanel()}>
''',
    "main create action",
)

venue_section = '''          <section className="venue-section" aria-labelledby="venue-heading">
  <div className="section-heading">
    <div>
      <h2 id="venue-heading">场地运行状态</h2>
      <p>点按卡片快速创建提醒 · 页面每 30 秒更新</p>
    </div>
    <span><ArrowsClockwiseIcon size={17} />最长缓存 2 分钟</span>
  </div>

  <div className="venue-card-legend" aria-label="卡片指标说明">
    <span><i className="venue-status-dot healthy" aria-hidden="true" />巡检</span>
    <span><ArrowsClockwiseIcon size={14} aria-hidden="true" />同步</span>
    <span><UsersThreeIcon size={14} aria-hidden="true" />关注</span>
    <span><EnvelopeSimpleIcon size={14} aria-hidden="true" />送达</span>
  </div>

  <div className="venue-grid">
    {popularVenues.map((venue) => {
      const VenueIcon = VENUE_ICONS[venue.id];
      const venueState = resolveVenueDisplayState(availability, venue.healthy);
      const inspectionCadence = formatInspectionCadence(venue.id);
      const compactCadence = inspectionCadence.replace("/次", "");
      const compactRelative = formatCompactRelative(venue.lastInspectionAt);
      const existingSubscriptionCount = activeVenueSubscriptionCounts.get(venue.id) ?? 0;
      const actionState = existingSubscriptionCount > 0
        ? "subscribed"
        : subscriptionLimitReached ? "full" : "add";
      const actionLabel = existingSubscriptionCount > 0
        ? `✓${existingSubscriptionCount}`
        : subscriptionLimitReached ? "已满" : "+";
      const statusText = venueState === "unknown"
        ? availability === "loading" ? "读取中" : "未知"
        : venueState === "healthy" ? "正常" : "异常";
      const mailText = formatCardNotification(
        venue.lastNotificationAt,
        venueState,
        Boolean(dashboard.weatherEmailGate?.suppressed),
      );
      const mailTone = venue.lastNotificationAt
        ? ""
        : dashboard.weatherEmailGate?.suppressed ? "is-paused" : "is-muted";

      return (
        <button
          className={[
            "venue-card",
            `venue-card-${venueState}`,
            existingSubscriptionCount > 0 ? "is-subscribed" : "",
            highlightedVenueId === venue.id ? "is-highlighted" : "",
          ].filter(Boolean).join(" ")}
          type="button"
          key={venue.id}
          data-testid={`venue-card-${venue.id}`}
          data-venue-id={venue.id}
          aria-label={`为${venue.name}快速创建提醒；${statusText}，${inspectionCadence}，状态同步${compactRelative}，${venue.subscriberCount}人关注，${mailText}`}
          onClick={() => openCreatePanel(venue.id)}
        >
          <span className="venue-card-heading">
            <span className={`venue-card-icon venue-icon-${VENUE_ACCENTS[venue.id]}`} aria-hidden="true">
              <VenueIcon size={17} weight="duotone" />
            </span>
            <span className="venue-card-name">{venue.name}</span>
            <span className={`venue-card-action is-${actionState}`} aria-hidden="true">
              {actionLabel}
            </span>
          </span>

          <span className="venue-card-status">
            <i className={`venue-status-dot ${venueState}`} aria-hidden="true" />
            <strong>{statusText}</strong>
            <small>{compactCadence}</small>
          </span>

          <span className="venue-card-meta">
            <span><ArrowsClockwiseIcon size={13} aria-hidden="true" />{compactRelative}</span>
            <span className="venue-card-followers">
              <UsersThreeIcon size={13} aria-hidden="true" />{venue.subscriberCount}
            </span>
          </span>

          <span className={`venue-card-mail ${mailTone}`.trim()}>
            <EnvelopeSimpleIcon size={13} weight="fill" aria-hidden="true" />
            {mailText}
          </span>
        </button>
      );
    })}
  </div>
</section>
'''
source = replace_regex(
    source,
    r'          <section className="venue-section" aria-labelledby="venue-heading">.*?          </section>\n\n        </main>',
    venue_section + '\n        </main>',
    "venue card section",
)

source = replace_once(
    source,
    '''          if (!open) {
      if (panel === "coffee") resetCoffeeFlow();
      setPanel(null);
    }
''',
    '''          if (!open) {
      if (panel === "coffee") resetCoffeeFlow();
      setPanel(null);
      setQuickVenueId(null);
    }
''',
    "close quick context",
)

source = replace_once(
    source,
    '''        description={
      panel === "create"
        ? "只设置提醒条件，不展示或代订场地。"
        : undefined
    }
    snap={panel === "coffee" || panel === "community" || panel === "admin"
      ? 0.94
      : panel === "create" ? 0.86 : panel === "priority" ? 0.82 : 0.72}
''',
    '''        description={
      panel === "create"
        ? quickVenue
          ? `已选择${quickVenue.name}，设置星期、时段和有效期即可。`
          : "只设置提醒条件，不展示或代订场地。"
        : undefined
    }
    snap={panel === "coffee" || panel === "community" || panel === "admin"
      ? 0.94
      : panel === "create" ? quickVenue ? 0.82 : 0.86 : panel === "priority" ? 0.82 : 0.72}
''',
    "quick sheet description",
)

source = replace_once(
    source,
    '''                <button type="button" onClick={() => setPanel("create")}>创建第一个订阅</button>
''',
    '''                <button type="button" onClick={() => openCreatePanel()}>创建第一个订阅</button>
''',
    "empty state create",
)
source = replace_once(
    source,
    '''                <button type="button" onClick={() => setPanel("create")}>去验证邮箱</button>
''',
    '''                <button type="button" onClick={() => openCreatePanel()}>去验证邮箱</button>
''',
    "priority verification",
)

identity_block = '''              <div className="sheet-identity">
      <ShieldCheckIcon size={22} weight="fill" />
      <span><strong>{receipt.maskedEmail}</strong> 已验证</span>
      <button type="button" onClick={changeEmail}>更换</button>
    </div>
'''
source = replace_once(
    source,
    identity_block,
    identity_block + '''
    {subscriptionLimitReached ? (
      <div className="subscription-limit-notice" role="alert">
        <ShieldCheckIcon size={22} weight="fill" aria-hidden="true" />
        <div>
          <strong>有效订阅已达到 {dashboard.identity.activeSubscriptionLimit} 个上限</strong>
          <span>先取消不再需要的提醒，再创建新的场地订阅。</span>
        </div>
        <button type="button" onClick={() => openPanel("subscriptions")}>管理</button>
      </div>
    ) : null}
''',
    "subscription limit notice",
)

create_venue_block = '''              {quickVenue ? (
      <fieldset className="quick-venue-selection">
        <legend>已选场地 <span>快速创建</span></legend>
        <div className="quick-venue-chip">
          <span className={`quick-venue-icon venue-icon-${VENUE_ACCENTS[quickVenue.id]}`} aria-hidden="true">
            <QuickVenueIcon size={20} weight="duotone" />
          </span>
          <span className="quick-venue-copy">
            <strong>{quickVenue.name}</strong>
            <small>
              {quickVenueSubscriptions.length
                ? `已有 ${quickVenueSubscriptions.length} 个有效提醒包含此场地`
                : "场地已选好，继续设置提醒条件"}
            </small>
          </span>
          <button type="button" onClick={() => setQuickVenueId(null)}>
            添加其他场地
          </button>
        </div>
        {quickVenueSubscriptions.length ? (
          <div className="quick-subscription-notice" role="status">
            <CheckCircleIcon size={18} weight="fill" aria-hidden="true" />
            <span>可以继续新增不同星期或时段的提醒。</span>
            <button type="button" onClick={() => openPanel("subscriptions")}>查看已有</button>
          </div>
        ) : null}
      </fieldset>
    ) : (
      <fieldset>
        <legend>选择场地 <span>可多选</span></legend>
        <div className="choice-toolbar">
          <span>已选 {venueIds.length}/{popularVenues.length} · 热门优先</span>
          <div>
            <button type="button" onClick={selectAllVenues}>全选</button>
            <button type="button" onClick={clearVenues}>清空</button>
          </div>
        </div>
        <div className="venue-choices">
          {popularVenues.map((venue) => {
            const selected = venueIds.includes(venue.id);
            return (
              <button
                type="button"
                key={venue.id}
                className={selected ? "selected" : ""}
                aria-pressed={selected}
                onClick={() => toggleVenue(venue.id)}
              >
                <CheckCircleIcon size={18} weight={selected ? "fill" : "regular"} />
                <span>{venue.name}</span>
                <small>{venue.subscriberCount} 人</small>
              </button>
            );
          })}
        </div>
      </fieldset>
    ))}
'''
source = replace_regex(
    source,
    r'              <fieldset>\n                <legend>选择场地 <span>可多选</span></legend>.*?              </fieldset>\n\n(?=              <fieldset aria-describedby="weekday-help">)',
    create_venue_block + '\n\n',
    "conditional venue picker",
)

source = replace_once(
    source,
    '''              <div className="subscription-summary" aria-live="polite" id="subscription-summary">
      <span>即将创建</span>
      <strong>{subscriptionSummary}</strong>
      <p>{selectedVenueNames.length ? selectedVenueNames.join("、") : "尚未选择场地"}</p>
    </div>

    {formError ? <p className="form-error" role="alert">{formError}</p> : null}
''',
    '''              <div className="subscription-summary" aria-live="polite" id="subscription-summary">
      <span>即将创建</span>
      <strong>{subscriptionSummary}</strong>
      <p>{selectedVenueNames.length ? selectedVenueNames.join("、") : "尚未选择场地"}</p>
    </div>

    {duplicateSubscription ? (
      <p className="form-notice duplicate-subscription" role="status">
        已存在完全相同的提醒，无需重复创建；可以修改星期、时段或有效期。
      </p>
    ) : null}
    {formError ? <p className="form-error" role="alert">{formError}</p> : null}
''',
    "duplicate notice",
)

source = replace_once(
    source,
    '''                aria-describedby="subscription-summary"
      disabled={formBusy || !subscriptionFormReady}
      onClick={() => void submitSubscription()}
    >
      {formBusy ? "正在创建…" : "确认创建订阅"}
''',
    '''                aria-describedby="subscription-summary"
      aria-label={quickVenue ? `创建${quickVenue.name}提醒` : "确认创建订阅"}
      disabled={formBusy || !subscriptionFormReady}
      onClick={() => void submitSubscription()}
    >
      {formBusy ? "正在创建…" : quickVenue ? "创建该场地提醒" : "确认创建订阅"}
''',
    "quick submit label",
)

source = replace_once(
    source,
    '''            <div className="verification-form">
      {receipts.length ? (
''',
    '''            <div className="verification-form">
      {quickVenue ? (
        <div className="quick-verification-context">
          <span className={`quick-venue-icon venue-icon-${VENUE_ACCENTS[quickVenue.id]}`} aria-hidden="true">
            <QuickVenueIcon size={20} weight="duotone" />
          </span>
          <div>
            <strong>已选择 {quickVenue.name}</strong>
            <span>验证邮箱后会继续保留该场地，并进入提醒条件设置。</span>
          </div>
        </div>
      ) : null}
      {receipts.length ? (
''',
    "verification quick context",
)

prototype_path.write_text(source, encoding="utf-8")

css_path = Path("webapp/src/prototype.css")
css = css_path.read_text(encoding="utf-8")
card_css = '''.venue-card-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin: 0 4px 9px;
  color: var(--muted);
  font-size: 10px;
}

.venue-card-legend span,
.venue-card-status,
.venue-card-meta,
.venue-card-mail {
  display: flex;
  align-items: center;
}

.venue-card-legend span {
  gap: 4px;
}

.venue-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}

.venue-card {
  appearance: none;
  display: flex;
  min-width: 0;
  min-height: 120px;
  flex-direction: column;
  padding: 9px;
  overflow: hidden;
  border: 1px solid #dfe6e6;
  border-radius: 12px;
  background: #ffffff;
  color: var(--ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
  touch-action: manipulation;
}

.venue-card:active {
  border-color: #91cfc9;
  background: #eff9f7;
}

.venue-card-heading {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 34px;
  align-items: start;
  gap: 5px;
}

.venue-card-icon,
.quick-venue-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
}

.venue-card-icon {
  width: 24px;
  height: 24px;
}

.venue-icon-teal { background: #2babaa; }
.venue-icon-blue { background: #3288ed; }
.venue-icon-royal { background: #1268bd; }
.venue-icon-cyan { background: #19a4a1; }
.venue-icon-green { background: #53ae2d; }

.venue-card-name {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  color: #202b2a;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.25;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.venue-card-action {
  display: grid;
  min-width: 22px;
  height: 22px;
  padding: 0 4px;
  place-items: center;
  border-radius: 999px;
  background: #eaf7f5;
  color: var(--teal-dark);
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.venue-card-action.is-subscribed {
  background: #e9f7ec;
  color: #19763a;
}

.venue-card-action.is-full {
  background: #f1f3f3;
  color: #727d7a;
  font-size: 9px;
}

.venue-card-status {
  gap: 4px;
  margin-top: 7px;
  white-space: nowrap;
}

.venue-status-dot {
  display: inline-block;
  flex: 0 0 7px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #99a29f;
}

.venue-status-dot.healthy {
  background: #20a447;
  box-shadow: 0 0 0 2px rgba(32, 164, 71, 0.11);
}

.venue-status-dot.unhealthy {
  background: #e2614f;
  box-shadow: 0 0 0 2px rgba(226, 97, 79, 0.12);
}

.venue-status-dot.unknown {
  background: #9aa39f;
}

.venue-card-status strong {
  color: #28733d;
  font-size: 10px;
  font-weight: 700;
}

.venue-card-unhealthy .venue-card-status strong {
  color: #c84c3c;
}

.venue-card-unknown .venue-card-status strong {
  color: #77817e;
}

.venue-card-status small {
  margin-left: auto;
  color: #5f6d69;
  font-size: 10px;
  font-weight: 600;
}

.venue-card-meta {
  justify-content: space-between;
  gap: 4px;
  margin-top: auto;
  padding-top: 7px;
  border-top: 1px solid #edf1f0;
  color: #65736f;
  font-size: 10px;
  white-space: nowrap;
}

.venue-card-meta span,
.venue-card-mail {
  min-width: 0;
  gap: 3px;
}

.venue-card-followers {
  display: inline-flex;
  align-items: center;
}

.venue-card-mail {
  margin-top: 5px;
  overflow: hidden;
  color: var(--blue);
  font-size: 10px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.venue-card-mail.is-muted {
  color: #838e8a;
}

.venue-card-mail.is-paused {
  color: #9a6b18;
}

.venue-card.is-subscribed {
  border-color: #b7dccc;
  background: #fbfefc;
}

.venue-card-unhealthy {
  border-color: #efc6c0;
  background: #fffafa;
}

.venue-card.is-highlighted {
  animation: venue-card-highlight 1.8s ease-out;
}

@keyframes venue-card-highlight {
  0%, 30% {
    border-color: var(--teal);
    box-shadow: 0 0 0 3px rgba(6, 155, 152, 0.18);
  }
  100% {
    box-shadow: none;
  }
}

@media (max-width: 359px) {
  .venue-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

'''
css = replace_regex(
    css,
    r'\.venue-list \{.*?(?=\.subscriptions-link \{)',
    card_css,
    "base venue card styles",
)

quick_css_marker = '''.sheet-identity span {
  flex: 1;
  color: #2a323c;
}

'''
quick_css = quick_css_marker + '''.quick-verification-context,
.subscription-limit-notice,
.quick-venue-chip,
.quick-subscription-notice {
  display: grid;
  align-items: center;
}

.quick-verification-context {
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid #cfe4e1;
  border-radius: 12px;
  background: #f2faf8;
}

.quick-verification-context > div,
.quick-venue-copy,
.subscription-limit-notice > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.quick-verification-context strong,
.quick-venue-copy strong,
.subscription-limit-notice strong {
  color: #22312f;
  font-size: 13px;
}

.quick-verification-context span,
.quick-venue-copy small,
.subscription-limit-notice span {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.4;
}

.quick-venue-icon {
  width: 36px;
  height: 36px;
}

.subscription-limit-notice {
  grid-template-columns: 24px minmax(0, 1fr) auto;
  gap: 9px;
  padding: 11px;
  border: 1px solid #efd1a7;
  border-radius: 12px;
  background: #fff9ef;
  color: #96601c;
}

.subscription-limit-notice button,
.quick-venue-chip button,
.quick-subscription-notice button {
  min-height: 36px;
  padding: 0 9px;
  border: 0;
  border-radius: 9px;
  background: #ffffff;
  color: var(--teal-dark);
  font: inherit;
  font-size: 11px;
  font-weight: 700;
}

.quick-venue-chip {
  grid-template-columns: 38px minmax(0, 1fr) auto;
  gap: 9px;
  padding: 10px;
  border: 1px solid #cfe4e1;
  border-radius: 12px;
  background: #f5fbfa;
}

.quick-subscription-notice {
  grid-template-columns: 20px minmax(0, 1fr) auto;
  gap: 7px;
  margin-top: 8px;
  padding: 8px 9px;
  border-radius: 10px;
  background: #eef8f0;
  color: #24733b;
  font-size: 11px;
}

.form-notice {
  margin: -4px 0 0;
  padding: 10px 11px;
  border: 1px solid #cfe4e1;
  border-radius: 10px;
  background: #f2faf8;
  color: #35645f;
  font-size: 11px;
  line-height: 1.45;
}

'''
css = replace_once(css, quick_css_marker, quick_css, "quick create base styles")
css_path.write_text(css, encoding="utf-8")

mobile_path = Path("webapp/public/mobile-v2.css")
mobile = mobile_path.read_text(encoding="utf-8")
mobile = replace_once(
    mobile,
    '''  html body .venue-section {
      margin-top: 14px;
      padding: 14px 12px 6px;
''',
    '''  html body .venue-section {
      margin-top: 14px;
      padding: 14px 8px 8px;
''',
    "mobile venue section padding",
)

mobile_cards = '''  html body .venue-card-legend {
  gap: 5px 10px;
  margin: 0 3px 9px;
  font-size: 10px;
}

html body .venue-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

html body .venue-card {
  min-height: 122px;
  padding: 8px;
  border-color: #e0e7e6;
  border-radius: 13px;
  box-shadow: 0 3px 11px rgba(20, 64, 60, 0.035);
}

html body .venue-card:active {
  border-color: #7dc5be;
  background: #edf8f6;
  transform: none;
}

html body .venue-card-heading {
  grid-template-columns: 22px minmax(0, 1fr) auto;
  min-height: 36px;
  gap: 4px;
}

html body .venue-card-icon {
  width: 22px;
  height: 22px;
  border-radius: 7px;
}

html body .venue-card-name {
  font-size: 12px;
  line-height: 1.24;
}

html body .venue-card-action {
  min-width: 22px;
  height: 22px;
}

html body .venue-card-action.is-full {
  font-size: 9px;
}

html body .venue-card-status {
  margin-top: 6px;
}

html body .venue-card-status strong,
html body .venue-card-status small,
html body .venue-card-meta,
html body .venue-card-mail {
  font-size: 10px;
}

html body .venue-card-meta {
  padding-top: 7px;
}

html body .venue-card-mail {
  min-height: 15px;
  margin-top: 5px;
}

'''
mobile = replace_regex(
    mobile,
    r'  html body \.venue-list \{.*?(?=  html body \.subscriptions-link \{)',
    mobile_cards,
    "mobile venue card styles",
)

mobile_sheet_marker = '''  html body .sheet-identity {
  min-height: 46px;
  padding: 9px 11px;
  border: 1px solid #d6e9dc;
  border-radius: 12px;
}

'''
mobile = replace_once(
    mobile,
    mobile_sheet_marker,
    mobile_sheet_marker + '''  html body .quick-verification-context,
  html body .subscription-limit-notice,
  html body .quick-venue-chip {
    border-radius: 14px;
  }

  html body .subscription-limit-notice button,
  html body .quick-venue-chip button,
  html body .quick-subscription-notice button {
    min-height: 44px;
    padding-right: 10px;
    padding-left: 10px;
  }

  html body .quick-venue-selection {
    padding: 12px;
  }

  html body .quick-venue-chip {
    grid-template-columns: 38px minmax(0, 1fr);
  }

  html body .quick-venue-chip > button {
    grid-column: 1 / -1;
    width: 100%;
  }

  html body .quick-subscription-notice {
    grid-template-columns: 20px minmax(0, 1fr);
  }

  html body .quick-subscription-notice > button {
    grid-column: 1 / -1;
    width: 100%;
  }

''',
    "mobile quick create styles",
)

mobile = replace_once(
    mobile,
    '''  html body .venue-mail span {
      display: none;
    }
''',
    '''  html body .venue-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    html body .venue-card {
      min-height: 116px;
    }
''',
    "narrow two-column cards",
)

mobile = replace_once(
    mobile,
    '''@media (max-width: 520px) and (prefers-reduced-motion: reduce) {
  html body .primary-button:active,
  html body .sheet-primary:active {
    transform: none;
  }
}
''',
    '''@media (max-width: 520px) and (prefers-reduced-motion: reduce) {
  html body .primary-button:active,
  html body .sheet-primary:active {
    transform: none;
  }

  html body .venue-card.is-highlighted {
    animation: none;
    border-color: var(--teal);
    box-shadow: 0 0 0 3px rgba(6, 155, 152, 0.18);
  }
}
''',
    "reduced motion card feedback",
)
mobile_path.write_text(mobile, encoding="utf-8")

subscription_test_path = Path("webapp/tests/subscription-ux.spec.ts")
tests = subscription_test_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    '''  const venueNames = await page.locator(".venue-list .venue-name h3").allTextContents();
  expect(venueNames).toEqual(["TOPS 科技园", "金地威新", "深圳湾"]);
  await expect(page.locator(".venue-list .venue-name p").first()).toHaveText("9 人关注");
});
''',
    '''  const venueNames = await page.locator(".venue-grid .venue-card-name").allTextContents();
  expect(venueNames).toEqual(["TOPS 科技园", "金地威新", "深圳湾"]);
  await expect(page.locator(".venue-grid .venue-card-followers").first()).toContainText("9");
});

test("opens a venue-card quick-create flow and submits only that venue", async ({ page }) => {
  let submittedPayload: Record<string, unknown> | null = null;
  await page.route("**/api/subscriptions", async (route) => {
    submittedPayload = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        subscription: {
          id: "quick-tops-subscription",
          venueIds: ["tops"],
          weekdays: [1, 2, 3, 4, 5, 6, 7],
          startTime: "18:00",
          endTime: "22:00",
          durationDays: 7,
          termCode: "7d",
          autoRenew: false,
          eligible: true,
          activeUntil: "2026-09-05T12:00:00.000Z",
          active: true,
          createdAt: "2026-08-29T12:00:00.000Z",
        },
      }),
    });
  });

  await page.goto("/");
  const venueCard = page.getByTestId("venue-card-tops");
  await expect(venueCard).toContainText("TOPS 科技园");
  await expect(venueCard.locator(".venue-card-status")).toContainText("正常");
  await expect(venueCard.locator(".venue-card-status")).toContainText("1分钟");
  await expect(venueCard.locator(".venue-card-followers")).toContainText("9");

  await venueCard.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("创建TOPS 科技园提醒", { exact: true })).toBeVisible();
  await expect(dialog.locator(".quick-venue-selection")).toContainText("TOPS 科技园");
  await expect(dialog.locator(".venue-choices")).toHaveCount(0);

  await dialog.getByRole("button", { name: "创建TOPS 科技园提醒", exact: true }).click();
  await expect.poll(() => submittedPayload).not.toBeNull();
  expect(submittedPayload).toMatchObject({ venueIds: ["tops"] });
  await expect(page.locator(".app-toast")).toContainText("TOPS 科技园提醒已创建");
});

test("marks existing venue subscriptions and blocks an exact duplicate", async ({ page }) => {
  const dashboardWithSubscription = {
    ...dashboard,
    identity: {
      ...dashboard.identity,
      activeSubscriptionCount: 1,
      remainingSubscriptions: 4,
    },
    subscriptions: [{
      id: "existing-tops-subscription",
      venueIds: ["tops"],
      weekdays: [1, 2, 3, 4, 5, 6, 7],
      startTime: "18:00",
      endTime: "22:00",
      durationDays: 7,
      termCode: "7d",
      autoRenew: false,
      eligible: true,
      activeUntil: "2026-09-05T12:00:00.000Z",
      active: true,
      createdAt: "2026-08-29T12:00:00.000Z",
    }],
  };
  await page.route("**/api/bootstrap", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(dashboardWithSubscription),
    });
  });

  await page.goto("/");
  const venueCard = page.getByTestId("venue-card-tops");
  await expect(venueCard.locator(".venue-card-action")).toHaveText("✓1");
  await venueCard.click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".quick-subscription-notice")).toContainText("已有");
  await expect(dialog.locator(".duplicate-subscription")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "创建TOPS 科技园提醒", exact: true })).toBeDisabled();
});
''',
    "subscription UX tests",
)
subscription_test_path.write_text(tests, encoding="utf-8")

mobile_test_path = Path("webapp/tests/mobile-v2.spec.ts")
mobile_tests = mobile_test_path.read_text(encoding="utf-8")
mobile_tests = replace_once(
    mobile_tests,
    '''    const firstVenue = page.locator(".venue-row").first();
      await expect(firstVenue).toBeVisible();
      const venueBox = await firstVenue.boundingBox();
      expect(venueBox?.height ?? 0).toBeGreaterThanOrEqual(78);
      await expect(firstVenue.locator(".venue-mail")).toHaveCSS("display", "flex");
''',
    '''    const venueCards = page.locator(".venue-card");
      expect(await venueCards.count()).toBeGreaterThan(3);
      const venueBoxes = await Promise.all(
        [0, 1, 2, 3].map((index) => venueCards.nth(index).boundingBox()),
      );
      expect(venueBoxes[0]?.height ?? 0).toBeGreaterThanOrEqual(116);
      expect(venueBoxes[0]?.width ?? 0).toBeGreaterThanOrEqual(100);
      expect(Math.abs((venueBoxes[0]?.y ?? 0) - (venueBoxes[1]?.y ?? 0))).toBeLessThan(2);
      expect(Math.abs((venueBoxes[0]?.y ?? 0) - (venueBoxes[2]?.y ?? 0))).toBeLessThan(2);
      expect(venueBoxes[3]?.y ?? 0).toBeGreaterThan((venueBoxes[0]?.y ?? 0) + 40);
      await expect(venueCards.first().locator(".venue-card-mail")).toBeVisible();
''',
    "mobile three-column cards",
)

mobile_tests = replace_once(
    mobile_tests,
    '''  test("shows visible keyboard focus and keeps key status text readable", async ({ page }) => {
''',
    '''  test("uses two venue columns on a 320px screen without hiding metrics", async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 720 });
      await page.goto("/");

      const venueCards = page.locator(".venue-card");
      expect(await venueCards.count()).toBeGreaterThan(2);
      const first = await venueCards.nth(0).boundingBox();
      const second = await venueCards.nth(1).boundingBox();
      const third = await venueCards.nth(2).boundingBox();

      expect(first?.width ?? 0).toBeGreaterThanOrEqual(130);
      expect(Math.abs((first?.y ?? 0) - (second?.y ?? 0))).toBeLessThan(2);
      expect(third?.y ?? 0).toBeGreaterThan((first?.y ?? 0) + 40);
      await expect(venueCards.first().locator(".venue-card-status")).toBeVisible();
      await expect(venueCards.first().locator(".venue-card-meta")).toBeVisible();
      await expect(venueCards.first().locator(".venue-card-mail")).toBeVisible();

      const gridFits = await page.locator(".venue-grid").evaluate((grid) => {
        const viewportWidth = document.documentElement.clientWidth;
        const rect = grid.getBoundingClientRect();
        return document.documentElement.scrollWidth <= viewportWidth
          && rect.left >= -0.5
          && rect.right <= viewportWidth + 0.5;
      });
      expect(gridFits).toBe(true);
    });

    test("shows visible keyboard focus and keeps key status text readable", async ({ page }) => {
''',
    "mobile two-column test",
)

mobile_tests = replace_once(
    mobile_tests,
    '''    const keyTextSizes = await page.locator(
        ".metric span, .venue-health span, .venue-mail span",
      ).evaluateAll((elements) => elements.map((element) =>
''',
    '''    const keyTextSizes = await page.locator(
        ".metric span, .venue-card-status strong, .venue-card-status small, .venue-card-meta, .venue-card-mail",
      ).evaluateAll((elements) => elements.map((element) =>
''',
    "mobile readable card text",
)
mobile_test_path.write_text(mobile_tests, encoding="utf-8")
