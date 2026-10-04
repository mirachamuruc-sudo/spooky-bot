"""
================================================================================
🎃 HALLOWEEN FULL-STACK DISCORD BOT (discord.py 2.x)
================================================================================
Theme: Düsteres, mystisches Halloween (Orange #E67E22 & Violett #2C3E50)
Features:
  1. Bot-System & SQLite-Datenbank (aiosqlite)
  2. Ticket-Support-System (#ticket-support, private Kanäle, Transkripte)
  3. 3 Minispiele mit DB-Speicherung (/pumpkin, /geisterhaus, /trick-or-treat, /punkte)
  4. Automatisches Channel-Setup (/setup_halloween)
================================================================================
"""

import os
import sys
import time
import random
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# 1. KONFIGURATION & FARBEN
# -----------------------------------------------------------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("HalloweenBot")

# Halloween Farbpalette
COLOR_PUMPKIN = 0xE67E22   # Dunkelorange (#E67E22)
COLOR_HAUNTED = 0x2C3E50   # Düsteres Nachtgrau/Blau (#2C3E50)
COLOR_PURPLE  = 0x8E44AD   # Mystisches Dunkelviolett (#8E44AD)
COLOR_BLOOD   = 0xC0392B   # Blutrot (#C0392B)
COLOR_SLIME   = 0x27AE60   # Giftgrün (#27AE60)

# Pfad zur SQLite-Datenbank: Fly.io Volume (/data) oder lokal
DB_DIR = "/data" if os.path.exists("/data") else "."
DB_PATH = os.path.join(DB_DIR, "bot_data.db")

# -----------------------------------------------------------------------------
# 2. DATENBANK-INITIALISIERUNG (aiosqlite)
# -----------------------------------------------------------------------------
async def init_db():
    """Erstellt alle benötigten SQLite-Tabellen für Punkte, Tickets und Minigames."""
    logger.info(f"Initialisiere SQLite-Datenbank unter: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:
        # Benutzertabelle für Punkte & Minispiel-Statistiken
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                points INTEGER DEFAULT 0,
                pumpkins_caught INTEGER DEFAULT 0,
                haunted_cleared INTEGER DEFAULT 0,
                trick_treat_plays INTEGER DEFAULT 0,
                last_trick_treat INTEGER DEFAULT 0
            )
        """)
        # Tickettabelle
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER UNIQUE,
                guild_id INTEGER,
                user_id INTEGER,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
        # Transkript-Logs
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                user_id INTEGER,
                transcript_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    logger.info("Datenbank-Tabellen erfolgreich verifiziert / angelegt.")

async def get_or_create_user(user_id: int, username: str) -> dict:
    """Holt Benutzerdaten oder legt neuen User in der DB an."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        
        # Neu anlegen
        await db.execute(
            "INSERT INTO users (user_id, username, points) VALUES (?, ?, 0)",
            (user_id, username)
        )
        await db.commit()
        return {
            "user_id": user_id,
            "username": username,
            "points": 0,
            "pumpkins_caught": 0,
            "haunted_cleared": 0,
            "trick_treat_plays": 0,
            "last_trick_treat": 0
        }

