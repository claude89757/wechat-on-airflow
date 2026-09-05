import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ArrowUpRightIcon, ArrowsClockwiseIcon, BellRingingIcon,
  CheckCircleIcon, ClockIcon, CoffeeIcon, DotsThreeIcon,
  EnvelopeSimpleIcon, GithubLogoIcon, ListBulletsIcon, MagnifyingGlassIcon,
  MapPinIcon, PlusIcon, QuestionIcon, ShieldCheckIcon, StarIcon,
  TennisBallIcon, UsersThreeIcon, XIcon,
} from "@phosphor-icons/react";
import { useMemo, useRef, useState } from "react";
import type { Dashboard, VenueId } from "./api";
import { resolveVenueDisplayState } from "./dashboard-state";
import { LULU_LABELS, type LuluState } from "./lulu";
import { KeyboardInput } from "./mobile";
import { formatInspectionCadence } from "./venue-inspection-display";

export type StudioPanel = "create" | "help" | "subscriptions" | "priority" | "community" | "admin" | "coffee";
type Props = {
  dashboard: Dashboard;
  availability: "loading" | "unknown" | "stale" | "ready";
  hasData: boolean;
  loading: boolean;
  activeIdentity: string | null | undefined;
  luluState: LuluState;
  statusLabel: string;
  statusDetail: string;
  highlightedVenueId: VenueId | null;
  onCreate: (venueId?: VenueId) => void;
  onPanel: (panel: StudioPanel) => void;
  onRefresh: () => void;
  onChangeEmail: () => void;
};
type Filter = "all" | "subscribed" | "attention";

function relativeTime(value: string | null): string {
  const timestamp = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(timestamp)) return "暂无记录";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60_000));
  return minutes < 1 ? "刚刚上报" : minutes < 60 ? `${minutes}分钟前` : `${Math.floor(minutes / 60)}小时前`;
}
function deliveryTime(value: string | null): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "今日无送达";
  return `${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" }).format(new Date(value))} 送达`;
}

