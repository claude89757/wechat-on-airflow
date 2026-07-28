# Design QA

## Evidence

- Source visual truth:
  `/Users/claude89757/.codex/generated_images/019f23e2-004c-7ad1-95da-89f91af664b8/call_O6d4HI0zEZasqx1VwEj1OmDc.png`
- Source pixels: `853 x 1844`
- Normalized source:
  `qa/source-option-2-393x852.png`
- Browser-rendered implementation:
  `qa/implementation-home-393x852.png`
- Full-view combined comparison:
  `qa/comparison-home.png`
- Focused create-card comparison:
  `qa/comparison-create-card.png`
- Browser viewport: `1400 x 1200` CSS px
- App screen: `393 x 852` CSS px
- Implementation pixels: `393 x 852`
- Device scale factor: `1`
- State: mobile home, first visit, unverified email, light theme
- Runtime integrity: `npm run check:runtime` passed

The source was normalized to the app screen dimensions before comparison. The
implementation screenshot is a content-screen crop from a browser-rendered
`[data-testid="device-screen"]` measured at exactly `393 x 852` CSS px.

## Full-View Comparison

The implementation preserves the selected option's hierarchy: brand and live
status, three service metrics, one standalone create-subscription card, compact
venue health rows, and a subscriptions entry below the list. Teal, blue, green,
white, and pale-cyan tokens align with the source. The mobile runtime owns the
status bar and home indicator, so the subscriptions entry falls below the
initial fold; it remains reachable by the screen's native vertical scroll.

The source depicts a previously verified email while the implementation
capture depicts the required first-visit state. This is an intentional state
difference, not missing functionality. Both states use the same identity row
and card geometry.

## Focused Comparison

The focused create-card comparison verifies the Lulu asset, title hierarchy,
venue/time/duration affordances, identity state, border, and primary action at
readable scale. Lulu uses the supplied Petdex sprite rather than a CSS or SVG
approximation. The implementation intentionally says “系统才会发邮件” instead
of exposing Airflow as a user-facing concept.

## Fidelity Surfaces

- Fonts and typography: Roboto with PingFang SC and Microsoft YaHei fallbacks
  closely matches the source's neutral mobile sans serif. Weights, line
  heights, wrapping, and zero letter spacing preserve the hierarchy.
- Spacing and layout rhythm: 8px-or-less radii, metric separators, card
  padding, and 54px venue rows reproduce the source density without overlap.
- Colors and tokens: teal actions, blue mail status, green health status,
  lime brand mark, white canvas, and pale-cyan surfaces match the reference
  balance. No decorative gradients were introduced.
- Image quality and assets: the animated Lulu raster sprite is sharp at its
  rendered size. Phosphor icons replace generic repeated symbols with
  venue-specific, semantically recognizable icons.
- Copy and content: the implementation keeps copy shorter than the mock,
  removes backend terminology from the primary card, and never displays
  available time slots.

## Interaction And Browser Checks

- Opened the standalone create-subscription sheet.
- Entered a valid-format email and confirmed the send-code action enabled.
- Confirmed an unavailable local API produces an inline error without layout
  breakage.
- Opened and dismissed the help sheet.
- Verified the home screen is vertically scrollable and the compact venue rows
  remain aligned.
- Checked browser warning and error logs: none.

## Comparison History

### Iteration 1

- P2: venue rows were 66px high, so almost two fewer venue statuses appeared
  above the fold than in the source.
- P2: all venues reused a tennis-ball icon, reducing scanability compared with
  the source's distinct venue symbols.
- Fixes: reduced rows to 54px, tightened card and identity controls, and added
  Waves, Tennis Ball, Buildings, Court, and Apartment icons by venue.
- Post-fix evidence: `qa/comparison-home.png` shows all five venue rows
  represented in the viewport with consistent columns and no text overlap.

### Final Pass

No actionable P0, P1, or P2 differences remain. The protected mobile runtime's
device chrome and the first-visit identity state are expected deviations.

## Follow-Up Polish

- P3: capture a second evidence state after a real production email
  verification to document the verified identity row.

final result: passed
