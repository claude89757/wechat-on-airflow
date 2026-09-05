import "./court-studio.css";
import { CourtStudio, StudioMobileNav } from "./CourtStudio";
import {
  BuildingApartmentIcon,
  BuildingsIcon,
  CheckCircleIcon,
  CourtBasketballIcon,
  EnvelopeSimpleIcon,
  MapPinIcon,
  ShieldCheckIcon,
  StarIcon,
  KeyIcon,
  TennisBallIcon,
  TrashIcon,
  WavesIcon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelSubscription,
  claimCoffeeInvite,
  createSubscription,
  EMPTY_DASHBOARD,
  FALLBACK_DASHBOARD,
  getDashboard,
  loadReceipts,
  removeReceipt,
  requestVerificationCode,
  redeemPriorityInvite,
  saveReceipt,
  startCoffeeInviteSession,
  WEEKDAYS,
  type Dashboard,
  type SubscriptionTerm,
  type VenueId,
  type VerificationReceipt,
  type Weekday,
  verifyEmail,
} from "./api";
import { resolveDashboardAvailability } from "./dashboard-state";
import { resolveLuluState } from "./lulu";
import { AdminPanel, CommunityPanel } from "./OperationsPanel";
import { BottomSheet, KeyboardInput, MobileScroll, useKeyboard } from "./mobile";
import { isTextEntry, useNativeKeyboardViewport } from "./nativeKeyboard";

type Panel = "create" | "help" | "subscriptions" | "priority" | "community" | "admin" | "coffee" | null;

type CoffeeInviteSession = Awaited<ReturnType<typeof startCoffeeInviteSession>>;
type CoffeeInviteReward = Awaited<ReturnType<typeof claimCoffeeInvite>>;

const COFFEE_REVEAL_DELAY_MS = 5_000;

const WEEKDAY_LABELS: Record<Weekday, string> = {
  1: "星期一",
  2: "星期二",
  3: "星期三",
  4: "星期四",
  5: "星期五",
  6: "星期六",
  7: "星期日",
};

const WEEKDAY_SHORT_LABELS: Record<Weekday, string> = {
  1: "一",
  2: "二",
  3: "三",
  4: "四",
  5: "五",
  6: "六",
  7: "日",
};

const WEEKDAY_PRESETS: Array<{ label: string; weekdays: Weekday[] }> = [
  { label: "每天", weekdays: [...WEEKDAYS] },
  { label: "工作日", weekdays: [1, 2, 3, 4, 5] },
  { label: "周末", weekdays: [6, 7] },
];

const VENUE_ACCENTS: Record<VenueId, string> = {
  szw: "teal",
  gba: "cyan",
  dsh_free: "green",
  dsh: "teal",
  sysh: "blue",
  tops: "royal",
  fsb: "blue",
  fsb_shenyun: "teal",
  fsb_shekou: "cyan",
  fsb_xinan: "green",
  fsb_zhengzhong: "royal",
  fsb_atuoshan: "blue",
  fsb_zonglvquan: "teal",
  fsb_guanhu: "cyan",
  fsb_bantian: "green",
  fsb_shahe: "royal",
  fsb_baoshui: "blue",
  fsb_nanyou: "teal",
  fsb_xinqiao: "cyan",
  fsb_yifangcheng: "green",
  fsb_qilin: "royal",
  fsb_maozhouhe: "blue",
  fft_qianhai: "teal",
  ppba: "royal",
  tyzx: "cyan",
  jdwx: "green",
};

