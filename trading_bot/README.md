# Trading Bot — SLK + Daily CRT + 4H CRT

One dashboard. Three independent strategies. Toggle each on/off. Telegram alerts. OANDA data. New York time.

## Strategies

| Strategy | Logic | When alert fires |
|----------|--------|------------------|
| **SLK** | Daily rejection at A/V/Open-Close KL + **4H External BO** | When structure + key level confirm |
| **Daily CRT** | Monday range → Tue/Wed sweep | **5 minutes before Daily candle closes** |
| **4H CRT** | C1 range → C2 sweeps high/low | **5 minutes before that 4H C2 closes** |

All alerts are **bias only** — not entry signals.

## Local run

```bash
cd trading_bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

1. Tick the strategies you want  
2. Click **Test alert** for each (confirm Telegram)  
3. Click **Start**

## Deploy on Render

1. Push this folder to a GitHub repo  
2. In Render → **New → Blueprint** (or Web Service)  
3. Connect the repo  
4. Set environment variables:
   - `OANDA_API_TOKEN`
   - `OANDA_ACCOUNT_ID`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Start command:  
   `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`

Or use the included `render.yaml`.

**Note:** Free Render web services sleep after inactivity. Use a paid instance or a cron ping if you need 24/7 scanning.

## Dashboard

- Start / Stop  
- Tick/untick **SLK · Daily CRT · 4H CRT**  
- Test alert per strategy  
- Activity feed  

## CRT timing (NY)

- **4H CRT:** When current 4H candle (C2) has swept previous candle (C1) high or low, alert when ~5 minutes remain until that 4H bar closes.  
- **Daily CRT:** When weekly Monday-range CRT setup is valid, alert ~5 minutes before the daily candle closes.

## Disclaimer

Educational tool only. Not financial advice. Trading involves risk of loss.
