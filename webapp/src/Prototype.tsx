import {
  ArrowsClockwiseIcon,
  BuildingApartmentIcon,
  BuildingsIcon,
  CalendarDotsIcon,
  CheckCircleIcon,
  ClockIcon,
  CourtBasketballIcon,
  EnvelopeSimpleIcon,
  ListBulletsIcon,
  MapPinIcon,
  PlusCircleIcon,
  QuestionIcon,
  ShieldCheckIcon,
  StarIcon,
  KeyIcon,
  TennisBallIcon,
  TrashIcon,
  UsersThreeIcon,
  WavesIcon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelSubscription,
  createSubscription,
  EMPTY_DASHBOARD,
  FALLBACK_DASHBOARD,
  getDashboard,
  loadReceipts,
  removeReceipt,
  requestVerificationCode,
  redeemPriorityInvite,
  saveReceipt,
  type Dashboard,
  type VenueId,
  type VerificationReceipt,
  verifyEmail,
} from "./api";
import { LULU_LABELS, resolveLuluState } from "./lulu";
import { BottomSheet, KeyboardInput, MobileScroll, useKeyboard } from "./mobile";
import { isTextEntry, useNativeKeyboardViewport } from "./nativeKeyboard";

type Panel = "create" | "help" | "subscriptions" | "priority" | null;

const VENUE_ACCENTS: Record<VenueId, string> = {
  szw: "teal",
  gba: "cyan",
  dsh_free: "green",
  sysh: "blue",
  tops: "royal",
  tyzx: "cyan",
  jdwx: "green",
};

const VENUE_ICONS: Record<VenueId, React.ElementType> = {
  szw: WavesIcon,
  gba: BuildingApartmentIcon,
  dsh_free: TennisBallIcon,
  sysh: TennisBallIcon,
  tops: BuildingsIcon,
  tyzx: CourtBasketballIcon,
  jdwx: BuildingApartmentIcon,
};

const TIME_OPTIONS = [
  "06:00",
  "07:00",
  "08:00",
  "09:00",
  "10:00",
  "11:00",
  "12:00",
  "13:00",
  "14:00",
  "15:00",
  "16:00",
  "17:00",
  "18:00",
  "19:00",
  "20:00",
  "21:00",
  "22:00",
  "23:00",
];

