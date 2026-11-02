import { CheckIcon, CopyIcon, MapPinIcon, XIcon } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { isTextEntry } from "./nativeKeyboard";
import "./gear-promo.css";

// v1 counted attempted renders, including cards immediately hidden by scrolling.
// Give visitors who never saw that version a real first impression after the fix.
const STORAGE_KEY = "zacks:gear-promo:2026-11:seen-v2";
const COOLDOWN_MS = 24 * 60 * 60 * 1_000;
const SHOW_DELAY_MS = 3_000;
const AUTO_CLOSE_MS = 5_000;
let memoryLastShown = 0;

export type GearPromoRequest = { id: number; trigger: HTMLElement | null };
type Props = { ready: boolean; blocked: boolean; request: GearPromoRequest };
type Mode = "auto" | "manual" | null;

function lastShown(): number {
  let timestamp = memoryLastShown;
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      const value = Number(window[name].getItem(STORAGE_KEY));
      if (Number.isFinite(value)) timestamp = Math.max(timestamp, value);
    } catch { /* Storage may be unavailable in private or embedded browsers. */ }
  }
  return timestamp;
}

function recordShown(now: number): void {
  memoryLastShown = now;
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      window[name].setItem(STORAGE_KEY, String(now));
    } catch { /* Memory still limits this page if an embedded browser blocks both stores. */ }
  }
}

function businessSurfaceOpen(): boolean {
  return Boolean(document.querySelector('.bottom-sheet, [role="menu"][data-state="open"]'))
    || isTextEntry(document.activeElement);
}

function ProductImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  return <div className="gear-promo-image">{failed
    ? <span>{alt}<small>图片暂未加载</small></span>
    : <img src={src} alt={alt} width={320} height={240} decoding="async" draggable={false}
      onError={() => setFailed(true)} />}</div>;
}

