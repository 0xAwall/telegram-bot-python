import yfinance as yf
import requests
import json
import os
import pandas as pd

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = "8194568122:AAFv79ViDFOkMAMQH6JrtB0AvSPspDSLyHg"

# ========================
# DATABASE PORTFOLIO
# ========================
DB_FILE = "portfolio.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)


# ========================
# RSI FUNCTION
# ========================
def calculate_rsi(data, period=14):
    delta = data["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi.iloc[-1]


# ========================
# /harga
# ========================
async def harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /harga BBRI")
        return

    saham = context.args[0].upper()
    if "." not in saham:
        saham += ".JK"

    try:
        hist = yf.Ticker(saham).history(period="1d")

        if hist.empty:
            await update.message.reply_text("Saham tidak ditemukan")
            return

        o = hist["Open"].iloc[-1]
        c = hist["Close"].iloc[-1]
        h = hist["High"].iloc[-1]
        l = hist["Low"].iloc[-1]

        change = c - o
        percent = (change / o) * 100
        arrow = "🔺" if change > 0 else "🔻" if change < 0 else "➖"

        await update.message.reply_text(
            f"📊 {saham}\n"
            f"Harga: Rp {c:,.0f}\n"
            f"{arrow} {change:+,.0f} ({percent:+.2f}%)\n\n"
            f"High: Rp {h:,.0f}\nLow: Rp {l:,.0f}"
        )

    except:
        await update.message.reply_text("Error")


# ========================
# /info
# ========================
async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /info BBRI")
        return

    saham = context.args[0].upper()
    if "." not in saham:
        saham += ".JK"

    try:
        info = yf.Ticker(saham).info

        text = (
            f"📊 {saham}\n"
            f"{info.get('longName','-')}\n\n"
            f"Sector: {info.get('sector','-')}\n"
            f"PE: {info.get('trailingPE','-')}\n"
            f"PB: {info.get('priceToBook','-')}"
        )

        await update.message.reply_text(text)

    except:
        await update.message.reply_text("Error")


# ========================
# /top (INDO)
# ========================
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saham_list = ["BBRI.JK","BBCA.JK","TLKM.JK","ASII.JK","BMRI.JK","ADRO.JK"]

    data_list = []

    for s in saham_list:
        hist = yf.Ticker(s).history(period="1d")
        if hist.empty:
            continue

        o = hist["Open"].iloc[-1]
        c = hist["Close"].iloc[-1]
        pct = ((c - o) / o) * 100

        data_list.append((s, pct))

    gainers = sorted(data_list, key=lambda x: x[1], reverse=True)[:3]
    losers = sorted(data_list, key=lambda x: x[1])[:3]

    text = "🔥 Top Indo Gainers:\n"
    for g in gainers:
        text += f"{g[0]} ({g[1]:+.2f}%)\n"

    text += "\n📉 Top Indo Losers:\n"
    for l in losers:
        text += f"{l[0]} ({l[1]:+.2f}%)\n"

    await update.message.reply_text(text)


# ========================
# /rsi
# ========================
async def rsi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saham = context.args[0].upper() + ".JK"

    hist = yf.Ticker(saham).history(period="1mo")

    nilai = calculate_rsi(hist)

    status = "Overbought 🔥" if nilai > 70 else "Oversold ❄️" if nilai < 30 else "Normal"

    await update.message.reply_text(
        f"📊 {saham}\nRSI: {nilai:.2f}\n{status}"
    )


# ========================
# /signal
# ========================
async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saham = context.args[0].upper() + ".JK"

    hist = yf.Ticker(saham).history(period="3mo")

    rsi_val = calculate_rsi(hist)

    ma20 = hist["Close"].rolling(20).mean().iloc[-1]
    price = hist["Close"].iloc[-1]

    if rsi_val < 30:
        sig = "🟢 BUY"
    elif rsi_val > 70:
        sig = "🔴 SELL"
    else:
        sig = "⚖️ HOLD"

    trend = "UPTREND 📈" if price > ma20 else "DOWNTREND 📉"

    await update.message.reply_text(
        f"📊 {saham}\n\n"
        f"Trend: {trend}\n"
        f"RSI: {rsi_val:.2f}\n\n"
        f"Signal: {sig}"
    )


# ========================
# /scalp (AREA SCALPING)
# ========================
async def scalp(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) == 0:
        await update.message.reply_text("Gunakan: /scalp BBRI")
        return

    saham = context.args[0].upper()
    if "." not in saham:
        saham += ".JK"

    try:
        hist = yf.Ticker(saham).history(period="1mo")

        if hist.empty:
            await update.message.reply_text("Saham tidak ditemukan")
            return

        price = hist["Close"].iloc[-1]

        support = hist["Low"].tail(20).min()
        resistance = hist["High"].tail(20).max()

        range_price = resistance - support

        buy_zone = support + (range_price * 0.25)
        sell_zone = resistance - (range_price * 0.25)

        if price <= buy_zone:
            signal = "🟢 BUY AREA"
        elif price >= sell_zone:
            signal = "🔴 TAKE PROFIT"
        else:
            signal = "⚖️ WAIT"

        await update.message.reply_text(
            f"📊 {saham}\n\n"
            f"Harga sekarang : Rp {price:,.0f}\n\n"
            f"Support : Rp {support:,.0f}\n"
            f"Resistance : Rp {resistance:,.0f}\n\n"
            f"Scalp Buy : Rp {buy_zone:,.0f}\n"
            f"Scalp Sell : Rp {sell_zone:,.0f}\n\n"
            f"Signal : {signal}"
        )

    except:
        await update.message.reply_text("Error menghitung scalping")


# ========================
# /pl
# ========================
async def pl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saham = context.args[0].upper() + ".JK"
    beli = float(context.args[1])
    lot = int(context.args[2])

    hist = yf.Ticker(saham).history(period="1d")
    now = hist["Close"].iloc[-1]

    lembar = lot * 100
    modal = beli * lembar
    nilai = now * lembar

    profit = nilai - modal
    pct = (profit / modal) * 100

    status = "🟢 PROFIT" if profit > 0 else "🔴 LOSS"

    await update.message.reply_text(
        f"{saham}\n{status}\nRp {profit:,.0f} ({pct:+.2f}%)"
    )


# ========================
# /add
# ========================
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    saham = context.args[0].upper() + ".JK"
    harga = float(context.args[1])
    lot = int(context.args[2])

    db = load_db()

    if user not in db:
        db[user] = []

    db[user].append({"saham": saham, "harga": harga, "lot": lot})

    save_db(db)

    await update.message.reply_text("✅ Ditambahkan")


# ========================
# /portfolio
# ========================
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    db = load_db()

    if user not in db:
        await update.message.reply_text("Kosong")
        return

    text = "📊 Portfolio\n\n"

    total_modal = 0
    total_now = 0

    for item in db[user]:
        saham = item["saham"]
        hist = yf.Ticker(saham).history(period="1d")

        if hist.empty:
            continue

        now = hist["Close"].iloc[-1]

        lembar = item["lot"] * 100
        modal = item["harga"] * lembar
        nilai = now * lembar

        profit = nilai - modal

        total_modal += modal
        total_now += nilai

        text += f"{saham} {profit:,.0f}\n"

    total_profit = total_now - total_modal
    pct = (total_profit / total_modal) * 100 if total_modal else 0

    text += f"\nTOTAL: {total_profit:,.0f} ({pct:+.2f}%)"

    await update.message.reply_text(text)


# ========================
# /delete
# ========================
async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    saham = context.args[0].upper() + ".JK"

    db = load_db()

    if user not in db:
        return

    db[user] = [x for x in db[user] if x["saham"] != saham]

    save_db(db)

    await update.message.reply_text("🗑️ Dihapus")


# ========================
# MAIN
# ========================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("harga", harga))
app.add_handler(CommandHandler("info", info))
app.add_handler(CommandHandler("top", top))
app.add_handler(CommandHandler("rsi", rsi))
app.add_handler(CommandHandler("signal", signal))
app.add_handler(CommandHandler("scalp", scalp))
app.add_handler(CommandHandler("pl", pl))
app.add_handler(CommandHandler("add", add))
app.add_handler(CommandHandler("portfolio", portfolio))
app.add_handler(CommandHandler("delete", delete))

print("BOT SAHAM AKTIF...")

app.run_polling()