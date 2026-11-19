# Operation Dumb Bunny — Project Rules & Web Tracker Standard

## Live Web Tracker UI Requirement: Collapsible Live Gantt Chart

Every web tracker built in this repository (including `tracker/index.html` and any future tracker or template copied from this project) **must** include a collapsible **Live Gantt Chart** panel directly at the **top** of the page (right below the hero header, above the pipeline stages):

- **Collapsible Header Bar**: Expanded by default with a smooth `Collapse` / `Expand` toggle button (with animated chevron icon, state persisted in `localStorage`), displaying live total elapsed time, active parallel lane count, and completed phase count.
- **Time Ruler & Live NOW Cursor**: Adaptive elapsed-time ruler from `started_at` to live current time (`+0m`, `+1m`, `+2m` / `HH:MM:SS` ticks), vertical gridlines, and a glowing vertical **NOW** cursor line with a live timestamp badge.
- **Parallel Agent & Pipeline Stage Timelines**:
  - Dedicated horizontal Gantt swimlane rows for every parallel agent (`agents[]`, displaying agent name + model pill + progress).
  - Compact grouped horizontal rows for every pipeline phase (`pipeline_stages[]`) on the same time axis.
  - Real-time bar positioning from `started_at`, `[HH:MM:SS]` timestamps in `logs` and `events`, `progress`, and `status`: `RUNNING`/`ACTIVE` bars pulse smoothly up to the live NOW cursor; `DONE` bars lock in emerald green with duration labels (e.g. `✓ 1m 42s`); `QUEUED`/`PENDING` render subtle dashed waiting bars.
- **Hover Tooltips**: Show exact start time, duration, model/phase, progress `%`, and current task without flickering on 1s live updates.

Reference implementation: `tracker/index.html` and detailed rule in `.agents/rules/web-tracker-gantt.md`.
