# S-O Projekt Status

## Aktueller Stand: 2026-02-03

### System-Architektur
```
TradingView (Pine Script)
  │  alert() mit JSON (READY / UPDATE / TRIGGERED)
  │  1 Alert pro Watchlist = 2 Alerts total
  ▼
Railway Server (Flask)
  ├── webhook_server.py  → empfängt Alerts, platziert Orders
  ├── executor.py        → Bybit API (Cross Margin)
  ├── trailing_sl.py     → Websocket SL-Nachzug in Echtzeit
  ├── trade_logger.py    → Supabase Logging
  └── telegram_alerts.py → Benachrichtigungen
  │
  ▼
Bybit (Cross Margin, Limit Orders mit TP/SL)
  │
  ▼
Supabase (trades Tabelle) → Next.js Dashboard
```

---

## Was in dieser Session gemacht wurde

### 1. Alert-System komplett umgebaut
- **Vorher**: 12x `alertcondition()` = 12 Alerts pro Coin = 240 Alerts bei 20 Coins
- **Jetzt**: `alert()` Calls im Script = **2 Alerts total** (1 Long-Watchlist, 1 Short-Watchlist)
- Nur noch 3 Alert-Types: READY, UPDATE, TRIGGERED
- EXIT und CANCELLED entfernt (Server erkennt das selbst via Bybit API / Timeout)

### 2. Trailing SL System eingebaut
- **Pine Script**: Trailing SL Logik für korrekte Backtesting-Ergebnisse
- **Server**: `trailing_sl.py` — Bybit Websocket Ticker-Stream monitored Preis in Echtzeit
- Wenn Preis 85% des TP-Abstands erreicht → SL wird auf 30% über Entry verschoben
- Einmalig pro Position (kein Step-Trailing)
- Telegram Notification bei SL-Move

### 3. Dead Code entfernt
- `useLowerTF` und `lowerTF` Inputs entfernt (waren nie implementiert, nur TODO)
- `ORDER_CANCEL_MINUTES` nicht mehr in Env Vars dokumentiert

### 4. Doku-Fehler gefixt
- "Binance Fees" → korrigiert zu Bybit Fees
- `BYBIT_TESTNET` → `USE_TESTNET` als primärer Var-Name
- Cross Margin dokumentiert

---

## Konfiguration

### Railway Environment Variables (aktuell)
```
# Pflicht
BYBIT_API_KEY, BYBIT_API_SECRET, USE_TESTNET
SUPABASE_URL, SUPABASE_KEY
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Risk
RISK_PER_TRADE_PCT=2.0
MAX_LEVERAGE=20
MAX_POSITION_SIZE_PCT=5
TP_MODE=single
MAX_LONGS=4
MAX_SHORTS=4

# Trailing SL
TRAIL_ENABLED=true
TRAIL_TP_THRESHOLD_PCT=85
TRAIL_SL_MOVE_PCT=30

# Server
PORT=8080
BOT_NAME=S-O Trader
```

### Duplikat-Vars (können raus, werden als Fallback unterstützt)
- `BYBIT_TESTNET` (Duplikat von `USE_TESTNET`)
- `DEFAULT_LEVERAGE` (Duplikat von `MAX_LEVERAGE`)
- `RISK_PER_TRADE` (Duplikat von `RISK_PER_TRADE_PCT`)

---

## Alert Flow (Live-Trading)

```
Kerze 1:  Low < S3        → READY_LONG    → Server merkt sich Entry/TP/SL
Kerze 2:  (wartet)        → UPDATE_LONG   → Server aktualisiert Levels
Kerze 3:  (wartet)        → UPDATE_LONG   → Server aktualisiert Levels
Kerze 4:  High > S1       → TRIGGERED     → Limit Order auf Bybit + TP/SL
                                              trailing_sl.py subscribed Ticker
  ...
Preis erreicht 85% von TP → Server verschiebt SL auf 30% über Entry (Websocket)
  ...
Preis trifft TP oder neuen SL → Bybit schließt Position automatisch
                                  Server erkennt Exit, loggt in Supabase
```

### TradingView Alert Setup
1. Long-Watchlist Chart → 1 Alert: Zustand = "Jeder alert()-Funktionsaufruf" → Webhook URL
2. Short-Watchlist Chart → 1 Alert: gleich → Webhook URL
3. **Fertig. 2 Alerts für alle Coins.**

---

## Was noch zu tun ist

### 1. Railway Deploy
- [ ] GitHub Repo in Railway von sysv1 auf S-O umstellen
- [ ] Neue Env Vars setzen (TRAIL_ENABLED, TRAIL_TP_THRESHOLD_PCT, TRAIL_SL_MOVE_PCT)
- [ ] Deploy auslösen
- [ ] Health Check testen: `GET /health`

### 2. TradingView Alerts einrichten
- [ ] Long-Watchlist: 1 Alert mit "Jeder alert()-Funktionsaufruf" + Webhook URL
- [ ] Short-Watchlist: 1 Alert mit "Jeder alert()-Funktionsaufruf" + Webhook URL
- [ ] `enableWebhookAlerts = true` im Backtester Settings

### 3. Testen (Testnet)
- [ ] `USE_TESTNET=true` setzen
- [ ] Manuellen Webhook senden (curl) → prüfen ob Order auf Bybit Testnet erscheint
- [ ] Trailing SL testen: Position manuell in Profit bringen → SL verschoben?
- [ ] Telegram Nachrichten kommen an? (READY, TRIGGERED, SL MOVED)
- [ ] Supabase Trade wird geloggt?
- [ ] Dashboard zeigt Trade an?

### 4. Später
- [ ] Dashboard deployen (Vercel oder zweiter Railway Service)
- [ ] ML Feature Collection starten (Daten sammeln sich automatisch)
- [ ] Exit-Erkennung server-seitig implementieren (Bybit Position-Check statt TV-Alert)
- [ ] Duplikat-Vars aus Railway löschen

---

## Bekannte Limitierungen

- **Trailing SL ist einmalig**: Wird nur 1x verschoben (kein progressives Trailing)
- **Exit-Erkennung**: Server hat noch `handle_exit()` und `handle_cancelled()` für Legacy-Support, aber TV sendet diese Alerts nicht mehr. Server-seitige Exit-Erkennung via Bybit Position-Polling fehlt noch.
- **Gunicorn Workers**: Bei 2 Workers teilen sich die Worker NICHT den `trailing_monitor` State. Entweder auf 1 Worker reduzieren oder Redis/shared State einbauen.

---

*Stand: 2026-02-03*