async def update_user_points(user_id: int, username: str, delta: int, stat_field: Optional[str] = None) -> int:
    """Verändert die Punkte eines Benutzers und erhöht ggf. einen Zähler."""
    async with aiosqlite.connect(DB_PATH) as db:
        await get_or_create_user(user_id, username)
        
        if stat_field:
            query = f"UPDATE users SET points = MAX(0, points + ?), {stat_field} = {stat_field} + 1, username = ? WHERE user_id = ?"
        else:
            query = "UPDATE users SET points = MAX(0, points + ?), username = ? WHERE user_id = ?"
            
        await db.execute(query, (delta, username, user_id))
        await db.commit()
        
        async with db.execute("SELECT points FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

# -----------------------------------------------------------------------------
# 3. BOT-KLASSE MIT DISCORD.PY 2.X SETUP_HOOK
# -----------------------------------------------------------------------------
class HalloweenBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        
        super().__init__(
            command_prefix="!spuk ",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # 1. Datenbank initialisieren
        await init_db()
        
        # 2. Persistente Views registrieren (damit Ticket-Buttons nach Neustart funktionieren)
        self.add_view(TicketLaunchView())
        self.add_view(TicketControlView())
        
        # 3. Slash Commands synchronisieren
        try:
            synced = await self.tree.sync()
            logger.info(f"Slash Commands erfolgreich synchronisiert: {len(synced)} Befehle aktiv.")
        except Exception as e:
            logger.error(f"Fehler beim Synchronisieren der Slash Commands: {e}")

    async def on_ready(self):
        logger.info(f"🎃 {self.user.name} ist erwacht! (ID: {self.user.id})")
        logger.info(f"Verbunden mit {len(self.guilds)} Server(n).")
        
        # Spooky Status setzen
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="die verfluchten Seelen | /setup_halloween 🎃"
        )
        await self.change_presence(status=discord.Status.dnd, activity=activity)

bot = HalloweenBot()

# -----------------------------------------------------------------------------
# 4. HALLOWEEN TICKET-SUPPORT SYSTEM
# -----------------------------------------------------------------------------
class TicketControlView(discord.ui.View):
    """Buttons innerhalb des erstellten Ticket-Kanals: Schließen & Transkript."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket schließen",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="halloween_ticket_close_btn"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        embed = discord.Embed(
            title="🔒 Ticket-Schließung eingeleitet",
            description="Das Ticket wird in **5 Sekunden** archiviert und gelöscht...\nTranskript wird gesichert. 📜",
            color=COLOR_BLOOD
        )
        embed.set_footer(text="Halloween Ticket-Support 🎃", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.followup.send(embed=embed)

        transcript_text = f"=== 🎃 HALLOWEEN TICKET TRANSKRIPT ===\n"
        transcript_text += f"Kanal: {interaction.channel.name}\n"
        transcript_text += f"Geschlossen von: {interaction.user.name} ({interaction.user.id})\n"
        transcript_text += f"Datum: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        transcript_text += "=" * 50 + "\n\n"

        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            transcript_text += f"[{timestamp}] {msg.author.name}: {msg.content}\n"
            if msg.attachments:
                for att in msg.attachments:
                    transcript_text += f"   [Anhang: {att.url}]\n"

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?",
                    (interaction.channel.id,)
                )
                await db.execute(
                    "INSERT INTO ticket_transcripts (user_id, transcript_text) VALUES (?, ?)",
                    (interaction.user.id, transcript_text)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Transkripts in DB: {e}")

        try:
            temp_file_path = f"/tmp/ticket_{interaction.channel.id}.txt"
            with open(temp_file_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)
            
            dm_embed = discord.Embed(
                title="📜 Dein Ticket-Transkript",
                description=f"Hier ist das Transkript für deinen Support-Kanal `{interaction.channel.name}`.",
                color=COLOR_PURPLE
            )
            await interaction.user.send(embed=dm_embed, file=discord.File(temp_file_path, filename=f"transkript-{interaction.channel.name}.txt"))
            os.remove(temp_file_path)
        except Exception:
            pass

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket geschlossen durch {interaction.user.name}")
        except Exception as e:
            logger.error(f"Kanal konnte nicht gelöscht werden: {e}")

    @discord.ui.button(
        label="Transkript speichern",
        style=discord.ButtonStyle.secondary,
        emoji="📜",
        custom_id="halloween_ticket_transcript_btn"
    )
    async def save_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=False)
        
        lines = [
            f"=== 🎃 HALLOWEEN TICKET TRANSKRIPT ===",
            f"Server: {interaction.guild.name}",
            f"Kanal: {interaction.channel.name}",
            f"Erstellt von: {interaction.user.name}",
            f"Zeitstempel: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "=" * 50,
            ""
        ]

        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            t_str = msg.created_at.strftime("%H:%M:%S")
            lines.append(f"[{t_str}] {msg.author.name}: {msg.clean_content}")

        transcript_content = "\n".join(lines)
        temp_path = f"/tmp/transcript_{interaction.channel.id}.txt"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(transcript_content)

        embed = discord.Embed(
            title="📜 Transkript generiert",
            description="Das vollständige Protokoll dieses Support-Falles wurde erfolgreich exportiert.",
            color=COLOR_PUMPKIN
        )
        embed.set_footer(text="Spuk-Support-System 👻")

        file = discord.File(temp_path, filename=f"transkript-{interaction.channel.name}.txt")
        await interaction.followup.send(embed=embed, file=file)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)


class TicketLaunchView(discord.ui.View):
    """Das Haupt-Panel im Kanal #ticket-support mit dem 'Ticket öffnen' Button."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket öffnen",
        style=discord.ButtonStyle.primary,
        emoji="🎃",
        custom_id="halloween_ticket_open_btn"
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT channel_id FROM tickets WHERE user_id = ? AND guild_id = ? AND status = 'open'",
                (user.id, guild.id)
            ) as cursor:
                existing = await cursor.fetchone()
                if existing:
                    existing_channel = guild.get_channel(existing[0])
                    if existing_channel:
                        await interaction.response.send_message(
                            f"👻 Du hast bereits ein aktives Ticket in {existing_channel.mention}!",
                            ephemeral=True
                        )
                        return

        await interaction.response.defer(ephemeral=True)

        category_name = "🎃 SPÜK-TICKETS 🎃"
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            try:
                category = await guild.create_category(category_name)
            except discord.Forbidden:
                category = None

        channel_name = f"ticket-{user.name.lower().replace(' ', '-')}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True
            )
        }

        support_role = discord.utils.find(lambda r: r.name.lower() in ["support", "moderator", "admin", "team"], guild.roles)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True
            )

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"🎃 Halloween-Support für {user.mention} (ID: {user.id})"
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Fehler beim Erstellen des Kanals: {e}. Bitte überprüfe meine Bot-Rechte!",
                ephemeral=True
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO tickets (channel_id, guild_id, user_id, status) VALUES (?, ?, ?, 'open')",
                (ticket_channel.id, guild.id, user.id)
            )
            await db.commit()

        ticket_embed = discord.Embed(
            title=f"🎃 Willkommen in deinem Support-Ticket, {user.name}!",
            description=(
                "Ein Mitglied unseres mystischen Geister-Teams wird dir in Kürze behilflich sein.\n\n"
                "🕷️ **Hinweise:**\n"
                "• Beschreibe dein Anliegen so detailliert wie möglich.\n"
                "• Halte Screenshots oder Fehlermeldungen bereit.\n"
                "• Nutze die Buttons unten, um das Transkript zu sichern oder das Ticket zu schließen."
            ),
            color=COLOR_PUMPKIN
        )
        ticket_embed.add_field(name="👤 Ticket-Ersteller", value=user.mention, inline=True)
        ticket_embed.add_field(name="🕯️ Status", value="`🟢 Offen & Aktiv`", inline=True)
        ticket_embed.set_footer(text="Halloween Support-Zentrale • 24/7 Geisterwache 👻")
        ticket_embed.set_thumbnail(url=user.display_avatar.url)

        await ticket_channel.send(
            content=f"Hallo {user.mention}, dein Ticket wurde geöffnet! 🦇",
            embed=ticket_embed,
            view=TicketControlView()
        )

        await interaction.followup.send(
            f"✅ Dein Ticket wurde erfolgreich erstellt: {ticket_channel.mention}",
            ephemeral=True
        )