const VENUE_ICONS: Record<VenueId, React.ElementType> = {
  szw: WavesIcon,
  gba: BuildingApartmentIcon,
  dsh_free: TennisBallIcon,
  dsh: TennisBallIcon,
  sysh: TennisBallIcon,
  tops: BuildingsIcon,
  fsb: MapPinIcon,
  fsb_shenyun: TennisBallIcon,
  fsb_shekou: MapPinIcon,
  fsb_xinan: TennisBallIcon,
  fsb_zhengzhong: BuildingsIcon,
  fsb_atuoshan: MapPinIcon,
  fsb_zonglvquan: TennisBallIcon,
  fsb_guanhu: MapPinIcon,
  fsb_bantian: BuildingsIcon,
  fsb_shahe: TennisBallIcon,
  fsb_baoshui: MapPinIcon,
  fsb_nanyou: BuildingsIcon,
  fsb_xinqiao: TennisBallIcon,
  fsb_yifangcheng: MapPinIcon,
  fsb_qilin: BuildingsIcon,
  fsb_maozhouhe: TennisBallIcon,
  fft_qianhai: TennisBallIcon,
  ppba: TennisBallIcon,
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

const TERM_LABELS: Record<SubscriptionTerm, string> = {
  "7d": "7天", "8d": "8天", "9d": "9天", "10d": "10天",
  "11d": "11天", "12d": "12天", "13d": "13天", "14d": "14天 · 两周",
  "30d": "30天", "90d": "3个月", "180d": "半年", long_term: "长期",
};

function formatWeekdays(value: readonly Weekday[] | undefined): string {
  const weekdays = value?.length ? [...value].sort((left, right) => left - right) : [...WEEKDAYS];
  if (weekdays.length === 7) return "每天";
  if (weekdays.join(",") === "1,2,3,4,5") return "工作日";
  if (weekdays.join(",") === "6,7") return "周末";
  return weekdays.map((weekday) => WEEKDAY_LABELS[weekday].replace("星期", "周")).join("、");
}

function SubscriptionCelebration({ celebrationId }: { celebrationId: number }) {
  const particles = Array.from({ length: 30 }, (_, index) => {
    const angle = (index % 10) * 36;
    const burst = Math.floor(index / 10);
    const style = {
      "--firework-angle": `${angle}deg`,
      "--firework-distance": `${58 + (index % 4) * 8}px`,
      "--firework-delay": `${burst * 150 + (index % 3) * 20}ms`,
    } as React.CSSProperties;
    return <i key={`${celebrationId}-${index}`} style={style} />;
  });
  return (
    <div className="subscription-celebration" aria-hidden="true" data-testid="subscription-celebration">
      <div className="firework-burst firework-burst-left">{particles.slice(0, 10)}</div>
      <div className="firework-burst firework-burst-center">{particles.slice(10, 20)}</div>
      <div className="firework-burst firework-burst-right">{particles.slice(20)}</div>
    </div>
  );
}

function sameSelection(
  left: readonly (string | number)[],
  right: readonly (string | number)[],
): boolean {
  if (left.length !== right.length) return false;
  return left.map(String).sort().join("|") === right.map(String).sort().join("|");
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

function dataStoreUnavailable(message: string): boolean {
  return /D1(?:_ERROR)?|daily row read limit|code[:\s]*7500|data_store_unavailable|database (?:is )?(?:unavailable|temporarily unavailable)/i.test(message);
}

function formatInviteExpiry(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "30 天内";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(date);
}

function waitForImagePaint(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()));
  });
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
      ? { ...initialDashboard.identity, verified: true, maskedEmail: receipt.maskedEmail }
      : initialDashboard.identity,
  }));
  const [panel, setPanel] = useState<Panel>(null);
  const [loading, setLoading] = useState(true);
  const [serviceOnline, setServiceOnline] = useState(import.meta.env.DEV);
  const [hasSuccessfulDashboard, setHasSuccessfulDashboard] = useState(import.meta.env.DEV);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [toast, setToast] = useState("");
  const [celebrationId, setCelebrationId] = useState<number | null>(null);
  const celebrationCounter = useRef(0);
  const [notificationBurst, setNotificationBurst] = useState(false);
  const previousReminderCount = useRef<number | null>(null);
  const [email, setEmail] = useState(receipt?.email ?? "");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const codeInputRef = useRef<HTMLInputElement>(null);
  const [venueIds, setVenueIds] = useState<VenueId[]>(["szw", "tops"]);
  const [quickVenueId, setQuickVenueId] = useState<VenueId | null>(null);
  const [highlightedVenueId, setHighlightedVenueId] = useState<VenueId | null>(null);
  const [weekdays, setWeekdays] = useState<Weekday[]>([...WEEKDAYS]);
  const [startTime, setStartTime] = useState("18:00");
  const [endTime, setEndTime] = useState("22:00");
  const [subscriptionTerm, setSubscriptionTerm] = useState<SubscriptionTerm>("7d");
  const [inviteCode, setInviteCode] = useState("");
  const [coffeeImageKey, setCoffeeImageKey] = useState(0);
  const [coffeeImageLoaded, setCoffeeImageLoaded] = useState(false);
  const [coffeeSessionBusy, setCoffeeSessionBusy] = useState(false);
  const [coffeeClaimBusy, setCoffeeClaimBusy] = useState(false);
  const [coffeeSession, setCoffeeSession] = useState<CoffeeInviteSession | null>(null);
  const [coffeeRevealAt, setCoffeeRevealAt] = useState<number | null>(null);
  const [coffeeClaimReady, setCoffeeClaimReady] = useState(false);
  const [coffeeReward, setCoffeeReward] = useState<CoffeeInviteReward | null>(null);
  const [coffeeError, setCoffeeError] = useState("");
  const coffeeFlowId = useRef(0);
  const coffeeImageHandledForFlow = useRef<number | null>(null);

  const resetCoffeeFlow = useCallback(() => {
    coffeeFlowId.current += 1;
    coffeeImageHandledForFlow.current = null;
    setCoffeeImageKey((current) => current + 1);
    setCoffeeImageLoaded(false);
    setCoffeeSessionBusy(false);
    setCoffeeClaimBusy(false);
    setCoffeeSession(null);
    setCoffeeRevealAt(null);
    setCoffeeClaimReady(false);
    setCoffeeReward(null);
    setCoffeeError("");
  }, []);

  const refresh = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const next = await getDashboard(receipt, { force });
      const stale = next.dataStatus?.stale === true;
      setDashboard(next);
      setServiceOnline(true);
      setHasSuccessfulDashboard(true);
      setRefreshFailed(stale);
      setRefreshError(stale ? "data_store_unavailable" : "");
      if (receipt && !next.identity.verified) {
        setReceipts(removeReceipt(receipt.token));
        setReceipt(null);
      }
      if (force) setToast(stale ? "状态库暂时不可用，已保留上次数据" : "已获取最新数据");
    } catch (error) {
      setServiceOnline(import.meta.env.DEV);
      setRefreshFailed(true);
      setRefreshError(error instanceof Error ? error.message : "请求处理失败");
    } finally {
      setLoading(false);
    }
  }, [receipt]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const allowed = dashboard.subscriptionTerms[dashboard.identity.tier];
    if (!allowed.includes(subscriptionTerm)) setSubscriptionTerm("7d");
  }, [dashboard.identity.tier, dashboard.subscriptionTerms, subscriptionTerm]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (celebrationId === null) return;
    const timer = window.setTimeout(() => setCelebrationId(null), 2200);
    return () => window.clearTimeout(timer);
  }, [celebrationId]);

  useEffect(() => {
    if (!highlightedVenueId) return;
    const timer = window.setTimeout(() => setHighlightedVenueId(null), 1800);
    return () => window.clearTimeout(timer);
  }, [highlightedVenueId]);

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

  useEffect(() => {
    if (panel !== "coffee" || coffeeRevealAt === null) return;

    const reveal = () => setCoffeeClaimReady(true);
    const delay = Math.max(0, coffeeRevealAt - Date.now());
    if (delay === 0) {
      reveal();
      return;
    }

    const timer = window.setTimeout(reveal, delay);
    return () => window.clearTimeout(timer);
  }, [coffeeRevealAt, panel]);

  const popularVenues = useMemo(() => [...dashboard.venues].sort((left, right) =>
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

  const activeIdentity = dashboard.identity.verified
    ? dashboard.identity.maskedEmail
    : receipt?.maskedEmail;
  const coffeeRewardAvailable = coffeeReward?.status === "available";
  const coffeeRewardTitle = coffeeReward?.status === "redeemed"
    ? "邀请码已兑换"
    : coffeeReward?.status === "expired"
      ? "邀请码已过期"
      : coffeeReward?.status === "disabled" || coffeeReward?.status === "deleted"
        ? "邀请码不可用"
        : "彩蛋已解锁";
  const coffeeRewardMessage = coffeeReward?.status === "redeemed"
    ? "这个邀请码已经完成兑换，无需再次操作。"
    : coffeeReward?.status === "expired"
      ? "这是你此前领取的邀请码，但 30 天有效期已经结束。"
      : coffeeReward?.status === "disabled" || coffeeReward?.status === "deleted"
        ? "这是你此前领取的邀请码，但它目前不能兑换。"
        : coffeeReward?.reused
          ? "这是你此前领取且仍可使用的邀请码。"
          : "谢谢你的咖啡，送你一个优先用户邀请码。";
  const availability = resolveDashboardAvailability({ hasSuccessfulDashboard, loading, refreshFailed });
  const storeUnavailable = dashboard.dataStatus?.reason === "data_store_unavailable"
    || dataStoreUnavailable(refreshError);
  const statusLabel = availability === "loading" ? "正在读取状态数据"
    : availability === "unknown" && storeUnavailable ? "状态库暂时不可用"
    : availability === "unknown" ? "暂时无法读取状态"
    : availability === "stale" ? "状态库暂时不可用，显示上次数据" : "数据已加载";
  const statusDetail = hasSuccessfulDashboard
    ? dashboard.dataStatus?.stale
      ? `显示 ${formatUpdatedAt(dashboard.generatedAt)} 的上次数据 · 状态库恢复后可手动刷新`
      : `数据生成于 ${formatUpdatedAt(dashboard.generatedAt)} · 点击右侧按钮手动刷新`
    : loading ? "正在获取最新数据"
      : storeUnavailable
        ? "后台巡检与页面独立运行；暂时无法读取最新状态，请稍后重试"
        : "请求暂时失败，请稍后点击刷新";
  const luluState = resolveLuluState({
    serviceOnline: serviceOnline && hasSuccessfulDashboard,
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
    if (nextPanel === "coffee") resetCoffeeFlow();
    setPanel(nextPanel);
  };

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

  const handleCoffeeImageLoad = async (image: HTMLImageElement) => {
    const flowId = coffeeFlowId.current;
    if (coffeeImageHandledForFlow.current === flowId) return;
    coffeeImageHandledForFlow.current = flowId;

    try {
      await image.decode();
    } catch {
      // A loaded image can still be paintable when decode() rejects on older engines.
    }
    await waitForImagePaint();
    if (coffeeFlowId.current !== flowId || !image.isConnected) return;

    const imagePaintedAt = Date.now();
    setCoffeeImageLoaded(true);
    if (!receipt) {
      setCoffeeRevealAt(imagePaintedAt + COFFEE_REVEAL_DELAY_MS);
      return;
    }

    setCoffeeSessionBusy(true);
    setCoffeeError("");
    try {
      const session = await startCoffeeInviteSession(receipt);
      if (coffeeFlowId.current !== flowId) return;

      const serverAvailableAt = Date.parse(session.availableAt);
      const revealAt = Math.max(
        imagePaintedAt + COFFEE_REVEAL_DELAY_MS,
        Number.isNaN(serverAvailableAt) ? 0 : serverAvailableAt,
      );
      setCoffeeSession(session);
      setCoffeeRevealAt(revealAt);
    } catch (error) {
      if (coffeeFlowId.current !== flowId) return;
      setCoffeeError(error instanceof Error ? error.message : "暂时无法准备彩蛋，请重试");
    } finally {
      if (coffeeFlowId.current === flowId) setCoffeeSessionBusy(false);
    }
  };

  const claimCoffeeReward = async () => {
    if (!receipt) {
      resetCoffeeFlow();
      setToast("请先验证邮箱，再回来领取彩蛋");
      setPanel("create");
      return;
    }
    if (!coffeeSession) {
      setCoffeeError("领取会话已失效，请重新加载");
      return;
    }

    const flowId = coffeeFlowId.current;
    setCoffeeClaimBusy(true);
    setCoffeeError("");
    try {
      const reward = await claimCoffeeInvite(receipt, coffeeSession.claimToken);
      if (coffeeFlowId.current !== flowId) return;
      setCoffeeReward(reward);
    } catch (error) {
      if (coffeeFlowId.current !== flowId) return;
      setCoffeeError(error instanceof Error ? error.message : "彩蛋领取失败，请重试");
    } finally {
      if (coffeeFlowId.current === flowId) setCoffeeClaimBusy(false);
    }
  };

  const copyCoffeeInvite = async () => {
    if (!coffeeReward || coffeeReward.status !== "available") return;
    setCoffeeError("");
    try {
      await navigator.clipboard.writeText(coffeeReward.code);
      setToast("邀请码已复制");
    } catch {
      setCoffeeError("未能自动复制，请长按邀请码手动复制");
    }
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
    setSubscriptionTerm("7d");
    setFormError("");
    setPanel("create");
  };

  const sendCode = async () => {
    if (formBusy) return;
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
    if (formBusy) return;
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
    setVenueIds((current) => {
      const next = current.includes(venueId)
        ? current.filter((item) => item !== venueId)
        : [...current, venueId];
      setFormError(next.length ? "" : "请至少选择一个场地");
      return next;
    });
  };

  const selectAllVenues = () => {
    setVenueIds(popularVenues.map((venue) => venue.id));
    setFormError("");
  };

  const clearVenues = () => {
    setVenueIds([]);
    setFormError("请至少选择一个场地");
  };

  const toggleWeekday = (weekday: Weekday) => {
    setWeekdays((current) => {
      const next = current.includes(weekday)
        ? current.filter((item) => item !== weekday)
        : [...current, weekday].sort((left, right) => left - right);
      setFormError(next.length ? "" : "请至少选择一个星期");
      return next;
    });
  };

  const applyWeekdayPreset = (preset: readonly Weekday[]) => {
    setWeekdays([...preset]);
    setFormError("");
  };

  const submitSubscription = async () => {
    if (formBusy) return;
    if (!receipt) {
      setFormError("请先验证邮箱");
      return;
    }
    if (!venueIds.length) {
      setFormError("请至少选择一个场地");
      return;
    }
    if (!weekdays.length) {
      setFormError("请至少选择一个星期");
      return;
    }
    if (startTime >= endTime) {
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
    setFormError("");
    try {
      await createSubscription(receipt, {
        venueIds,
        weekdays,
        startTime,
        endTime,
        termCode: subscriptionTerm,
      });
      const createdQuickVenue = quickVenue;
      setPanel(null);
      setQuickVenueId(null);
      if (createdQuickVenue) setHighlightedVenueId(createdQuickVenue.id);
      celebrationCounter.current += 1;
      setCelebrationId(celebrationCounter.current);
      setToast(createdQuickVenue
        ? `${createdQuickVenue.name}提醒已创建 · ${formatWeekdays(weekdays)} · ${startTime}–${endTime} · ${TERM_LABELS[subscriptionTerm]}`
        : `订阅已创建：${subscriptionSummary}`);
      await refresh();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "订阅创建失败");
    } finally {
      setFormBusy(false);
    }
  };

  const cancelExistingSubscription = async (subscriptionId: string) => {
    if (!receipt) return;
    const confirmed = window.confirm(
      "确认取消这个订阅吗？取消后将不再收到该条件的场地提醒。",
    );
    if (!confirmed) return;
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
    if (panel === "community") return "用户社区";
    if (panel === "admin") return "管理后台";
    if (panel === "coffee") return "支持 Zacks";
    if (panel === "create" && quickVenue) {
      return receipt ? `创建${quickVenue.name}提醒` : `订阅${quickVenue.name}`;
    }
    return receipt ? "创建订阅" : "验证邮箱";
  }, [panel, quickVenue, receipt]);

  return (
    <>
      <MobileScroll className="app-screen">
        <CourtStudio
          dashboard={dashboard}
          availability={availability}
          hasData={hasSuccessfulDashboard}
          loading={loading}
          activeIdentity={activeIdentity}
          luluState={luluState}
          statusLabel={statusLabel}
          statusDetail={statusDetail}
          highlightedVenueId={highlightedVenueId}
          onCreate={openCreatePanel}
          onPanel={openPanel}
          onRefresh={() => void refresh(true)}
          onChangeEmail={changeEmail}
        />
      </MobileScroll>
      {panel === null ? <StudioMobileNav onCreate={openCreatePanel} onPanel={openPanel} /> : null}

      <BottomSheet
        open={panel !== null}
        onOpenChange={(open) => {
          if (!open) {
            if (panel === "coffee") resetCoffeeFlow();
            setPanel(null);
            setQuickVenueId(null);
          }
        }}
        title={panelTitle}
        description={
          panel === "create"
            ? quickVenue
              ? `已选择${quickVenue.name}，设置星期、时段和有效期即可。`
              : "只设置提醒条件，不展示或代订场地。"
            : undefined
        }
        snap={panel === "coffee" || panel === "community" || panel === "admin"
          ? 0.94
          : panel === "create" ? quickVenue ? 0.82 : 0.86 : panel === "priority" ? 0.82 : 0.72}
      >
        {panel === "coffee" ? (
          <div className="coffee-panel" data-testid="coffee-panel">
            <p className="coffee-intro">
              如果这个小工具帮到了你，可以用微信请作者喝杯咖啡。完全自愿，不影响普通提醒服务。
            </p>
            <div className="coffee-qr-frame">
              <img
                key={coffeeImageKey}
                className="coffee-qr-image"
                src="/assets/wechat-coffee-qr.jpeg"
                alt="微信支付收款二维码，收款人 Tt（**添）"
                decoding="async"
                draggable={false}
                onLoad={(event) => void handleCoffeeImageLoad(event.currentTarget)}
                onError={() => setCoffeeError("收款码加载失败，请重试")}
              />
            </div>

            {coffeeReward ? (
              <section className="coffee-reward" aria-labelledby="coffee-reward-title">
                <StarIcon size={34} weight="fill" aria-hidden="true" />
                <div aria-live="polite">
                  <strong id="coffee-reward-title">{coffeeRewardTitle}</strong>
                  <p>{coffeeRewardMessage}</p>
                </div>
                <code className="coffee-invite-code">{coffeeReward.code}</code>
                {coffeeRewardAvailable ? (
                  <button className="coffee-copy-button" type="button" onClick={() => void copyCoffeeInvite()}>
                    复制邀请码
                  </button>
                ) : null}
                {coffeeReward.status === "available" ? (
                  <p className="coffee-expiry">
                    邀请码有效期 30 天，请在 <time dateTime={coffeeReward.expiresAt}>{formatInviteExpiry(coffeeReward.expiresAt)}</time> 前兑换。
                  </p>
                ) : coffeeReward.status === "expired" ? (
                  <p className="coffee-expiry">
                    该邀请码已于 <time dateTime={coffeeReward.expiresAt}>{formatInviteExpiry(coffeeReward.expiresAt)}</time> 过期。
                  </p>
                ) : null}
                {coffeeError ? <p className="form-error" role="alert">{coffeeError}</p> : null}
              </section>
            ) : (
              <>
                <p className="coffee-waiting" role="status" aria-live="polite">
                  {!coffeeImageLoaded
                    ? "正在加载收款码…"
                    : coffeeSessionBusy
                      ? "收款码已显示，请完成支付…"
                      : coffeeClaimReady
                        ? "谢谢你的支持，可以继续了。"
                        : coffeeError ? "" : "收款码已显示，请完成支付，稍候片刻。"}
                </p>
                {coffeeError ? <p className="form-error" role="alert">{coffeeError}</p> : null}
                {coffeeError && !coffeeSession ? (
                  <button className="coffee-retry-button" type="button" onClick={resetCoffeeFlow}>
                    重新加载
                  </button>
                ) : null}
                {coffeeClaimReady ? (
                  <button
                    className="sheet-primary coffee-claim-button"
                    type="button"
                    disabled={coffeeClaimBusy}
                    onClick={() => void claimCoffeeReward()}
                  >
                    {coffeeClaimBusy ? "正在领取…" : "已请咖啡"}
                  </button>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {panel === "help" ? (
          <div className="help-content">
            <div className="help-row">
              <span>1</span>
              <div><strong>选择提醒条件</strong><p>可指定场地、星期和时间段；普通用户可选 7–14 天，优先用户还支持更长期限。</p></div>
            </div>
            <div className="help-row">
              <span>2</span>
              <div>
                <strong>后台巡检与页面刷新分开</strong>
                <p>
                  后台按各场地的巡检频率持续检查。关闭网页不影响提醒；页面仅在首次打开、创建或取消订阅、手动刷新时读取数据。卡片显示最近一次巡检上报，不代表当前有空位。
                </p>
              </div>
            </div>
            <div className="help-row">
              <span>3</span>
              <div><strong>命中后发邮件</strong><p>同一轮的多个场地和时段会合并为一封摘要邮件。</p></div>
            </div>
            <div className="help-row">
              <span>4</span>
              <div>
                <strong>每日邮件额度</strong>
                <p>
                  普通用户每天最多 {dashboard.deliveryTiers.standard} 封，优先用户最多
                  {dashboard.deliveryTiers.priority} 封；按深圳时间 00:00 重置。
                </p>
              </div>
            </div>
            <div className="help-row">
              <span>5</span>
              <div><strong>确保邮件能送达</strong><p>首次使用请留意垃圾邮件或广告邮件，并将 Zacks 通知标记为“不是垃圾邮件”。</p></div>
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
                  <span>{formatWeekdays(subscription.weekdays)}</span>
                  <span>{subscription.startTime}–{subscription.endTime}</span>
                  <span>{!subscription.eligible ? "优先资格已失效，长期订阅已暂停"
                    : subscription.autoRenew ? "长期有效 · 自动续期"
                    : `有效至 ${subscription.activeUntil.slice(0, 10)}`}</span>
                </div>
                <button
                  type="button"
                  aria-label="取消订阅"
                  title="取消订阅（需要确认）"
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
                <button type="button" onClick={() => openCreatePanel()}>创建第一个订阅</button>
              </div>
            )}
            {formError ? <p className="form-error" role="alert">{formError}</p> : null}
          </div>
        ) : null}

        {panel === "community" && receipt ? (
          <CommunityPanel receipt={receipt} />
        ) : null}

        {panel === "admin" && receipt && dashboard.identity.isAdmin ? (
          <AdminPanel receipt={receipt} />
        ) : null}

        {panel === "priority" ? (
          <div className="priority-panel">
            <div className="tier-comparison">
              <article>
                <span>普通用户</span>
                <strong>{dashboard.deliveryTiers.standard} 封/天</strong>
                <p>邮箱验证后自动获得，适合日常关注场地空位。</p>
              </article>
              <article className="featured">
                <span><StarIcon size={17} weight="fill" />优先用户</span>
                <strong>{dashboard.deliveryTiers.priority} 封/天</strong>
                <p>使用一次性趣味口令升级，解锁长期订阅；大雨天气也正常推送邮件。</p>
              </article>
            </div>

            <ul className="quota-rules">
              <li><strong>每天重置：</strong>按深圳时间 00:00 重新计算。</li>
              <li><strong>天气保障：</strong>优先用户不受降雨暂停影响，命中空位后正常发送邮件。</li>
              <li><strong>摘要计数：</strong>一封邮件可合并多个场地和时段，只计 1 封。</li>
              <li><strong>达到上限：</strong>当天后续空位邮件不发送，也不会隔天补发旧空位。</li>
              <li><strong>不计额度：</strong>邮箱验证码和微信消息不受档位限制。</li>
              <li><strong>长期订阅：</strong>优先资格有效期间自动续期，直到主动取消。</li>
            </ul>

            {receipt ? (
              dashboard.identity.tier === "priority" ? (
                <div className="priority-active">
                  <ShieldCheckIcon size={34} weight="fill" />
                  <strong>优先提醒已开启</strong>
                  <p>
                    今日还可发送 {dashboard.identity.remainingToday} 封场地摘要邮件。
                    达到降雨暂停阈值时，优先用户邮件仍会正常发送；验证码和微信消息也不受此档位限制。
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
                      maxLength={32}
                      placeholder="ACE-SUNNY-PANDA-7K9P2Q"
                      value={inviteCode}
                      onChange={(event) => setInviteCode(event.target.value.toUpperCase())}
                    />
                  </label>
                  <p className="verification-note">
                    这是一个短而有趣的一次性口令，例如
                    <code className="invite-example">ACE-SUNNY-PANDA-7K9P2Q</code>。
                    不区分大小写，空格或连字符都可以；升级后优先档位会跟随此邮箱。
                  </p>
                  {formError ? <p className="form-error" role="alert">{formError}</p> : null}
                  <button
                    className="sheet-primary"
                    type="button"
                    disabled={formBusy || inviteCode.trim().length < 12}
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
                <button type="button" onClick={() => openCreatePanel()}>去验证邮箱</button>
              </div>
            )}
          </div>
        ) : null}

        {panel === "create" ? (
          receipt ? (
            <div className="subscription-form" aria-busy={formBusy}>
              <div className="sheet-identity">
                <ShieldCheckIcon size={22} weight="fill" />
                <span><strong>{receipt.maskedEmail}</strong> 已验证</span>
                <button type="button" onClick={changeEmail}>更换</button>
              </div>

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

              {quickVenue ? (
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
              )}

              <fieldset aria-describedby="weekday-help">
                <legend>选择打球星期 <span>至少选择一天</span></legend>
                <div className="weekday-presets" aria-label="星期快捷选择">
                  {WEEKDAY_PRESETS.map((preset) => {
                    const selected = preset.weekdays.length === weekdays.length
                      && preset.weekdays.every((weekday) => weekdays.includes(weekday));
                    return (
                      <button
                        type="button"
                        key={preset.label}
                        className={selected ? "selected" : ""}
                        aria-pressed={selected}
                        onClick={() => applyWeekdayPreset(preset.weekdays)}
                      >
                        {preset.label}
                      </button>
                    );
                  })}
                </div>
                <div className="weekday-choices">
                  {WEEKDAYS.map((weekday) => {
                    const selected = weekdays.includes(weekday);
                    return (
                      <button
                        type="button"
                        key={weekday}
                        className={selected ? "selected" : ""}
                        aria-label={WEEKDAY_LABELS[weekday]}
                        aria-pressed={selected}
                        onClick={() => toggleWeekday(weekday)}
                      >
                        <span aria-hidden="true">{WEEKDAY_SHORT_LABELS[weekday]}</span>
                      </button>
                    );
                  })}
                </div>
                <p className="field-help" id="weekday-help">
                  只在所选星期匹配场地日期；例如选择“周末”，星期一至星期五不会发送提醒。
                </p>
              </fieldset>

              <fieldset>
                <legend>希望打球的时间段</legend>
                <div className="studio-time-presets" role="group" aria-label="打球时段快捷选择">
                  {[
                    { label: "清晨", start: "06:00", end: "09:00" },
                    { label: "午后", start: "12:00", end: "18:00" },
                    { label: "下班后", start: "18:00", end: "22:00" },
                  ].map(preset => <button type="button" key={preset.label}
                    aria-pressed={startTime === preset.start && endTime === preset.end}
                    onClick={() => { setStartTime(preset.start); setEndTime(preset.end); setFormError(""); }}>
                    {preset.label}<small>{preset.start}–{preset.end}</small>
                  </button>)}
                </div>
                <div className="time-range">
                  <label>
                    <span>开始</span>
                    <select value={startTime} onChange={(event) => {
                      setStartTime(event.target.value);
                      setFormError("");
                    }}>
                      {TIME_OPTIONS.slice(0, -1).map((time) => <option key={time}>{time}</option>)}
                    </select>
                  </label>
                  <span aria-hidden="true">—</span>
                  <label>
                    <span>结束</span>
                    <select value={endTime} onChange={(event) => {
                      setEndTime(event.target.value);
                      setFormError("");
                    }}>
                      {TIME_OPTIONS.slice(1).map((time) => <option key={time}>{time}</option>)}
                    </select>
                  </label>
                </div>
              </fieldset>

              <fieldset>
                <legend>订阅有效期 <span>{dashboard.identity.tier === "priority" ? "优先用户支持长期" : "默认 7 天，最长 14 天"}</span></legend>
                <div className="day-choices term-choices">
                  {dashboard.subscriptionTerms.priority.map((term) => {
                    const allowed = dashboard.subscriptionTerms[dashboard.identity.tier].some((allowedTerm) => allowedTerm === term);
                    return <button type="button" key={term}
                      className={`${subscriptionTerm === term ? "selected" : ""} ${allowed ? "" : "locked"}`.trim()}
                      aria-pressed={subscriptionTerm === term}
                      onClick={() => allowed ? setSubscriptionTerm(term) : setPanel("priority")}>
                      {!allowed ? <KeyIcon size={14} weight="fill" /> : null}{TERM_LABELS[term]}
                    </button>;
                  })}
                </div>
                {subscriptionTerm === "long_term" ? <p className="term-note">
                  长期订阅会在优先资格有效期间自动续期，直到你主动取消；每日邮件额度仍然适用，降雨天气不会暂停优先用户邮件。
                </p> : null}
              </fieldset>

              <div className="subscription-summary" aria-live="polite" id="subscription-summary">
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
              <span className="sr-only" aria-live="polite">
                {formBusy ? "正在创建订阅，请稍候" : ""}
              </span>
              <button
                className="sheet-primary"
                type="button"
                aria-describedby="subscription-summary"
                aria-label={quickVenue ? `创建${quickVenue.name}提醒` : "确认创建订阅"}
                disabled={formBusy || !subscriptionFormReady}
                onClick={() => void submitSubscription()}
              >
                {formBusy ? "正在创建…" : quickVenue ? "创建该场地提醒" : "确认创建订阅"}
              </button>
            </div>
          ) : (
            <div className="verification-form">
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
                  onChange={(event) => { setEmail(event.target.value); setChallengeId(""); setCode(""); setFormError(""); }}
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
              <div className="email-delivery-tip" role="note">
                <EnvelopeSimpleIcon size={20} weight="fill" aria-hidden="true" />
                <p>
                  没有收到验证码或场地提醒？请先检查垃圾邮件或广告邮件；找到来自 Zacks
                  的通知后，点击“不是垃圾邮件”或将发件人加入白名单，后续提醒会更稳定。
                </p>
              </div>
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

      {celebrationId !== null ? (
        <SubscriptionCelebration celebrationId={celebrationId} />
      ) : null}
      {toast ? <div className="app-toast" role="status">{toast}</div> : null}
    </>
  );
}
