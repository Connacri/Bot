"""Bot Telegram de parrainage - version 100% gratuite (Render Web Service gratuit + Neon Postgres).

Variables d'environnement :
  BOT_TOKEN     token BotFather
  CHANNEL_URL   lien de ta chaîne
  DATABASE_URL  chaîne de connexion Postgres (Neon)
  PORT          fourni automatiquement par Render

import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_URL = os.environ.get("CHANNEL_URL", "https://t.me/ta_chaine")
DATABASE_URL = os.environ["DATABASE_URL"]

PALIERS = {
    3: "🎁 Palier 3 : ta liste « 20 logiciels gratuits indispensables » : https://exemple.com/liste20",
    10: "🔥 Palier 10 : le guide « Alternatives gratuites aux logiciels payants » : https://exemple.com/guide",
    25: "👑 Palier 25 : accès au groupe VIP : https://t.me/+lien_prive",
}

WELCOME_GIFT = (
    "🎉 Bienvenue ! Voici ton cadeau : une sélection de logiciels 100% gratuits et légaux.\\n"
    "• LibreOffice (bureautique)\\n• GIMP (retouche photo)\\n• OBS Studio (capture/streaming)\\n"
    "• VLC (lecteur vidéo)\\n• Bitwarden (mots de passe)\\n"
)

# ---------- Base de données (une connexion par requête : adapté à Neon) ----------
def q(sql, params=(), fetch=None):
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()

q(
    """CREATE TABLE IF NOT EXISTS users (
        id BIGINT PRIMARY KEY,
        name TEXT,
        referrer BIGINT,
        referrals INTEGER DEFAULT 0
    )"""
)

# ---------- Mini serveur HTTP : requis par Render + cible d'UptimeRobot ----------
class Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def run_http():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), Ping).serve_forever()

# ---------- Bot ----------
def my_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = q("SELECT 1 FROM users WHERE id=%s", (user.id,), "one") is None

    if is_new:
        referrer = None
        if context.args and context.args[0].startswith("ref_"):
            try:
                candidate = int(context.args[0][4:])
            except ValueError:
                candidate = None
            if candidate and candidate != user.id and q(
                "SELECT 1 FROM users WHERE id=%s", (candidate,), "one"
            ):
                referrer = candidate

        q(
            "INSERT INTO users (id, name, referrer) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (user.id, user.first_name, referrer),
        )
        if referrer:
            q("UPDATE users SET referrals = referrals + 1 WHERE id=%s", (referrer,))
            await notify_referrer(context, referrer, user.first_name)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📢 Rejoindre la chaîne", url=CHANNEL_URL)]]
    )
    link = my_link(context.bot.username, user.id)
    await update.message.reply_text(
        f"{WELCOME_GIFT}\\n"
        f"🚀 Invite tes amis avec ton lien perso pour débloquer des bonus :\\n{link}\\n\\n"
        "Commandes : /monlien  /stats  /top",
        reply_markup=keyboard,
    )


async def notify_referrer(context, referrer_id: int, new_name: str):
    count = q("SELECT referrals FROM users WHERE id=%s", (referrer_id,), "one")[0]
    text = f"✅ {new_name} a rejoint grâce à toi ! Tu as {count} filleul(s)."
    if count in PALIERS:
        text += f"\\n\\n{PALIERS[count]}"
    try:
        await context.bot.send_message(referrer_id, text)
    except Exception:
        pass


async def monlien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = my_link(context.bot.username, update.effective_user.id)
    await update.message.reply_text(f"🔗 Ton lien de parrainage :\\n{link}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = q("SELECT referrals FROM users WHERE id=%s", (update.effective_user.id,), "one")
    count = row[0] if row else 0
    prochain = next((p for p in sorted(PALIERS) if p > count), None)
    msg = f"📊 Tu as {count} filleul(s)."
    if prochain:
        msg += f"\\nProchain palier : {prochain} (encore {prochain - count})."
    else:
        msg += "\\nTous les paliers sont débloqués 👑"
    await update.message.reply_text(msg)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = q(
        "SELECT name, referrals FROM users WHERE referrals > 0 ORDER BY referrals DESC LIMIT 10",
        fetch="all",
    )
    if not rows:
        await update.message.reply_text("Pas encore de classement. Sois le premier ! 🚀")
        return
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    lines = [f"{medals[i]} {name} : {n}" for i, (name, n) in enumerate(rows)]
    await update.message.reply_text("🏆 Top parrains\\n\\n" + "\\n".join(lines))


def main():
    threading.Thread(target=run_http, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("monlien", monlien))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.run_polling()


if __name__ == "__main__":
    main()
