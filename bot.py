#!/usr/bin/env python3
"""
OpenClaw AI Agent Bot
"""

import os, json, logging, requests, re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BASE_DIR  = Path.home() / ".openclaw" / "users"

# ── States ──────────────────────────────────────────────────────────────────────
(
    S_MAIN, S_CHAT,
    S_PROVIDER, S_MODEL, S_MODEL_CUSTOM,
    S_APIKEY,
    S_SKILL, S_SKILL_NAME, S_SKILL_CONTENT, S_SKILL_DEL,
    S_CUSTAPI, S_CUSTAPI_NAME, S_CUSTAPI_KEY, S_CUSTAPI_DEL,
    S_SYSPROMPT,
) = range(15)

# ── Providers ───────────────────────────────────────────────────────────────────
PROVIDERS = {
    "openai":     {"name": "🟢 OpenAI",            "key": "openaiKey",     "url": "https://api.openai.com/v1",                        "models": ["gpt-4o","gpt-4o-mini","gpt-4-turbo","gpt-3.5-turbo"]},
    "anthropic":  {"name": "🟣 Anthropic",          "key": "anthropicKey",  "url": "https://api.anthropic.com/v1",                     "models": ["claude-opus-4-5","claude-sonnet-4-5","claude-haiku-4-5"]},
    "google":     {"name": "🔵 Google Gemini",      "key": "googleKey",     "url": "https://generativelanguage.googleapis.com/v1beta/openai", "models": ["gemini-2.0-flash","gemini-1.5-pro","gemini-1.5-flash"]},
    "groq":       {"name": "⚡ Groq",               "key": "groqKey",       "url": "https://api.groq.com/openai/v1",                   "models": ["llama-3.3-70b-versatile","llama-3.1-8b-instant","mixtral-8x7b-32768"]},
    "openrouter": {"name": "🟠 OpenRouter",         "key": "openrouterKey", "url": "https://openrouter.ai/api/v1",                     "models": ["meta-llama/llama-3.3-70b-instruct","deepseek/deepseek-chat","nvidia/nemotron-3-super-120b-a12b:free"]},
    "mistral":    {"name": "🌀 Mistral",            "key": "mistralKey",    "url": "https://api.mistral.ai/v1",                        "models": ["mistral-large-latest","mistral-small-latest","open-mistral-7b"]},
}

# ── Data helpers ─────────────────────────────────────────────────────────────────
def udir(uid):
    d = BASE_DIR / str(uid); d.mkdir(parents=True, exist_ok=True); return d

def load_cfg(uid):
    p = udir(uid) / "config.json"
    try: return json.loads(p.read_text()) if p.exists() else {}
    except: return {}

def save_cfg(uid, cfg):
    (udir(uid) / "config.json").write_text(json.dumps(cfg, indent=2))

def skill_dir(uid):
    d = udir(uid) / "skills"; d.mkdir(exist_ok=True); return d

def get_skills(uid):
    return sorted(skill_dir(uid).glob("*.md"))

def mask(k):
    if not k or len(k) < 8: return "❌ Belum diset"
    return f"✅ `{k[:6]}...{k[-4:]}`"

