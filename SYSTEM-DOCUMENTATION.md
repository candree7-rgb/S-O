# Universal Backtester & Trading System Documentation

## Overview

Komplettes Trading-System bestehend aus:
1. **Universal Backtester** (PineScript) - Signal-Generierung & Backtesting
2. **Railway Webhook Server** (Python/Flask) - Empfängt TV-Alerts, führt Trades aus
3. **Bybit Integration** - Order Execution via API
4. **Supabase Database** - Speichert alle Trades
5. **Next.js Dashboard** - Performance-Monitoring & Analytics
6. **Telegram Notifications** - Real-time Trade Alerts
7. **ML Model** (geplant) - Filtert Signale basierend auf historischen Daten

---

## Projektstruktur

```
S-O/
├── Universal-Backtester.pine   # PineScript v6 - Signal Generator
├── SYSTEM-DOCUMENTATION.md     # Diese Datei
│
├── server/                     # Python Backend (Railway)
│   ├── webhook_server.py       # Flask Webhook Server (Haupt-Entry)
│   ├── config.py               # Konfiguration via Env Vars
│   ├── executor.py             # Bybit API Order Execution
│   ├── trade_logger.py         # Supabase Trade Logging
│   ├── telegram_alerts.py      # Telegram Benachrichtigungen
│   ├── requirements.txt        # Python Dependencies
│   └── .env.example            # Env Var Template
│
├── dashboard/                  # Next.js 14 Dashboard
│   ├── app/                    # App Router
│   │   ├── layout.tsx          # Root Layout
│   │   ├── page.tsx            # Main Dashboard Page
│   │   ├── globals.css         # Global Styles
│   │   └── api/                # API Routes
│   │       ├── stats/route.ts       # Performance Statistics
│   │       ├── trades/route.ts      # Trade List
│   │       ├── equity/route.ts      # Equity Curve
│   │       └── tp-distribution/route.ts  # TP/SL Distribution
│   ├── components/             # React Components
│   │   ├── stats-cards.tsx     # KPI Cards
│   │   ├── equity-chart.tsx    # Equity Chart
│   │   ├── trades-table.tsx    # Trade History Table
│   │   ├── tp-distribution.tsx # TP/SL Pie Chart
│   │   ├── time-range-selector.tsx  # Date Filter
│   │   └── theme-provider.tsx  # Dark/Light Theme
│   ├── lib/
│   │   ├── supabase.ts         # Supabase Client & Types
│   │   └── utils.ts            # Utility Functions
│   ├── package.json
│   ├── tailwind.config.js
│   └── next.config.js
│
├── supabase/                   # Database Scripts
│   ├── schema.sql              # Table Creation
│   └── reset.sql               # Reset/Migration Scripts
│
├── Dockerfile                  # Python Server Container
└── railway.json                # Railway Deployment Config
```

---

## 1. Universal Backtester (PineScript)

### Datei: `Universal-Backtester.pine`

### Benötigte Indikatoren auf dem Chart
- **LuxAlgo Signals & Overlays** - Reversal Zones (S1, S2, S3, R1, R2, R3)
- **ATR Bands** - Momentum Filter (Lower/Upper ATR Band)

### Beste RZ Settings (LuxAlgo)
```
Filter: Butterworth
Length: 120
Double Smooth: 5
Source: TR (True Range)
Volatility Length: 200
Outer Multiplier: 1.8
Gradient: 0.75
```

---

## 2. Multi-Step Signal System

### Konzept
Nachbildung des LuxAlgo Alert-Scripting Systems:
- **Step 1 (READY)**: Preis betritt die Zone (z.B. Low kreuzt unter S3)
- **Step 2 (TRIGGERED)**: Preis verlässt die Zone (z.B. High kreuzt über S1)
- **Step 3 (FILTER)**: Kontinuierliche Bedingung während dem Warten

### LONG Setup (Standard)
```
Condition 1:
  Price Type: Low
  Condition: Crossing Under
  Level Source: RZ S3
  Step: 1 (READY)

Condition 2:
  Price Type: High
  Condition: Crossing Over
  Level Source: RZ S1
  Step: 2 (TRIGGERED)
```

