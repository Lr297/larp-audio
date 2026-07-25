# AdsCreativeHouse reference audit

## Scope and sources

The live site at `https://www.adscreativehouse.com/` was accessible on
2026-07-20. The audit used the rendered page, accessibility/DOM structure,
computed styles at a 1280×720 browser viewport, and the site's current public
`/css/style.css`. The screenshots remain the primary visual reference; computed
styles were used to replace guesswork with measurable values.

Seven supplied screenshots were inspected at original resolution:

1. Metrics, compact navigation, founder split composition.
2. “Inside Our Operations” numbered-card grid.
3. Team-count metric cards.
4. “Why brands pick us” comparison with one red focal column.
5. Oversized two-line final CTA statement.
6. Case-study stamp, display heading, and supporting copy.
7. Current LARP Audio production window.

The live sections inspected were navigation, hero/kinetic type, primary CTA,
trusted strip, metrics, founder, cases, operations, portfolio, team metrics,
comparison table, FAQ, booking, and footer.

## Extracted token table

| Token | Live value | Evidence and intended desktop use |
|---|---|---|
| Canvas | `#060606` | Root `--bg`; primary window canvas |
| Panel | `#101010` | Root `--panel`; input/result surface |
| Elevated panel | `#161616` | Root `--panel-2`; hover/secondary surface |
| Divider | `#232323` | Root `--line`; 1 px separators and neutral borders |
| Primary text | `#F2F2F2` | Root `--text`; headings and primary copy |
| Muted text | `#9A9A9A` | Root `--muted`; helper text/navigation |
| Intermediate text | `#CFCFCF` | Founder body copy; secondary high-emphasis text |
| Disabled text | `#555555` | Footer/low-emphasis source; disabled desktop state |
| Primary red | `#FF3F3D` | Root `--red`; CTA, active markers, indexes |
| Dark red | `#B3221F` | Root `--red-dim`; pressed/deep state |
| Red hover | `#FF5A51` | Highlight gradient start; safe hover lift |
| Selection tint | `rgba(255,63,61,.08)` | Derived from stamp background; selected pause/cue fill |
| Focus/glow | `rgba(255,63,61,.35)` | Primary CTA shadow; use sparingly or omit in dense UI |
| Panel radius | `18px` | Root `--radius`; rare input/result surfaces only |
| CTA radius | `12px` | `.btn`; primary desktop action |
| Compact nav CTA radius | `999px` | `.nav-cta`; not used for the primary Process action |

The previous Stage 12.1 colors (`#080506`, `#D94A5D`) are not the live reference
tokens and were therefore not used by the approval prototype.

## Typography

The site declares:

- display: `Archivo Black`, then `Archivo`, sans-serif;
- body: `Inter`, sans-serif;
- signature-only: `Mr De Haviland`.

The public Google Fonts request includes Archivo 500/700, Archivo Black, Inter
400/500/600, and Mr De Haviland. No webfont is downloaded, copied, or bundled in
the prototype.

Measured desktop styles:

| Role | Family | Size / line height | Weight | Tracking |
|---|---|---:|---:|---:|
| Body | Inter | 17 / 27.2 px | 400 | normal |
| Hero H1 | Archivo Black | 54 / 60.48 px | 900 | −0.54 px |
| Section H2 | Archivo Black | 48 / 53.76 px | 900 | −0.48 px |
| Operation H3 | Archivo Black | 19 / 21.28 px | 900 | −0.19 px |
| Navigation | Inter | 15 / 24 px | 600 | +0.6 px |
| Stamp/kicker | Archivo Black | 13 / 20.8 px | display face | +1.3 px |
| Operation body | Inter | 15 / 24 px | 400 | normal |
| Large index | Archivo Black | 46 / 73.6 px | display face | normal |

The character is wide, heavy, blunt, and editorial rather than geometric-SaaS.
Hierarchy comes primarily from display/body contrast, not nested cards.

### System substitutions

The approval environment has `Arial Black`, `Arial`, `Helvetica Neue`, and
`Helvetica`. It does not have Archivo Black or Inter as guaranteed system
families. The prototype therefore uses:

- **Arial Black** for display headings, numbers, kickers, and the primary CTA;
- **Helvetica Neue**, falling back to Helvetica/Arial, for body and controls.

Arial Black is wider and slightly less refined than Archivo Black, but preserves
the reference's heavy, dense counters and short statements. Helvetica Neue is
less neutral than Inter but gives a close x-height, compact secondary text, and
reliable Windows/macOS fallbacks. The website's signature face has no product
UI use and is deliberately omitted.

## Spacing system

The live website uses large section rhythm and a constrained inner width:

- navigation height: 72 px;
- nav max width: 1200 px, 20 px inner padding;
- desktop section padding: 110 px vertical / 24 px horizontal;
- primary inner widths: 1020, 1060, 1120, 1200, and 1240 px;
- operation grid gap: 22 px;
- operation padding: 34×30 px;
- case padding: 48 px and 44 px column gap;
- common micro rhythm: 10, 12, 14, 18, 20, 22, 24, 30, 34, 44 px.

For a 1440×900 desktop tool, the prototype compresses section-scale whitespace
but retains the ratios: 38 px window gutters, 18 px input gap, 12–18 px component
rhythm, 72 px-equivalent compact header, and one dominant script column. This is
an intentional density adaptation, not a direct website viewport copy.

## Button system

The live primary CTA is 63 px high at the measured viewport: 18×44 px padding,
12 px radius, Archivo Black 17 px, `#FF3F3D`, white text, and a red shadow. Hover
moves it upward by 2 px and increases the shadow. The compact navigation CTA is
44 px high with 9×18 px padding, 1 px red outline, and a pill radius.