# ── AI call ──────────────────────────────────────────────────────────────────────
def call_ai(pid, api_key, model, messages, system=""):
    p = PROVIDERS[pid]
    hdrs = {"Content-Type":"application/json","Authorization":f"Bearer {api_key}"}

    if pid == "anthropic":
        hdrs = {"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"}
        body = {"model":model,"max_tokens":2048,"messages":messages}
        if system: body["system"] = system
        try:
            r = requests.post(f"{p['url']}/messages", headers=hdrs, json=body, timeout=60)
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        except Exception as e: return f"❌ Error: {e}"

    msgs = ([{"role":"system","content":system}] if system else []) + messages
    body = {"model":model,"max_tokens":2048,"messages":msgs}
    try:
        r = requests.post(f"{p['url']}/chat/completions", headers=hdrs, json=body, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"❌ Error: {e}"

def build_system(uid, custom=""):
    skills = get_skills(uid)
    parts = []
    if custom:
        parts.append(custom)
    if skills:
        skill_texts = []
        for s in skills:
            try:
                isi = s.read_text(encoding="utf-8").strip()
                skill_texts.append(f"### Skill: {s.stem}\n{isi}")
                logger.info(f"Skill loaded: {s.stem} ({len(isi)} chars)")
            except Exception as e:
                logger.error(f"Gagal baca skill {s}: {e}")
        if skill_texts:
            parts.append("Ikuti instruksi skill berikut dengan ketat:\n\n" + "\n\n".join(skill_texts))
    if not parts:
        parts.append("Kamu adalah asisten AI yang membantu.")
    system = "\n\n".join(parts)
    logger.info(f"System prompt length: {len(system)} chars, skills: {len(skills)}")
    return system

# ── DexScreener ──────────────────────────────────────────────────────────────────
def is_address(txt):
    t = txt.strip()
    if re.match(r"^0x[a-fA-F0-9]{40}$", t): return True
    if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", t): return True
    return False

def fetch_dex(address):
    hdrs = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
    for url in [
        f"https://api.dexscreener.com/latest/dex/tokens/{address}",
        f"https://api.dexscreener.com/latest/dex/search?q={address}",
    ]:
        try:
            r = requests.get(url, headers=hdrs, timeout=15)
            if r.status_code == 200:
                pairs = r.json().get("pairs")
                if pairs:
                    return sorted(pairs, key=lambda p: float(p.get("liquidity",{}).get("usd",0) or 0), reverse=True)
        except: continue
    return None

def fmt_dex(pairs):
    if not pairs: return "❌ Token tidak ditemukan."
    p = pairs[0]
    base = p.get("baseToken",{})
    def num(n):
        try:
            n=float(n)
            if n>=1e9: return f"${n/1e9:.2f}B"
            if n>=1e6: return f"${n/1e6:.2f}M"
            if n>=1e3: return f"${n/1e3:.2f}K"
            return f"${n:.6f}"
        except: return str(n)
    def pct(v):
        try:
            v=float(v); a="🟢" if v>=0 else "🔴"; return f"{a} {v:+.2f}%"
        except: return "-"
    chg = p.get("priceChange",{})
    vol = p.get("volume",{})
    txn = p.get("txns",{}).get("h24",{})
    lines = [
        f"🔍 {base.get('name','?')} ({base.get('symbol','?')})",
        f"⛓ {p.get('chainId','?').upper()} | {p.get('dexId','?')}",
        f"",
        f"💰 Harga: ${p.get('priceUsd','?')}",
        f"📊 5m {pct(chg.get('m5'))} | 1h {pct(chg.get('h1'))} | 24h {pct(chg.get('h24'))}",
        f"",
        f"💧 Liquidity: {num(p.get('liquidity',{}).get('usd',0))}",
        f"📈 Volume 24h: {num(vol.get('h24',0))}",
        f"🏦 Market Cap: {num(p.get('marketCap',0)) if p.get('marketCap') else 'N/A'}",
        f"🔄 Txn 24h: {txn.get('buys',0)} beli | {txn.get('sells',0)} jual",
    ]
    if len(pairs) > 1:
        lines += ["", f"📋 {len(pairs)} pairs ditemukan. Top 3:"]
        for i,pp in enumerate(pairs[:3],1):
            lines.append(f"  {i}. {pp.get('chainId','?').upper()} | {pp.get('dexId','?')} | Liq: {num(pp.get('liquidity',{}).get('usd',0))}")
    if p.get("url"): lines += ["", f"🔗 {p['url']}"]
    return "\n".join(lines)

# ── Keyboards ────────────────────────────────────────────────────────────────────
def kb_main(uid=0):
    cfg = load_cfg(uid)
    dex = cfg.get("dex_on", False)
    dex_lbl = f"📡 Crypto {'🟢 ON' if dex else '⚫ OFF'}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Mulai Chat", callback_data="chat")],
        [InlineKeyboardButton(dex_lbl, callback_data="toggle_dex")],
        [InlineKeyboardButton("⚙️ Provider & Model", callback_data="provider")],
        [InlineKeyboardButton("🔑 Kelola API Key", callback_data="apikey")],
        [InlineKeyboardButton("🔌 Custom API", callback_data="custapi")],
        [InlineKeyboardButton("🧠 Kelola Skill", callback_data="skill")],
        [InlineKeyboardButton("📊 Status", callback_data="status")],
    ])

