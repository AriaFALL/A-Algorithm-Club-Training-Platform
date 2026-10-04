---
name: Pulse Atlas 算法社团训练台
description: 把每周训练材料、审核状态和团队反馈组织成清晰而有活力的训练节拍。
colors:
  primary: "#2468e8"
  ink: "#162d50"
  canvas: "#f5f8fc"
  mint: "#eaf2ff"
  coral: "#e87566"
  lemon: "#f3c94f"
  blue: "#478ff0"
typography:
  display: {fontFamily: "Aptos, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif", fontSize: "clamp(29px, 3vw, 42px)", fontWeight: 750, lineHeight: 1.08, letterSpacing: "-0.025em"}
  body: {fontFamily: "Aptos, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif", fontSize: "14px", fontWeight: 400, lineHeight: 1.5, letterSpacing: "0"}
rounded:
  sm: "10px"
  md: "15px"
  lg: "18px"
spacing:
  unit: "4px"

# Design System: Pulse Atlas

## Overview

**Creative North Star: "Pulse Atlas"**

Pulse Atlas treats weekly training as a living rhythm. A cool near-white canvas gives the content room to breathe, while navy ink and cobalt action color make the task hierarchy easy to scan. The interface uses sky-blue surfaces, coral deadlines, lemon highlights and blue future states to make progress readable without turning the platform into a game costume.

The signature pattern is a weekly training atlas: a dark, soft-corner stage makes the current score and next action memorable, while a clickable week pulse keeps completed, current and upcoming weeks on one connected line. Floating status cards echo the supplied editorial product references without importing unrelated travel or real-estate imagery. The entrance surfaces use the same palette and rounded geometry, while the authenticated workbench keeps visual expression subordinate to the next useful action.

**Key Characteristics:**
- Light, high-contrast canvas with fresh accent colors.
- Weekly rhythm as the recurring navigation motif.
- One large training stage instead of a wall of equal metric cards.
- Action-first hierarchy for high-frequency training work.
- Soft depth through tonal layering and restrained shadows.

## Colors

The palette uses navy ink and cobalt blue as the anchor, with brighter colors reserved for state, progress and action.

### Primary
- **Cobalt Training Blue** (#2468e8): Primary action, active navigation and completion signals.

### Secondary
- **Coral Deadline** (#e87566): Current week and attention states.
- **Lemon Milestone** (#f3c94f): Pending review and achievement accents.
- **Sky Future Blue** (#478ff0): Upcoming weeks and secondary data cues.

### Neutral
- **Navy Ink** (#162d50): Headlines, navigation and key data.
- **Quiet Slate** (#657790): Supporting copy and metadata.
- **Sky Paper** (#eaf2ff): Progress surfaces and selected states.
- **Cool Canvas** (#f5f8fc): Page background.

**The State Color Rule.** Bright colors communicate a real training state; they do not decorate inactive content.

## Typography

**Display Font:** Aptos / Segoe UI (with Chinese system sans fallback)
**Body Font:** Aptos / Segoe UI (with Chinese system sans fallback)

**Character:** A compact, modern sans system with strong dark headlines and quieter metadata. Headings carry the page voice; labels support scanning without competing with the task.

### Hierarchy
- **Display** (750, clamp 29px to 42px, 1.08): First viewport task statement and page titles.
- **Title** (700, 17px to 22px, 1.2): Panel and modal headings.
- **Body** (400, 14px, 1.5): Forms, explanatory copy and longer content.
- **Label** (700, 9px to 11px, tracked): Navigation context and state metadata.

## Layout

The workbench uses a fixed navigation rail with a fluid content column. The dashboard starts with the current task, then the week pulse, then supporting metrics and team feedback. Content-heavy views use open editorial columns and dividers instead of repeating enclosed cards: the showcase reads left-to-right across member entries, while the directory uses a two-column information flow. At mobile widths, the rail becomes an icon strip and every content region collapses into one readable column.

## Elevation & Depth

Surfaces are mostly flat with fine blue-gray dividers. A soft ambient shadow appears only on the pulse surface, modals and focused hover states. Content rows stay visually open so containers do not compete with the training material.

## Shapes

Controls and content surfaces use gently rounded corners from 10px to 18px. The week pulse uses circular markers connected by a thin line; no decorative gradients or hard offset shadows are used.

## Components

### Buttons
- **Primary:** Cobalt Training Blue, white text, 10px radius, lifts slightly on hover.
- **Secondary:** White surface with sky-blue border, navy ink text.
- **Focus:** A visible cobalt outline with a 3px offset.

### Cards / Containers
- **Surface:** White or sky-paper only where a task needs a clear boundary; content collections use the canvas with dividers.
- **Corner style:** 10px to 18px for task surfaces; open rows do not use container rounding.
- **Shadow:** Ambient only on the signature pulse, dialogs and focused hover states.

### Navigation

The active item is a quiet text state with a small cobalt marker, keeping the rail light and editorial. Inactive items use slate ink and a slight horizontal movement on hover. Mobile reduces the rail to familiar icon targets while preserving the active marker.

### Week Pulse

The signature component connects four weeks on one track. Completed weeks use teal, the current week uses coral, upcoming weeks use blue, and selecting any week reveals a concise focus and action link.

## Do's and Don'ts

### Do:
- **Do** make the next training action visible before secondary data.
- **Do** use color to explain completion, pending review, deadlines and future states.
- **Do** preserve readable Chinese text and full-width touch targets on mobile.

### Don't:
- **Don't** hide the submission action behind a decorative hero.
- **Don't** use bright accents without a real status meaning.
- **Don't** change backend behavior or invent data claims in the visual layer.
