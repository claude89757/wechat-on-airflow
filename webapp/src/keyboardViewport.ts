export type KeyboardViewportInput = {
  layoutHeight: number;
  visualHeight: number;
  visualOffsetTop: number;
  hasTextFocus: boolean;
};

export type KeyboardViewportMetrics = {
  height: number;
  inset: number;
  open: boolean;
};

const KEYBOARD_INSET_THRESHOLD = 80;

export function resolveKeyboardViewport({
  layoutHeight,
  visualHeight,
  visualOffsetTop,
  hasTextFocus,
}: KeyboardViewportInput): KeyboardViewportMetrics {
  const height = Math.max(1, Math.min(layoutHeight, visualHeight));
  const obscuredHeight = Math.max(
    0,
    layoutHeight - visualOffsetTop - visualHeight,
  );
  const open = hasTextFocus && obscuredHeight >= KEYBOARD_INSET_THRESHOLD;

  return {
    height,
    inset: open ? obscuredHeight : 0,
    open,
  };
}