### SHORT Setup (Standard)
```
Condition 1:
  Price Type: High
  Condition: Crossing Over
  Level Source: RZ R3
  Step: 1 (READY)

Condition 2:
  Price Type: Low
  Condition: Crossing Under
  Level Source: RZ R1
  Step: 2 (TRIGGERED)
```

---

## 3. Momentum Filter (ATR Bands)

### Konzept
Prüft ob der Markt Momentum in Trade-Richtung hat (nicht seitwärts/ranging).

### LONG Momentum Filter
```
Condition 3:
  Price Type: Custom
  Price Custom: ATR Bands: Lower ATR Band
  Condition: Greater Than
  Level Type: Source
  Level Source: ATR Bands: Lower ATR Band (GLEICHE Quelle!)
  Lookback: 3
  Step: 2
```
**Logik**: `Lower_Band[0] > Lower_Band[3]` = Band steigt = bullish momentum

### SHORT Momentum Filter
```
Condition 3:
  Price Type: Custom
  Price Custom: ATR Bands: Upper ATR Band
  Condition: Less Than
  Level Type: Source
  Level Source: ATR Bands: Upper ATR Band (GLEICHE Quelle!)
  Lookback: 3
  Step: 2
```
**Logik**: `Upper_Band[0] < Upper_Band[3]` = Band fällt = bearish momentum

### ATR Bands Settings
```
ATR Period: 3
ATR Band Scale Factor: 2.5
```

---

## 4. Condition Types

| Condition | Beschreibung | Trigger/State |
|-----------|--------------|---------------|
| Crossing | Kreuzt in beide Richtungen | Trigger |
| Crossing Under | Kreuzt von oben nach unten | Trigger |
| Crossing Over | Kreuzt von unten nach oben | Trigger |
| Less Than | Kleiner als | State |
| Less Or Equal | Kleiner oder gleich | State |
| Greater Than | Größer als | State |
| Greater Or Equal | Größer oder gleich | State |
| Equal To | Exakt gleich | State |
| Is True (>0) | Wert > 0 (für Boolean-Signale) | State |

### Trigger vs State
- **Trigger**: Feuert einmal beim Übergang (Crossing)
- **State**: Ist wahr solange Bedingung erfüllt (wird Edge-detected)

---

## 5. Step-Logik

### Step 1 (READY)
- Aktiviert den "Warte-Zustand"
- Braucht mindestens eine Trigger-Condition ODER State-Edge

### Step 2 (TRIGGERED)
- Löst den Trade aus
- Kann mehrere Conditions haben (alle müssen erfüllt sein)
- **Wichtig**: Step 1 und Step 2 dürfen NICHT auf derselben Kerze sein!

### Step 3 (FILTER)
- Muss kontinuierlich erfüllt sein während Step 1 aktiv
- Wenn Filter failed → Trade wird gecancelt

### Single-Step Mode
- Wenn keine Step 2 Conditions definiert → Signal feuert sofort bei Step 1

### Max Step Interval
- Maximale Anzahl Kerzen zwischen Step 1 und Step 2
- Default: 10 Bars
- Nach Ablauf wird READY-State gecancelt

---

## 6. Position Sizing & Risk Management

### Position Sizing Modes
1. **Percent**: X% des Kapitals pro Trade
2. **Fixed**: Fixer Betrag pro Trade
3. **Risk-Based**: Position so dimensioniert, dass SL = X% Verlust

### Max Risk Cap
- Reduziert Position automatisch wenn SL > Max Risk %
- Formel: `Position = MaxAllowedLoss / (SL% × Leverage)`

### Leverage
- 1x bis 125x einstellbar
- PnL Berechnung: `PriceChange% × Leverage × Position`

### Compounding
- **An**: Position basiert auf aktuellem Kapital
- **Aus**: Position basiert auf Initial Capital

---

## 7. TP/SL Berechnung

### TP/SL Types
| Type | Beschreibung |
|------|--------------|
| ATR | `Entry ± (ATR × Multiplier)` |
| Percent | `Entry ± (Entry × Percent%)` |
| Fixed Points | `Entry ± (Points × MinTick)` |
| Custom Source | Verbinde zu externem Level (z.B. RZ S2) |

### Empfohlene Settings
```
TP Type: ATR
TP ATR Multiplier: 2.0
SL Type: ATR
SL ATR Multiplier: 1.0
ATR Length: 14
```

---

