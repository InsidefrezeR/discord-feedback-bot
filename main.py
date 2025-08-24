# -*- coding: utf-8 -*-
# Feedback Bot — Doppio anchor (vecchio+nuovo), bottone persistente, DM de-duplicati, forward su due canali
# Requisiti: python 3.10+, pip install -U discord.py Flask python-dotenv

from flask import Flask
from threading import Thread
import os, json, asyncio
import discord
from discord.ext import commands
from discord.ui import Button, View

# ============ CONFIG FISSA ============
SOURCE_GUILD_ID  = 1310417606607634432  # Vecchio server
TARGET_GUILD_ID  = 1407462539289165884  # Nuovo server

# Canali "anchor" (embed + bottone)
BUTTON_CHANNEL_ID_OLD = 1401005055783735442
BUTTON_CHANNEL_ID_NEW = 1407515405034979428  # se vuoi un canale diverso nel nuovo server, metti l'ID qui

# Canali di forward dai DM
FORWARD_CHANNEL_ID_OLD = 1401005055783735442
FORWARD_CHANNEL_ID_NEW = 1407515405034979428

# Canali log
LOG_CHANNEL_OLD = 1401163197767221370
LOG_CHANNEL_NEW = 1407489479752552510

# Ping ruolo (opzionale): metti un ID oppure None
PING_ROLE_ID = None

# Marcatore per ancorare il messaggio
ANCHOR_MARK = "[FEEDBACK_ANCHOR]"

# Persistenza dedup DM
SEEN_STORE_PATH = "/mnt/data/dm_seen.json"
PROCESSED_DM_IDS = set()

# ============ KEEP ALIVE (Flask) ============
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

