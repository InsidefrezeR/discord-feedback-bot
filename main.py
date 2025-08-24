# -*- coding: utf-8 -*-
# Feedback Bot — Doppio anchor, bottone persistente, DM dedup, forward una sola volta (anche con più istanze)

from flask import Flask
from threading import Thread
import os, json, time
import discord
from discord.ext import commands
from discord.ui import Button, View

# ============ CONFIG (ID forniti) ============
SOURCE_GUILD_ID  = 1310417606607634432  # Vecchio server
TARGET_GUILD_ID  = 1407462539289165884  # Nuovo server

# Canali "anchor" (embed + bottone)
BUTTON_CHANNEL_ID_OLD = 1401005055783735442  # canale (old) con embed+bottone
BUTTON_CHANNEL_ID_NEW = 1407515405034979428  # canale (new) con embed+bottone

# Canali di forward dai DM
FORWARD_CHANNEL_ID_OLD = 1401005055783735442  # DM -> old
FORWARD_CHANNEL_ID_NEW = 1407515405034979428  # DM -> new

# Canali log
LOG_CHANNEL_OLD = 1401163197767221370
LOG_CHANNEL_NEW = 1407489479752552510

# Ping ruolo (opzionale): metti un ID oppure None
PING_ROLE_ID = None

# Marcatore messaggi anchor e store su disco
ANCHOR_MARK = "[FEEDBACK_ANCHOR]"
SEEN_STORE_PATH = "/mnt/data/dm_seen.json"
ANCHORS_PATH    = "/mnt/data/anchors.json"

# ============ Stato runtime ============
PROCESSED_DM_IDS = set()          # dedup locale DM (message.id)
ANCHORS = {}                      # {channel_id:int -> message_id:str}
RECENT_INTERACTION_IDS = set()    # dedup per interaction.id (click bottone)
LAST_DM_BY_USER = {}              # {user_id:int -> ts}
USER_DM_COOLDOWN_SEC = 10.0       # evita doppi DM ravvicinati
STARTED = False                   # guardia anti-doppio on_ready

# ============ KEEP ALIVE (Flask) ============
app = Flask('')
@app.route('/')
def home(): return "Bot attivo!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run, daemon=True).start()

# ============ Persistenza su disco ============
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
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            ch = None
    return ch if isinstance(ch, discord.TextChannel) else None

# ---------- View con bottone (persistente) ----------
class FeedbackView(View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="📝 Lascia il tuo Feedback",
                       style=discord.ButtonStyle.primary,
                       custom_id="feedback:open_dm")  # custom_id fisso = persistenza
    async def open_feedback(self, interaction: discord.Interaction, button: Button):
        now = time.time()

        # De-dup per interaction.id (evita doppio callback)
        iid = getattr(interaction, "id", None)
        if iid and iid in RECENT_INTERACTION_IDS:
            return
        if iid:
            RECENT_INTERACTION_IDS.add(iid)

        # Cooldown per utente (evita 2 DM ravvicinati se il callback parte due volte)
        uid = interaction.user.id
        last = LAST_DM_BY_USER.get(uid, 0.0)
        if now - last < USER_DM_COOLDOWN_SEC:
            try:
                await interaction.response.send_message(
                    "✅ Ti ho già inviato il modulo in DM. Controlla i messaggi privati.",
                    ephemeral=True
                )
            except Exception:
                pass
            return

        # Invia UN SOLO DM
        try:
            await interaction.user.send(
                "**📋 Compila il feedback coaching rispondendo a queste domande in UN SOLO messaggio:**\n\n"
                "🟡 **INFO GENERALI**\n"
                "1) Nome squadra\n2) Nome del capitano\n3) Competizione giocata\n4) Periodo del coaching\n\n"
                "🟢 **PRIMA DEL COACHING**\n"
                "5) Situazione iniziale\n6) Problemi principali\n📎 Screen iniziale? (puoi inviarlo dopo)\n\n"
                "🔵 **LAVORO SVOLTO**\n"
                "7) Su cosa abbiamo lavorato\n8) Cosa ti è piaciuto\n\n"
                "🔴 **DOPO IL COACHING**\n"
                "9) Miglioramenti\n10) Risultati\n📎 Screen finale/clip? (puoi inviarlo dopo)\n\n"
                "🟣 **VALUTAZIONE**\n"
                "11) Voto 1-10\n12) Testimonianza pubblicabile\n13) Lo consiglieresti? Perché?\n\n"
                "🟤 **AUTORIZZAZIONE**\n"
                "14) Consenti pubblicazione feedback/immagini? (Sì/No)\n\n"
                "🔁 *Invia tutto in un unico messaggio. Poi allega immagini/clip subito dopo.*"
            )
            LAST_DM_BY_USER[uid] = now
            await interaction.response.send_message("📨 Ti ho mandato il modulo in DM!", ephemeral=True)
        except discord.Forbidden:
            try:
                await interaction.response.send_message(
                    "❌ Non riesco a scriverti in DM. Attiva i messaggi privati e riprova.",
                    ephemeral=True
                )
            except Exception:
                pass

