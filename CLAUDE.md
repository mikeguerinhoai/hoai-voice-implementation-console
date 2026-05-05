# Implementation Console

Onboarding pipeline dashboard with editable HTML + JSON-file-on-disk storage.

## Architecture

**Canonical data source**: `data.json` on disk (sibling of `latest.html` in OneDrive).

```
OneDrive/.../Voice/Implementation Console/
  ├─ latest.html     (template, ~45 KB, no embedded data)
  ├─ data.json        (customer data, ~26 KB, editable)
  └─ snapshots/       (timestamped HTML + JSON pairs)
```

- HTML loads `data.json` via `fetch('./data.json')` on page load
- Edits save back to `data.json` via File System Access API
- Serve via HTTP: `npx serve` or OneDrive local server. `file://` fallback uses "Load Data" picker.

## Pipeline

### Default (no Notion)
```bash
npm run onboarding-console          # Copy template + data.json to OneDrive
npm run implementation              # Run trigger engine against local data
```

### Notion sync (opt-in)
```bash
npm run onboarding-console:notion   # Fetch from Notion + generate (overwrites local edits)
npm run implementation:notion       # Full: fetch + triggers + write-back to Notion
```

### Dashboard usage
```bash
npx serve "OneDrive - Vantaca, LLC/HOAi - Documents/Voice/Implementation Console"
# Open http://localhost:3000/latest.html
# Edit customer -> Save -> data.json updated
# "+" button to add new customers
```

## Key Files

| File | Purpose |
|------|---------|
| `onboarding-template.html` | Self-contained dashboard (Chart.js, editable detail overlay, Gantt, budget timeline) |
| `generate-onboarding-console.js` | Copy template + data.json to OneDrive output dir |
| `data/implementation-data.json` | Local working copy of customer data |
| `implementation-config.json` | Stage definitions, thresholds, timeline offsets |
| `fetch-implementation-data.py` | Query Notion + Supabase (opt-in via `:notion` scripts) |
| `check-triggers.py` | Trigger engine — morning (T1-T13) + evening (T5, T8, T10) |
| `write-back-notion.py` | Write computed fields back to Notion (opt-in) |
| `generate-welcome-package.js` | Welcome email draft → Teams |
| `teams-notify.js` | Adaptive Cards v1.4 sender utility |

## Dashboard Tabs

| Tab | Visualization |
|-----|--------------|
| Overview | KPI cards + Stage/Health/FDE summary charts + Needs Attention table |
| Pipeline Gantt | Horizontal Gantt chart — actual progress bars per customer, colored by stage |
| Budget vs. Actual | Dual-row timeline — planned (faded) vs actual (solid) bars per customer |
| KPIs | Detailed metrics table with CSAT, calls, deflection, health, status |

## Trigger Matrix

| # | Condition | Mode | When |
|---|-----------|------|------|
| T1 | Welcome Pkg today/tomorrow | AUTO | Morning |
| T2 | Questionnaire done + alignment in 7d + no AOP | SUGGEST | Morning |
| T3 | Alignment Call in 2 days + no deck | AUTO | Morning |
| T4 | AOP just checked | INFO | Morning |
| T5 | HOAi Testing date = today | AUTO | Evening |
| T6 | HOAi Testing Complete just checked | SUGGEST | Morning |
| T7 | Customer Testing + 3 days | SUGGEST | Morning |
| T8 | Customer Testing date = today | AUTO | Evening |
| T9 | Customer Testing Complete just checked | SUGGEST | Morning |
| T10 | Live Testing date = today | AUTO | Evening |
| T11 | Live Testing Complete just checked | SUGGEST | Morning |
| T12 | Stalled > 7 days | ALERT | Morning |
| T13 | Daily briefing | INFO | Morning |

## Environment Variables

```
TEAMS_IMPLEMENTATION_WEBHOOK_URL=https://...
NOTION_API_KEY=ntn_...    # Only needed for :notion scripts
```
