# S-O Projekt Status

## Migration von sysv1 - Erledigt

Die komplette Infrastruktur wurde von `candree7-rgb/sysv1` (SMC Ultra V2) übernommen und für den Universal Backtester adaptiert:

| Komponente | Status | Anpassung |
|---|---|---|
| Webhook Server (Flask) | Fertig | 5 Alert-Types statt `action=entry` |
| Bybit Executor (pybit) | Fertig | Market Orders bei TRIGGERED |
| Supabase Trade Logger | Fertig | Neues Schema (`tp_price` statt `tp1/tp2`) |
| Telegram Notifications | Fertig | READY/CANCELLED Nachrichten neu |
| Next.js Dashboard | Fertig | TP Distribution vereinfacht |
| Dockerfile + Railway | Fertig | Gleiche Struktur wie sysv1 |

---

## Aktuelle Konfiguration

### Supabase
- Tabelle `trades` mit neuem Schema erstellt
- Alte sysv1-Daten gelöscht
- Indexes für Performance angelegt

### Railway Environment Variables
```
BOT_NAME, BYBIT_API_KEY, BYBIT_API_SECRET, USE_TESTNET,
MAX_LEVERAGE, MAX_LONGS=4, MAX_SHORTS=4, MAX_POSITION_SIZE_PCT,
RISK_PER_TRADE_PCT, TP_MODE, SUPABASE_URL, SUPABASE_KEY,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

Können noch raus (Duplikate/Altlasten):
- `BYBIT_TESTNET` (Duplikat von `USE_TESTNET`)
- `DEFAULT_LEVERAGE` (Duplikat von `MAX_LEVERAGE`)
- `RISK_PER_TRADE` (Duplikat von `RISK_PER_TRADE_PCT`)
- `ORDER_CANCEL_MINUTES` (nicht mehr gebraucht)

---

## Alert Flow (TradingView → Bybit)

### 2 Charts nötig (Long-Chart + Short-Chart)

**Long-Chart - 6 Alerts:**
| Alert | Wann | Was passiert auf Server |
|---|---|---|
| `READY_LONG` | Low kreuzt unter S3 | Speichert Entry/TP/SL, Telegram "watching" |
| `UPDATE_LONG` | Jede 15min Kerze solange READY | Aktualisiert Entry/TP/SL im Memory |
| `TRIGGERED_LONG` | High kreuzt über S1 | **Market Order auf Bybit + TP/SL setzen** |
| `EXIT_LONG_WIN` | TP getroffen | PnL berechnen, Supabase loggen, Telegram |
| `EXIT_LONG_LOSS` | SL getroffen | PnL berechnen, Supabase loggen, Telegram |
| `CANCELLED_LONG` | Max Step Interval abgelaufen | Cleanup, Telegram |

**Short-Chart - 6 Alerts:**
Gleich, nur mit SHORT, R3, R1.

### Flow Visualisierung
```
Kerze 1:  Low < S3        → READY_LONG    → Server merkt sich Levels
Kerze 2:  (wartet)        → UPDATE_LONG   → Server aktualisiert Levels
Kerze 3:  (wartet)        → UPDATE_LONG   → Server aktualisiert Levels
Kerze 4:  High > S1       → TRIGGERED     → Market Order auf Bybit!
  ...                                        TP + SL als Conditional Orders
Kerze N:  Preis trifft TP → EXIT_LONG_WIN → PnL loggen, Telegram
```

### Wichtig
- **Keine Limit Order**: Bei TRIGGERED wird sofort eine Market Order platziert
- **TP/SL auf Exchange**: Werden als Conditional Orders auf Bybit gesetzt, nicht vom Server überwacht
- **EXIT kommt von TradingView**: Der Backtester erkennt TP/SL Hit auf dem Chart und sendet EXIT Alert
- **MAX_LONGS=4 / MAX_SHORTS=4**: Server prüft vor jeder Order ob Limit erreicht

---

## Was noch zu tun ist

### 1. Railway Deploy
- [ ] GitHub Repo in Railway von sysv1 auf S-O umstellen
- [ ] Deploy auslösen
- [ ] Health Check testen: `GET /health`
- [ ] Webhook URL notieren

### 2. TradingView Alerts einrichten
- [ ] Long-Chart: 6 Alerts mit Webhook URL erstellen
- [ ] Short-Chart: 6 Alerts mit Webhook URL erstellen
- [ ] Alert Message = automatisch vom Backtester (alertcondition)

### 3. Testen
- [ ] Testnet Mode an (`USE_TESTNET=true`)
- [ ] Manuellen Webhook senden (curl/Postman) → prüfen ob Order auf Bybit Testnet erscheint
- [ ] Telegram Nachricht kommt an?
- [ ] Supabase Trade wird geloggt?
- [ ] Dashboard zeigt Trade an?

### 4. Später (optional)
- [ ] Dashboard deployen (Vercel oder zweiter Railway Service)
- [ ] ML Feature Collection starten
- [ ] Duplikat-Vars aus Railway löschen

---

## Offene Fragen
- Limit Orders statt Market Orders bei TRIGGERED gewünscht?
- Dashboard separat deployen oder reicht Supabase Dashboard?
- Multi-Coin: Mehrere Coins auf einem Chart oder ein Chart pro Coin?

---

*Stand: 2026-02-03*