def kb_back(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu Utama", callback_data="main")]])
def kb_cancel(): return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Batal", callback_data="main")]])
def kb_chat(): return InlineKeyboardMarkup([
    [InlineKeyboardButton("🗑 Hapus Riwayat", callback_data="chat_clear")],
    [InlineKeyboardButton("📝 System Prompt", callback_data="chat_sysprompt")],
    [InlineKeyboardButton("🔙 Menu Utama", callback_data="chat_exit")],
])

# ── /start ───────────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name
    cfg = load_cfg(uid)
    if not cfg:
        save_cfg(uid, {})

    disclaimer = (
        "⚠️ *Disclaimer*\n\n"
        "Penggunaan bot ini sepenuhnya menjadi tanggung jawab pengguna. "
        "Data pribadi maupun informasi apapun yang dibagikan ke dalam bot ini "
        "berada di luar tanggung jawab pembuat bot.\n\n"
        "Dengan menggunakan bot ini, kamu dianggap telah memahami dan menyetujui hal tersebut.\n\n"
        "- Terima kasih 🙏"
    )

    await update.message.reply_text(disclaimer, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Saya Mengerti, Lanjutkan", callback_data="disclaimer_ok")
        ]]))
    return S_MAIN

# ── Main callback ────────────────────────────────────────────────────────────────
async def cb_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    d = q.data

    if d in ("main", "disclaimer_ok"):
        name = q.from_user.first_name
        txt = f"😸 Halo *{name}*! Selamat datang di BatBut Bot\n\nMau ngapain?" if d == "disclaimer_ok" else "😸 *Menu Utama*"
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb_main(uid))
        return S_MAIN

    if d == "toggle_dex":
        cfg = load_cfg(uid)
        cfg["dex_on"] = not cfg.get("dex_on", False)
        save_cfg(uid, cfg)
        status = "🟢 ON — Kirim alamat kontrak token di chat untuk cek harga!" if cfg["dex_on"] else "⚫ OFF"
        await q.answer(f"Crypto {status}", show_alert=True)
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid))
        return S_MAIN

    if d == "chat":
        cfg = load_cfg(uid)
        pid = cfg.get("provider","")
        mdl = cfg.get("model","")
        akey = cfg.get(PROVIDERS.get(pid,{}).get("key",""),"") if pid else ""
        if not pid or not mdl:
            await q.edit_message_text("⚠️ Set *Provider & Model* dulu!", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Set Sekarang", callback_data="provider"),InlineKeyboardButton("🔙 Kembali", callback_data="main")]]))
            return S_MAIN
        if not akey:
            await q.edit_message_text("⚠️ Set *API Key* dulu!", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 Set Sekarang", callback_data="apikey"),InlineKeyboardButton("🔙 Kembali", callback_data="main")]]))
            return S_MAIN
        ctx.user_data["history"] = []
        pname = PROVIDERS[pid]["name"]
        dex_info = " | 📡 Crypto ON" if cfg.get("dex_on") else ""
        await q.edit_message_text(
            f"💬 *Mode Chat*\n{pname} | `{mdl}`{dex_info}\n\nKetik pesanmu:",
            parse_mode="Markdown", reply_markup=kb_chat())
        return S_CHAT

    if d == "status":
        cfg = load_cfg(uid)
        pid = cfg.get("provider","")
        mdl = cfg.get("model","belum diset")
        pname = PROVIDERS.get(pid,{}).get("name", "❌ Belum diset")
        akey = cfg.get(PROVIDERS.get(pid,{}).get("key",""),"") if pid else ""
        key_ok = "✅" if akey else "⚠️ Key belum diset!"
        keys_n = sum(1 for p in PROVIDERS.values() if cfg.get(p["key"],""))
        skills_n = len(get_skills(uid))
        capis_n = len(cfg.get("custom_apis",{}))
        dex = "🟢 ON" if cfg.get("dex_on") else "⚫ OFF"
        sysp = "✅" if cfg.get("system_prompt") else "❌"
        await q.edit_message_text(
            f"📊 *Status*\n\n"
            f"🔌 Provider: {pname} {key_ok}\n"
            f"🤖 Model: `{mdl}`\n"
            f"🔑 API Key: {keys_n}/{len(PROVIDERS)}\n"
            f"🔌 Custom API: {capis_n}\n"
            f"🧠 Skill: {skills_n}\n"
            f"📡 Crypto: {dex}\n"
            f"📝 System Prompt: {sysp}",
            parse_mode="Markdown", reply_markup=kb_back())
        return S_MAIN

    if d == "provider":
        rows = [[InlineKeyboardButton(v["name"], callback_data=f"prov_{k}")] for k,v in PROVIDERS.items()]
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text("⚙️ *Pilih Provider:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_PROVIDER

    if d == "apikey":
        cfg = load_cfg(uid)
        rows = []
        for k,v in PROVIDERS.items():
            has = bool(cfg.get(v["key"],""))
            s = "✅" if has else "❌"
            row = [InlineKeyboardButton(f"{s} {v['name']}", callback_data=f"setkey_{k}")]
            if has: row.append(InlineKeyboardButton("🗑", callback_data=f"delkey_{k}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text("🔑 *Kelola API Key:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_APIKEY

    if d == "skill":
        skills = get_skills(uid)
        rows = []
        for s in skills:
            rows.append([
                InlineKeyboardButton(f"📄 {s.stem}", callback_data=f"skill_view_{s.stem}"),
                InlineKeyboardButton("🗑", callback_data=f"skill_del_{s.stem}"),
            ])
        rows.append([InlineKeyboardButton("➕ Tambah Skill", callback_data="skill_add")])
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text(f"🧠 *Skill* ({len(skills)} aktif):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_SKILL

    if d == "custapi":
        cfg = load_cfg(uid)
        apis = cfg.get("custom_apis", {})
        rows = []
        for name,val in apis.items():
            m = f"{val[:6]}...{val[-4:]}" if len(val)>=10 else "***"
            rows.append([
                InlineKeyboardButton(f"🔌 {name} ({m})", callback_data=f"capi_view_{name}"),
                InlineKeyboardButton("🗑", callback_data=f"capi_del_{name}"),
            ])
        rows.append([InlineKeyboardButton("➕ Tambah Custom API", callback_data="capi_add")])
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text(f"🔌 *Custom API* ({len(apis)} tersimpan):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_CUSTAPI

    return S_MAIN

# ── Provider callback ─────────────────────────────────────────────────────────────
async def cb_provider(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "main":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN

    if d.startswith("prov_"):
        pid = d[5:]
        ctx.user_data["sel_provider"] = pid
        cfg = load_cfg(uid)
        cur = cfg.get("model","-")
        models = PROVIDERS[pid]["models"]
        rows = [[InlineKeyboardButton(m, callback_data=f"mdl_{pid}_{m}")] for m in models]
        rows.append([InlineKeyboardButton("✏️ Model Custom", callback_data=f"mdl_{pid}_custom")])
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text(f"🤖 *{PROVIDERS[pid]['name']}*\nModel sekarang: `{cur}`\n\nPilih model:",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_MODEL

    return S_PROVIDER

# ── Model callback ────────────────────────────────────────────────────────────────
async def cb_model(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "main":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN

    if d.startswith("mdl_"):
        parts = d.split("_", 2); pid = parts[1]; mdl = parts[2]
        if mdl == "custom":
            ctx.user_data["sel_provider"] = pid
            await q.edit_message_text(f"✏️ Ketik nama model custom untuk *{PROVIDERS[pid]['name']}*:\n\n/batal untuk kembali",
                parse_mode="Markdown"); return S_MODEL_CUSTOM
        cfg = load_cfg(uid)
        cfg["provider"] = pid; cfg["model"] = mdl
        save_cfg(uid, cfg)
        await q.edit_message_text(f"✅ Provider: *{PROVIDERS[pid]['name']}*\n🤖 Model: *{mdl}*",
            parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN

    return S_MODEL

async def recv_model_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = ctx.user_data.get("sel_provider","openai")
    mdl = update.message.text.strip()
    cfg = load_cfg(uid); cfg["provider"] = pid; cfg["model"] = mdl; save_cfg(uid, cfg)
    await update.message.reply_text(f"✅ Provider: *{PROVIDERS[pid]['name']}*\n🤖 Model: *{mdl}*",
        parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN

# ── API Key callback ──────────────────────────────────────────────────────────────
async def cb_apikey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "main":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN
    if d == "apikey":
        cfg = load_cfg(uid)
        rows = []
        for k,v in PROVIDERS.items():
            has = bool(cfg.get(v["key"],""))
            s = "✅" if has else "❌"
            row = [InlineKeyboardButton(f"{s} {v['name']}", callback_data=f"setkey_{k}")]
            if has: row.append(InlineKeyboardButton("🗑", callback_data=f"delkey_{k}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text("🔑 *Kelola API Key:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_APIKEY

    if d.startswith("setkey_"):
        pid = d[7:]
        ctx.user_data["setkey_pid"] = pid
        cfg = load_cfg(uid)
        cur = mask(cfg.get(PROVIDERS[pid]["key"],""))
        await q.edit_message_text(
            f"🔑 *{PROVIDERS[pid]['name']}*\nKey sekarang: {cur}\n\nKirim API key baru:\n_(pesan otomatis dihapus)_\n\n/batal",
            parse_mode="Markdown"); return S_APIKEY

    if d.startswith("delkey_"):
        pid = d[7:]
        cfg = load_cfg(uid); cfg.pop(PROVIDERS[pid]["key"], None); save_cfg(uid, cfg)
        await q.answer(f"✅ Key {PROVIDERS[pid]['name']} dihapus!", show_alert=True)
        # refresh
        rows = []
        for k,v in PROVIDERS.items():
            has = bool(cfg.get(v["key"],""))
            s = "✅" if has else "❌"
            row = [InlineKeyboardButton(f"{s} {v['name']}", callback_data=f"setkey_{k}")]
            if has: row.append(InlineKeyboardButton("🗑", callback_data=f"delkey_{k}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Kembali", callback_data="main")])
        await q.edit_message_text("🔑 *Kelola API Key:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_APIKEY

    return S_APIKEY

async def recv_apikey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pid = ctx.user_data.get("setkey_pid","openai")
    key = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    cfg = load_cfg(uid); cfg[PROVIDERS[pid]["key"]] = key; save_cfg(uid, cfg)
    await update.message.reply_text(f"✅ API key *{PROVIDERS[pid]['name']}* disimpan!\n{mask(key)}",
        parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN

# ── Skill callback ────────────────────────────────────────────────────────────────
async def cb_skill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "main":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN
    if d == "skill":
        skills = get_skills(uid)
        rows = []
        for s in skills:
            rows.append([InlineKeyboardButton(f"📄 {s.stem}", callback_data=f"skill_view_{s.stem}"),InlineKeyboardButton("🗑", callback_data=f"skill_del_{s.stem}")])
        rows += [[InlineKeyboardButton("➕ Tambah Skill", callback_data="skill_add")],[InlineKeyboardButton("🔙 Kembali", callback_data="main")]]
        await q.edit_message_text(f"🧠 *Skill* ({len(skills)}):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows)); return S_SKILL
    if d == "skill_add":
        await q.edit_message_text("➕ Ketik *nama skill* (tanpa spasi):\n\n/batal", parse_mode="Markdown"); return S_SKILL_NAME
    if d.startswith("skill_view_"):
        name = d[11:]
        f2 = skill_dir(uid)/f"{name}.md"
        txt = f2.read_text()[:2000] if f2.exists() else "?"
        await q.edit_message_text(f"📄 *{name}*\n\n```\n{txt}\n```", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Hapus", callback_data=f"skill_del_{name}"),InlineKeyboardButton("🔙", callback_data="skill")]])); return S_SKILL
    if d.startswith("skill_del_"):
        name = d[10:]
        f2 = skill_dir(uid)/f"{name}.md"
        if f2.exists(): f2.unlink()
        await q.answer("✅ Skill dihapus!", show_alert=True)
        skills = get_skills(uid)
        rows = []
        for s in skills:
            rows.append([InlineKeyboardButton(f"📄 {s.stem}", callback_data=f"skill_view_{s.stem}"),InlineKeyboardButton("🗑", callback_data=f"skill_del_{s.stem}")])
        rows += [[InlineKeyboardButton("➕ Tambah Skill", callback_data="skill_add")],[InlineKeyboardButton("🔙 Kembali", callback_data="main")]]
        await q.edit_message_text(f"🧠 *Skill* ({len(skills)}):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows)); return S_SKILL
    return S_SKILL

async def recv_skill_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.message.text.strip().replace(" ","_")
    ctx.user_data["skill_name"] = name
    await update.message.reply_text(f"📝 Nama: *{name}*\n\nSekarang ketik *isi skill* (instruksi untuk AI):\n\n/batal", parse_mode="Markdown")
    return S_SKILL_CONTENT

async def recv_skill_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = ctx.user_data.get("skill_name","skill")
    skill_path = skill_dir(uid) / f"{name}.md"
    skill_path.write_text(update.message.text.strip(), encoding="utf-8")
    skills_total = len(get_skills(uid))
    await update.message.reply_text(
        "\u2705 Skill *" + name + "* berhasil disimpan!\n\U0001F9E0 Total skill aktif: *" + str(skills_total) + "*",
        parse_mode="Markdown", reply_markup=kb_main(uid))
    return S_MAIN

# ── Custom API callback ───────────────────────────────────────────────────────────
async def cb_custapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "main":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN
    if d == "capi_add":
        await q.edit_message_text("➕ Ketik *nama* API (tanpa spasi):\nContoh: `dextools`, `binance`\n\n/batal", parse_mode="Markdown")
        return S_CUSTAPI_NAME
    if d.startswith("capi_del_"):
        name = d[9:]
        cfg = load_cfg(uid); cfg.setdefault("custom_apis",{}).pop(name,None); save_cfg(uid,cfg)
        await q.answer(f"✅ {name} dihapus!", show_alert=True)
        apis = cfg.get("custom_apis",{})
        rows = []
        for n,v in apis.items():
            m = f"{v[:6]}...{v[-4:]}" if len(v)>=10 else "***"
            rows.append([InlineKeyboardButton(f"🔌 {n} ({m})", callback_data=f"capi_view_{n}"),InlineKeyboardButton("🗑", callback_data=f"capi_del_{n}")])
        rows += [[InlineKeyboardButton("➕ Tambah Custom API", callback_data="capi_add")],[InlineKeyboardButton("🔙 Kembali", callback_data="main")]]
        await q.edit_message_text(f"🔌 *Custom API* ({len(apis)}):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_CUSTAPI
    if d.startswith("capi_view_"):
        name = d[10:]
        cfg = load_cfg(uid); val = cfg.get("custom_apis",{}).get(name,"")
        m = f"{val[:6]}...{val[-4:]}" if len(val)>=10 else "***"
        await q.edit_message_text(f"🔌 *{name}*\nKey: `{m}`", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Ganti", callback_data=f"capi_edit_{name}"),InlineKeyboardButton("🗑 Hapus", callback_data=f"capi_del_{name}")],[InlineKeyboardButton("🔙", callback_data="custapi")]]))
        return S_CUSTAPI
    if d.startswith("capi_edit_"):
        name = d[10:]; ctx.user_data["capi_name"] = name
        await q.edit_message_text(f"✏️ Kirim key baru untuk *{name}*:\n_(pesan otomatis dihapus)_\n\n/batal", parse_mode="Markdown")
        return S_CUSTAPI_KEY
    if d == "custapi":
        cfg = load_cfg(uid); apis = cfg.get("custom_apis",{})
        rows = []
        for n,v in apis.items():
            m = f"{v[:6]}...{v[-4:]}" if len(v)>=10 else "***"
            rows.append([InlineKeyboardButton(f"🔌 {n} ({m})", callback_data=f"capi_view_{n}"),InlineKeyboardButton("🗑", callback_data=f"capi_del_{n}")])
        rows += [[InlineKeyboardButton("➕ Tambah Custom API", callback_data="capi_add")],[InlineKeyboardButton("🔙 Kembali", callback_data="main")]]
        await q.edit_message_text(f"🔌 *Custom API* ({len(apis)}):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
        return S_CUSTAPI
    return S_CUSTAPI

async def recv_custapi_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip().replace(" ","_")
    ctx.user_data["capi_name"] = name
    await update.message.reply_text(f"🔌 Nama: *{name}*\n\nKirim API key-nya:\n_(pesan otomatis dihapus)_\n\n/batal", parse_mode="Markdown")
    return S_CUSTAPI_KEY

async def recv_custapi_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = ctx.user_data.get("capi_name","api")
    key = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    cfg = load_cfg(uid); cfg.setdefault("custom_apis",{})[name] = key; save_cfg(uid,cfg)
    m = f"{key[:6]}...{key[-4:]}" if len(key)>=10 else "***"
    await update.message.reply_text(f"✅ *{name}* disimpan!\nKey: `{m}`", parse_mode="Markdown", reply_markup=kb_main(uid))
    return S_MAIN

# ── Chat handlers ─────────────────────────────────────────────────────────────────
async def cb_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; d = q.data

    if d == "chat_exit":
        await q.edit_message_text("😸 *Menu Utama*", parse_mode="Markdown", reply_markup=kb_main(uid)); return S_MAIN
    if d == "chat_clear":
        ctx.user_data["history"] = []
        await q.answer("✅ Riwayat dihapus!", show_alert=False); return S_CHAT
    if d == "chat_sysprompt":
        await q.edit_message_text("📝 Ketik system prompt baru:\n_(Ketik /kosong untuk hapus)_\n\n/batal", parse_mode="Markdown")
        return S_SYSPROMPT
    return S_CHAT

async def recv_sysprompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.strip()
    cfg = load_cfg(uid)
    if txt == "/kosong":
        cfg.pop("system_prompt",None); save_cfg(uid,cfg)
        await update.message.reply_text("✅ System prompt dihapus.", reply_markup=kb_chat())
    else:
        cfg["system_prompt"] = txt; save_cfg(uid,cfg)
        await update.message.reply_text(f"✅ System prompt disimpan!", reply_markup=kb_chat())
    return S_CHAT

async def recv_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = update.message.text.strip()
    cfg = load_cfg(uid)

    # Cek contract address kalau dex ON
    if cfg.get("dex_on") and is_address(txt):
        msg = await update.message.reply_text("📡 Mengambil data token...")
        pairs = fetch_dex(txt)
        await msg.delete()
        if not pairs:
            await update.message.reply_text("❌ Token tidak ditemukan di DexScreener.\nPastikan alamat kontrak benar.", reply_markup=kb_chat())
            return S_CHAT
        dex_txt = fmt_dex(pairs)
        pid = cfg.get("provider",""); mdl = cfg.get("model",""); akey = cfg.get(PROVIDERS.get(pid,{}).get("key",""),"") if pid else ""
        if pid and mdl and akey:
            msg2 = await update.message.reply_text("🤖 AI menganalisis...")
            ai_txt = call_ai(pid, akey, mdl, [{"role":"user","content":f"Analisis singkat token ini dalam 2-3 kalimat:\n\n{dex_txt}"}],
                "Kamu analis crypto. Jawab singkat dan netral.")
            await msg2.delete()
            await update.message.reply_text(dex_txt + "\n\n─────\n🤖 Analisis AI:\n" + ai_txt, reply_markup=kb_chat())
        else:
            await update.message.reply_text(dex_txt, reply_markup=kb_chat())
        return S_CHAT

    # Chat biasa
    pid = cfg.get("provider",""); mdl = cfg.get("model",""); akey = cfg.get(PROVIDERS.get(pid,{}).get("key",""),"") if pid else ""
    if not pid or not mdl or not akey:
        await update.message.reply_text("⚠️ Konfigurasi belum lengkap!", reply_markup=kb_main(uid)); return S_MAIN

    if "history" not in ctx.user_data: ctx.user_data["history"] = []
    ctx.user_data["history"].append({"role":"user","content":txt})

    msg = await update.message.reply_text("⏳ _Berpikir..._", parse_mode="Markdown")
    reply = call_ai(pid, akey, mdl, ctx.user_data["history"], build_system(uid, cfg.get("system_prompt","")))
    ctx.user_data["history"].append({"role":"assistant","content":reply})
    await msg.delete()

    if len(reply) > 4000:
        for i in range(0,len(reply),4000): await update.message.reply_text(reply[i:i+4000])
    else:
        await update.message.reply_text(reply, reply_markup=kb_chat())
    return S_CHAT

# ── Cancel ────────────────────────────────────────────────────────────────────────
async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text("🔙 Kembali ke menu.", reply_markup=kb_main(uid))
    return S_MAIN

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Daftar Command:*\n\n"
        "/start - Buka menu utama\n"
        "/help - Tampilkan daftar command\n"
        "/api - Kelola API Key\n"
        "/skill - Kelola Skill\n"
        "/status - Lihat status konfigurasi\n"
        "/clear - Hapus riwayat chat\n"
        "/batal - Batalkan aksi saat ini\n\n"
        "💡 *Tips:*\n"
        "Aktifkan 📡 Crypto lalu kirim alamat kontrak token untuk cek harga.",
        parse_mode="Markdown",
        reply_markup=kb_main(update.effective_user.id)
    )
    return S_MAIN

async def cmd_api(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = load_cfg(uid)
    rows = []
    for k,v in PROVIDERS.items():
        has = bool(cfg.get(v["key"],""))
        s = "✅" if has else "❌"
        row = [InlineKeyboardButton(f"{s} {v['name']}", callback_data=f"setkey_{k}")]
        if has: row.append(InlineKeyboardButton("🗑", callback_data=f"delkey_{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Menu Utama", callback_data="main")])
    await update.message.reply_text("🔑 *Kelola API Key:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    return S_APIKEY

async def cmd_skill(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    skills = get_skills(uid)
    rows = []
    for s in skills:
        rows.append([InlineKeyboardButton(f"📄 {s.stem}", callback_data=f"skill_view_{s.stem}"),
                     InlineKeyboardButton("🗑", callback_data=f"skill_del_{s.stem}")])
    rows += [[InlineKeyboardButton("➕ Tambah Skill", callback_data="skill_add")],
             [InlineKeyboardButton("🔙 Menu Utama", callback_data="main")]]
    await update.message.reply_text(f"🧠 *Skill* ({len(skills)} aktif):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    return S_SKILL

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = load_cfg(uid)
    pid = cfg.get("provider","")
    mdl = cfg.get("model","belum diset")
    pname = PROVIDERS.get(pid,{}).get("name","❌ Belum diset")
    akey = cfg.get(PROVIDERS.get(pid,{}).get("key",""),"") if pid else ""
    key_ok = "✅" if akey else "⚠️ Key belum diset!"
    keys_n = sum(1 for p in PROVIDERS.values() if cfg.get(p["key"],""))
    skills_n = len(get_skills(uid))
    capis_n = len(cfg.get("custom_apis",{}))
    dex = "🟢 ON" if cfg.get("dex_on") else "⚫ OFF"
    sysp = "✅" if cfg.get("system_prompt") else "❌"
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"🔌 Provider: {pname} {key_ok}\n"
        f"🤖 Model: `{mdl}`\n"
        f"🔑 API Key: {keys_n}/{len(PROVIDERS)}\n"
        f"🔌 Custom API: {capis_n}\n"
        f"🧠 Skill: {skills_n}\n"
        f"📡 Crypto: {dex}\n"
        f"📝 System Prompt: {sysp}",
        parse_mode="Markdown", reply_markup=kb_main(uid))
    return S_MAIN

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["history"] = []
    await update.message.reply_text("✅ Riwayat chat dihapus!", reply_markup=kb_main(update.effective_user.id))
    return S_MAIN

async def cmd_customapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cfg = load_cfg(uid)
    apis = cfg.get("custom_apis", {})
    rows = []
    for name, val in apis.items():
        m = f"{val[:6]}...{val[-4:]}" if len(val) >= 10 else "***"
        rows.append([
            InlineKeyboardButton(f"🔌 {name} ({m})", callback_data=f"capi_view_{name}"),
            InlineKeyboardButton("🗑", callback_data=f"capi_del_{name}"),
        ])
    rows += [
        [InlineKeyboardButton("➕ Tambah Custom API", callback_data="capi_add")],
        [InlineKeyboardButton("🔙 Menu Utama", callback_data="main")],
    ]
    await update.message.reply_text(f"🔌 *Custom API* ({len(apis)} tersimpan):", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    return S_CUSTAPI

# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            S_MAIN:         [CallbackQueryHandler(cb_main)],
            S_CHAT:         [CallbackQueryHandler(cb_chat), MessageHandler(filters.TEXT & ~filters.COMMAND, recv_chat)],
            S_SYSPROMPT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_sysprompt), CommandHandler("batal", cmd_cancel), CommandHandler("kosong", recv_sysprompt)],
            S_PROVIDER:     [CallbackQueryHandler(cb_provider)],
            S_MODEL:        [CallbackQueryHandler(cb_model)],
            S_MODEL_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_model_custom), CommandHandler("batal", cmd_cancel)],
            S_APIKEY:       [CallbackQueryHandler(cb_apikey), MessageHandler(filters.TEXT & ~filters.COMMAND, recv_apikey)],
            S_SKILL:        [CallbackQueryHandler(cb_skill)],
            S_SKILL_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_skill_name), CommandHandler("batal", cmd_cancel)],
            S_SKILL_CONTENT:[MessageHandler(filters.TEXT & ~filters.COMMAND, recv_skill_content), CommandHandler("batal", cmd_cancel)],
            S_CUSTAPI:      [CallbackQueryHandler(cb_custapi)],
            S_CUSTAPI_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_custapi_name), CommandHandler("batal", cmd_cancel)],
            S_CUSTAPI_KEY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_custapi_key), CommandHandler("batal", cmd_cancel)],
        },
        fallbacks=[CommandHandler("batal", cmd_cancel), CommandHandler("start", cmd_start)],
        per_user=True,
        per_chat=False,
        per_message=False,
    )

    app.add_handler(conv)
    # Command shortcuts
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("api",    cmd_api))
    app.add_handler(CommandHandler("skill",  cmd_skill))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear",     cmd_clear))
    app.add_handler(CommandHandler("customapi",  cmd_customapi))
    logger.info("🦞 OpenClaw Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
