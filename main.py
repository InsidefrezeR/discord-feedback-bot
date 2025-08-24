# -*- coding: utf-8 -*-
# Feedback Bot — Auto anchor + Persistent Button + DM forward a VECCHIO e NUOVO server
# Requisiti: python 3.10+, pip install -U discord.py Flask python-dotenv (opzionale)

from flask import Flask
from threading import Thread
import os
import discord
from discord.ext import commands
from discord.ui import Button, View

# ============ CONFIG FISSA ============
SOURCE_GUILD_ID  = 1310417606607634432  # Vecchio server (dove compare il bottone)
TARGET_GUILD_ID  = 1407462539289165884  # Nuovo server (dove arrivano i feedback)

BUTTON_CHANNEL_ID        = 1401005055783735442  # canale nel vecchio server per embed + bottone
FORWARD_CHANNEL_ID_OLD   = 1401005055783735442  # (vecchio server) dove inoltrare i DM
FORWARD_CHANNEL_ID_NEW   = 1407515405034979428  # (nuovo server) dove inoltrare i DM

LOG_CHANNEL_OLD = 1401163197767221370          # log nel vecchio server
LOG_CHANNEL_NEW = 1407489479752552510          # log nel nuovo server

# (Opzionale) ping ruolo quando arriva un feedback: metti un ID o lascia None
PING_ROLE_ID = None  # es. 123456789012345678 oppure None per disattivare

# Messaggio marcatore per riconoscere/aggiornare l’anchor ai riavvii
ANCHOR_MARK = "[FEEDBACK_ANCHOR]"

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
        # timeout=None => persistenza dopo i restart
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Lascia il tuo Feedback",
        style=discord.ButtonStyle.primary,
        custom_id="feedback:open_dm"  # custom_id fisso richiesto per la persistenza
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

# ---- Pubblica o aggiorna l'anchor (embed + bottone) nel vecchio server ----
async def ensure_anchor_message():
    channel = await get_text_channel(BUTTON_CHANNEL_ID)
    if channel is None:
        print(f"[ANCHOR] Canale {BUTTON_CHANNEL_ID} non trovato o non testuale.")
        return

    # 1) Pulisce vecchi anchor del bot (se ha permesso Manage Messages è più pulito)
    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and (msg.content or "").startswith(ANCHOR_MARK):
                try:
                    await msg.delete()
                except Exception as e:
                    print(f"[ANCHOR] Impossibile cancellare anchor precedente: {e}")
    except Exception as e:
        print(f"[ANCHOR] Lettura history fallita: {e}")

    # 2) Invia nuovo embed + bottone e prova a pinnare
    embed = discord.Embed(
        title="🎯 Feedback Coaching",
        description="Clicca il pulsante qui sotto per aprire il modulo in DM e inviare il tuo feedback.",
        color=0x00B0F4
    )
    try:
        msg = await channel.send(f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).", embed=embed, view=FeedbackView())
        try:
            await msg.pin()
        except Exception:
            pass
        print(f"[ANCHOR] Pubblicato anchor in #{channel.name}")
    except Exception as e:
        print(f"[ANCHOR] Invio anchor fallito: {e}")

# ---- Ready ----
@bot.event
async def on_ready():
    print(f"✅ Bot online come {bot.user} (id: {bot.user.id})")
    # Registra la View persistente per mantenere attivi i bottoni su messaggi già esistenti
    bot.add_view(FeedbackView())
    # Auto-setup dell’anchor nel vecchio server
    await ensure_anchor_message()

# ---- DM handler: inoltra SEMPRE a DUE canali (vecchio + nuovo) ----
@bot.event
async def on_message(message: discord.Message):
    # Gestione DM dell’utente (no bot)
    if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
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

        # Eventuale ping ruolo
        content_prefix = f"<@&{PING_ROLE_ID}>\n" if PING_ROLE_ID else None

        # Inoltra nei due canali target (vecchio + nuovo)
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

        # Log (vecchio e/o nuovo server)
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

    # Non bloccare altri comandi/listeners
    await bot.process_commands(message)

# ============ AVVIO ============
if __name__ == "__main__":
    keep_alive()  # utile su Render/Replit
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN non impostato nelle variabili d'ambiente.")
    bot.run(token)
