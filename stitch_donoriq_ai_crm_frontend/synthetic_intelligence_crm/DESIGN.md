---
name: Synthetic Intelligence CRM
colors:
  surface: '#111319'
  surface-dim: '#111319'
  surface-bright: '#373940'
  surface-container-lowest: '#0c0e14'
  surface-container-low: '#191b22'
  surface-container: '#1e1f26'
  surface-container-high: '#282a30'
  surface-container-highest: '#33343b'
  on-surface: '#e2e2eb'
  on-surface-variant: '#c7c4d7'
  inverse-surface: '#e2e2eb'
  inverse-on-surface: '#2e3037'
  outline: '#908fa0'
  outline-variant: '#464554'
  surface-tint: '#c0c1ff'
  primary: '#c0c1ff'
  on-primary: '#1000a9'
  primary-container: '#8083ff'
  on-primary-container: '#0d0096'
  inverse-primary: '#494bd6'
  secondary: '#d0bcff'
  on-secondary: '#3c0091'
  secondary-container: '#571bc1'
  on-secondary-container: '#c4abff'
  tertiary: '#ffb783'
  on-tertiary: '#4f2500'
  tertiary-container: '#d97721'
  on-tertiary-container: '#452000'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e1e0ff'
  primary-fixed-dim: '#c0c1ff'
  on-primary-fixed: '#07006c'
  on-primary-fixed-variant: '#2f2ebe'
  secondary-fixed: '#e9ddff'
  secondary-fixed-dim: '#d0bcff'
  on-secondary-fixed: '#23005c'
  on-secondary-fixed-variant: '#5516be'
  tertiary-fixed: '#ffdcc5'
  tertiary-fixed-dim: '#ffb783'
  on-tertiary-fixed: '#301400'
  on-tertiary-fixed-variant: '#703700'
  background: '#111319'
  on-background: '#e2e2eb'
  surface-variant: '#33343b'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  container-max: 1440px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style

This design system is built for a high-performance AI CRM environment. It prioritizes a **Premium Dark-Mode** aesthetic that feels sophisticated, analytical, and fast. The design narrative centers on "The Intelligence Layer"—a UI that feels like a HUD (Heads-Up Display) for donor researchers.

The style leverages **Glassmorphism** and **SaaS Minimalism**. Interfaces use semi-transparent surfaces, subtle backdrops, and high-fidelity gradients to create a sense of depth without visual clutter. The emotional response should be one of confidence and precision, similar to the experience of using industry-leading developer tools.

Key visual principles:
- **Luminosity:** Elements "glow" subtly against deep backgrounds.
- **Precision:** Tight alignment and thin, 1px borders.
- **Fluidity:** Soft transitions and micro-animations for data updates.

## Colors

The palette is anchored in a deep slate-navy (#0F1117) to provide maximum contrast for AI-generated insights. 

**Core Palette:**
- **Primary Indigo:** Used for main actions, active states, and focus indicators.
- **Secondary Violet:** Reserved for high-value "Tier-A" prospects and premium AI features.
- **Surface Layer:** Cards and containers use #1A1D2E with a subtle 1px border (#2E3245).

**Status & Scoring Logic:**
- **Dynamic Pulses:** The "Researching" status utilizes a CSS-driven yellow pulse animation to indicate active background processing.
- **Score Tiers:** Colors transition from warm (Red/Yellow) to cool/premium (Teal/Indigo) as lead quality increases. Tier-A prospects feature a subtle violet-to-indigo gradient background with a 10% opacity "sparkle" texture overlay.

## Typography

The system uses **Inter** exclusively to maintain a clean, systematic feel. It relies on varying weights and tight letter spacing for large headers to create an editorial SaaS look.

- **Display & Headlines:** Use semi-bold or bold weights with negative letter-spacing to feel "compact" and engineered.
- **Labels:** Small caps or all-caps are used for metadata, donor IDs, and table headers to distinguish them from editable content.
- **Numeric Data:** For scores and financial amounts, use medium weights to ensure high legibility against dark backgrounds.

## Layout & Spacing

The layout uses a **12-column fluid grid** for the main dashboard content, while maintaining a fixed-width (280px) collapsible sidebar for navigation.

- **Grid:** 24px gutters provide ample "air" between complex data widgets.
- **Safe Zones:** Content is inset by 48px on large displays to maintain focus.
- **Data Density:** While the overall style is spacious, data tables use a "Compact" mode with 8px vertical padding to allow for viewing many donor leads simultaneously.
- **Responsiveness:** On mobile, the 12-column grid collapses to a single column, and horizontal padding reduces to 16px. Glass cards switch from horizontal to vertical stacks.

## Elevation & Depth

Depth is achieved through **Tonal Layering** and **Backdrop Blurs** rather than traditional heavy shadows.

- **Level 0 (Base):** #0F1117 background.
- **Level 1 (Cards):** #1A1D2E with a 1px solid border (#2E3245).
- **Level 2 (Modals/Popovers):** Semi-transparent indigo tint (#1A1D2E with 80% opacity) and a 12px backdrop-blur filter. 
- **Shadows:** Use a single, highly diffused "Ambient Glow" for active elements. Instead of black, use a low-opacity indigo shadow: `0px 20px 40px rgba(99, 102, 241, 0.1)`.
- **Active State:** Elements in focus should have a subtle inner-glow (1px stroke) to simulate light hitting the edge of a glass pane.

## Shapes

The design system uses a **Rounded** shape language to soften the "technical" feel of the dark UI.

- **Standard Elements:** Buttons, inputs, and small cards use 0.5rem (8px) corner radius.
- **Large Containers:** Main dashboard widgets and sections use 1rem (16px) for a modern, nested appearance.
- **Progress Rings:** Scores are represented by 100% circular strokes.
- **Status Pills:** Fully rounded (pill-shaped) for high-contrast visibility within tables.

## Components

### Buttons & Inputs
- **Primary Action:** Indigo-to-Violet horizontal gradient with white text.
- **Secondary Action:** Ghost style with 1px border (#2E3245) and hover state brightness increase.
- **Inputs:** Darker background than cards (#0F1117), clear focus ring in Primary Indigo.

### Glass Cards
- Cards must use `backdrop-filter: blur(10px)`.
- Borders should be 1px wide, using a linear gradient from top-left (#4F5269) to bottom-right (transparent).

### Data Visualization
- **Circular Progress Rings:** Use a 4px stroke width. The track should be a low-opacity version of the score color (e.g., 10% opacity Teal), and the progress bar should be the solid score color with a 2px outer glow.
- **Status Badges:** Include a small 6px dot to the left of the text. For "Researching," the dot should pulse via an opacity animation (0.4 to 1.0).

### Navigation
- **Tabbed Navigation:** Underline style for active tabs using the Primary Indigo color, with a subtle vertical gradient extending 8px upward to indicate the active section.
- **Animated Transition:** Tabs and card hover states should use a 200ms `cubic-bezier(0.4, 0, 0.2, 1)` transition for all color and transform changes.