# -----------------------------------------------------------------------------
# 5. INTERAKTIVE MINISPIELE MIT DATENBANK-SPEICHERUNG
# -----------------------------------------------------------------------------

# GAME 1: 🎃 Kürbis-Jagd (/pumpkin)
class PumpkinHuntView(discord.ui.View):
    def __init__(self, target_user: discord.User):
        super().__init__(timeout=20.0)
        self.target_user = target_user
        self.start_time = time.time()
        self.solved = False

        self.pumpkin_index = random.randint(0, 8)
        spooky_icons = ["🦇", "🕷️", "🕸️", "🪦", "💀", "🕯️", "🧟", "🌙"]
        random.shuffle(spooky_icons)

        icon_cursor = 0
        for i in range(9):
            row_idx = i // 3
            if i == self.pumpkin_index:
                btn = discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="???",
                    emoji="❓",
                    row=row_idx,
                    custom_id=f"pumpkin_real_{i}"
                )
                btn.callback = self.make_pumpkin_callback(is_real=True)
            else:
                decoy_icon = spooky_icons[icon_cursor % len(spooky_icons)]
                icon_cursor += 1
                btn = discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="???",
                    emoji="❓",
                    row=row_idx,
                    custom_id=f"pumpkin_decoy_{i}"
                )
                btn.callback = self.make_pumpkin_callback(is_real=False, decoy=decoy_icon)
            self.add_item(btn)

    def make_pumpkin_callback(self, is_real: bool, decoy: str = "🕷️"):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.target_user.id:
                await interaction.response.send_message("❌ Das ist nicht deine Kürbis-Jagd!", ephemeral=True)
                return

            if self.solved:
                await interaction.response.send_message("Das Spiel ist bereits beendet!", ephemeral=True)
                return

            self.solved = True
            reaction_time = round(time.time() - self.start_time, 2)

            for child in self.children:
                child.disabled = True
                if child.custom_id == f"pumpkin_real_{self.pumpkin_index}":
                    child.emoji = "🎃"
                    child.style = discord.ButtonStyle.success
                    child.label = "GEFUNDEN!"
                else:
                    child.label = "Niete"
                    child.style = discord.ButtonStyle.secondary

            if is_real:
                gained_points = max(15, int(60 - (reaction_time * 8)))
                new_total = await update_user_points(
                    self.target_user.id,
                    self.target_user.name,
                    gained_points,
                    stat_field="pumpkins_caught"
                )

                embed = discord.Embed(
                    title="🎃 TREFFER! Du hast den Kürbis erwischt!",
                    description=(
                        f"⚡ Reaktionszeit: **{reaction_time}s**\n"
                        f"🍬 Belohnung: **+{gained_points} Halloween-Punkte**\n"
                        f"🏆 Neuer Gesamtpunktestand: **{new_total}** Punkte"
                    ),
                    color=COLOR_PUMPKIN
                )
                embed.set_footer(text="Gute Reflexe in der Dunkelheit! 🕯️")
            else:
                loss = 5
                new_total = await update_user_points(
                    self.target_user.id,
                    self.target_user.name,
                    -loss
                )
                embed = discord.Embed(
                    title="💀 DANEBEN! Du griffst in Spinnweben!",
                    description=(
                        f"Du wurdest von {decoy} erschreckt!\n"
                        f"Der echte Kürbis war in Feld #{self.pumpkin_index + 1}.\n"
                        f"🩸 Strafe: **-{loss} Punkte**\n"
                        f"🏆 Neuer Gesamtpunktestand: **{new_total}** Punkte"
                    ),
                    color=COLOR_BLOOD
                )
                embed.set_footer(text="Vielleicht beim nächsten Vollmond... 🦇")

            await interaction.response.edit_message(embed=embed, view=self)

        return callback


