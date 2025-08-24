# -*- coding: utf-8 -*-
# Feedback Bot — Doppio anchor + bottone persistente + DM dedup + anchor persistente anti-duplicati

from flask import Flask
from threading import Thread
import os, json, asyncio
import discord
from discord.ext import commands
from discord.ui import Button, View

# ============ CONFIG ============
SOURCE_GUILD_ID  = 1310417606607634432  # Vecchio server
TARGET_GUILD_ID  = 1407462539289165884  # Nuovo server

BUTTON_CHANNEL_ID_OLD = 1401005055783735442  # canale (old) con embed+bottone
BUTTON_CHANNEL_ID_NEW = 1407515405034979428  # canale (new) con embed+bottone

FORWARD_CHANNEL_ID_OLD = 1401005055783735442  # DM -> old
FORWARD_CHANNEL_ID_NEW = 1407515405034979428  # DM -> new

LOG_CHANNEL_OLD = 1401163197767221370
LOG_CHANNEL_NEW = 1407489479752552510

PING_ROLE_ID = None
ANCHOR_MARK = "[FEEDBACK_ANCHOR]"

SEEN_STORE_PATH = "/mnt/data/dm_seen.json"
ANCHORS_PATH    = "/mnt/data/anchors.json"

PROCESSED_DM_IDS = set()
ANCHORS = {}  # {channel_id:str -> message_id:str}

STARTED = False  # guardia anti-doppio avvio