## 8. Webhook Alert Messages

### Alert Types

#### READY (Step 1 triggered)
```json
{
  "type": "READY",
  "direction": "LONG",
  "coin": "BTCUSDT",
  "entry": 42000.50,
  "tp": 42500.00,
  "sl": 41800.00,
  "atr": 250.25,
  "zoneWidth": 150.00,
  "time": "2024-01-15T10:30:00Z"
}
```

#### UPDATE (while READY)
```json
{
  "type": "UPDATE",
  "direction": "LONG",
  "coin": "BTCUSDT",
  "entry": 42010.00,
  "tp": 42510.00,
  "sl": 41810.00,
  "barsReady": 3,
  "time": "2024-01-15T10:45:00Z"
}
```

#### TRIGGERED (Entry executed)
```json
{
  "type": "TRIGGERED",
  "direction": "LONG",
  "coin": "BTCUSDT",
  "entry": 42005.00,
  "tp": 42505.00,
  "sl": 41805.00,
  "time": "2024-01-15T10:50:00Z"
}
```

#### EXIT (Trade closed)
```json
{
  "type": "EXIT",
  "direction": "LONG",
  "outcome": "WIN",
  "coin": "BTCUSDT",
  "exitPrice": 42505.00,
  "time": "2024-01-15T11:30:00Z"
}
```

#### CANCELLED (READY state expired/failed)
```json
{
  "type": "CANCELLED",
  "direction": "LONG",
  "coin": "BTCUSDT",
  "time": "2024-01-15T11:00:00Z"
}
```

---

## 9. Webhook Server (server/)

### Architektur
```
TradingView Alert ──▶ Railway Server (Flask) ──▶ Bybit API
                           │                         │
                           ├──▶ Supabase DB          │ Orders
                           │                         │ TP/SL
                           └──▶ Telegram Bot         ▼
                                                  Exchange
```

### Dateien

| Datei | Beschreibung |
|-------|-------------|
| `webhook_server.py` | Flask App, Webhook-Handler für alle 5 Alert-Types |
| `config.py` | Konfiguration via Environment Variables (dataclasses) |
| `executor.py` | Bybit pybit API: Orders, Leverage, Position Sizing |
| `trade_logger.py` | Supabase Client: Trade Entry/Exit Logging |
| `telegram_alerts.py` | Telegram Bot: Trade/Ready/Error Notifications |

### Endpunkte

| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `POST` | `/webhook` | Empfängt TradingView Alerts |
| `GET` | `/health` | Health Check (Railway) |
| `GET` | `/status` | Bot Status, Equity, Positionen |
| `GET` | `/orders` | Pending Orders |
| `POST` | `/close` | Manuelles Position-Schliessen |

### Webhook Handler Flow

```
POST /webhook
  │
  ├── type=READY     → ready_states speichern + Telegram
  ├── type=UPDATE    → ready_states aktualisieren
  ├── type=TRIGGERED → Bybit Order + Supabase Log + Telegram
  ├── type=EXIT      → PnL berechnen + Supabase Update + Telegram
  ├── type=CANCELLED → ready_states cleanup + Telegram
  └── fallback       → Legacy format (action=entry) Support
```

### Konfiguration (Environment Variables)

```env
# Bybit API
BYBIT_API_KEY=xxx
BYBIT_API_SECRET=xxx
BYBIT_TESTNET=true              # true=testnet, false=mainnet

# Risk Settings
RISK_PER_TRADE=2.0              # % of equity risked per trade
DEFAULT_LEVERAGE=20             # Leverage multiplier
MAX_POSITION_SIZE_PCT=5         # Max position as % of equity
TP_MODE=single                  # "single" = 100% at TP, "split" = 50/50

# Webhook
WEBHOOK_SECRET=                 # Optional HMAC secret
PORT=8080
ORDER_CANCEL_MINUTES=30

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# Telegram
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
BOT_NAME=S-O Trader
```

### TP Mode

| Mode | Beschreibung |
|------|-------------|
| `single` | 100% der Position wird bei TP geschlossen |
| `split` | 50% bei TP1 (= TP Preis), 50% bei TP2 (= 2x TP-Distanz) |

---

## 10. Supabase Database

### Schema (`supabase/schema.sql`)