# GAME 2: 👻 Geisterhaus (/geisterhaus)
class HauntedHouseView(discord.ui.View):
    def __init__(self, target_user: discord.User, stage: int = 1, current_loot: int = 0):
        super().__init__(timeout=30.0)
        self.target_user = target_user
        self.stage = stage
        self.current_loot = current_loot
        self.settled = False

        outcomes = ["monster", "candy", "safe"]
        random.shuffle(outcomes)
        self.door_outcomes = outcomes

        for i in range(3):
            btn = discord.ui.Button(
                label=f"Tür {i + 1}",
                emoji="🚪",
                style=discord.ButtonStyle.primary,
                custom_id=f"door_{i}"
            )
            btn.callback = self.make_door_callback(i)
            self.add_item(btn)

    def make_door_callback(self, door_index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.target_user.id:
                await interaction.response.send_message("❌ Das ist nicht dein Spukhaus-Abenteuer!", ephemeral=True)
                return

            if self.settled:
                return
            self.settled = True

            outcome = self.door_outcomes[door_index]

            for child in self.children:
                child.disabled = True

            if outcome == "monster":
                penalty = 15
                new_total = await update_user_points(
                    self.target_user.id,
                    self.target_user.name,
                    -penalty
                )
                embed = discord.Embed(
                    title=f"👻 GEISTERANGRIFF in Etage {self.stage}!",
                    description=(
                        f"Du öffnest Tür #{door_index + 1} und ein blutrünstiger Poltergeist stürmt heraus!\n\n"
                        f"😱 Du verlierst deinen gesammelten Schatz und **{penalty} Punkte**!\n"
                        f"🏆 Neuer Kontostand: **{new_total}** Punkte"
                    ),
                    color=COLOR_BLOOD
                )
                embed.set_footer(text="Das Geisterhaus hat dich verschlungen... 🪦")
                await interaction.response.edit_message(embed=embed, view=self)

            elif outcome == "candy":
                loot = 25 * self.stage
                self.current_loot += loot
                
                if self.stage < 3:
                    next_view = HauntedHouseView(self.target_user, stage=self.stage + 1, current_loot=self.current_loot)
                    embed = discord.Embed(
                        title=f"🍬 FETTE BEUTE in Etage {self.stage}!",
                        description=(
                            f"Hinter Tür #{door_index + 1} lag ein verfluchter Süßigkeitenkessel!\n"
                            f"Du findest **+{loot} Punkte**!\n"
                            f"Aktuelle gesicherte Beute: **{self.current_loot} Punkte**.\n\n"
                            f"🦇 **Etage {self.stage + 1} wartet:** Traust du dich tiefer in das Herrenhaus?"
                        ),
                        color=COLOR_PURPLE
                    )
                    await interaction.response.edit_message(embed=embed, view=next_view)
                else:
                    new_total = await update_user_points(
                        self.target_user.id,
                        self.target_user.name,
                        self.current_loot,
                        stat_field="haunted_cleared"
                    )
                    embed = discord.Embed(
                        title="🏆 DACHBODEN ERREICHT! Du hast das Geisterhaus bezwungen!",
                        description=(
                            f"Du bist allen Gespenstern entkommen und hast den Ausgang gefunden!\n\n"
                            f"🍬 Gesamter Gewinn: **+{self.current_loot} Punkte**!\n"
                            f"🏆 Neuer Punktestand: **{new_total}** Punkte"
                        ),
                        color=COLOR_SLIME
                    )
                    embed.set_footer(text="Ein wahrer Meister der Geisteraustreibung! 🧙‍♂️")
                    await interaction.response.edit_message(embed=embed, view=self)

            else: # safe
                loot = 10 * self.stage
                self.current_loot += loot
                if self.stage < 3:
                    next_view = HauntedHouseView(self.target_user, stage=self.stage + 1, current_loot=self.current_loot)
                    embed = discord.Embed(
                        title=f"🕸️ Sicherer Pfad in Etage {self.stage}!",
                        description=(
                            f"Nur alte Spinnweben hinter Tür #{door_index + 1}. Du schleichst leise hindurch (+{loot} Punkte).\n"
                            f"Gesammelte Beute: **{self.current_loot} Punkte**.\n\n"
                            f"Möchtest du in Etage {self.stage + 1} vorrücken?"
                        ),
                        color=COLOR_HAUNTED
                    )
                    await interaction.response.edit_message(embed=embed, view=next_view)
                else:
                    new_total = await update_user_points(
                        self.target_user.id,
                        self.target_user.name,
                        self.current_loot,
                        stat_field="haunted_cleared"
                    )
                    embed = discord.Embed(
                        title="🏆 ENTKOMMEN! Du bist aus dem Geisterhaus entwischt!",
                        description=(
                            f"Du hast alle 3 Etagen lebend verlassen!\n"
                            f"🍬 Gesamtgewinn: **+{self.current_loot} Punkte**!\n"
                            f"🏆 Neuer Punktestand: **{new_total}**"
                        ),
                        color=COLOR_PUMPKIN
                    )
                    await interaction.response.edit_message(embed=embed, view=self)

        return callback


# GAME 3: 🍬 Süßes oder Saures (/trick-or-treat)
class TrickOrTreatView(discord.ui.View):
    def __init__(self, target_user: discord.User):
        super().__init__(timeout=25.0)
        self.target_user = target_user
        self.used = False

    @discord.ui.button(
        label="An der Spukhaus-Pforte klopfen!",
        style=discord.ButtonStyle.primary,
        emoji="🚪",
        custom_id="knock_spooky_door"
    )
    async def knock_door(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_user.id:
            await interaction.response.send_message("❌ Das ist nicht deine Haustür!", ephemeral=True)
            return

        if self.used:
            return
        self.used = True

        for child in self.children:
            child.disabled = True

        roll = random.random()
        if roll < 0.45:
            gain = random.randint(25, 65)
            new_total = await update_user_points(
                self.target_user.id,
                self.target_user.name,
                gain,
                stat_field="trick_treat_plays"
            )
            embed = discord.Embed(
                title="🍬 SÜSSES! Eine freundliche Hexe öffnet die Tür!",
                description=(
                    f"Die Hexe lächelt und füllt deine Tasche mit magischen Bonbons!\n\n"
                    f"✨ Gewinn: **+{gain} Punkte**\n"
                    f"🏆 Neuer Punktestand: **{new_total}**"
                ),
                color=COLOR_SLIME
            )
            embed.set_footer(text="Fröhliches Schlemmen! 🍭")

        elif roll < 0.75:
            loss = random.randint(10, 25)
            new_total = await update_user_points(
                self.target_user.id,
                self.target_user.name,
                -loss,
                stat_field="trick_treat_plays"
            )
            embed = discord.Embed(
                title="🦇 SAURES! Ein Vampir faucht dich an!",
                description=(
                    f"Ein uralter Graf öffnet im Fledermausmantel und klaut dir Proviant!\n\n"
                    f"🩸 Verlust: **-{loss} Punkte**\n"
                    f"🏆 Neuer Punktestand: **{new_total}**"
                ),
                color=COLOR_BLOOD
            )
            embed.set_footer(text="Hättest du bloß Knoblauch mitgebracht... 🧄")

        elif roll < 0.90:
            jackpot = 120
            new_total = await update_user_points(
                self.target_user.id,
                self.target_user.name,
                jackpot,
                stat_field="trick_treat_plays"
            )
            embed = discord.Embed(
                title="🎃 JACK O'LANTERN JACKPOT!",
                description=(
                    f"Der legendäre Kürbiskönig persönlich überreicht dir ein goldenes Artefakt!\n\n"
                    f"🌟 Mega-Bonus: **+{jackpot} Punkte**!\n"
                    f"🏆 Neuer Punktestand: **{new_total}**"
                ),
                color=COLOR_PUMPKIN
            )
            embed.set_footer(text="Die Geisterwelt verbeugt sich vor dir! 👑")

        else:
            new_total = await update_user_points(
                self.target_user.id,
                self.target_user.name,
                0,
                stat_field="trick_treat_plays"
            )
            embed = discord.Embed(
                title="💀 NIEMAND ZU HAUSE...",
                description=(
                    f"Eine unheimliche Puppe starrt dich durch das Fenster an. Du rennst lieber weg!\n\n"
                    f"🛡️ Keine Punkte gewonnen oder verloren.\n"
                    f"🏆 Punktestand: **{new_total}**"
                ),
                color=COLOR_HAUNTED
            )
            embed.set_footer(text="Schnell weg hier... 🏃💨")

        await interaction.response.edit_message(embed=embed, view=self)


# -----------------------------------------------------------------------------
# 6. SLASH-COMMANDS FÜR MINISPIELE & PROFIL
# -----------------------------------------------------------------------------

@bot.tree.command(name="pumpkin", description="🎃 Kürbis-Jagd: Finde den fliehenden Geisterkürbis!")
async def slash_pumpkin(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎃 Die Jagd nach dem Geisterkürbis beginnt!",
        description=(
            "In einem der 9 finsteren Verstecke verbirgt sich der leuchtende Kürbis.\n"
            "Klicke so schnell wie möglich auf das richtige Feld, bevor er verblasst!"
        ),
        color=COLOR_PUMPKIN
    )
    embed.set_footer(text="Schnelligkeit bringt zusätzliche Punkte! ⚡")
    view = PumpkinHuntView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="geisterhaus", description="👻 Geisterhaus: Wähle die richtige Tür und entkomme den Monstern!")
async def slash_geisterhaus(interaction: discord.Interaction):
    embed = discord.Embed(
        title="👻 Willkommen im Geisterhaus (Etage 1)",
        description=(
            "Du betrittst eine alte, knarrende Villa. Drei verstaubte Türen stehen vor dir.\n"
            "Hinter einer lauert ein schreckliches Monster, hinter den anderen Schätze!\n\n"
            "Welche Tür wagst du zu öffnen?"
        ),
        color=COLOR_HAUNTED
    )
    embed.set_footer(text="Überlebe bis in die 3. Etage für maximale Punkte! 🏰")
    view = HauntedHouseView(interaction.user, stage=1, current_loot=0)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="trick-or-treat", description="🍬 Süßes oder Saures: Wage den Besuch an der verfluchten Villa!")