Desktop adaptation:

- Process: 44–48 px, solid red, display face, 10–12 px radius;
- Upload audio: solid red only in the empty state;
- Replace/Upload script/Advanced: neutral `#232323` outline;
- Start over/Clear/About: borderless muted text actions;
- hover: red text or red border on secondary actions;
- pressed: dark red;
- disabled: deep red surface and muted red text, never a bright outline.

Red is not applied to every border. It identifies the next action, current
workflow state, active cue, or selected pause style.

## Navigation system

The live navigation is a fixed 72 px black/translucent strip with a single
neutral divider. Links are compact, 15 px/600, +0.04 em, muted until hover. The
logo is centered and the CTA is the only outlined-red item.

The desktop header maps this to a left product mark and statement plus right
local-status dot, Start over, Advanced Settings, and About. There is no large
status badge. A single hairline separates it from the static workflow strip.

## Section composition

Reference composition alternates between:

- open canvas with oversized type;
- split editorial layouts;
- flat metric rows divided by hairlines;
- numbered process/case elements;
- occasional panels only where content needs containment;
- one focused red element among neutral peers.

The current LARP screenshot instead gives Audio, Script, Pause, and Setup nearly
equal burgundy-card weight. The prototype changes that hierarchy: the script is
dominant, audio is compact, pause choices are a numbered horizontal process,
setup and Process share one strip, and review is one integrated result section.

## Large-number and label treatment

The reference uses 43–64 px display numbers, often transparent with a thin dark
stroke; selected/important values become solid red. Kicker labels are compact,
uppercase, red, and tracked around 0.1 em. The prototype applies this to:

- `01 / AUDIO`, `02 / SCRIPT`, `03 / SETUP`, `04 / REVIEW`;
- pause options `01`, `02`, `03`;
- processing stage `03 / 07`;
- cue indexes and future diagnostic metrics.

Qt stylesheet text stroke is unavailable, so inactive prototype numbers use a
low-contrast solid `#3C3C3C` fill. Production integration could use a custom
painted label if true outline numbers are approved as essential.

## Border and surface treatment

The site uses `#232323` 1 px borders, mostly on elements that need containment.
Large open sections have no card border. Panels are `#101010`; elevated content
is `#161616`. Radii are usually 18 px, with 24 px reserved for major case cards.

The prototype therefore avoids four equal cards. Audio and Script use only one
input surface each; pauses use top/bottom rules; setup is a horizontal strip;
result is one contained workspace. Internal content is separated by whitespace
and typography rather than more boxes.

## Red accent usage

Reference red is punctuation:

- a 3 px progress line;
- one CTA;
- one metric or selected column;
- a stamp/kicker;
- active/hover outline;
- selected process number;
- short glow around high-value emphasis.

The prototype mirrors that scarcity. Red does not tint the whole window or every
card. Balanced, Process, current stage, current cue, local dot, and kickers are
the primary red moments.

## Patterns transferred to the desktop tool

- compact editorial header and neutral navigation;
- static workflow strip instead of a CPU-consuming marquee;
- strong script statement plus compact helper copy;
- numbered pause-style process;
- integrated setup/readiness/CTA strip;
- uppercase result navigation with an active red underline;
- large current-subtitle statement and cue indexes;
- future large diagnostic metrics;
- neutral hairlines instead of heavy grids;
- one red focal state at a time.

## Patterns deliberately not copied

- AdsCreativeHouse name, logo, copy, client logos, photographs, videos, case
  assets, illustrations, or marketing claims;
- autoplay video, large landing-page hero, booking CTA, portfolio, testimonials,
  comparison marketing table, FAQ, and footer;
- animated film grain, infinite marquee, glow breathing, sticky case stack,
  hover elevation, and decorative signature;
- 110 px section gaps that would reduce desktop tool efficiency.

## PySide6 limitations

- QSS has no CSS `backdrop-filter`, `clamp()`, text stroke, masking, or comparable
  web typography control.
- QSS letter spacing and multiline line-height are less precise than browser CSS.
- Platform/native file dialogs cannot be made identical to the custom surface
  without sacrificing native behavior.
- Exact font metrics vary between Windows and macOS.
- CSS shadows/transforms and animated gradients require custom painting or
  animations; the prototype avoids them rather than faking web motion.
- Static workflow text is preferable to a timer-driven marquee in a local tool.

## Proposed LARP Audio component mapping

| Reference pattern | LARP component |
|---|---|
| Compact nav | Product header, local status, Start over, Advanced, About |
| Kinetic/marquee type | Static workflow strip: Audio / Script / Process / Review |
| Split founder/case composition | Compact Audio input + dominant Script editor |
| Numbered operations | Tight / Balanced / Natural selector |
| Primary CTA | Process at the end of the setup/readiness strip |
| Large metrics | Diagnostics overview |
| Case indexes | Subtitle cue indexes |
| Navigation underline | Result tabs |
| Editorial statement | Current subtitle display |
| Comparison focal column | Single selected pause/cue state |
| FAQ hairlines | Files and diagnostic section rows |

## Approval and production boundary

The four PNGs under `design_exploration/` remain the isolated real-PySide6
approval prototype. The user approved its quieter second iteration on
2026-07-20. Production integration reuses the audited tokens and composition in
`gui/design/` and `production_workspace.py`; controller, workers, processing
services, audio/STT/alignment/subtitle algorithms, and persisted output schemas
remain unchanged.