```sql
CREATE TABLE trades (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Basics
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),

    -- Entry
    entry_price DOUBLE PRECISION NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    qty DOUBLE PRECISION NOT NULL,
    leverage INTEGER NOT NULL DEFAULT 20,
    margin_used DOUBLE PRECISION,
    equity_at_entry DOUBLE PRECISION,

    -- TP/SL
    sl_price DOUBLE PRECISION NOT NULL,
    tp_price DOUBLE PRECISION NOT NULL,

    -- Order Tracking
    order_id TEXT,

    -- Exit (filled when trade closes)
    exit_price DOUBLE PRECISION,
    exit_time TIMESTAMPTZ,
    exit_reason TEXT,              -- 'tp', 'sl', 'manual', 'be'
    duration_minutes INTEGER,

    -- PnL
    realized_pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,           -- PnL as % of margin
    pnl_pct_equity DOUBLE PRECISION,    -- PnL as % of equity
    equity_at_close DOUBLE PRECISION,
    is_win BOOLEAN,
    total_fees DOUBLE PRECISION DEFAULT 0,
    net_pnl DOUBLE PRECISION,

    -- Risk
    risk_pct DOUBLE PRECISION,
    risk_amount DOUBLE PRECISION,

    -- RZ/ATR Features (for ML)
    atr_value DOUBLE PRECISION,
    zone_width DOUBLE PRECISION,
    bars_in_ready INTEGER,

    -- Session Context
    hour_utc INTEGER,
    day_of_week INTEGER,
    is_asian_session BOOLEAN,
    is_london_session BOOLEAN,
    is_ny_session BOOLEAN
);
```

### Indexes
```sql
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_exit_time ON trades(exit_time);
CREATE INDEX idx_trades_direction ON trades(direction);
CREATE INDEX idx_trades_is_win ON trades(is_win);
CREATE INDEX idx_trades_entry_time ON trades(entry_time);
```

### Supabase Reset Commands

```sql
-- Option 1: Alle Trades löschen (Tabelle behalten)
DELETE FROM trades;

-- Option 2: Tabelle komplett neu erstellen
DROP TABLE IF EXISTS trades;
-- Dann schema.sql erneut ausführen

-- Option 3: Nur alte Trades löschen (z.B. älter als 30 Tage)
DELETE FROM trades WHERE entry_time < NOW() - INTERVAL '30 days';

-- Option 4: Nur offene Trades löschen
DELETE FROM trades WHERE exit_time IS NULL;
```

---

## 11. Dashboard (dashboard/)

### Tech Stack
- **Next.js 14** (App Router)
- **TypeScript**
- **Tailwind CSS** (Dark Theme)
- **Recharts** (Charts)
- **Supabase JS Client** (Daten)

### Features
- **Stats Cards**: Total Trades, Win Rate, PnL, Profit Factor, Avg Win/Loss, TP/SL Rate, Avg Duration
- **Equity Chart**: Kumulierte PnL-Kurve über Zeit
- **Trades Table**: Alle Trades mit Sortierung und Pagination
- **TP Distribution**: Pie Chart (Take Profit / Stop Loss / Other)
- **Time Range Filter**: 24h, 7d, 30d, 90d, All, Custom

### API Routes

| Route | Beschreibung |
|-------|-------------|
| `/api/stats` | Aggregierte Performance-Statistiken |
| `/api/trades` | Paginierte Trade-Liste |
| `/api/equity` | Equity-Kurve Datenpunkte |
| `/api/tp-distribution` | TP/SL Verteilung |

### Dashboard Environment Variables
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
```

---

## 12. Telegram Notifications

### Benachrichtigungstypen

| Event | Nachricht |
|-------|-----------|
| Bot Started | Equity, aktive Positionen |
| Ready State | Symbol, Richtung, Entry/TP/SL Levels |
| Trade Opened | Symbol, Richtung, Entry, SL, TP, Leverage, Risk |
| Trade Closed | Symbol, PnL %, Outcome (WIN/LOSS), Duration |
| Ready Cancelled | Symbol, Richtung |
| Error | Fehlermeldung + Kontext |
| Daily Summary | Win Rate, PnL, beste/schlechteste Trades |

### Setup
1. Erstelle Bot via @BotFather → Token erhalten
2. Starte Chat mit dem Bot
3. Hole Chat ID via `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Setze `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` in Env Vars