function formatClock(value: string | null): string {
  if (!value) return "暂无发送";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无发送";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function formatRelative(value: string | null): string {
  if (!value) return "等待首次巡检";
  const then = new Date(value).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${Math.max(seconds, 1)} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  return `${Math.floor(seconds / 3600)} 小时前`;
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function Metric({
  icon,
  value,
  label,
  tone,
}: {
  icon: React.ReactNode;
  value: string | number;
  label: string;
  tone: "teal" | "blue" | "green";
}) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-icon" aria-hidden="true">
        {icon}
      </div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

export default function Prototype() {
  const keyboard = useKeyboard();
  const keyboardRef = useRef(keyboard);
  keyboardRef.current = keyboard;
  useNativeKeyboardViewport();
  const [receipts, setReceipts] = useState<VerificationReceipt[]>(() => loadReceipts());
  const [receipt, setReceipt] = useState<VerificationReceipt | null>(() => loadReceipts()[0] ?? null);
  const initialDashboard = import.meta.env.DEV ? FALLBACK_DASHBOARD : EMPTY_DASHBOARD;
  const [dashboard, setDashboard] = useState<Dashboard>(() => ({
    ...initialDashboard,
    identity: receipt
      ? {
          verified: true,
          maskedEmail: receipt.maskedEmail,
          remindersToday: initialDashboard.identity.remindersToday,
          tier: initialDashboard.identity.tier,
          dailyLimit: initialDashboard.identity.dailyLimit,
          remainingToday: initialDashboard.identity.remainingToday,
        }
      : initialDashboard.identity,
  }));
  const [panel, setPanel] = useState<Panel>(null);
  const [loading, setLoading] = useState(true);
  const [serviceOnline, setServiceOnline] = useState(true);
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [toast, setToast] = useState("");
  const [notificationBurst, setNotificationBurst] = useState(false);
  const previousReminderCount = useRef<number | null>(null);
  const [email, setEmail] = useState(receipt?.email ?? "");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const codeInputRef = useRef<HTMLInputElement>(null);
  const [venueIds, setVenueIds] = useState<VenueId[]>(["szw", "tops"]);
  const [startTime, setStartTime] = useState("18:00");
  const [endTime, setEndTime] = useState("22:00");
  const [durationDays, setDurationDays] = useState(7);
  const [inviteCode, setInviteCode] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getDashboard(receipt);
      setDashboard(next);
      setServiceOnline(true);
      if (receipt && !next.identity.verified) {
        setReceipts(removeReceipt(receipt.token));
        setReceipt(null);
      }
    } catch {
      const unavailable = import.meta.env.DEV ? FALLBACK_DASHBOARD : EMPTY_DASHBOARD;
      setDashboard({
        ...unavailable,
        generatedAt: new Date().toISOString(),
        identity: receipt
          ? {
              verified: true,
              maskedEmail: receipt.maskedEmail,
              remindersToday: unavailable.identity.remindersToday,
              tier: unavailable.identity.tier,
              dailyLimit: unavailable.identity.dailyLimit,
              remainingToday: unavailable.identity.remainingToday,
            }
          : unavailable.identity,
      });
      setServiceOnline(import.meta.env.DEV);
    } finally {
      setLoading(false);
    }
  }, [receipt]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    previousReminderCount.current = null;
    setNotificationBurst(false);
  }, [receipt?.token]);

  useEffect(() => {
    const current = dashboard.identity.remindersToday;
    const previous = previousReminderCount.current;
    previousReminderCount.current = current;
    if (previous === null || current <= previous) return;

    setNotificationBurst(true);
    const timer = window.setTimeout(() => setNotificationBurst(false), 5000);
    return () => window.clearTimeout(timer);
  }, [dashboard.identity.remindersToday]);

  useEffect(() => {
    if (panel !== "create" || receipt) return;

    const timer = window.setTimeout(() => {
      const activeElement = document.activeElement;
      if (isTextEntry(activeElement) && activeElement.closest(".bottom-sheet")) {
        activeElement.blur();
        keyboardRef.current.hide();
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, [panel, receipt?.token]);

  useEffect(() => {
    if (!challengeId || panel !== "create") return;

    const timer = window.setTimeout(() => codeInputRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [challengeId, panel]);

  const activeIdentity = dashboard.identity.verified
    ? dashboard.identity.maskedEmail
    : receipt?.maskedEmail;
  const luluState = resolveLuluState({
    serviceOnline,
    healthyVenues: dashboard.metrics.healthyVenues,
    totalVenues: dashboard.metrics.totalVenues,
    identityVerified: dashboard.identity.verified,
    subscriptionCount: dashboard.subscriptions.length,
    remindersToday: dashboard.identity.remindersToday,
    notificationBurst,
  });

  const openPanel = (nextPanel: Exclude<Panel, null>) => {
    keyboard.hide();
    setFormError("");
    setPanel(nextPanel);
  };

  const switchReceipt = (next: VerificationReceipt) => {
    keyboard.hide();
    setReceipt(next);
    setEmail(next.email);
    setPanel("create");
    setFormError("");
  };

  const changeEmail = () => {
    keyboard.hide();
    setReceipt(null);
    setEmail("");
    setChallengeId("");
    setCode("");
    setInviteCode("");
    setFormError("");
    setPanel("create");
  };

  const sendCode = async () => {
    setFormBusy(true);
    setFormError("");
    try {
      const result = await requestVerificationCode(email.trim());
      setChallengeId(result.challengeId);
      setToast("验证码已发送");
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "验证码发送失败");
    } finally {
      setFormBusy(false);
    }
  };

  const confirmCode = async () => {
    setFormBusy(true);
    setFormError("");
    try {
      const nextReceipt = await verifyEmail(challengeId, code.trim());
      setReceipts(saveReceipt(nextReceipt));
      setReceipt(nextReceipt);
      setEmail(nextReceipt.email);
      setCode("");
      setChallengeId("");
      setToast("邮箱验证成功");
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "验证码无效");
    } finally {
      setFormBusy(false);
    }
  };

  const redeemInvite = async () => {
    if (!receipt) {
      setFormError("请先验证邮箱");
      return;
    }
    setFormBusy(true);
    setFormError("");
    try {
      await redeemPriorityInvite(receipt, inviteCode.trim());
      setInviteCode("");
      setPanel(null);
      setToast("邀请码验证成功，已升级为优先用户");
      await refresh();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "邀请码验证失败");
    } finally {
      setFormBusy(false);
    }
  };

  const toggleVenue = (venueId: VenueId) => {
    setVenueIds((current) =>
      current.includes(venueId)
        ? current.filter((item) => item !== venueId)
        : [...current, venueId],
    );
  };

  const submitSubscription = async () => {
    if (!receipt) {
      setFormError("请先验证邮箱");
      return;
    }
    if (!venueIds.length) {
      setFormError("请至少选择一个场地");
      return;
    }
    if (startTime >= endTime) {
      setFormError("结束时间必须晚于开始时间");
      return;
    }

    setFormBusy(true);
    setFormError("");
    try {
      await createSubscription(receipt, {
        venueIds,
        startTime,
        endTime,
        durationDays,
      });
      setPanel(null);
      setToast("订阅已创建，噜噜会持续帮你盯场");
      await refresh();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "订阅创建失败");
    } finally {
      setFormBusy(false);
    }
  };

  const cancelExistingSubscription = async (subscriptionId: string) => {
    if (!receipt) return;
    setFormBusy(true);
    setFormError("");
    try {
      await cancelSubscription(receipt, subscriptionId);
      setToast("订阅已取消");
      await refresh();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "取消订阅失败");
    } finally {
      setFormBusy(false);
    }
  };

  const panelTitle = useMemo(() => {
    if (panel === "help") return "提醒如何工作";
    if (panel === "subscriptions") return "我的订阅";
    if (panel === "priority") return "提醒档位";
    return receipt ? "创建订阅" : "验证邮箱";
  }, [panel, receipt]);

  return (
    <>
      <MobileScroll className="app-screen">
        <main className="dashboard-screen" aria-label="Zacks 网球提醒">
          <header className="product-header">
            <div className="brand-lockup">
              <span className="brand-mark" aria-hidden="true">
                <TennisBallIcon weight="fill" size={30} />
              </span>
              <div>
                <h1>Zacks 网球提醒</h1>
                <p>未来有位，邮件通知你</p>
              </div>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="查看帮助"
              title="查看帮助"
              onClick={() => openPanel("help")}
            >
              <QuestionIcon size={23} weight="bold" />
            </button>
          </header>

          <div className="service-line" aria-live="polite">
            <span className={`live-dot ${serviceOnline ? "" : "offline"}`} aria-hidden="true" />
            <strong>{serviceOnline ? "服务运行正常" : "服务暂时不可用"}</strong>
            <span>更新于 {formatUpdatedAt(dashboard.generatedAt)}</span>
            <button
              type="button"
              aria-label="刷新状态"
              title="刷新状态"
              onClick={() => void refresh()}
              disabled={loading}
            >
              <ArrowsClockwiseIcon className={loading ? "is-spinning" : ""} size={18} />
            </button>
          </div>

          <section className="metric-band" aria-label="运行概况">
            <Metric
              icon={<UsersThreeIcon size={25} weight="fill" />}
              value={dashboard.metrics.activeSubscriptions}
              label="个有效订阅"
              tone="teal"
            />
            <Metric
              icon={<EnvelopeSimpleIcon size={25} weight="fill" />}
              value={dashboard.metrics.remindersToday}
              label="今日提醒"
              tone="blue"
            />
            <Metric
              icon={<ShieldCheckIcon size={27} weight="fill" />}
              value={`${dashboard.metrics.healthyVenues}/${dashboard.metrics.totalVenues}`}
              label="场地巡检正常"
              tone="green"
            />
          </section>

          <section className="create-card" aria-labelledby="create-card-title">
            <div className="create-card-main">
              <div
                className="lulu-stage"
                data-lulu-state={luluState}
                aria-label={LULU_LABELS[luluState]}
                title={LULU_LABELS[luluState]}
              >
                <img
                  key={luluState}
                  className="lulu-sprite"
                  data-testid="lulu-sprite"
                  src="/assets/lulu-sprite.webp"
                  alt=""
                  aria-hidden="true"
                  decoding="async"
                  draggable={false}
                />
              </div>
              <div className="create-copy">
                <h2 id="create-card-title">新建订阅</h2>
                <div className="feature-line">
                  <span><MapPinIcon size={18} weight="bold" />选择场地</span>
                  <i aria-hidden="true">·</i>
                  <span><ClockIcon size={18} weight="bold" />提醒时段</span>
                  <i aria-hidden="true">·</i>
                  <span><CalendarDotsIcon size={18} weight="bold" />7–14天</span>
                </div>
                <p>有匹配的未来场地位，系统才会发邮件。</p>
              </div>
            </div>

            <div className="identity-row">
              <span className={activeIdentity ? "identity-ok" : "identity-pending"}>
                <CheckCircleIcon size={21} weight="fill" />
                {activeIdentity ? `${activeIdentity} 已验证 · 本机记住` : "验证邮箱后即可创建"}
              </span>
              {activeIdentity ? (
                <button type="button" onClick={changeEmail}>
                  更换邮箱
                </button>
              ) : null}
            </div>

            {activeIdentity ? (
              <div className={`tier-row tier-${dashboard.identity.tier}`}>
                <span className="tier-summary">
                  <StarIcon size={20} weight="fill" />
                  <span>
                    <strong>
                      {dashboard.identity.tier === "priority" ? "优先用户" : "普通用户"}
                    </strong>
                    <small>
                      今日已发送 {dashboard.identity.remindersToday}/{dashboard.identity.dailyLimit} 封
                    </small>
                  </span>
                </span>
                {dashboard.identity.tier === "priority" ? (
                  <span className="tier-enabled">优先队列已开启</span>
                ) : (
                  <button type="button" onClick={() => openPanel("priority")}>
                    输入邀请码
                  </button>
                )}
              </div>
            ) : null}

            <button className="primary-button" type="button" onClick={() => openPanel("create")}>
              <PlusCircleIcon size={24} weight="bold" />
              创建订阅
            </button>
          </section>

          <section className="venue-section" aria-labelledby="venue-heading">
            <div className="section-heading">
              <div>
                <h2 id="venue-heading">场地运行状态</h2>
                <p>按最后一次成功巡检时间排序</p>
              </div>
              <span><ArrowsClockwiseIcon size={17} />30 秒自动更新</span>
            </div>

            <div className="venue-list">
              {dashboard.venues.map((venue) => (
                (() => {
                  const VenueIcon = VENUE_ICONS[venue.id];
                  return (
                    <article className="venue-row" key={venue.id}>
                      <span className={`venue-icon venue-icon-${VENUE_ACCENTS[venue.id]}`}>
                        <VenueIcon size={23} weight="duotone" />
                      </span>
                      <div className="venue-name">
                        <h3>{venue.name}</h3>
                        <p>{venue.subscriberCount} 个订阅者</p>
                      </div>
                      <div className="venue-health">
                        <strong className={venue.healthy ? "healthy" : "unhealthy"}>
                          <CheckCircleIcon size={16} weight="fill" />
                          {venue.healthy ? "巡检正常" : "巡检异常"}
                        </strong>
                        <span>{formatRelative(venue.lastInspectionAt)}</span>
                      </div>
                      <div className="venue-mail">
                        <strong className={venue.lastNotificationAt ? "" : "muted"}>
                          <EnvelopeSimpleIcon size={16} weight="fill" />
                          {formatClock(venue.lastNotificationAt)}
                        </strong>
                        <span>{venue.lastNotificationAt ? "今日发送" : "今日未发送"}</span>
                      </div>
                    </article>
                  );
                })()
              ))}
            </div>
          </section>

          <button
            className="subscriptions-link"
            type="button"
            onClick={() => openPanel("subscriptions")}
          >
            <ListBulletsIcon size={24} weight="bold" />
            <span>我的订阅</span>
            <span aria-hidden="true">›</span>
          </button>
        </main>
      </MobileScroll>

      <BottomSheet
        open={panel !== null}
        onOpenChange={(open) => {
          if (!open) setPanel(null);
        }}
        title={panelTitle}
        description={
          panel === "create"
            ? "只设置提醒条件，不展示或代订场地。"
            : undefined
        }
        snap={panel === "create" ? 0.86 : panel === "priority" ? 0.66 : 0.72}
      >
        {panel === "help" ? (
          <div className="help-content">
            <div className="help-row">
              <span>1</span>
              <div><strong>选择提醒条件</strong><p>设置场地、每日时间段和 7–14 天有效期。</p></div>
            </div>
            <div className="help-row">
              <span>2</span>
              <div><strong>系统持续巡检</strong><p>Airflow 按场地开放节奏检查未来可订情况。</p></div>
            </div>
            <div className="help-row">
              <span>3</span>
              <div><strong>命中后发邮件</strong><p>只有出现符合条件的场地位才会通知，不会重复轰炸。</p></div>
            </div>
          </div>
        ) : null}

        {panel === "subscriptions" ? (
          <div className="subscription-list">
            {dashboard.subscriptions.length ? dashboard.subscriptions.map((subscription) => (
              <article key={subscription.id}>
                <div>
                  <strong>
                    {subscription.venueIds
                      .map((venueId) => dashboard.venues.find((venue) => venue.id === venueId)?.name)
                      .filter(Boolean)
                      .join("、")}
                  </strong>
                  <span>{subscription.startTime}–{subscription.endTime}</span>
                  <span>有效至 {subscription.activeUntil.slice(0, 10)}</span>
                </div>
                <button
                  type="button"
                  aria-label="取消订阅"
                  title="取消订阅"
                  disabled={formBusy}
                  onClick={() => void cancelExistingSubscription(subscription.id)}
                >
                  <TrashIcon size={20} />
                </button>
              </article>
            )) : (
              <div className="empty-state">
                <ShieldCheckIcon size={38} weight="duotone" />
                <strong>还没有订阅</strong>
                <p>创建后会在这里管理提醒条件。</p>
                <button type="button" onClick={() => setPanel("create")}>创建第一个订阅</button>
              </div>
            )}
            {formError ? <p className="form-error" role="alert">{formError}</p> : null}
          </div>
        ) : null}

        {panel === "priority" ? (
          <div className="priority-panel">
            <div className="tier-comparison">
              <article>
                <span>普通用户</span>
                <strong>3 封/天</strong>
                <p>适合日常关注；达到上限后，当天后续场地提醒不再补发。</p>
              </article>
              <article className="featured">
                <span><StarIcon size={17} weight="fill" />优先用户</span>
                <strong>12 封/天</strong>
                <p>更高提醒额度，并在系统全局邮件额度紧张时优先处理。</p>
              </article>
            </div>

            {receipt ? (
              dashboard.identity.tier === "priority" ? (
                <div className="priority-active">
                  <ShieldCheckIcon size={34} weight="fill" />
                  <strong>优先提醒已开启</strong>
                  <p>
                    今日还可发送 {dashboard.identity.remainingToday} 封场地摘要邮件。
                    验证码和微信消息不受此档位限制。
                  </p>
                </div>
              ) : (
                <>
                  <label className="field">
                    <span>优先用户邀请码</span>
                    <KeyboardInput
                      type="text"
                      autoCapitalize="characters"
                      autoComplete="off"
                      spellCheck={false}
                      maxLength={40}
                      placeholder="ZACKS-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX"
                      value={inviteCode}
                      onChange={(event) => setInviteCode(event.target.value.toUpperCase())}
                    />
                  </label>
                  <p className="verification-note">
                    邀请码仅可使用一次。验证成功后，优先档位会跟随此邮箱，
                    更换浏览器重新验证邮箱后仍然有效。
                  </p>
                  {formError ? <p className="form-error" role="alert">{formError}</p> : null}
                  <button
                    className="sheet-primary"
                    type="button"
                    disabled={formBusy || inviteCode.replace(/[^A-Z0-9]/gi, "").length !== 33}
                    onClick={() => void redeemInvite()}
                  >
                    {formBusy ? "正在验证…" : "验证邀请码并升级"}
                  </button>
                </>
              )
            ) : (
              <div className="empty-state">
                <KeyIcon size={38} weight="duotone" />
                <strong>请先验证邮箱</strong>
                <p>优先档位绑定到邮箱，验证后才能兑换邀请码。</p>
                <button type="button" onClick={() => setPanel("create")}>去验证邮箱</button>
              </div>
            )}
          </div>
        ) : null}

        {panel === "create" ? (
          receipt ? (
            <div className="subscription-form">
              <div className="sheet-identity">
                <ShieldCheckIcon size={22} weight="fill" />
                <span><strong>{receipt.maskedEmail}</strong> 已验证</span>
                <button type="button" onClick={changeEmail}>更换</button>
              </div>

              <fieldset>
                <legend>选择场地 <span>可多选</span></legend>
                <div className="venue-choices">
                  {dashboard.venues.map((venue) => {
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
                        {venue.name}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <fieldset>
                <legend>希望收到提醒的时间段</legend>
                <div className="time-range">
                  <label>
                    <span>开始</span>
                    <select value={startTime} onChange={(event) => setStartTime(event.target.value)}>
                      {TIME_OPTIONS.slice(0, -1).map((time) => <option key={time}>{time}</option>)}
                    </select>
                  </label>
                  <span aria-hidden="true">—</span>
                  <label>
                    <span>结束</span>
                    <select value={endTime} onChange={(event) => setEndTime(event.target.value)}>
                      {TIME_OPTIONS.slice(1).map((time) => <option key={time}>{time}</option>)}
                    </select>
                  </label>
                </div>
              </fieldset>

              <fieldset>
                <legend>订阅有效期 <span>默认 7 天，最长 14 天</span></legend>
                <div className="day-choices">
                  {[7, 8, 9, 10, 11, 12, 13, 14].map((days) => (
                    <button
                      type="button"
                      key={days}
                      className={durationDays === days ? "selected" : ""}
                      aria-pressed={durationDays === days}
                      onClick={() => setDurationDays(days)}
                    >
                      {days}天
                    </button>
                  ))}
                </div>
              </fieldset>

              {formError ? <p className="form-error" role="alert">{formError}</p> : null}
              <button
                className="sheet-primary"
                type="button"
                disabled={formBusy}
                onClick={() => void submitSubscription()}
              >
                {formBusy ? "正在创建…" : "确认创建订阅"}
              </button>
            </div>
          ) : (
            <div className="verification-form">
              {receipts.length ? (
                <div className="receipt-history">
                  <span>本浏览器验证过</span>
                  {receipts.map((item) => (
                    <button type="button" key={item.token} onClick={() => switchReceipt(item)}>
                      <ShieldCheckIcon size={18} weight="fill" />
                      {item.maskedEmail}
                    </button>
                  ))}
                </div>
              ) : null}

              <label className="field">
                <span>订阅邮箱</span>
                <KeyboardInput
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  placeholder="name@example.com"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>

              {challengeId ? (
                <label className="field">
                  <span>6 位验证码</span>
                  <KeyboardInput
                    ref={codeInputRef}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    placeholder="000000"
                    value={code}
                    onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
                  />
                </label>
              ) : null}

              <p className="verification-note">
                验证成功后，此浏览器会记住邮箱；更换浏览器时需要重新验证。
              </p>
              {formError ? <p className="form-error" role="alert">{formError}</p> : null}
              <button
                className="sheet-primary"
                type="button"
                disabled={formBusy || !email.trim() || (Boolean(challengeId) && code.length !== 6)}
                onClick={() => void (challengeId ? confirmCode() : sendCode())}
              >
                {formBusy ? "请稍候…" : challengeId ? "验证并继续" : "发送验证码"}
              </button>
            </div>
          )
        ) : null}
      </BottomSheet>

      {toast ? <div className="app-toast" role="status">{toast}</div> : null}
    </>
  );
}