# ============ KEEP ALIVE ============
app = Flask('')
@app.route('/')
def home(): return "Bot attivo!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ============ PERSISTENZA ============
def load_seen():
    try:
        with open(SEEN_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                PROCESSED_DM_IDS.update(data[-5000:])
    except Exception:
        pass

def save_seen():
    try:
        os.makedirs(os.path.dirname(SEEN_STORE_PATH), exist_ok=True)
        arr = list(PROCESSED_DM_IDS)[-5000:]
        with open(SEEN_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(arr, f)
    except Exception as e:
        print(f"[SEEN] Save error: {e}")

def load_anchors():
    global ANCHORS
    try:
        with open(ANCHORS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                ANCHORS = {int(k): str(v) for k, v in data.items()}
    except Exception:
        ANCHORS = {}

def save_anchors():
    try:
        os.makedirs(os.path.dirname(ANCHORS_PATH), exist_ok=True)
        with open(ANCHORS_PATH, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in ANCHORS.items()}, f)
    except Exception as e:
        print(f"[ANCHORS] Save error: {e}")

# ============ DISCORD ============
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

async def get_text_channel(channel_id: int) -> discord.TextChannel | None:
    ch = bot.get_channel(channel_id)
    if ch is None:
        try: ch = await bot.fetch_channel(channel_id)
        except Exception: ch = None
    return ch if isinstance(ch, discord.TextChannel) else None

class FeedbackView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="📝 Lascia il tuo Feedback", style=discord.ButtonStyle.primary, custom_id="feedback:open_dm")
    async def open_feedback(self, interaction: discord.Interaction, button: Button):
        try:
            await interaction.user.send(
                "**📋 Compila il feedback coaching rispondendo a queste domande in UN SOLO messaggio:**\n\n"
                "🟡 **INFO GENERALI**\n1) Nome squadra:\n2) Nome del capitano:\n3) Competizione giocata:\n4) Periodo del coaching:\n\n"
                "🟢 **PRIMA DEL COACHING**\n5) Situazione iniziale:\n6) Problemi principali:\n📎 Screen iniziale? (puoi inviarlo dopo)\n\n"
                "🔵 **LAVORO SVOLTO**\n7) Su cosa abbiamo lavorato:\n8) Cosa ti è piaciuto:\n\n"
                "🔴 **DOPO IL COACHING**\n9) Miglioramenti:\n10) Risultati:\n📎 Screen finale/clip? (puoi inviarlo dopo)\n\n"
                "🟣 **VALUTAZIONE**\n11) Voto 1-10:\n12) Testimonianza pubblicabile:\n13) Lo consiglieresti? Perché?\n\n"
                "🟤 **AUTORIZZAZIONE**\n14) Consenti pubblicazione feedback/immagini? (Sì/No)\n\n"
                "🔁 *Invia tutto in un unico messaggio. Poi allega immagini/clip subito dopo.*"
            )
            await interaction.response.send_message("📨 Ti ho mandato il modulo in DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Attiva i messaggi privati e riprova.", ephemeral=True)

async def find_existing_anchor(channel: discord.TextChannel):
    """Trova un anchor esistente del bot in questo canale.
    Priorità: ID salvato -> history con ANCHOR_MARK o bottone con custom_id -> None."""
    # 1) prova da ID salvato
    cid = channel.id
    msg_id = ANCHORS.get(cid)
    if msg_id:
        try:
            m = await channel.fetch_message(int(msg_id))
            if m and m.author == bot.user:
                return m
        except Exception:
            pass  # non esiste più

    # 2) cerca in history (più robusto)
    candidates = []
    try:
        async for m in channel.history(limit=200):
            if m.author != bot.user:
                continue
            has_mark = (m.content or "").startswith(ANCHOR_MARK)
            has_button = False
            try:
                # controlla se contiene un nostro bottone (custom_id)
                if getattr(m, "components", None):
                    for row in m.components:
                        for comp in getattr(row, "children", []):
                            if getattr(comp, "custom_id", None) == "feedback:open_dm":
                                has_button = True
                                break
            except Exception:
                pass
            if has_mark or has_button:
                candidates.append(m)
    except Exception as e:
        print(f"[ANCHOR] History error in #{getattr(channel,'name',channel.id)}: {e}")

    if not candidates:
        return None

    # se ce ne sono più di uno: tieni il più recente, elimina gli altri
    candidates.sort(key=lambda x: x.created_at, reverse=True)
    keep = candidates[0]
    for extra in candidates[1:]:
        try: await extra.delete()
        except Exception as e: print(f"[ANCHOR] Cleanup extra failed: {e}")
    ANCHORS[cid] = str(keep.id)
    save_anchors()
    return keep

async def ensure_anchor_in_channel(channel_id: int):
    channel = await get_text_channel(channel_id)
    if channel is None:
        print(f"[ANCHOR] Canale {channel_id} non trovato.")
        return

    existing = await find_existing_anchor(channel)

    embed = discord.Embed(
        title="🎯 Feedback Coaching",
        description="Clicca il pulsante qui sotto per aprire il modulo in DM e inviare il tuo feedback.",
        color=0x00B0F4
    )

    try:
        if existing:
            await existing.edit(content=f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).", embed=embed, view=FeedbackView())
            try: await existing.pin()
            except Exception: pass
            ANCHORS[channel.id] = str(existing.id)
            save_anchors()
            print(f"[ANCHOR] Ri-usato anchor in #{getattr(channel,'name',channel.id)}")
        else:
            msg = await channel.send(f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).", embed=embed, view=FeedbackView())
            try: await msg.pin()
            except Exception: pass
            ANCHORS[channel.id] = str(msg.id)
            save_anchors()
            print(f"[ANCHOR] Creato anchor in #{getattr(channel,'name',channel.id)}")
    except Exception as e:
        print(f"[ANCHOR] Update/create error in {channel_id}: {e}")

@bot.event
async def on_ready():
    global STARTED
    print(f"✅ Bot online come {bot.user} (id: {bot.user.id})")

    # Evita doppie esecuzioni su reconnect/shard
    if STARTED:
        print("↩️ on_ready richiamato: routine già eseguita, salto.")
        return
    STARTED = True

    load_seen()
    load_anchors()

    # La View persistente permette ai bottoni su messaggi già esistenti di restare attivi
    bot.add_view(FeedbackView())

    # Assicura anchor in ENTRAMBI i canali
    await ensure_anchor_in_channel(BUTTON_CHANNEL_ID_OLD)
    await ensure_anchor_in_channel(BUTTON_CHANNEL_ID_NEW)

@bot.event
async def on_message(message: discord.Message):
    # DM utente (non bot)
    if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
        mid = str(message.id)
        if mid in PROCESSED_DM_IDS:
            return
        PROCESSED_DM_IDS.add(mid)
        save_seen()

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

        for log_id in (LOG_CHANNEL_OLD, LOG_CHANNEL_NEW):
            log_ch = await get_text_channel(log_id)
            if not log_ch:
                continue
            try:
                await log_ch.send(
                    f"📥 **Nuovo feedback ricevuto in DM**\n"
                    f"👤 Autore: {message.author} (`{message.author.id}`)\n"
                    f"🧾 Caratteri: {len(message.content or '')}\n"
                    f"📎 Allegati: {len(message.attachments)}"
                )
            except Exception as e:
                print(f"[LOG] Errore invio log in {log_id}: {e}")

    await bot.process_commands(message)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if isinstance(after.channel, discord.DMChannel):
        return  # ignora edit dei DM

# ============ AVVIO ============
if __name__ == "__main__":
    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN non impostato.")
    bot.run(token)