async def slash_trick_or_treat(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = int(time.time())

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT last_trick_treat FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                elapsed = now - row[0]
                cooldown_time = 300
                if elapsed < cooldown_time:
                    remaining = cooldown_time - elapsed
                    minutes = remaining // 60
                    seconds = remaining % 60
                    await interaction.response.send_message(
                        f"⏳ Deine Tasche ist noch voll! Die Anwohner brauchen eine Pause. Bitte warte noch **{minutes}m {seconds}s**.",
                        ephemeral=True
                    )
                    return
        
        await db.execute("UPDATE users SET last_trick_treat = ? WHERE user_id = ?", (now, user_id))
        await db.commit()

    embed = discord.Embed(
        title="🍬 Süßes oder Saures: Das Tor zur Villa",
        description=(
            "Du stehst vor einer verfallenen viktorianischen Villa.\n"
            "Kerzen flackern hinter den Gardinen. Klopfst du an die schwere Eichentür?"
        ),
        color=COLOR_PURPLE
    )
    embed.set_footer(text="Chance auf Süßes, Saures oder den Jack O'Lantern Jackpot! 🎃")
    view = TrickOrTreatView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="punkte", description="🎃 Zeigt deine gesammelten Halloween-Punkte und deinen Rang an")
@app_commands.describe(mitglied="Optional: Das Servermitglied, dessen Punkte du einsehen möchtest")
async def slash_punkte(interaction: discord.Interaction, mitglied: Optional[discord.Member] = None):
    target = mitglied or interaction.user
    user_data = await get_or_create_user(target.id, target.name)

    points = user_data.get("points", 0)
    pumpkins = user_data.get("pumpkins_caught", 0)
    haunted = user_data.get("haunted_cleared", 0)
    plays = user_data.get("trick_treat_plays", 0)

    if points >= 500:
        rank_title = "👑 Herrscher der Unterwelt"
    elif points >= 250:
        rank_title = "🧙 Meister-Hexenmeister"
    elif points >= 100:
        rank_title = "🎃 Kürbisritter"
    elif points >= 50:
        rank_title = "🦇 Vampirjäger"
    else:
        rank_title = "🕯️ Geisterlehrling"

    embed = discord.Embed(
        title=f"🎃 Spuk-Profil von {target.name}",
        description=f"Aktueller Rang: **{rank_title}**",
        color=COLOR_PUMPKIN
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🍬 Gesamtpunkte", value=f"**{points:,}**", inline=True)
    embed.add_field(name="🎃 Gefangene Kürbisse", value=f"{pumpkins}", inline=True)
    embed.add_field(name="🏰 Geisterhaus Siege", value=f"{haunted}", inline=True)
    embed.add_field(name="🚪 Süßes/Saures Runden", value=f"{plays}", inline=True)
    embed.set_footer(text="Spiele mit /pumpkin, /geisterhaus und /trick-or-treat! 👻")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rangliste", description="🏆 Zeigt die Top 10 Halloween-Punktejäger des Servers")
async def slash_rangliste(interaction: discord.Interaction):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message("🕸️ Noch wurden keine Halloween-Punkte gesammelt!", ephemeral=True)
        return

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    leaderboard_text = ""
    for idx, row in enumerate(rows):
        medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
        leaderboard_text += f"{medal} **{row['username']}** — `{row['points']} Punkte` 🍬\n"

    embed = discord.Embed(
        title="🏆 Halloween-Rangliste: Die mächtigsten Seelen",
        description=leaderboard_text,
        color=COLOR_PURPLE
    )
    embed.set_footer(text="Wer erklimmt den Spuk-Thron? 🎃")
    await interaction.response.send_message(embed=embed)


# -----------------------------------------------------------------------------
# 7. AUTOMATISCHES CHANNEL-SETUP (/setup_halloween)
# -----------------------------------------------------------------------------

@bot.tree.command(name="setup_halloween", description="🏰 Admin-Setup: Sendet Halloween-Embeds in die passenden Kanäle")
@app_commands.default_permissions(administrator=True)
async def slash_setup_halloween(interaction: discord.Interaction):
    guild = interaction.guild
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Nur Server-Administratoren können diesen Befehl ausführen!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    created_info = []

    async def get_or_create_channel(name: str, topic: str):
        existing = discord.utils.get(guild.text_channels, name=name)
        if existing:
            return existing, False
        try:
            new_chan = await guild.create_text_channel(name=name, topic=topic)
            return new_chan, True
        except Exception:
            return None, False

    # 1. #welcome
    welcome_chan, created = await get_or_create_channel("welcome", "🎃 Herzlich willkommen auf unserem Spukserver!")
    if welcome_chan:
        welcome_embed = discord.Embed(
            title="🎃 WILLKOMMEN IM REICH DER SCHATTEN 🎃",
            description=(
                "Tritt ein, wenn du dich traust! Die Tore unseres Halloween-Servers stehen weit offen.\n\n"
                "🦇 **Was dich hier erwartet:**\n"
                "• Eine gruselig-aktive Community voller Nachtgestalten\n"
                "• Spannende Minispiele mit Punktejagd (`/pumpkin`, `/geisterhaus`, `/trick-or-treat`)\n"
                "• 24/7 Geister-Support über unser Ticket-System\n"
                "• Epische Halloween-Events und Ränge!\n\n"
                "Viel Spaß beim Gruseln und Geisterjagen! 🕯️"
            ),
            color=COLOR_PUMPKIN
        )
        welcome_embed.set_image(url="https://images.unsplash.com/photo-1509557965875-b88c97052f0e?auto=format&fit=crop&w=1000&q=80")
        welcome_embed.set_footer(text=f"{guild.name} • Möge die Nacht mit dir sein 👻")
        await welcome_chan.send(embed=welcome_embed)
        created_info.append(f"• {'Erstellt & gepostet in' if created else 'Gepostet in'} {welcome_chan.mention}")

    # 2. #rules
    rules_chan, created = await get_or_create_channel("rules", "📜 Die Gesetze der Unterwelt")
    if rules_chan:
        rules_embed = discord.Embed(
            title="📜 DIE GESETZE DES SPUKHAUSES (REGELN) 🕷️",
            description=(
                "Damit das Zusammenleben zwischen Geistern, Hexen und Sterblichen friedlich bleibt:\n\n"
                "**1. Respektvoller Umgang 🕯️**\nKeine Beleidigungen, Diskriminierung oder Hetze.\n\n"
                "**2. Kein Spam & Hexenwerk 🕸️**\nKein Flooding, keine unerwünschte Eigenwerbung in DMs.\n\n"
                "**3. Angemessene Inhalte 🦇**\nNSFW-Inhalte sind strengstens verboten.\n\n"
                "**4. Moderation & Geisterrat 👑**\nAnweisungen des Support- und Admin-Teams ist Folge zu leisten.\n\n"
                "Verstöße führen zu Verbannung in das Jenseits! 💀"
            ),
            color=COLOR_HAUNTED
        )
        rules_embed.set_footer(text="Gelesen und verstanden? Dann gute Reise! 🎃")
        await rules_chan.send(embed=rules_embed)
        created_info.append(f"• {'Erstellt & gepostet in' if created else 'Gepostet in'} {rules_chan.mention}")

    # 3. #ticket-support (MIT PERSISTENTEM BUTTON)
    ticket_chan, created = await get_or_create_channel("ticket-support", "🎃 Offizieller Ticket-Support")
    if ticket_chan:
        ticket_embed = discord.Embed(
            title="🎃 HALLOWEEN TICKET-SUPPORT 🎃",
            description=(
                "Brauchst du Hilfe, hast du Fragen oder möchtest du einen Spuk melden?\n\n"
                "Klicke auf den Button **'🎃 Ticket öffnen'** unten, um einen privaten Support-Kanal zu eröffnen.\n"
                "Unser Team wird sich umgehend um deine Angelegenheit kümmern! 👻"
            ),
            color=COLOR_PUMPKIN
        )
        ticket_embed.add_field(name="🕒 Verfügbarkeit", value="Rund um die Uhr erreichbar", inline=True)
        ticket_embed.add_field(name="🔒 Privatsphäre", value="Nur du und das Team haben Einsicht", inline=True)
        ticket_embed.set_footer(text="Spuk-Support-System • Klicke unten zum Starten")
        await ticket_chan.send(embed=ticket_embed, view=TicketLaunchView())
        created_info.append(f"• {'Erstellt & gepostet in' if created else 'Gepostet in'} {ticket_chan.mention} *(mit Ticket-Button)*")

    # 4. #minigames
    mini_chan, created = await get_or_create_channel("minigames", "🎮 Halloween Minispiele & Punkte")
    if mini_chan:
        mini_embed = discord.Embed(
            title="🎮 DIE HALLOWEEN-SPIELHALLE DER VERDAMMTEN 🍬",
            description=(
                "Sammle Punkte, steige in den Rängen auf und werde zum Herrscher der Unterwelt!\n\n"
                "🎃 **/pumpkin**\nReaktionstest! Finde den echten Kürbis im finsteren 3x3 Grid.\n\n"
                "👻 **/geisterhaus**\nWage dich durch 3 unheimliche Etagen. Finde Schätze und meide die Monster!\n\n"
                "🍬 **/trick-or-treat**\nKlopfe an die verfluchte Villa. Erhalte Süßes, Saures oder den goldenen Jackpot!\n\n"
                "🏆 **/punkte** & **/rangliste**\nSieh deinen aktuellen Kontostand und die Server-Rangliste ein."
            ),
            color=COLOR_PURPLE
        )
        mini_embed.set_footer(text="Mögen die Geister dir hold sein! 🎲")
        await mini_chan.send(embed=mini_embed)
        created_info.append(f"• {'Erstellt & gepostet in' if created else 'Gepostet in'} {mini_chan.mention}")

    summary_embed = discord.Embed(
        title="🏰 Halloween Channel-Setup abgeschlossen!",
        description="Alle Embeds und interaktiven Systeme wurden eingerichtet:\n\n" + "\n".join(created_info),
        color=COLOR_SLIME
    )
    await interaction.followup.send(embed=summary_embed, ephemeral=True)


# -----------------------------------------------------------------------------
# 8. START DES BOTS
# -----------------------------------------------------------------------------
def main():
    if not TOKEN:
        logger.critical("FEHLER: 'DISCORD_TOKEN' Umgebungsvariable wurde nicht gefunden!")
        logger.critical("Bitte erstelle eine .env Datei mit DISCORD_TOKEN=dein_token oder setze die Variable.")
        sys.exit(1)
    
    logger.info("Starte Halloween Discord-Bot...")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
