import { useEffect, useState } from "react";
import { CheckIcon, CopyIcon, DownloadSimpleIcon, XIcon } from "@phosphor-icons/react";
import { BottomSheet } from "./mobile";
import "./wechat-group.css";

export const WECHAT_ID = "claude89757";
export const WECHAT_QR = "/assets/zacks-wechat-contact.png";

type Props = { open: boolean; onOpenChange: (open: boolean) => void };

export function WeChatGroupSheet({ open, onOpenChange }: Props) {
  const [feedback, setFeedback] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => {
    if (open) { setFeedback(""); setImageFailed(false); }
  }, [open]);

  async function copyWechat() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(WECHAT_ID);
      setFeedback("已复制微信号");
    } catch {
      setFeedback("请长按微信号复制");
    }
  }

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange} title="加入 Zacks 网球群"
      description="添加好友，备注「网球群」，获取场地推送与更多资讯。" snap={0.9}>
      <div className="wechat-group" data-testid="wechat-group">
        <button className="wechat-group-close" type="button" aria-label="关闭入群说明" onClick={() => onOpenChange(false)}><XIcon size={20} aria-hidden="true" /></button>
        {imageFailed ? <p className="wechat-group-error" role="status">二维码暂未加载，请搜索微信号添加。</p> :
          <img className="wechat-group-qr" src={WECHAT_QR} alt="Zacks 的个人微信二维码，添加好友后邀请入群" width={656} height={656} onError={() => setImageFailed(true)} data-scroll-drag="ignore" />}
        <p className="wechat-group-id">微信号 <span data-testid="wechat-id" data-scroll-drag="ignore">{WECHAT_ID}</span></p>
        <div className="wechat-group-actions">
          <button type="button" onClick={() => void copyWechat()}>{feedback === "已复制微信号" ? <CheckIcon size={18} aria-hidden="true" /> : <CopyIcon size={18} aria-hidden="true" />}复制微信号</button>
          {!imageFailed ? <a href={WECHAT_QR} download="Zacks-wechat.png" target="_blank" rel="noopener noreferrer"><DownloadSimpleIcon size={18} aria-hidden="true" />保存二维码</a> : null}
        </div>
        <p className="wechat-group-hint">长按二维码保存，在微信中扫一扫。</p>
        <p className="wechat-group-feedback" role="status" aria-live="polite">{feedback}</p>
      </div>
    </BottomSheet>
  );
}
