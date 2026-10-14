# Web UI

React + Vite + Recharts UI for the network management app.

## Run

From `web/`:

```sh
npm install
npm run dev
```

Default uses in-memory mock data (`src/api/mock.ts`). `VITE_API_MODE=live npm run dev` uses the FastAPI backend; Vite proxies `/api` to `http://localhost:8000`.

## Layout

- `src/nav.tsx`: sidebar + routes.
- `src/pages/`: one file per screen.
- `src/components/ui/`: shared Meter-style primitives: Button, IconButton, Pill, Select, TextInput, TextArea, FilterBar, PanelSection, StatRow, ToolCard, ChartSection, TimeSeries, DataTable, SectionHeader, Checkbox, ConfirmDialog.
- `src/api/`: `types.ts` mirrors backend schemas; `live.ts`/`mock.ts` share signatures; `useApi` hook.
- `src/lib/`: format, diff.

## Add a screen

1. Create `src/pages/X.tsx` using PageHeader → FilterBar → content and `<RightPanel>` (from `src/components/Layout.tsx`) for the right column.
2. Add one entry to `src/nav.tsx`.
3. Add API functions to both `src/api/live.ts` and `src/api/mock.ts` with the same signature.

## Monitoring contract

Monitoring endpoints under `/api/v1/monitoring/*` are implemented by the backend in `app/monitoring.py`: `/api/v1/monitoring/status`, `/api/v1/monitoring/alerts`, `/api/v1/monitoring/metrics?window={window}`, `/api/v1/monitoring/devices/{deviceId}/metrics?window={window}`, `/api/v1/monitoring/topology`, `/api/v1/monitoring/devices/{deviceId}/interfaces`. The poller runs when `MONITORING_ENABLED=true`.
