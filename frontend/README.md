# Smartify Kombi dashboard

React + TypeScript + Vite. No UI framework: a small set of components and one
stylesheet (`src/styles.css`) holding the design tokens. Fonts are bundled, so
the dashboard works in the van without internet (map tiles excepted).

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api to the backend on :8000
npm run build    # writes dist/, served by the backend (SMARTIFY_FRONTEND_DIR)
```

Run the backend in mock mode alongside (`cd ../backend && python -m smartify`)
to develop without a Raspberry Pi.

| Route | What |
|---|---|
| `/` | Overview (cards can be hidden and reordered per device) |
| `/energy` | Victron battery, solar, Orion, MultiPlus + history |
| `/climate` | DHT22 sensors, water tank, outside weather |
| `/switches`, `/switches/:id` | Relay control, rules, settings, safety cutoff |
| `/map` | Route history, distance per day, GPX archive |
| `/settings` | WiFi, water calibration, overview layout |
| `/system` | Pi health, background tasks, log |
| `/panel` | Full-screen instrument panel for a tablet in the van |

API types live in `src/api/types.ts` and mirror `backend/smartify/api`.
