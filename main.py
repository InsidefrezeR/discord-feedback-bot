from flask import Flask
from threading import Thread
import os
import discord
from discord.ext import commands
from discord.ui import Button, View

# ===== KEEP ALIVE FLASK APP =====
app = Flask('')

@app.route('/')
def home():
    return "Bot attivo!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== CONFIG =====
FEEDBACK_CHANNEL_ID = 1401005055783735442
LOG_CHANNEL_ID = 1401163197767221370
AUTHORIZED_ROLE = "Feedback"

# ===== BOT SETUP =====
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot online come {bot.user}")

@bot.command()
async def setupfeedback(ctx):
    if not any(role.name == AUTHORIZED_ROLE for role in ctx.author.roles):
        await ctx.send("❌ Non hai i permessi per usare questo comando. Serve il ruolo **Feedback**.")
        return

    # 🔍 Controlla se esiste già un messaggio con bottoni nel canale
    async for msg in ctx.channel.history(limit=20):
        if msg.author == bot.user and msg.components:
            await ctx.send("⚠️ Il bottone per il feedback è già stato inviato in questo canale.")
            return

    button = Button(label="📝 Lascia il tuo Feedback", style=discord.ButtonStyle.primary, custom_id="feedback_button")

    async def button_callback(interaction: discord.Interaction):
        try:
            await interaction.user.send(
                "**📋 Compila il feedback coaching rispondendo a queste domande:**\n\n"
                "🟡 **INFO GENERALI**\n"
                "1️⃣ Nome squadra:\n"
                "2️⃣ Nome del capitano:\n"
                "3️⃣ Competizione giocata:\n"
                "4️⃣ Periodo del coaching (es. Maggio-Giugno 2025):\n\n"
                "🟢 **SITUAZIONE PRIMA DEL COACHING**\n"
                "5️⃣ Dove vi trovavate prima del coaching? (Classifica, problemi tattici, ecc.)\n"
                "6️⃣ Quali erano i problemi principali?\n"
                "📎 Hai uno screen della classifica iniziale o statistiche? Scrivi 'sì' e invialo dopo.\n\n"
                "🔵 **LAVORO SVOLTO**\n"
                "7️⃣ Su cosa abbiamo lavorato? (Tattica, mentalità, gestione...)\n"
                "8️⃣ Cosa ti è piaciuto del coaching?\n\n"
                "🔴 **DOPO IL COACHING**\n"
                "9️⃣ In cosa siete migliorati?\n"
                "🔟 Quali risultati avete raggiunto?\n"
                "📎 Hai uno screen della classifica finale o clip? Scrivi 'sì' e invialo dopo.\n\n"
                "🟣 **VALUTAZIONE E TESTIMONIANZA**\n"
                "1️⃣1️⃣ Da 1 a 10, quanto valuti il coaching?\n"
                "1️⃣2️⃣ Scrivi una testimonianza pubblicabile:\n"
                "1️⃣3️⃣ Consiglieresti il percorso ad altri? Perché?\n\n"
                "🟤 **AUTORIZZAZIONE PUBBLICAZIONE**\n"
                "1️⃣4️⃣ Autorizzi la pubblicazione del tuo feedback e delle immagini? (Sì/No)\n\n"
                "🔁 Scrivi tutto in un unico messaggio. Puoi inviare immagini subito dopo."
            )
            await interaction.response.send_message("📨 Ti ho mandato il modulo in DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Non riesco a mandarti un DM. Attiva i messaggi privati!", ephemeral=True)

    button.callback = button_callback
    view = View()
    view.add_item(button)

    await ctx.send("🧾 **Clicca il pulsante qui sotto per lasciare il tuo feedback coaching:**", view=view)

@bot.event
async def on_message(message):
    if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
        feedback_channel = bot.get_channel(FEEDBACK_CHANNEL_ID)
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        if feedback_channel:
            embed = discord.Embed(
                title=f"📝 Feedback da {message.author.name}",
                description=message.content if message.content else "*[Solo allegato senza testo]*",
                color=0x00b0f4
            )
            embed.set_footer(text="Coaching Feedback Bot")

            files = [await attachment.to_file() for attachment in message.attachments]
            await feedback_channel.send(embed=embed, files=files)

            if log_channel:
                log_msg = (
                    f"📥 **Nuovo feedback ricevuto**\n"
                    f"👤 Autore: {message.author} ({message.author.id})\n"
                    f"📄 Testo:\n{message.content if message.content else '[Solo allegato]'}"
                )
                await log_channel.send(log_msg)

    await bot.process_commands(message)

# ===== AVVIO BOT =====
keep_alive()
bot.run(os.getenv("DISCORD_TOKEN"))