/** A non-modal notice: automatic display never takes focus or locks scrolling. */
export function GearPromo({ ready, blocked, request }: Props) {
  const [mode, setMode] = useState<Mode>(null);
  const [remaining, setRemaining] = useState(AUTO_CLOSE_MS);
  const [feedback, setFeedback] = useState("");
  const cardRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const eligibleAt = useRef(Date.now() + SHOW_DELAY_MS);
  const autoAttempted = useRef(false);
  const handledRequest = useRef(0);
  const modeRef = useRef<Mode>(null);
  modeRef.current = mode;

  const dismiss = useCallback((restoreFocus = false, interrupted = false) => {
    const hadFocus = cardRef.current?.contains(document.activeElement);
    if (modeRef.current === "auto") {
      if (interrupted) {
        // A sheet or background tab is not a completed impression. Retry after
        // returning to ordinary browsing instead of suppressing it for a day.
        autoAttempted.current = false;
        eligibleAt.current = Date.now() + SHOW_DELAY_MS;
      } else {
        recordShown(Date.now());
      }
    }
    modeRef.current = null;
    setMode(null);
    if (restoreFocus && hadFocus && returnFocusRef.current?.isConnected) {
      returnFocusRef.current.focus({ preventScroll: true });
    }
  }, []);

  useEffect(() => {
    const handleFocus = () => {
      if (isTextEntry(document.activeElement)) dismiss(false, true);
    };
    const handleVisibility = () => {
      eligibleAt.current = Date.now() + SHOW_DELAY_MS;
      if (document.hidden) dismiss(false, true);
    };
    document.addEventListener("focusin", handleFocus);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("focusin", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [dismiss]);

  useEffect(() => {
    eligibleAt.current = Date.now() + SHOW_DELAY_MS;
    if (blocked || !ready) dismiss(false, true);
  }, [ready, blocked, dismiss]);

  useEffect(() => {
    if (!request.id || request.id === handledRequest.current || blocked) return;
    handledRequest.current = request.id;
    autoAttempted.current = true;
    recordShown(Date.now());
    returnFocusRef.current = request.trigger;
    setFeedback("");
    setMode("manual");
  }, [request, blocked]);

  useEffect(() => {
    if (!ready || blocked || mode || autoAttempted.current) return;
    let timer = 0;
    const tryShow = () => {
      const now = Date.now();
      if (autoAttempted.current || now - lastShown() < COOLDOWN_MS) {
        autoAttempted.current = true;
        window.clearInterval(timer);
        return;
      }
      if (document.hidden || businessSurfaceOpen()) {
        eligibleAt.current = now + SHOW_DELAY_MS;
        return;
      }
      if (now < eligibleAt.current) return;
      autoAttempted.current = true;
      window.clearInterval(timer);
      returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setFeedback("");
      setRemaining(AUTO_CLOSE_MS);
      setMode("auto");
    };
    timer = window.setInterval(tryShow, 250);
    tryShow();
    return () => window.clearInterval(timer);
  }, [ready, blocked, mode]);

  useEffect(() => {
    if (mode !== "auto") return;
    const closesAt = Date.now() + AUTO_CLOSE_MS;
    const countdown = window.setInterval(() => setRemaining(Math.max(0, closesAt - Date.now())), 100);
    const close = window.setTimeout(() => dismiss(true), AUTO_CLOSE_MS);
    return () => { window.clearInterval(countdown); window.clearTimeout(close); };
  }, [mode, dismiss]);

  useEffect(() => {
    if (!mode) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss(true);
    };
    document.addEventListener("keydown", onKey);
    const focus = mode === "manual" ? window.requestAnimationFrame(() => closeRef.current?.focus({ preventScroll: true })) : 0;
    return () => { document.removeEventListener("keydown", onKey); window.cancelAnimationFrame(focus); };
  }, [mode, dismiss]);

  async function copyWechat() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText("thanks0");
      setFeedback("已复制，去微信添加 thanks0");
    } catch {
      setFeedback("请长按或选中 thanks0，手动复制");
    }
  }

  if (!mode || blocked) return null;

  return createPortal(
    <section ref={cardRef} className="gear-promo" data-testid="gear-promo" data-mode={mode}
      role={mode === "manual" ? "dialog" : "complementary"} aria-modal={mode === "manual" ? false : undefined}
      aria-labelledby="gear-promo-title" aria-describedby="gear-promo-timing">
      <header className="gear-promo-header">
        <div><span className="gear-promo-kicker">COURTSIDE FINDS <span>广告</span></span><h2 id="gear-promo-title">球友好物</h2></div>
        <button ref={closeRef} className="gear-promo-close" type="button" aria-label="关闭商品推荐" onClick={() => dismiss(true)}><XIcon size={20} aria-hidden="true" /></button>
      </header>
      <div className="gear-promo-products">
        <article><ProductImage src="/assets/promos/wilson-tennis-bag.webp" alt="Wilson 白色网球包" /><div className="gear-promo-product-copy"><h3>Wilson 网球包</h3><p><span>¥</span>860</p></div></article>
        <article><ProductImage src="/assets/promos/wilson-tennis-cap.webp" alt="Wilson 粉色网球帽" /><div className="gear-promo-product-copy"><h3>Wilson 网球帽</h3><p><span>¥</span>300</p></div></article>
      </div>
      <div className="gear-promo-contact">
        <p><MapPinIcon size={14} aria-hidden="true" />深圳南山自提</p>
        <div className="gear-promo-contact-row"><span>联系微信 <strong data-testid="gear-promo-wechat">thanks0</strong></span><button className="gear-promo-copy" type="button" onClick={() => void copyWechat()}>{feedback.startsWith("已复制") ? <CheckIcon size={16} aria-hidden="true" /> : <CopyIcon size={16} aria-hidden="true" />}复制微信号</button></div>
        <p className="gear-promo-feedback" role="status">{feedback}</p>
      </div>
      <footer className="gear-promo-footer"><span id="gear-promo-timing">{mode === "auto" ? `${Math.ceil(remaining / 1_000)} 秒后自动关闭` : "看完点右上角关闭"}</span>{mode === "auto" ? <button type="button" onClick={() => { recordShown(Date.now()); setMode("manual"); }}>慢慢看</button> : <span>更多 · 球友好物可再查看</span>}</footer>
      {mode === "auto" ? <div className="gear-promo-progress" aria-hidden="true"><span /></div> : null}
    </section>, document.body,
  );
}
