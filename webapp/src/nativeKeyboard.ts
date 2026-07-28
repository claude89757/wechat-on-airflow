import { useEffect } from "react";

import { resolveKeyboardViewport } from "./keyboardViewport";

export function isTextEntry(
  element: Element | null,
): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  if (element.matches("textarea, [contenteditable='true']")) return true;
  if (!(element instanceof HTMLInputElement)) return false;

  return ![
    "button",
    "checkbox",
    "color",
    "file",
    "hidden",
    "image",
    "radio",
    "range",
    "reset",
    "submit",
  ].includes(element.type);
}

function keepFocusedFieldVisible() {
  const field = document.activeElement;
  if (!isTextEntry(field)) return;

  const content = field.closest<HTMLElement>(".sheet-content");
  if (!content) return;

  const visualViewport = window.visualViewport;
  const viewportTop = visualViewport?.offsetTop ?? 0;
  const viewportBottom =
    viewportTop + (visualViewport?.height ?? window.innerHeight);
  const fieldRect = field.getBoundingClientRect();
  const contentRect = content.getBoundingClientRect();
  const safeTop = Math.max(viewportTop + 12, contentRect.top + 12);
  const safeBottom = Math.min(viewportBottom - 16, contentRect.bottom - 16);

  if (fieldRect.bottom > safeBottom) {
    content.scrollBy({
      top: fieldRect.bottom - safeBottom + 12,
      behavior: "smooth",
    });
  } else if (fieldRect.top < safeTop) {
    content.scrollBy({
      top: fieldRect.top - safeTop - 12,
      behavior: "smooth",
    });
  }
}

export function useNativeKeyboardViewport() {
  useEffect(() => {
    const root = document.documentElement;
    const visualViewport = window.visualViewport;
    let animationFrame = 0;
    let focusTimer = 0;

    const update = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        const activeElement = document.activeElement;
        const metrics = resolveKeyboardViewport({
          layoutHeight: window.innerHeight,
          visualHeight: visualViewport?.height ?? window.innerHeight,
          visualOffsetTop: visualViewport?.offsetTop ?? 0,
          hasTextFocus: isTextEntry(activeElement),
        });

        root.style.setProperty(
          "--app-visual-viewport-height",
          `${metrics.height}px`,
        );
        root.style.setProperty("--app-keyboard-inset", `${metrics.inset}px`);
        root.dataset.nativeKeyboardOpen = metrics.open ? "true" : "false";

        window.clearTimeout(focusTimer);
        if (isTextEntry(activeElement)) {
          focusTimer = window.setTimeout(keepFocusedFieldVisible, 120);
        }
      });
    };

    window.addEventListener("resize", update);
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", update);
    visualViewport?.addEventListener("resize", update);
    visualViewport?.addEventListener("scroll", update);
    update();

    return () => {
      window.cancelAnimationFrame(animationFrame);
      window.clearTimeout(focusTimer);
      window.removeEventListener("resize", update);
      document.removeEventListener("focusin", update);
      document.removeEventListener("focusout", update);
      visualViewport?.removeEventListener("resize", update);
      visualViewport?.removeEventListener("scroll", update);
      root.style.removeProperty("--app-visual-viewport-height");
      root.style.removeProperty("--app-keyboard-inset");
      delete root.dataset.nativeKeyboardOpen;
    };
  }, []);
}
