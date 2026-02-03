# Universal Backtester & Trading System Documentation

## Overview

Komplettes Trading-System bestehend aus:
1. **Universal Backtester** (PineScript) - Signal-Generierung & Backtesting
2. **Railway Webhook Server** (geplant) - Empfängt TV-Alerts, führt Trades aus
3. **Supabase Database** (geplant) - Speichert Trades für ML-Analyse
4. **ML Model** (geplant) - Filtert Signale basierend auf historischen Daten

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

## 9. Railway Webhook Server (Geplant)

### Architektur
```
TradingView Alert → Railway Server → Bybit API
                         ↓
                    Supabase DB
                         ↓
                    ML Model (Filter)
```

### Endpunkte
```
POST /webhook          - Empfängt TV Alerts
GET  /status           - Server Status
GET  /positions        - Aktuelle Positionen
GET  /stats            - Performance Stats
```

### Webhook Handler Logic
```javascript
// Pseudocode
async function handleWebhook(alert) {
  // 1. Parse Alert
  const { type, direction, coin, entry, tp, sl } = alert;

  // 2. ML Filter (optional)
  if (ML_ENABLED) {
    const prediction = await mlModel.predict(features);
    if (prediction.confidence < MIN_CONFIDENCE) {
      return { action: 'SKIP', reason: 'ML filtered' };
    }
  }

  // 3. Execute based on type
  switch (type) {
    case 'READY':
      await db.savePendingSignal(alert);
      break;

    case 'TRIGGERED':
      await exchange.placeOrder({
        symbol: coin,
        side: direction === 'LONG' ? 'BUY' : 'SELL',
        type: 'LIMIT',
        price: entry,
        stopLoss: sl,
        takeProfit: tp
      });
      await db.saveOpenTrade(alert);
      break;

    case 'EXIT':
      await db.updateTradeResult(alert);
      break;

    case 'CANCELLED':
      await db.cancelPendingSignal(alert);
      break;
  }
}
```

### Environment Variables
```env
BYBIT_API_KEY=xxx
BYBIT_API_SECRET=xxx
SUPABASE_URL=xxx
SUPABASE_KEY=xxx
ML_MODEL_URL=xxx (optional)
WEBHOOK_SECRET=xxx
```

---

## 10. Supabase Database Schema (Geplant)

### Tables

#### `signals`
```sql
CREATE TABLE signals (
  id UUID PRIMARY KEY,
  coin VARCHAR(20),
  direction VARCHAR(10),
  type VARCHAR(20),
  entry_price DECIMAL,
  tp_price DECIMAL,
  sl_price DECIMAL,
  atr DECIMAL,
  zone_width DECIMAL,
  bars_ready INT,
  status VARCHAR(20),
  created_at TIMESTAMP,
  triggered_at TIMESTAMP,
  closed_at TIMESTAMP
);
```

#### `trades`
```sql
CREATE TABLE trades (
  id UUID PRIMARY KEY,
  signal_id UUID REFERENCES signals(id),
  coin VARCHAR(20),
  direction VARCHAR(10),
  entry_price DECIMAL,
  exit_price DECIMAL,
  tp_price DECIMAL,
  sl_price DECIMAL,
  position_size DECIMAL,
  pnl_amount DECIMAL,
  pnl_percent DECIMAL,
  outcome VARCHAR(10),
  duration_bars INT,
  created_at TIMESTAMP
);
```

#### `ml_features`
```sql
CREATE TABLE ml_features (
  id UUID PRIMARY KEY,
  signal_id UUID REFERENCES signals(id),
  atr DECIMAL,
  zone_width DECIMAL,
  bars_in_ready INT,
  rsi DECIMAL,
  volume_ratio DECIMAL,
  momentum_score DECIMAL,
  hour_of_day INT,
  day_of_week INT,
  outcome VARCHAR(10)
);
```

---

## 11. ML Model (Geplant)

### Features für Training
| Feature | Beschreibung |
|---------|--------------|
| atr | ATR Wert bei Signal |
| zone_width | Abstand S1-S3 oder R1-R3 |
| bars_in_ready | Wie lange im READY state |
| rsi | RSI Wert bei Signal |
| volume_ratio | Volume vs Average |
| momentum_score | ATR Band Momentum |
| hour_of_day | Stunde (0-23) |
| day_of_week | Wochentag (0-6) |

### Target
- `outcome`: WIN (1) oder LOSS (0)

### Model Options
1. **Logistic Regression** - Einfach, interpretierbar
2. **Random Forest** - Robust, Feature Importance
3. **XGBoost** - Beste Performance
4. **Neural Network** - Komplex, braucht viele Daten

### Training Pipeline
```python
# Pseudocode
def train_model():
    # 1. Load data from Supabase
    df = load_trades_with_features()

    # 2. Feature Engineering
    X = df[FEATURE_COLUMNS]
    y = df['outcome'].map({'WIN': 1, 'LOSS': 0})

    # 3. Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(X, y)

    # 4. Train Model
    model = XGBClassifier()
    model.fit(X_train, y_train)

    # 5. Evaluate
    accuracy = model.score(X_test, y_test)

    # 6. Save Model
    model.save('model.pkl')
```

### Inference
```python
def should_take_trade(features):
    prediction = model.predict_proba([features])[0]
    confidence = prediction[1]  # Probability of WIN
    return confidence >= MIN_CONFIDENCE
```

---

## 12. Wichtige Hinweise

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

## 13. Roadmap

### Phase 1: Backtesting (DONE)
- [x] Universal Backtester
- [x] Multi-Step Signal System
- [x] Flexible Conditions
- [x] Momentum Filter (Lookback)
- [x] Position Sizing & Risk Management
- [x] Webhook Alert Messages

### Phase 2: Live Trading
- [ ] Railway Webhook Server
- [ ] Bybit API Integration
- [ ] Supabase Database
- [ ] Real-time Position Tracking

### Phase 3: ML Enhancement
- [ ] Feature Collection
- [ ] Model Training
- [ ] Confidence Filter
- [ ] A/B Testing (mit/ohne ML)

### Phase 4: Optimization
- [ ] Multi-Coin Support
- [ ] Auto-Parameter Tuning
- [ ] Dashboard UI
- [ ] Performance Analytics

---

## 14. Quick Start Checklist

1. [ ] LuxAlgo Signals & Overlays auf Chart laden
2. [ ] ATR Bands Indicator auf Chart laden
3. [ ] Universal Backtester auf Chart laden
4. [ ] RZ Settings konfigurieren (Butterworth, Length 120, etc.)
5. [ ] Long Conditions verbinden (S1, S3)
6. [ ] Short Conditions verbinden (R1, R3)
7. [ ] Momentum Filter aktivieren (Condition 3)
8. [ ] TP/SL Settings anpassen
9. [ ] Backtest analysieren
10. [ ] Webhook Alerts aktivieren (wenn live)

---

*Letzte Aktualisierung: 2024*
*Version: 1.0*