export function CourtStudio(props: Props) {
  const { dashboard, availability, hasData, loading, activeIdentity, luluState,
    statusLabel, statusDetail, highlightedVenueId, onCreate, onPanel, onRefresh, onChangeEmail } = props;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const searchRef = useRef<HTMLInputElement>(null);
  const directoryRef = useRef<HTMLElement>(null);
  const subscribed = useMemo(() => {
    const counts = new Map<VenueId, number>();
    if (!dashboard.identity.verified) return counts;
    for (const subscription of dashboard.subscriptions) {
      if (!subscription.active || !subscription.eligible) continue;
      for (const id of subscription.venueIds) counts.set(id, (counts.get(id) ?? 0) + 1);
    }
    return counts;
  }, [dashboard.subscriptions, dashboard.identity.verified]);
  const sortedVenues = useMemo(() => [...dashboard.venues].sort((a, b) =>
    b.subscriberCount - a.subscriberCount || a.name.localeCompare(b.name, "zh-CN") || a.id.localeCompare(b.id),
  ), [dashboard.venues]);
  const matchingVenues = useMemo(() => sortedVenues.filter(venue => {
    const normalized = query.trim().toLocaleLowerCase();
    const matchesQuery = !normalized || venue.name.toLocaleLowerCase().includes(normalized)
      || venue.id.toLocaleLowerCase().includes(normalized);
    return matchesQuery && (filter === "all" || (filter === "subscribed" ? subscribed.has(venue.id)
      : resolveVenueDisplayState(availability, venue.healthy) !== "healthy"));
  }), [sortedVenues, query, filter, subscribed, availability]);
  const verified = hasData && dashboard.identity.verified;
  const companionState = availability === "ready" ? luluState : "concerned";
  const companionLabel = availability === "ready" ? LULU_LABELS[luluState] : "暂时无法确认最新巡检状态";
  const hasSubscriptions = verified && dashboard.identity.activeSubscriptionCount > 0;
  const quotaPercent = Math.min(100, Math.max(0, dashboard.identity.remindersToday / Math.max(1, dashboard.identity.dailyLimit) * 100));
  const weatherSuppressed = Boolean(dashboard.weatherEmailGate?.suppressed && dashboard.identity.tier !== "priority");
  const resetFilters = () => { setQuery(""); setFilter("all"); };
  const scrollToDirectory = () => directoryRef.current?.scrollIntoView({ behavior: "instant", block: "start" });

  return (
    <main className="dashboard-screen court-studio" aria-label="Zacks 网球提醒" data-ui-version="0.8.0">
      <header className="product-header studio-header">
        <a className="brand-lockup" href="#studio-top" aria-label="Zacks 网球提醒首页">
          <span className="brand-mark" aria-hidden="true"><TennisBallIcon size={24} /></span>
          <div><h1>Zacks <span>网球提醒</span></h1><p>COURT STUDIO</p></div>
        </a>
        <nav className="studio-desktop-nav" aria-label="主要功能">
          <button type="button" onClick={scrollToDirectory}>探索场地</button>
          <button type="button" onClick={() => onPanel("subscriptions")}>我的订阅</button>
          <button type="button" onClick={() => onPanel("help")}>使用指南</button>
        </nav>
        <div className="header-actions">
          <button className="coffee-button" type="button" aria-label="支持 Zacks，请作者喝咖啡" title="支持 Zacks" onClick={() => onPanel("coffee")}>
            <CoffeeIcon size={18} aria-hidden="true" /><span>支持 Zacks</span>
          </button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button className="more-button" type="button" aria-label="更多功能"><DotsThreeIcon size={22} weight="bold" aria-hidden="true" /><span>更多</span></button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="more-menu" align="end" sideOffset={8} collisionPadding={12}>
                <DropdownMenu.Label className="more-menu-label">你的网球工作台</DropdownMenu.Label>
                <DropdownMenu.Item className="more-menu-item" onSelect={() => onPanel("subscriptions")}><ListBulletsIcon size={20} /><span>我的订阅</span></DropdownMenu.Item>
                {verified ? <DropdownMenu.Item className="more-menu-item" onSelect={() => onPanel("community")}><UsersThreeIcon size={20} /><span>用户社区</span></DropdownMenu.Item> : null}
                {verified && dashboard.identity.isAdmin ? <DropdownMenu.Item className="more-menu-item" onSelect={() => onPanel("admin")}><ShieldCheckIcon size={20} /><span>管理后台</span></DropdownMenu.Item> : null}
                <DropdownMenu.Item className="more-menu-item" onSelect={() => onPanel("priority")}><StarIcon size={20} /><span>提醒档位</span></DropdownMenu.Item>
                <DropdownMenu.Item className="more-menu-item" onSelect={() => onPanel("help")}><QuestionIcon size={20} /><span>查看帮助</span></DropdownMenu.Item>
                <DropdownMenu.Separator className="more-menu-separator" />
                <DropdownMenu.Item className="more-menu-item" asChild><a href="https://github.com/claude89757/wechat-on-airflow" target="_blank" rel="noopener noreferrer"><GithubLogoIcon size={20} /><span>项目开源地址</span></a></DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </header>

      <section className="studio-hero" id="studio-top" aria-labelledby="studio-title">
        <div className="studio-hero-copy">
          <span className="studio-eyebrow"><span /> SHENZHEN · 为每一次上场</span>
          <h2 id="studio-title">把时间，<br />留给<span>打球。</span></h2>
          <p>选好场地与打球时段，未来有位，邮件通知你。<br className="studio-desktop-break" />少一点反复查看，多一点上场的期待。</p>
          <div className="studio-hero-actions"><button className="studio-hero-cta" type="button" onClick={() => onCreate()}>设置我的提醒 <ArrowUpRightIcon size={18} /></button>
          <button className="studio-text-link" type="button" onClick={() => onPanel("help")}>了解提醒如何工作 <ArrowUpRightIcon size={17} /></button></div>
        </div>
        <div className="studio-court-art" aria-hidden="true">
          <div className="studio-court-label">LESS REFRESH. MORE PLAY.</div>
          <div className="studio-court"><i className="court-singles" /><i className="court-service" /><i className="court-center" /><i className="court-net" /><span className="court-ball" /></div>
          <div className="studio-art-caption"><span>01 / YOUR NEXT MATCH</span><TennisBallIcon size={20} /></div>
        </div>
      </section>

      <section className="metric-band studio-metrics" aria-label={verified ? "我的提醒与全站运行概况" : "全站运行概况"}>
        <div className="metric"><span className="studio-metric-label"><ListBulletsIcon size={18} />{verified ? "我的有效订阅" : "全站有效订阅"}</span><strong>{hasData ? verified ? dashboard.identity.activeSubscriptionCount : dashboard.metrics.activeSubscriptions : "—"}<small>条</small></strong><span>{verified ? "打球偏好，已为你记住" : "来自球友的每一份期待"}</span></div>
        <div className="metric"><span className="studio-metric-label"><EnvelopeSimpleIcon size={18} />{verified ? "我的今日送达" : "全站今日提醒"}</span><strong>{hasData ? verified ? dashboard.identity.deliveredToday : dashboard.metrics.remindersToday : "—"}<small>封</small></strong><span>{verified ? "以邮件服务商确认送达为准" : "一封摘要，汇集匹配时段"}</span></div>
        <div className="metric"><span className="studio-metric-label"><ShieldCheckIcon size={18} />全站巡检正常</span><strong>{availability === "ready" ? dashboard.metrics.healthyVenues : "—"}<small>/ {dashboard.metrics.totalVenues} 个场地</small></strong><span>巡检状态，不代表当前有位</span></div>
      </section>

      <div className={`service-line studio-service service-${availability}`} aria-live="polite">
        <span className={`live-dot ${availability === "ready" ? "" : availability}`} aria-hidden="true" />
        <div><strong>{statusLabel}</strong><span>{statusDetail}</span></div>
        <button type="button" aria-label="获取最新状态" title="获取最新状态" onClick={onRefresh} disabled={loading}><ArrowsClockwiseIcon className={loading ? "is-spinning" : ""} size={18} /><span>刷新</span></button>
      </div>
      {weatherSuppressed ? <div className="weather-notice studio-weather" role="status"><ShieldCheckIcon size={24} aria-hidden="true" /><div><strong>降雨提醒 · 普通邮件暂停</strong><p>预计降水 {dashboard.weatherEmailGate?.precipitationMm ?? "—"} mm，达到 {dashboard.weatherEmailGate?.thresholdMm} mm 阈值。优先用户和微信通知不受影响。</p></div></div> : null}

      <section className="create-card studio-create" aria-labelledby="create-card-title">
        <div className="studio-create-top"><span className="studio-eyebrow">YOUR COURT CONCIERGE</span><ArrowUpRightIcon size={20} /></div>
        <div className="create-card-main">
          <div className="create-copy"><h2 id="create-card-title">{hasSubscriptions ? "继续期待下一场。" : <>下一场，<br />交给 Zacks。</>}</h2><p>{hasSubscriptions ? "你的提醒正在守候。也可以为新的场地或时段，再留一份期待。" : "告诉我们你想在哪儿、什么时候打球。剩下的，交给 Zacks。"}</p></div>
          <div className="lulu-stage" data-lulu-state={companionState} aria-label={companionLabel} title={companionLabel}><img key={companionState} className="lulu-sprite" data-testid="lulu-sprite" src="/assets/lulu-sprite.webp" alt="" aria-hidden="true" decoding="async" draggable={false} /></div>
        </div>
        <div className="studio-steps" aria-label="创建提醒的三个步骤"><span><b>01</b>选择场地</span><span><b>02</b>设置时间</span><span><b>03</b>邮件提醒</span></div>
        <button className="primary-button" type="button" onClick={() => onCreate()}><PlusIcon size={20} weight="bold" />创建订阅<ArrowUpRightIcon className="studio-button-arrow" size={19} /></button>
        <button className="studio-manage" type="button" onClick={() => onPanel("subscriptions")}><ListBulletsIcon size={18} />管理我的提醒{verified ? <span>{dashboard.identity.activeSubscriptionCount}</span> : <ArrowUpRightIcon size={16} />}</button>
        <div className="identity-row"><span className={activeIdentity ? "identity-ok" : "identity-pending"}><CheckCircleIcon size={16} />{activeIdentity ? `${activeIdentity} · 本机记住` : "无需注册 · 验证邮箱即可开始"}</span>{activeIdentity ? <button type="button" onClick={onChangeEmail}>更换</button> : null}</div>
        {verified ? <>
          <div className={`tier-row tier-${dashboard.identity.tier}`}><span><StarIcon size={16} />{dashboard.identity.tier === "priority" ? "优先用户" : "普通用户"}</span><button type="button" onClick={() => onPanel("priority")}>{dashboard.identity.tier === "priority" ? "查看规则" : "输入邀请码"}</button></div>
          <div className="quota-card" aria-label="今日邮件额度"><div><span>今日邮件额度</span><strong>剩余 {dashboard.identity.remainingToday} / {dashboard.identity.dailyLimit}</strong></div><span className="quota-track" aria-hidden="true"><i style={{ width: `${quotaPercent}%` }} /></span><p>已提交 {dashboard.identity.submittedToday} · 送达 {dashboard.identity.deliveredToday} · 失败 {dashboard.identity.failedToday}</p></div>
        </> : null}
        <p className="studio-disclaimer"><ShieldCheckIcon size={15} />只做提醒，不代订，也不保证订到。</p>
      </section>

      <section className="venue-section studio-directory" ref={directoryRef} id="studio-directory" aria-labelledby="venue-heading">
        <div className="section-heading"><div><span className="studio-eyebrow">THE COURT DIRECTORY</span><h2 id="venue-heading">找到你想去的球场<span>{dashboard.venues.length}</span></h2><p>点按场地，直接设置提醒。状态仅表示后台最近巡检结果。</p></div></div>
        <div className="studio-toolbar">
          <label className="studio-search"><MagnifyingGlassIcon size={19} aria-hidden="true" /><KeyboardInput ref={searchRef} type="search" aria-label="搜索场地" placeholder="搜索场地名称…" autoComplete="off" value={query} onChange={event => setQuery(event.target.value)} />{query ? <button type="button" aria-label="清除搜索" onClick={() => { setQuery(""); searchRef.current?.focus(); }}><XIcon size={16} /></button> : null}</label>
          <div className="studio-filters" role="group" aria-label="筛选场地">
            {([["all", "全部场地"], ["subscribed", "我已订阅"], ["attention", "需要关注"]] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={filter === value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>{label}{value === "subscribed" && subscribed.size > 0 ? <small>{subscribed.size}</small> : null}</button>)}
          </div>
        </div>
        <div className="studio-directory-meta"><span role="status">{query || filter !== "all" ? `找到 ${matchingVenues.length} 个场地` : "按关注人数排序"}</span><span><i />巡检正常 ≠ 当前有位</span></div>
        <div className="venue-grid">
          {matchingVenues.map(venue => {
            const state = resolveVenueDisplayState(availability, venue.healthy);
            const count = subscribed.get(venue.id) ?? 0;
            const stateText = state === "healthy" ? "正常" : state === "unhealthy" ? "异常" : loading ? "读取中" : "未知";
            const cadence = formatInspectionCadence(venue.id).replace("/次", "");
            const mail = state === "unknown" ? "状态待确认" : venue.lastNotificationAt ? deliveryTime(venue.lastNotificationAt) : weatherSuppressed ? "邮件暂停" : "今日无送达";
            return <button type="button" key={venue.id} className={`venue-card studio-venue venue-card-${state}${count ? " is-subscribed" : ""}${highlightedVenueId === venue.id ? " is-highlighted" : ""}`} data-testid={`venue-card-${venue.id}`} data-venue-id={venue.id} aria-label={`为${venue.name}快速创建提醒；最近上报${stateText}，后台${cadence}，记录于${relativeTime(venue.lastInspectionAt)}，${hasData ? venue.subscriberCount : "未知"}人关注`} onClick={() => onCreate(venue.id)}>
              <span className="venue-card-heading"><span className="studio-venue-mark" aria-hidden="true"><TennisBallIcon size={21} weight="duotone" /></span><span className={`venue-card-action ${count ? "is-subscribed" : "is-add"}`} aria-hidden="true">{count ? `✓${count}` : <ArrowUpRightIcon size={19} />}</span></span>
              <span className="venue-card-name">{venue.name}</span>
              <span className="venue-card-status"><span><i className={`venue-status-dot ${state}`} />{stateText}</span><small>{cadence} / 次</small></span>
              <span className="venue-card-meta"><span><ClockIcon size={13} />{relativeTime(venue.lastInspectionAt)}</span><span className="venue-card-followers"><UsersThreeIcon size={13} />{hasData ? venue.subscriberCount : "—"}</span></span>
              <span className="venue-card-mail"><EnvelopeSimpleIcon size={13} />{mail}</span>
            </button>;
          })}
        </div>
        {!matchingVenues.length ? <div className="studio-empty" role="status"><MagnifyingGlassIcon size={32} /><h3>{query ? "没有找到这个场地" : filter === "subscribed" ? "还没有订阅场地" : "当前没有需要关注的场地"}</h3><p>{query ? "试试更短的关键词，或清除筛选看看。" : filter === "subscribed" ? "创建提醒后，你关注的场地会出现在这里。" : "可以切换到全部场地，继续选择提醒条件。"}</p><button type="button" onClick={resetFilters}>查看全部场地</button></div> : null}
      </section>
      <footer className="studio-footer"><span><TennisBallIcon size={18} /> ZACKS · COURT STUDIO</span><p>认真对待每一次上场的期待。</p><button type="button" onClick={() => onPanel("help")}>提醒规则与帮助 <ArrowUpRightIcon size={15} /></button></footer>

    </main>
  );
}

export function StudioMobileNav({ onCreate, onPanel }: Pick<Props, "onCreate" | "onPanel">) {
  const scrollToDirectory = () => document.getElementById("studio-directory")?.scrollIntoView({ behavior: "instant", block: "start" });
  return (
      <nav className="studio-mobile-nav" aria-label="快捷导航"><button type="button" onClick={scrollToDirectory}><MapPinIcon size={20} /><span>场地</span></button><button type="button" onClick={() => onPanel("subscriptions")}><BellRingingIcon size={20} /><span>我的订阅</span></button><button className="studio-mobile-create" type="button" onClick={() => onCreate()}><PlusIcon size={20} /><span>创建提醒</span></button></nav>
  );
}
