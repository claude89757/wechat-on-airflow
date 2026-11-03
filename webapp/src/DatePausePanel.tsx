import { ArrowLeftIcon, ArrowClockwiseIcon, CalendarBlankIcon, CheckIcon, XIcon } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiRequestError,
  getNotificationPauses,
  updateNotificationPauses,
  type NotificationPauseAction,
  type NotificationPauses,
  type VerificationReceipt,
} from "./api";
import { KeyboardInput, useKeyboard } from "./mobile";
import "./date-pause.css";

export function isPauseDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function addDays(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function formatPauseDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "long", day: "numeric", weekday: "short", timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

type Props = {
  receipt: VerificationReceipt | null;
  view: "summary" | "select";
  selectedDates: string[];
  onSelectionChange: (dates: string[]) => void;
  onSelect: () => void;
  onBack: () => void;
  onClose: () => void;
  onVerify: () => void;
  onUnauthorized: () => void;
  onChangeEmail: () => void;
  onChanged: () => void;
};

type Notice = {
  message: string;
  undoAction?: NotificationPauseAction;
  undoDates?: string[];
};

function checkedSnapshot(value: NotificationPauses): NotificationPauses {
  if (!isPauseDate(value.today) || value.timezone !== "Asia/Shanghai"
    || !Array.isArray(value.pausedDates) || !value.pausedDates.every(isPauseDate)) {
    throw new Error("未能读取最新暂停日期，请重试。");
  }
  return { ...value, pausedDates: [...new Set(value.pausedDates)].filter(date => date >= value.today).sort() };
}

export function DatePausePanel(props: Props) {
  const { receipt, view, selectedDates, onSelectionChange } = props;
  const keyboard = useKeyboard();
  const [snapshot, setSnapshot] = useState<NotificationPauses | null>(null);
  const [loading, setLoading] = useState(Boolean(receipt));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customDate, setCustomDate] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const mounted = useRef(true);
  const reading = useRef(0);
  const writing = useRef(false);
  const latest = useRef(props);
  latest.current = props;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; reading.current += 1; };
  }, []);

  const reload = useCallback(async (signal?: AbortSignal) => {
    if (!receipt) return;
    const version = ++reading.current;
    setLoading(true);
    setError("");
    try {
      const next = checkedSnapshot(await getNotificationPauses(receipt, signal));
      if (!mounted.current || version !== reading.current) return;
      setSnapshot(next);
      const previous = latest.current.selectedDates;
      const available = previous.filter(date => isPauseDate(date) && date >= next.today && date <= addDays(next.today, 365));
      if (available.length !== previous.length) {
        latest.current.onSelectionChange(available);
        setSelectionError("部分日期已过去或超出未来一年，请重新选择打球日期。");
      }
    } catch (reason) {
      if (!mounted.current || version !== reading.current || signal?.aborted) return;
      if (reason instanceof ApiRequestError && reason.status === 401) {
        latest.current.onUnauthorized();
      } else {
        setError(reason instanceof Error ? reason.message : "暂停日期读取失败，请重试。");
      }
    } finally {
      if (mounted.current && version === reading.current) setLoading(false);
    }
  }, [receipt?.token]);

  useEffect(() => {
    const controller = new AbortController();
    void reload(controller.signal);
    return () => controller.abort();
  }, [reload, view]);

  const pausedDates = snapshot?.pausedDates ?? [];
  const today = snapshot?.today;
  const maximumDate = today ? addDays(today, 365) : undefined;
  const days = today ? Array.from({ length: 14 }, (_, index) => addDays(today, index)) : [];
  const newDates = selectedDates.filter(date => !pausedDates.includes(date));
  const unavailable = loading || busy || !snapshot || Boolean(error);

  const chooseDate = (date: string) => {
    setSelectionError("");
    if (selectedDates.includes(date)) {
      onSelectionChange(selectedDates.filter(item => item !== date));
    } else if (selectedDates.length >= 31) {
      setSelectionError("一次最多选择 31 个打球日期，请分次设置。");
    } else {
      onSelectionChange([...selectedDates, date].sort());
    }
  };

  const addCustomDate = () => {
    keyboard.hide();
    if (!today || !maximumDate || !isPauseDate(customDate) || customDate < today || customDate > maximumDate) {
      setSelectionError("请选择今天起未来一年内的打球日期。");
      return;
    }
    if (pausedDates.includes(customDate)) {
      setSelectionError("这个日期已经暂停，可在“我的订阅”中恢复提醒。");
      return;
    }
    if (!selectedDates.includes(customDate)) chooseDate(customDate);
    setCustomDate("");
  };

  const mutate = async (action: NotificationPauseAction, dates: string[], undo = false) => {
    if (!receipt || writing.current || !dates.length) return;
    writing.current = true;
    setBusy(true);
    setError("");
    setSelectionError("");
    keyboard.hide();
    try {
      const result = await updateNotificationPauses(receipt, action, dates);
      const next = checkedSnapshot(result);
      if (!Array.isArray(result.changedDates) || !result.changedDates.every(isPauseDate)) {
        throw new Error("未能确认操作结果，请刷新日期后查看。");
      }
      if (!mounted.current) return;
      // A read started before this write completed must not replace the confirmed state.
      reading.current += 1;
      setLoading(false);
      setSnapshot(next);
      const changed = [...new Set(result.changedDates)].filter(date => dates.includes(date));
      const label = changed.length === 1 ? formatPauseDate(changed[0]) : `${changed.length} 个打球日期`;
      setNotice({
        message: undo ? "已撤销刚才的操作。" : changed.length
          ? action === "pause" ? `已暂停 ${label}的提醒，其他日期照常。` : `已恢复 ${label}的提醒。`
          : action === "pause" ? "所选日期已经暂停。" : "所选日期已经恢复提醒。",
        ...(!undo && changed.length ? {
          undoAction: action === "pause" ? "resume" as const : "pause" as const,
          undoDates: changed,
        } : {}),
      });
      latest.current.onChanged();
      if (action === "pause" && !undo && latest.current.view === "select") {
        latest.current.onSelectionChange([]);
        latest.current.onBack();
      }
    } catch (reason) {
      if (!mounted.current) return;
      if (reason instanceof ApiRequestError && reason.status === 401) latest.current.onUnauthorized();
      else setError(reason instanceof Error ? reason.message : "操作未完成，请重试。");
    } finally {
      writing.current = false;
      if (mounted.current) setBusy(false);
    }
  };

  return (
    <section className="date-pause-panel" data-testid="date-pause-panel" aria-busy={loading || busy}>
      <div className="date-pause-navigation">
        {view === "select" ? <button type="button" className="date-pause-back" onClick={props.onBack} disabled={busy}><ArrowLeftIcon size={18} />我的订阅</button>
          : <span className="date-pause-eyebrow">按日期管理提醒</span>}
        <button type="button" className="date-pause-close" aria-label="关闭订阅管理" onClick={props.onClose} disabled={busy}><XIcon size={19} /></button>
      </div>
      {receipt ? <div className="date-pause-identity"><span>当前邮箱 <strong>{receipt.maskedEmail}</strong></span><button type="button" onClick={props.onChangeEmail} disabled={busy}>更换</button></div> : null}
      {notice ? <div className="date-pause-notice" role="status"><span>{notice.message}</span>{notice.undoAction && notice.undoDates?.length ? <button type="button" disabled={busy || loading} onClick={() => void mutate(notice.undoAction!, notice.undoDates!, true)}>撤销</button> : null}</div> : null}

      {view === "summary" ? <>
        <div className="date-pause-intro">
          <CalendarBlankIcon size={28} weight="duotone" aria-hidden="true" />
          <div><h3>已经订到场地？</h3><p>暂停指定打球日期的提醒，其他日期照常。</p></div>
        </div>
        <button className="date-pause-primary" type="button" disabled={Boolean(receipt) && unavailable} onClick={receipt ? props.onSelect : props.onVerify}>
          {receipt ? "选择暂停日期" : "验证邮箱并管理提醒"}
        </button>
        {receipt ? <>
          <div className="date-pause-list-heading"><h4>已暂停日期 <span>{snapshot ? pausedDates.length : "—"}</span></h4><button type="button" onClick={() => void reload()} disabled={busy || loading} aria-label="刷新暂停日期"><ArrowClockwiseIcon size={16} />刷新</button></div>
          {loading ? <p className="date-pause-muted" role="status">正在读取最新日期…</p> : null}
          {snapshot && !loading && !pausedDates.length ? <p className="date-pause-muted">还没有暂停的日期，继续按原订阅提醒。</p> : null}
          {pausedDates.length ? <ul className="date-pause-list">{pausedDates.map(date => <li key={date} data-pause-date={date}>
            <div><strong>{formatPauseDate(date)}</strong><span>全部场馆 · 当天不提醒</span></div>
            <button type="button" disabled={unavailable} aria-label={`恢复 ${formatPauseDate(date)} 的提醒`} onClick={() => void mutate("resume", [date])}>恢复提醒</button>
          </li>)}</ul> : null}
          <p className="date-pause-footnote">恢复后按正常巡检规则提醒，不补发暂停期间的旧邮件。设置随邮箱同步。</p>
        </> : null}
      </> : <>
        <p className="date-pause-explanation">选择你已经有场地的<strong>打球日期</strong>，暂停该邮箱当天全部场馆、全部时段的邮件提醒。</p>
        <p className="date-pause-muted">以深圳时间（UTC+8）为准。其他日期照常，原订阅保留。</p>
        {loading ? <p className="date-pause-muted" role="status">正在读取最新日期…</p> : null}
        {snapshot ? <>
          <div className="date-pause-days" role="group" aria-label="未来 14 天打球日期">
            {days.map((date, index) => {
              const paused = pausedDates.includes(date);
              const selected = selectedDates.includes(date);
              const weekday = new Intl.DateTimeFormat("zh-CN", { weekday: "short", timeZone: "UTC" }).format(new Date(`${date}T00:00:00Z`));
              return <button key={date} type="button" data-date={date} aria-label={`${formatPauseDate(date)}${paused ? "，已暂停" : ""}`} aria-pressed={selected || paused} disabled={unavailable || paused} className={`date-pause-day ${selected ? "selected" : ""} ${paused ? "paused" : ""}`} onClick={() => chooseDate(date)}>
                <span>{index === 0 ? "今天" : index === 1 ? "明天" : weekday}</span><strong>{Number(date.slice(5, 7))}/{Number(date.slice(8))}</strong><small>{paused ? "已暂停" : selected ? <CheckIcon size={13} weight="bold" /> : "可选择"}</small>
              </button>;
            })}
          </div>
          <div className="date-pause-other"><label className="field"><span>其他打球日期</span><KeyboardInput type="date" value={customDate} min={today} max={maximumDate} disabled={unavailable} onChange={event => { setCustomDate(event.target.value); setSelectionError(""); }} /></label><button type="button" disabled={unavailable || !customDate} onClick={addCustomDate}>添加日期</button></div>
          {selectedDates.length ? <div className="date-pause-selection" aria-label="已选打球日期"><strong>已选 {selectedDates.length} 天</strong><ul>{selectedDates.map(date => <li key={date}><span>{formatPauseDate(date)}{pausedDates.includes(date) ? " · 已暂停" : ""}</span><button type="button" aria-label={`移除 ${formatPauseDate(date)}`} disabled={busy} onClick={() => onSelectionChange(selectedDates.filter(item => item !== date))}><XIcon size={15} /></button></li>)}</ul></div> : null}
          {selectionError ? <p className="form-error" role="alert">{selectionError}</p> : null}
          <div className="date-pause-confirm"><button className="date-pause-primary" type="button" disabled={unavailable || !newDates.length} onClick={() => void mutate("pause", newDates)}>{busy ? "正在保存…" : selectedDates.length && !newDates.length ? "所选日期已暂停" : newDates.length ? `暂停这 ${newDates.length} 天的提醒` : "请选择打球日期"}</button><p>点击按钮后生效。可以随时在“我的订阅”恢复。</p></div>
        </> : null}
      </>}
      {error ? <div className="date-pause-error"><p className="form-error" role="alert">{error}</p><button type="button" onClick={() => void reload()} disabled={busy || loading}>重新读取日期</button></div> : null}
    </section>
  );
}