---

## 13. Deployment (Railway)

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ .
EXPOSE 8080
CMD ["gunicorn", "webhook_server:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
```

### Railway Config (`railway.json`)
```json
{
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "healthcheckPath": "/health",
    "healthcheckTimeout": 10
  }
}
```

### Deployment Steps
1. Push Repo zu GitHub
2. Railway Project erstellen → GitHub Repo verbinden
3. Environment Variables setzen (alle aus `.env.example`)
4. Deploy → Railway baut Docker Image automatisch
5. Webhook URL von Railway kopieren (z.B. `https://s-o.up.railway.app/webhook`)
6. In TradingView Alert: Webhook URL einfügen

---

## 14. Wichtige Hinweise

### Repainting
- Aktuelle Kerze kann repainen bis sie schliesst
- Für 100% kein Repainting: Lookback +1 verwenden (z.B. 4 statt 3)
- Backtester zeigt historische Ergebnisse (kein Repainting im Backtest)

### Same-Candle Bug
- Step 1 und Step 2 können NICHT auf derselben Kerze triggern
- Implementiert via `bar_index > longStep1Bar` Check

### Entry Price
- "Custom Source" empfohlen für Entry
- Verbinde zu RZ S1 (Long) oder RZ R1 (Short)
- Das ist der theoretisch beste Entry-Preis

### Fees
- Binance Maker: 0.04% Entry + 0.04% Exit = 0.08% total
- Bei 100 Trades × $500 Position = $40 Fees gespart mit Limit Orders

### Timeframe
- Empfohlen: 15m Chart
- Lower TF Check: 5m für genauere TP/SL Erkennung

---

## 15. Roadmap

### Phase 1: Backtesting (DONE)
- [x] Universal Backtester
- [x] Multi-Step Signal System
- [x] Flexible Conditions
- [x] Momentum Filter (Lookback)
- [x] Position Sizing & Risk Management
- [x] Webhook Alert Messages

### Phase 2: Live Trading Infrastructure (DONE)
- [x] Railway Webhook Server (Flask/Gunicorn)
- [x] Bybit API Integration (pybit)
- [x] Supabase Database Schema
- [x] Telegram Notifications
- [x] Next.js Dashboard
- [x] Docker Deployment Config

### Phase 3: ML Enhancement
- [ ] Feature Collection (atr_value, zone_width, bars_in_ready already tracked)
- [ ] Model Training (XGBoost)
- [ ] Confidence Filter
- [ ] A/B Testing (mit/ohne ML)

### Phase 4: Optimization
- [ ] Multi-Coin Support
- [ ] Auto-Parameter Tuning
- [ ] Advanced Dashboard Analytics
- [ ] Performance Reporting

---

## 16. Quick Start Checklist

### TradingView Setup
1. [x] LuxAlgo Signals & Overlays auf Chart laden
2. [x] ATR Bands Indicator auf Chart laden
3. [x] Universal Backtester auf Chart laden
4. [x] RZ Settings konfigurieren (Butterworth, Length 120, etc.)
5. [x] Long Conditions verbinden (S1, S3)
6. [x] Short Conditions verbinden (R1, R3)
7. [x] Momentum Filter aktivieren (Condition 3)
8. [x] TP/SL Settings anpassen
9. [x] Backtest analysieren

### Server Deployment
1. [ ] Supabase Projekt erstellen
2. [ ] `supabase/schema.sql` im SQL Editor ausführen
3. [ ] Railway Projekt erstellen und GitHub verbinden
4. [ ] Environment Variables setzen (siehe `.env.example`)
5. [ ] Deploy und Webhook URL kopieren
6. [ ] Telegram Bot erstellen und Chat ID holen
7. [ ] TradingView Alert erstellen mit Webhook URL
8. [ ] Test-Trade auf Bybit Testnet ausführen

### Dashboard
1. [ ] Vercel/Railway Projekt für Dashboard erstellen
2. [ ] `SUPABASE_URL` und `SUPABASE_KEY` setzen
3. [ ] Deploy

---

*Letzte Aktualisierung: 2026-02*
*Version: 2.0*
*Migriert von sysv1 (SMC Ultra V2) - Infrastruktur übernommen, adaptiert für Universal Backtester*