# ---------- Anchor finder/creator (idempotente, anti-doppioni) ----------
async def find_existing_anchor(channel: discord.TextChannel):
    cid = channel.id
    msg_id = ANCHORS.get(cid)
    if msg_id:
        try:
            m = await channel.fetch_message(int(msg_id))
            if m and m.author == bot.user:
                return m
        except Exception:
            pass

    candidates = []
    try:
        async for m in channel.history(limit=200):
            if m.author != bot.user:
                continue
            has_mark = (m.content or "").startswith(ANCHOR_MARK)
            has_button = False
            try:
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

    candidates.sort(key=lambda x: x.created_at, reverse=True)
    keep = candidates[0]
    for extra in candidates[1:]:
        try: await extra.delete()
        except Exception as e: print(f"[ANCHOR] Cleanup extra failed: {e}")
    ANCHORS[cid] = str(keep.id); save_anchors()
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
            await existing.edit(
                content=f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).",
                embed=embed, view=FeedbackView()
            )
            try: await existing.pin()
            except Exception: pass
            ANCHORS[channel.id] = str(existing.id); save_anchors()
            print(f"[ANCHOR] Ri-usato anchor in #{getattr(channel,'name',channel.id)}")
        else:
            msg = await channel.send(
                f"{ANCHOR_MARK} Non rimuovere questo messaggio (anchor).",
                embed=embed, view=FeedbackView()
            )
            try: await msg.pin()
            except Exception: pass
            ANCHORS[channel.id] = str(msg.id); save_anchors()
            print(f"[ANCHOR] Creato anchor in #{getattr(channel,'name',channel.id)}")
    except Exception as e:
        print(f"[ANCHOR] Update/create error in {channel_id}: {e}")

# ---------- Forward UNA SOLA VOLTA per canale (anche con più istanze) ----------
async def send_feedback_once(channel_id: int, embed: discord.Embed, files, dm_id: int, ping_role_id: int | None):
    ch = await get_text_channel(channel_id)
    if not ch:
        print(f"[FORWARD] Canale {channel_id} non disponibile.")
        return

    marker = f"[DM_ID:{dm_id}]"

    # 1) Controllo history: se già presente un messaggio con quel DM_ID, non reinvia
    try:
        async for m in ch.history(limit=40):
            if m.author == bot.user:
                content_ok = (marker in (m.content or ""))
                footer_ok = False
                try:
                    if m.embeds:
                        foot = m.embeds[0].footer.text or ""
                        if marker in foot:
                            footer_ok = True
                except Exception:
                    pass
                if content_ok or footer_ok:
                    return  # già inviato (da questa o un'altra istanza)
    except Exception as e:
        print(f"[FORWARD] History check fallito in {channel_id}: {e}")

    # 2) Prepara content (con ping opzionale) + marker
    if ping_role_id:
        content = f"<@&{ping_role_id}>\n{marker}"
    else:
        content = marker

    # 3) Appendi marker anche nel footer dell'embed
    try:
        footer_txt = (embed.footer.text or "")
    except Exception:
        footer_txt = ""
    embed.set_footer(text=(footer_txt + (" " if footer_txt else "") + marker))

    # 4) Invia
    try:
        await ch.send(
            content=content,
            embed=embed,
            files=files,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.Forbidden:
        print(f"[FORWARD] Permesso negato nel canale {channel_id}.")
    except Exception as e:
        print(f"[FORWARD] Errore invio in {channel_id}: {e}")

# ---------- Eventi ----------
@bot.event
async def on_ready():
    global STARTED
    print(f"✅ Bot online come {bot.user} (id: {bot.user.id})")
    if STARTED:
        print("↩️ on_ready richiamato: routine già eseguita, salto.")
        return
    STARTED = True

    load_seen()
    load_anchors()

    # Registra view persistente UNA SOLA volta
    bot.add_view(FeedbackView())

    # Anchor in entrambi i canali
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

        # Inoltra UNA SOLA VOLTA nei due canali (anche con più istanze)
        dm_id_int = int(message.id)
        await send_feedback_once(FORWARD_CHANNEL_ID_OLD, embed, files, dm_id_int, PING_ROLE_ID)
        await send_feedback_once(FORWARD_CHANNEL_ID_NEW, embed, files, dm_id_int, PING_ROLE_ID)

        # Log (puoi aggiungere marker anche qui se vuoi evitare doppi log multi-istanza)
        for log_id in (LOG_CHANNEL_OLD, LOG_CHANNEL_NEW):
            ch = await get_text_channel(log_id)
            if not ch:
                continue
            try:
                await ch.send(
                    f"📥 **Nuovo feedback DM** (ID {message.id})\n"
                    f"👤 Autore: {message.author} (`{message.author.id}`)\n"
                    f"🧾 Caratteri: {len(message.content or '')}\n"
                    f"📎 Allegati: {len(message.attachments)}",
                    allowed_mentions=discord.AllowedMentions.none()
                )
            except Exception as e:
                print(f"[LOG] Errore invio log in {log_id}: {e}")

    await bot.process_commands(message)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if isinstance(after.channel, discord.DMChannel):
        return  # ignora edit DM (niente reinvii)

# ============ AVVIO ============
if __name__ == "__main__":
    keep_alive()  # utile su Render/Replit
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN non impostato nelle variabili d'ambiente.")
    bot.run(token)
