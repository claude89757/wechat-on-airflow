const MENU_TRIGGER_SELECTOR = '[aria-haspopup="menu"]';
const CUSTOM_SCROLL_SELECTOR = ".mobile-scroll";

/**
 * Radix opens dropdown menus on pointer-down. The custom MobileScroll surface
 * also starts a drag session on that same pointer-down, so moving toward the
 * newly opened menu can pull the page into its rubber-band state. Mark menu
 * triggers before React's bubble handlers run so MobileScroll ignores the
 * gesture while Radix still receives it normally.
 */
export function markMenuTriggerAsScrollDragIgnored(event: PointerEvent): void {
  if (!(event.target instanceof Element)) return;

  const trigger = event.target.closest<HTMLElement>(MENU_TRIGGER_SELECTOR);
  if (!trigger || !trigger.closest(CUSTOM_SCROLL_SELECTOR)) return;

  trigger.dataset.scrollDrag = "ignore";
}

document.addEventListener("pointerdown", markMenuTriggerAsScrollDragIgnored, {
  capture: true,
  passive: true,
});
