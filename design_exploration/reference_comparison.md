# Reference comparison

This comparison evaluates the isolated 1440×900 PySide6 prototype against the
supplied AdsCreativeHouse screenshots and the live website. The reference images
in `reference_comparison.png` are scaled proportionally and are not distorted,
recolored, retouched, or used as product assets.

## Header and navigation

- **Reference pattern:** compact 72 px navigation, small muted links, one strong
  action, neutral hairline, black canvas.
- **Desktop adaptation:** LARP AUDIO and a short statement occupy the left;
  local processing becomes a small dot plus uppercase label; Start over,
  Advanced Settings, and About behave as secondary navigation.
- **Not copied:** logo, centered brand lockup, “Book a call”, glass blur.
- **PySide6 limitation:** no backdrop blur in QSS.
- **Intentional deviation:** product name is left-aligned because a desktop tool
  needs a predictable application anchor rather than symmetric website nav.

## Workflow strip

- **Reference pattern:** oversized and repeating kinetic labels build horizontal
  rhythm.
- **Desktop adaptation:** one static, tracked line—AUDIO / SCRIPT / PROCESS /
  REVIEW—acts as a quiet workflow separator.
- **Not copied:** agency name, slogans, animation, film grain.
- **PySide6 limitation:** smooth mask-faded marquee would require custom painting
  and a timer.
- **Intentional deviation:** static copy avoids distraction and CPU work.

## Audio and script composition

- **Reference pattern:** asymmetric split layouts, large statement paired with
  compact supporting content, few boundaries.
- **Desktop adaptation:** Audio is a narrow 355 px utility surface; Script owns
  the remaining width. Short labels replace competing editorial slogans, while
  the script editor remains the largest input.
- **Not copied:** photographs, video facade, marketing copy.
- **PySide6 limitation:** multiline typography has less line-height control.
- **Intentional deviation:** both input surfaces retain a subtle neutral border
  to preserve drag/drop and focus affordance.

## Pause choices

- **Reference pattern:** numbered operation cards and case indexes; selected
  content uses one red outline/number among neutral peers.
- **Desktop adaptation:** 01 Tight, 02 Balanced, 03 Natural are a compact flat
  horizontal process with top/bottom dividers. Balanced has one red number and
  a two-pixel top marker; the former tinted panel was removed.
- **Not copied:** operation copy or six-card grid.
- **PySide6 limitation:** inactive numbers use dark fill because QSS lacks text
  stroke.
- **Intentional deviation:** no rounded radio cards; the selector reads as one
  editorial sequence.

## Setup and Process

- **Reference pattern:** compact nav proportions and a single dominant red CTA.
- **Desktop adaptation:** model, save folder, readiness, Cancel, and Process are
  one horizontal strip at the natural end of setup. Advanced Settings appears
  only once in the global header.
- **Not copied:** booking language, CTA glow animation.
- **PySide6 limitation:** hover transform/shadow parity would need custom effects.
- **Intentional deviation:** disabled Process is dark red rather than invisible,
  so readiness remains understandable.

## Empty and processing states

- **Reference pattern:** uppercase labels, strong horizontal rhythm, and very
  concise supporting copy.
- **Desktop adaptation:** the empty state uses a quiet Result label. Processing
  uses one title, one current-step line, a thin progress line, and three status
  labels; duplicate stage numbers and counters were removed.
- **Not copied:** marketing metrics or revenue claims.
- **PySide6 limitation:** no smooth CSS reveal/glow animation.
- **Intentional deviation:** progress remains functional and calm, not decorative.

## Preview result

- **Reference pattern:** case-study index plus oversized editorial headline;
  compact red kicker and restrained secondary copy.
- **Desktop adaptation:** left cue indexes pair with a large current-subtitle
  statement, compact timing/CPS/provenance, and a low-profile transport row.
- **Not copied:** case-study claims, photos, stamp copy.
- **PySide6 limitation:** precise outline type may need a custom-painted index.
- **Intentional deviation:** transport controls remain familiar desktop buttons
  because usability is more important than exact website mimicry.

## Result navigation

- **Reference pattern:** compact muted navigation with a strong active state.
- **Desktop adaptation:** PREVIEW / SUBTITLE BLOCKS / DIAGNOSTICS / FILES use
  uppercase tracking and a two-pixel red active underline, without a boxed tab
  pane.
- **Not copied:** site sections or sidebar navigation.
- **PySide6 limitation:** QTabBar padding and font metrics vary by platform.
- **Intentional deviation:** tabs remain native keyboard-navigable widgets.

## Comparison board

`design_exploration/reference_comparison.png` maps four visible patterns:

1. numbered operations → pause/cue stages;
2. case editorial hierarchy → dominant script/current subtitle;
3. metric emphasis → future diagnostics and selected state;
4. combined LARP Audio prototype.

## Approval status

This second exploration pass is intentionally not wired to real services. It
reduces simultaneous labels, nested borders, red surfaces, and duplicate setup
actions without changing the approved direction. Approval should decide whether
this quieter density is ready for production integration. Production integration
has not started.
