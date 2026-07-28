import { describe, expect, it } from "vitest";

import { resolveKeyboardViewport } from "../src/keyboardViewport";

describe("native keyboard viewport", () => {
  it("moves a focused sheet above an overlay keyboard", () => {
    expect(
      resolveKeyboardViewport({
        layoutHeight: 852,
        visualHeight: 512,
        visualOffsetTop: 0,
        hasTextFocus: true,
      }),
    ).toEqual({
      height: 512,
      inset: 340,
      open: true,
    });
  });

  it("uses a resized viewport without adding a second keyboard inset", () => {
    expect(
      resolveKeyboardViewport({
        layoutHeight: 512,
        visualHeight: 512,
        visualOffsetTop: 0,
        hasTextFocus: true,
      }),
    ).toEqual({
      height: 512,
      inset: 0,
      open: false,
    });
  });

  it("ignores browser chrome changes when no text field is focused", () => {
    expect(
      resolveKeyboardViewport({
        layoutHeight: 852,
        visualHeight: 760,
        visualOffsetTop: 0,
        hasTextFocus: false,
      }),
    ).toEqual({
      height: 760,
      inset: 0,
      open: false,
    });
  });
});