# ============ UTILS DEDUP ============
def load_seen():
    try:
        with open(SEEN_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                PROCESSED_DM_IDS.update(data[-5000:])  # limita dimensione
    except Exception:
        pass

def save_seen():
    try:
        os.makedirs(os.path.dirname(SEEN_STORE_PATH), exist_ok=True)
        # salva solo ultimi 5000
        arr = list(PROCESSED_DM_IDS)[-5000:]
        with open(SEEN_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(arr, f)
    except Exception as e:
        print(f"[SEEN] Save error: {e}")

# ============ DISCORD BOT ============
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---- Helpers canali (cache-safe) ----
async def get_text_channel(channel_id: int) -> discord.TextChannel | None:
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            ch = None
    return ch if isinstance(ch, discord.TextChannel) else None

# ---- Persistent View (bottone) ----
class FeedbackView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistente ai riavvii

    @discord.ui.button(
        label="📝 Lascia il tuo Feedback",
        style=discord.ButtonStyle.primary,
        custom_id="feedback:open_dm"  # custom_id fisso per persistenza
    )
    async def open_feedback(self, interaction: discord.Interaction, button: Button):
        # Invio istruzioni in DM; se fallisce (DM off), avvisa in ephemeral
        try:
            await interaction.user.send(
                "**📋 Compila il feedback coaching rispondendo a queste domande in UN SOLO messaggio:**\n\n"
                "🟡 **INFO GENERALI**\n"
                "1) Nome squadra:\n"
                "2) Nome del capitano:\n"
                "3) Competizione giocata:\n"
                "4) Periodo del coaching (es. Maggio-Giugno 2025):\n\n"
                "🟢 **PRIMA DEL COACHING**\n"
                "5) Situazione iniziale (classifica, problemi tattici, ecc.):\n"
                "6) Problemi principali:\n"
                "📎 Screen classifica iniziale/statistiche? (puoi inviarle subito dopo):\n\n"
                "🔵 **LAVORO SVOLTO**\n"
                "7) Su cosa abbiamo lavorato (tattica, mentalità, gestione…):\n"
                "8) Cosa ti è piaciuto del coaching:\n\n"
                "🔴 **DOPO IL COACHING**\n"
                "9) In cosa siete migliorati:\n"
                "10) Risultati raggiunti:\n"
                "📎 Screen classifica finale o clip? (puoi inviarle subito dopo):\n\n"
                "🟣 **VALUTAZIONE E TESTIMONIANZA**\n"
                "11) Voto da 1 a 10:\n"
                "12) Testimonianza pubblicabile:\n"
                "13) Lo consiglieresti? Perché?\n\n"
                "🟤 **AUTORIZZAZIONE**\n"
                "14) Autorizzi la pubblicazione del feedback e delle immagini? (Sì/No)\n\n"
                "🔁 *Invia tutto in un unico messaggio. Poi, in DM, puoi allegare immagini/clip subito dopo.*"
            )
            await interaction.response.send_message("📨 Ti ho mandato il modulo in DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Non riesco a scriverti in DM. Attiva i messaggi privati e riprova.",
                ephemeral=True
            )

# ---- Anchor: crea/ri-usa (no duplicati) e ri-attacca la View ----
async def ensure_anchor_in_channel(channel_id: int):
    channel = await get_text_channel(channel_id)
    if channel is None:
        print(f"[ANCHOR] Canale {channel_id} non trovato o non testuale.")
        return

    existing = None
    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and (msg.content or "").startswith(ANCHOR_MARK):
                existing = msg
                break
    except Exception as e:
        print(f"[ANCHOR] Lettura history fallita su {channel_id}: {e}")

    embed = discord.Embed(
        title="🎯 Feedback Coaching",
        description="Clicca il pulsante qui sotto per aprire il modulo in DM e inviare il tuo feedback.",
        color=0x00B0F4
    )

    try:
        if existing:
            # Ri-attacca la view (rebind bottone) e aggiorna embed
            await existing.edit(content=existing.content, embed=embed, view=FeedbackView())
            try:
                await existing.pin()
            except Exception:
                pass
            print(f"[ANCHOR] Ri-usato anchor in #{getattr(channel, 'name', channel_id)}")
        else:
            # Crea nuovo anchor
            msg = await channel.send(f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).", embed=embed, view=FeedbackView())
            try:
                await msg.pin()
            except Exception:
                pass
            print(f"[ANCHOR] Creato anchor in #{getattr(channel, 'name', channel_id)}")
    except Exception as e:
        print(f"[ANCHOR] Errore update/creazione in {channel_id}: {e}")

# ---- Ready ----
@bot.event
async def on_ready():
    print(f"✅ Bot online come {bot.user} (id: {bot.user.id})")
    load_seen()  # carica cache dedup da disco
    # Registra la View persistente per messaggi già presenti
    bot.add_view(FeedbackView())
    # Assicura anchor in ENTRAMBI i canali (vecchio + nuovo)
    await ensure_anchor_in_channel(BUTTON_CHANNEL_ID_OLD)
    await ensure_anchor_in_channel(BUTTON_CHANNEL_ID_NEW)

# ---- DM handler: de-dup + forward su due canali ----
@bot.event
async def on_message(message: discord.Message):
    # DM utente (non bot)
    if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
        # De-dup per message.id
        mid = str(message.id)
        if mid in PROCESSED_DM_IDS:
            return
        PROCESSED_DM_IDS.add(mid)
        save_seen()

        # Prepara embed + files
        embed = discord.Embed(
            title=f"📝 Feedback da {message.author.name}",
            description=message.content if message.content else "*[Solo allegato senza testo]*",
            color=0x00B0F4
        )
        embed.set_footer(text="Coaching Feedback Bot")

        files = []
        try:
            if message.attachments:
                files = [await a.to_file() for a in message.attachments]
        except Exception as e:
            print(f"[FILES] Errore conversione allegati: {e}")

        content_prefix = f"<@&{PING_ROLE_ID}>" if PING_ROLE_ID else None

        # Inoltra nei due canali target (vecchio + nuovo) UNA SOLA VOLTA
        for ch_id in (FORWARD_CHANNEL_ID_OLD, FORWARD_CHANNEL_ID_NEW):
            ch = await get_text_channel(ch_id)
            if not ch:
                print(f"[FORWARD] Canale {ch_id} non disponibile.")
                continue
            try:
                await ch.send(content=content_prefix, embed=embed, files=files)
            except discord.Forbidden:
                print(f"[FORWARD] Permesso negato nel canale {ch_id}.")
            except Exception as e:
                print(f"[FORWARD] Errore invio in {ch_id}: {e}")

        # Log (vecchio e nuovo server)
        for log_id in (LOG_CHANNEL_OLD, LOG_CHANNEL_NEW):
            log_ch = await get_text_channel(log_id)
            if not log_ch:
                continue
            try:
                log_msg = (
                    f"📥 **Nuovo feedback ricevuto in DM**\n"
                    f"👤 Autore: {message.author} (`{message.author.id}`)\n"
                    f"🧾 Lunghezza testo: {len(message.content or '')} caratteri\n"
                    f"📎 Allegati: {len(message.attachments)}"
                )
                await log_ch.send(log_msg)
            except Exception as e:
                print(f"[LOG] Errore invio log in {log_id}: {e}")

    await bot.process_commands(message)

# (Facoltativo) ignora edit dei DM per sicurezza
@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if isinstance(after.channel, discord.DMChannel):
        return  # non re-inoltrare edit dei DM

# ============ AVVIO ============
if __name__ == "__main__":
    keep_alive()  # utile su Render/Replit
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN non impostato nelle variabili d'ambiente.")
    bot.run(token)
