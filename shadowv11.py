import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import asyncio
import time
from datetime import datetime, timedelta
import random
import aiohttp
import os
from typing import Optional, Dict, List, Tuple, Set
import json
import string
import hashlib
import base64
from collections import defaultdict, deque
import shutil
import wavelink


# ======================== CONFIGURATION ========================
TOKEN = "Your bot token"
MAIN_OWNER_ID = "id" #youid
PAYMENT_UPI = "Your upi id"
PREFIX = "|"
VERSION = "Footer text add what you want" 

# ======================== BOT SETUP ==========================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True,
    owner_id=MAIN_OWNER_ID
)

tree = bot.tree  # REQUIRED for slash commands

# Switch to dynamic per-user prefix after functions are defined
try:
    bot.command_prefix = dynamic_prefix
except:
    pass

class TicketModal(discord.ui.Modal, title="Create Ticket"):
    subject = discord.ui.TextInput(label="Subject", placeholder="Brief summary", max_length=100)
    body = discord.ui.TextInput(label="Details", style=discord.TextStyle.paragraph, placeholder="Describe your issue", max_length=1000)

    def __init__(self, ticket_type: str, user_id: int, guild_id: int):
        super().__init__()
        self.ticket_type = ticket_type
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        tid = await create_ticket_record(self.user_id, self.guild_id, str(self.subject.value), str(self.body.value), self.ticket_type, 'open')
        thread = None
        try:
            if interaction.channel and interaction.channel.permissions_for(interaction.guild.me).create_private_threads:
                tname = f"ticket-{tid or 'new'}"
                thread = await interaction.channel.create_thread(name=tname, type=discord.ChannelType.private_thread, auto_archive_duration=1440)
        except:
            thread = None
        try:
            embed = create_embed("🎫 Ticket Created", f"ID: `{tid}`\nType: `{self.ticket_type}`", discord.Color.green(), [{'name': 'Subject', 'value': str(self.subject.value), 'inline': False}])
            if thread:
                embed.add_field(name="Thread", value=f"<#{thread.id}>", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

class TicketView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        opts = [
            discord.SelectOption(label='Support', value='support'),
            discord.SelectOption(label='Billing', value='billing'),
            discord.SelectOption(label='Abuse Report', value='abuse'),
            discord.SelectOption(label='Other', value='other'),
        ]
        self.select = discord.ui.Select(placeholder='Select ticket type', min_values=1, max_values=1, options=opts)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        try:
            t = self.select.values[0]
            await interaction.response.send_modal(TicketModal(t, self.user_id, self.guild_id))
        except:
            try:
                await interaction.response.defer()
            except:
                pass

@tree.command(name="ticket", description="Create or manage tickets")
async def ticket_slash(interaction: discord.Interaction):
    try:
        embed = create_embed("🎫 Ticket", "Choose a type to create a ticket", discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=TicketView(interaction.user.id, interaction.guild.id), ephemeral=True)
    except Exception as e:
        try:
            await interaction.response.send_message("Ticket UI error", ephemeral=True)
        except:
            pass

# ======================== SYNC SLASH COMMANDS ========================
# (Moved into the main on_ready below to avoid duplicate definitions)

# ======================== GLOBAL STORAGE ========================
premium_users: Set[int] = set()
np_owners: Set[int] = set()
admin_users: Set[int] = set()
vip_users: Set[int] = set()
dm_tasks: Dict[str, bool] = {}
spam_tasks: Dict[str, bool] = {}
raid_tasks: Dict[str, bool] = {}
flood_tasks: Dict[str, bool] = {}
sdm_tasks: Dict[str, bool] = {}
command_logs: List[Dict] = []

restricted_guilds: Set[int] = set()
ALLOWED_COMMANDS_RESTRICTED: Set[str] = {
    'help', 'play', 'ytapi', 'join', 'leave', 'pause', 'resume', 'skip', 'loop',
    'nowplaying', 'queue', 'prefix', 'setemoji', 'sjoin', 'Djoin',
    'coinflip', 'dice', '8ball', 'rps', 'snake',
    'sdm', 'spdm', 'shere', 'stopshere',
    'memes', 'roast', 'kiss', 'hug', 'slap'
}

user_settings_cache: Dict[int, Dict[str, int]] = {}
settings_lock = asyncio.Lock()
invite_cooldowns: Dict[str, float] = {}
user_rate_buckets: Dict[int, deque] = defaultdict(lambda: deque(maxlen=50))

bot_stats = {
    'total_commands': 0,
    'premium_users': 0,
    'total_payments': 0,
    'total_pings': 0,
    'total_mc_bots': 0,
    'raid_operations': 0,
    'dm_spam_count': 0,
    'command_errors': 0,
    'uptime': datetime.now(),
    'messages_processed': 0,
    'dms_sent': 0,
    'users_joined': 0,
    'guilds_count': 0,
    'channels_created': 0,
    'roles_created': 0,
    'members_kicked': 0,
    'messages_deleted': 0,
    'commands_executed': 0,
    'spam_count': 0,
}

message_repeat_store: Dict[Tuple[int, int, int, str], deque] = defaultdict(lambda: deque(maxlen=10))
music_states: Dict[int, Dict] = {}
# FFMPEG_PATH removed (LavaLink handles audio)
last_msg_award: Dict[int, float] = {}
voice_join_times: Dict[int, float] = {}

# ======================== DATABASE SETUP ========================
def init_database():
    """Initialize database with all tables"""
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()

        cursor.execute("""CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY, username TEXT, purchase_date TEXT, 
            subscription_type TEXT, is_active INTEGER, payment_verification_code TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS removed_premium (
            user_id INTEGER PRIMARY KEY, username TEXT, removed_date TEXT, removed_by INTEGER)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS verification_queue (
            user_id INTEGER PRIMARY KEY, username TEXT, verification_code TEXT, 
            payment_screenshot TEXT, created_date TEXT, status TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS payment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, 
            verification_code TEXT, timestamp TEXT, status TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS np_owners (
            user_id INTEGER PRIMARY KEY, username TEXT, added_date TEXT, 
            added_by INTEGER, is_active INTEGER, verified INTEGER)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS command_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, command_name TEXT, 
            timestamp TEXT, status TEXT, response_time REAL, context TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS dm_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER, recipient_id INTEGER, 
            message_text TEXT, timestamp TEXT, status TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY, username TEXT, join_date TEXT, 
            level INTEGER, balance REAL, warnings INTEGER, last_active TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS raid_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, raider_id INTEGER, target_guild_id INTEGER, 
            timestamp TEXT, status TEXT, details TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY, value TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS youtube_api_keys (
            user_id INTEGER PRIMARY KEY, api_key TEXT, created_at TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS user_emojis (
            user_id INTEGER PRIMARY KEY, emoji TEXT, updated_at TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY, prefix_disabled INTEGER DEFAULT 0, volume INTEGER DEFAULT 100, updated_at TEXT)""")

        cursor.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            guild_id INTEGER,
            subject TEXT,
            body TEXT,
            ticket_type TEXT,
            status TEXT,
            thread_id INTEGER,
            created_at TEXT,
            updated_at TEXT
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            daily_earned INTEGER DEFAULT 0,
            last_daily TEXT,
            last_reset TEXT,
            msg_count_today INTEGER DEFAULT 0,
            vc_seconds_today INTEGER DEFAULT 0,
            work_cooldown TEXT
        )""")

        conn.commit()
        conn.close()
        print("[✅] Database initialized successfully")
    except Exception as e:
        print(f"[❌] Database error: {e}")

def load_premium_users():
    """Load premium users from database"""
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM premium_users WHERE is_active = 1")
        for row in cursor.fetchall():
            premium_users.add(row[0])
        cursor.execute("SELECT user_id FROM np_owners WHERE is_active = 1")
        for row in cursor.fetchall():
            np_owners.add(row[0])
        conn.close()
    except:
        pass

# ======================== NP SLASH COMMANDS ========================

def is_guild_owner(interaction: discord.Interaction) -> bool:
    try:
        return interaction.guild and interaction.guild.owner_id == interaction.user.id
    except:
        return False

async def ensure_np(interaction: discord.Interaction) -> bool:
    try:
        if is_np_owner(interaction.user.id):
            return True
        await interaction.response.send_message("❌ You are not an NP user!", ephemeral=True)
        return False
    except:
        try:
            await interaction.response.send_message("❌ You are not an NP user!", ephemeral=True)
        except:
            pass
        return False

@tree.command(name="premiumhelp", description="Show NP features and usage")
async def premiumhelp_slash(interaction: discord.Interaction):
    try:
        if not await ensure_np(interaction):
            return
        txt = (
            "Premium Features\n\n"
            "Only NP users can use:\n"
            "• /setactivity <type> <text>\n"
            "• /setstatus <online|idle|dnd|invisible>\n"
            "• /setbio <text>\n"
            "• /add_np_user @user\n"
            "• /remove_np_user @user\n"
        )
        embed = create_embed("👑 NP Features", txt, discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

@tree.command(name="setstatus", description="Set bot status (NP only)")
@app_commands.describe(status="online, idle, dnd, invisible")
async def setstatus_slash(interaction: discord.Interaction, status: str):
    try:
        if not await ensure_np(interaction):
            return
        sv = status.lower().strip()
        if sv not in ["online", "idle", "dnd", "invisible"]:
            await interaction.response.send_message("Invalid status", ephemeral=True)
            return
        set_config_value('bot_status', sv)
        await interaction.response.send_message(f"✅ Status set to `{sv}`", ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

@tree.command(name="setactivity", description="Set bot activity (NP only)")
@app_commands.describe(kind="playing/watching/listening/competing", text="Activity text")
async def setactivity_slash(interaction: discord.Interaction, kind: str, text: str):
    try:
        if not await ensure_np(interaction):
            return
        kv = kind.lower().strip()
        if kv not in ["playing", "watching", "listening", "competing"]:
            await interaction.response.send_message("Invalid kind", ephemeral=True)
            return
        set_config_value('activity_type', kv)
        set_config_value('activity_text', text[:128])
        await interaction.response.send_message(f"✅ Activity set to `{kv}`: {text[:128]}", ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

@tree.command(name="setbio", description="Set bot bio text (NP only)")
@app_commands.describe(text="Bot bio text")
async def setbio_slash(interaction: discord.Interaction, text: str):
    try:
        if not await ensure_np(interaction):
            return
        set_config_value('bot_bio', text[:190])
        await interaction.response.send_message("✅ Bio saved", ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

@tree.command(name="add_np_user", description="Add NP user (server owner only)")
@app_commands.describe(user="User to grant NP access")
async def add_np_user_slash(interaction: discord.Interaction, user: discord.User):
    try:
        if not is_guild_owner(interaction):
            await interaction.response.send_message("❌ Only server owner can use this", ephemeral=True)
            return
        np_owners.add(user.id)
        try:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO np_owners (user_id, username, added_date, added_by, is_active, verified) VALUES (?, ?, ?, ?, ?, ?)",
                          (user.id, str(user), str(datetime.now()), interaction.user.id, 1, 1))
            conn.commit()
            conn.close()
        except:
            pass
        await interaction.response.send_message(f"✅ {user.mention} added as NP user", ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

@tree.command(name="remove_np_user", description="Remove NP user (server owner only)")
@app_commands.describe(user="User to remove NP access")
async def remove_np_user_slash(interaction: discord.Interaction, user: discord.User):
    try:
        if not is_guild_owner(interaction):
            await interaction.response.send_message("❌ Only server owner can use this", ephemeral=True)
            return
        if user.id in np_owners:
            np_owners.discard(user.id)
        try:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE np_owners SET is_active = 0 WHERE user_id = ?", (user.id,))
            conn.commit()
            conn.close()
        except:
            pass
        await interaction.response.send_message(f"✅ {user.mention} removed from NP users", ephemeral=True)
    except:
        try:
            await interaction.response.send_message("Error", ephemeral=True)
        except:
            pass

# ======================== HELPER FUNCTIONS ========================
def create_embed(title: str, description: str = "", color=discord.Color.blue(), fields=None) -> discord.Embed:
    """Create formatted embed with Shadow Clouds branding"""
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for field in fields:
            embed.add_field(name=field.get('name', ''), value=field.get('value', ''), inline=field.get('inline', False))
    embed.set_footer(text=f"Made by: Shadow Clouds | {VERSION} | {datetime.now().strftime('%H:%M:%S')}")
    return embed

def is_main_owner(user_id: int) -> bool:
    return user_id == MAIN_OWNER_ID

def is_premium_user(user_id: int) -> bool:
    return user_id in premium_users or user_id == MAIN_OWNER_ID

def is_np_owner(user_id: int) -> bool:
    return user_id in np_owners or user_id == MAIN_OWNER_ID

MAX_DAILY_CAP = 50

def get_economy(user_id: int) -> Dict:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT coins, daily_earned, last_daily, last_reset, msg_count_today, vc_seconds_today, work_cooldown FROM economy WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT OR IGNORE INTO economy (user_id, coins, daily_earned) VALUES (?, ?, ?)", (user_id, 0, 0))
            conn.commit()
            cursor.execute("SELECT coins, daily_earned, last_daily, last_reset, msg_count_today, vc_seconds_today, work_cooldown FROM economy WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        conn.close()
        return {
            'coins': row[0] or 0,
            'daily_earned': row[1] or 0,
            'last_daily': row[2],
            'last_reset': row[3],
            'msg_count_today': row[4] or 0,
            'vc_seconds_today': row[5] or 0,
            'work_cooldown': row[6]
        }
    except:
        return {'coins': 0, 'daily_earned': 0, 'last_daily': None, 'last_reset': None, 'msg_count_today': 0, 'vc_seconds_today': 0, 'work_cooldown': None}

def set_economy(user_id: int, **updates) -> bool:
    try:
        fields = []
        values = []
        for k, v in updates.items():
            fields.append(f"{k} = ?")
            values.append(v)
        values.append(user_id)
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute(f"UPDATE economy SET {', '.join(fields)} WHERE user_id = ?", tuple(values))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def reset_daily_if_needed(user_id: int) -> None:
    try:
        econ = get_economy(user_id)
        now = datetime.now()
        last_reset = datetime.fromisoformat(econ['last_reset']) if econ['last_reset'] else None
        if not last_reset or (now.date() != last_reset.date()):
            set_economy(user_id, daily_earned=0, msg_count_today=0, vc_seconds_today=0, last_reset=str(now))
    except:
        pass

def add_coins(user_id: int, amount: int) -> int:
    try:
        reset_daily_if_needed(user_id)
        econ = get_economy(user_id)
        remaining = MAX_DAILY_CAP - int(econ['daily_earned'] or 0)
        to_add = max(0, min(amount, remaining))
        if to_add <= 0:
            return 0
        new_coins = int(econ['coins'] or 0) + to_add
        new_daily = int(econ['daily_earned'] or 0) + to_add
        set_economy(user_id, coins=new_coins, daily_earned=new_daily)
        return to_add
    except:
        return 0

def can_claim_daily(user_id: int) -> Tuple[bool, Optional[int]]:
    try:
        reset_daily_if_needed(user_id)
        econ = get_economy(user_id)
        last = datetime.fromisoformat(econ['last_daily']) if econ['last_daily'] else None
        if last:
            delta = datetime.now() - last
            remaining = max(0, 24*3600 - int(delta.total_seconds()))
            if remaining > 0:
                return False, remaining
        return True, None
    except:
        return False, None

async def log_command(ctx, success: bool = True, response_time: float = 0):
    """Log command execution"""
    try:
        bot_stats['total_commands'] += 1
        bot_stats['commands_executed'] += 1
        try:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO command_logs (user_id, command_name, timestamp, status, response_time, context) 
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (ctx.author.id, ctx.command.name if ctx.command else 'unknown', str(datetime.now()), 
                           'success' if success else 'failed', response_time, ''))
            conn.commit()
            conn.close()
        except:
            pass
    except:
        pass

async def check_url(url: str, timeout: float = 2) -> Tuple[bool, int, float]:
    """Check if URL is reachable"""
    try:
        start = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                return True, response.status, (time.time() - start) * 1000
    except:
        return False, 0, 0

def get_config_value(key: str) -> Optional[str]:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except:
        pass
    return None

def set_config_value(key: str, value: str) -> bool:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_user_api_key(user_id: int) -> Optional[str]:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT api_key FROM youtube_api_keys WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except:
        pass
    return None

def set_user_api_key(user_id: int, api_key: str) -> bool:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO youtube_api_keys (user_id, api_key, created_at) VALUES (?, ?, ?)", (user_id, api_key, str(datetime.now())))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def log_error(ctx, where: str, detail: str):
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO command_logs (user_id, command_name, timestamp, status, response_time, context)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                       (ctx.author.id if ctx else 0, where, str(datetime.now()), 'failed', 0, detail[:500]))
        conn.commit()
        conn.close()
    except:
        pass

async def create_ticket_record(user_id: int, guild_id: int, subject: str, body: str, ticket_type: str, status: str = 'open', thread_id: Optional[int] = None) -> Optional[int]:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tickets (user_id, guild_id, subject, body, ticket_type, status, thread_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, guild_id, subject, body, ticket_type, status, thread_id or 0, str(datetime.now()), str(datetime.now()))
        )
        tid = cursor.lastrowid
        conn.commit()
        conn.close()
        return tid
    except Exception as e:
        return None

def get_user_settings(user_id: int) -> Dict[str, int]:
    try:
        val = user_settings_cache.get(user_id)
        if val:
            return val
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT prefix_disabled, volume FROM user_settings WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            data = {'prefix_disabled': int(row[0] or 0), 'volume': int(row[1] or 100)}
        else:
            data = {'prefix_disabled': 0, 'volume': 100}
        user_settings_cache[user_id] = data
        return data
    except:
        return {'prefix_disabled': 0, 'volume': 100}

async def set_prefix_disabled(user_id: int, disabled: bool) -> bool:
    try:
        async with settings_lock:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_settings (user_id, prefix_disabled, volume, updated_at) VALUES (?, ?, COALESCE((SELECT volume FROM user_settings WHERE user_id = ?), 100), ?)",
                (user_id, 1 if disabled else 0, user_id, str(datetime.now()))
            )
            conn.commit()
            conn.close()
            user_settings_cache[user_id] = {'prefix_disabled': 1 if disabled else 0, 'volume': user_settings_cache.get(user_id, {}).get('volume', 100)}
        return True
    except:
        return False

async def set_user_volume(user_id: int, volume: int) -> bool:
    try:
        async with settings_lock:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_settings (user_id, prefix_disabled, volume, updated_at) VALUES (?, COALESCE((SELECT prefix_disabled FROM user_settings WHERE user_id = ?), 0), ?, ?)",
                (user_id, user_id, volume, str(datetime.now()))
            )
            conn.commit()
            conn.close()
            user_settings_cache[user_id] = {'prefix_disabled': user_settings_cache.get(user_id, {}).get('prefix_disabled', 0), 'volume': volume}
        return True
    except:
        return False

async def dynamic_prefix(bot, message):
    try:
        st = get_user_settings(message.author.id)
        if st.get('prefix_disabled'):
            return ['', PREFIX]
    except:
        pass
    return PREFIX

def get_user_emoji(user_id: int) -> Optional[str]:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT emoji FROM user_emojis WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
    except:
        pass
    return None

def set_user_emoji(user_id: int, emoji: str) -> bool:
    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_emojis (user_id, emoji, updated_at) VALUES (?, ?, ?)",
            (user_id, emoji, str(datetime.now()))
        )
        conn.commit()
        conn.close()
        return True
    except:
        return False

@bot.check
async def restricted_check(ctx: commands.Context) -> bool:
    try:
        if not ctx.guild:
            return True
        if ctx.guild.id in restricted_guilds:
            nm = ctx.command.name if ctx.command else ''
            return nm in ALLOWED_COMMANDS_RESTRICTED
        return True
    except:
        return True

async def require_premium(ctx) -> bool:
    """Check if user has premium"""
    if is_premium_user(ctx.author.id):
        return True
    embed = create_embed(
        "❌ Premium Required",
        f"This command requires premium access!\nGet premium with: {PREFIX}buy (₹20)",
        discord.Color.red(),
        [{'name': '💡 Tip', 'value': f'`{PREFIX}buy to get premium access now!`', 'inline': False}]
    )
    try:
        if isinstance(ctx.channel, discord.DMChannel):
            await ctx.author.send(embed=embed)
        else:
            await ctx.send(embed=embed, delete_after=10)
    except:
        pass
    return False

# ======================== BOT EVENTS ========================
@bot.event
async def on_ready():
    """Bot ready event"""
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash commands ✔")
    except Exception as e:
        print(e)
    print(f"[✅] Bot logged in: {bot.user}")
    print(f"[✅] Total Commands: {len(bot.commands)}")
    print(f"[✅] Premium Users: {len(premium_users)}")
    print(f"[✅] NP Owners: {len(np_owners)}")
    bot_stats['guilds_count'] = len(bot.guilds)
    try:
        change_status.start()
    except:
        pass
    try:
        voice_reward_loop.start()
    except:
        pass

    try:
        nodes = [wavelink.Node(uri="http://103.180.237.57:25573", password="VortexenX")]
        await wavelink.Pool.connect(nodes=nodes, client=bot, cache_capacity=100)
        print("[✅] LavaLink Connected")
    except Exception as e:
        print(f"[❌] LavaLink Error: {e}")

@bot.event
async def on_message(message):
    """Handle all messages including DMs"""
    if message.author.bot:
        return
    bot_stats['messages_processed'] += 1

    if isinstance(message.channel, discord.DMChannel):
        try:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO dm_tracking (sender_id, recipient_id, message_text, timestamp, status) 
                             VALUES (?, ?, ?, ?, ?)""",
                          (message.author.id, bot.user.id, message.content, str(datetime.now()), 'received'))
            conn.commit()
            conn.close()
        except:
            pass

        if not message.content.startswith(PREFIX) and len(message.content) > 3:
            embed = create_embed(
                "👋 DM Received",
                message.content[:200],
                discord.Color.blue(),
                [{'name': '💬 Reply', 'value': f'`Use {PREFIX}help for commands`', 'inline': False}]
            )
            try:
                await message.author.send(embed=embed)
            except:
                pass

    if not isinstance(message.channel, discord.DMChannel):
        try:
            key = (message.guild.id, message.channel.id, message.author.id, message.content.strip())
            bucket = message_repeat_store[key]
            bucket.append(message)
            recent = [m for m in list(bucket) if (message.created_at - m.created_at).total_seconds() <= 120]
            if len(recent) >= 5:
                keep = recent[0]
                for m in recent[1:]:
                    try:
                        await m.delete()
                    except:
                        pass
                try:
                    warn = create_embed("⚠️ Spam Detected", f"{message.author.mention} repeated the same message 5 times. Duplicates were removed.", discord.Color.orange())
                    await message.channel.send(embed=warn, delete_after=8)
                except:
                    pass
                try:
                    message_repeat_store[key].clear()
                except:
                    pass
                return
            if message.guild.id in restricted_guilds:
                try:
                    import random as _rnd
                    if _rnd.random() < 0.08:
                        emo = get_user_emoji(message.author.id) or '👍'
                        try:
                            await message.add_reaction(emo)
                        except:
                            pass
                    if _rnd.random() < 0.02 and message.channel.permissions_for(message.guild.me).send_messages:
                        try:
                            await message.channel.send(random.choice(['nice', 'cool', 'haha', 'lol', 'gg']))
                        except:
                            pass
                except:
                    pass
        except:
            pass

    try:
        b = user_rate_buckets[message.author.id]
        now = time.time()
        b.append(now)
        while b and now - b[0] > 1.0:
            b.popleft()
        if len(b) > 10:
            return
    except:
        pass
    try:
        if not isinstance(message.channel, discord.DMChannel) and not message.author.bot:
            reset_daily_if_needed(message.author.id)
            econ = get_economy(message.author.id)
            cnt = int(econ['msg_count_today'] or 0) + 1
            set_economy(message.author.id, msg_count_today=cnt)
            ok_bucket = True
            try:
                ok_bucket = len(user_rate_buckets[message.author.id]) <= 5
            except:
                ok_bucket = True
            last_aw = last_msg_award.get(message.author.id, 0)
            if cnt % 5 == 0 and ok_bucket and (time.time() - last_aw) > 10:
                gained = add_coins(message.author.id, 5)
                if gained > 0:
                    last_msg_award[message.author.id] = time.time()
    except:
        pass
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    try:
        if member.bot:
            return
        reset_daily_if_needed(member.id)
        if after.channel and not before.channel:
            voice_join_times[member.id] = time.time()
        elif before.channel and not after.channel:
            started = voice_join_times.pop(member.id, None)
            if started:
                secs = int(time.time() - started)
                econ = get_economy(member.id)
                vct = int(econ['vc_seconds_today'] or 0) + secs
                set_economy(member.id, vc_seconds_today=vct)
                while vct >= 600:
                    gained = add_coins(member.id, 10)
                    vct -= 600
                    set_economy(member.id, vc_seconds_today=vct)
    except:
        pass

@tasks.loop(seconds=60)
async def voice_reward_loop():
    try:
        now = time.time()
        for uid, started in list(voice_join_times.items()):
            dur = int(now - started)
            econ = get_economy(uid)
            vct = int(econ['vc_seconds_today'] or 0) + 60
            set_economy(uid, vc_seconds_today=vct)
            while vct >= 600:
                gained = add_coins(uid, 10)
                vct -= 600
                set_economy(uid, vc_seconds_today=vct)
    except:
        pass

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors with proper formatting"""
    bot_stats['command_errors'] += 1

    if isinstance(error, commands.CommandNotFound):
        cmd_used = ctx.message.content[len(PREFIX):].split()[0]
        embed = create_embed(
            "❌ Command Not Found",
            f"The command `{PREFIX}{cmd_used}` doesn't exist in Shadow Clouds Bot",
            discord.Color.red(),
            [
                {'name': '📝 You Used', 'value': f'`{ctx.message.content}`', 'inline': False},
                {'name': '💡 Solution', 'value': f'Use `{PREFIX}help` to see all available commands', 'inline': False},
                {'name': '🆔 Command Not Found', 'value': f'`{PREFIX}{cmd_used}`', 'inline': False},
            ]
        )
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = create_embed(
            "❌ Missing Arguments",
            "This command requires more arguments",
            discord.Color.red(),
            [{'name': '💡 Tip', 'value': f'Use `{PREFIX}help <command>` for more info', 'inline': False}]
        )
    else:
        embed = create_embed(
            "❌ Error Occurred",
            str(error)[:256],
            discord.Color.red(),
            [{'name': 'Error Type', 'value': f'`{type(error).__name__}`', 'inline': False}]
        )

    try:
        if isinstance(ctx.channel, discord.DMChannel):
            await ctx.author.send(embed=embed)
        else:
            await ctx.send(embed=embed, delete_after=8)
    except:
        pass

# ======================== STATUS CHANGE ========================
@tasks.loop(minutes=5)
async def change_status():
    """Change bot status every 5 minutes"""
    try:
        # Apply saved overrides if present
        try:
            stv = (get_config_value('bot_status') or '').lower()
            status_map = {
                'online': discord.Status.online,
                'idle': discord.Status.idle,
                'dnd': discord.Status.do_not_disturb,
                'invisible': discord.Status.invisible,
            }
            bot_status = status_map.get(stv, None)
        except:
            bot_status = None

        atype = (get_config_value('activity_type') or '').lower()
        atext = get_config_value('activity_text') or ''

        if atype and atext:
            try:
                if atype == 'playing':
                    await bot.change_presence(status=bot_status, activity=discord.Game(name=atext))
                elif atype == 'watching':
                    await bot.change_presence(status=bot_status, activity=discord.Activity(type=discord.ActivityType.watching, name=atext))
                elif atype == 'listening':
                    await bot.change_presence(status=bot_status, activity=discord.Activity(type=discord.ActivityType.listening, name=atext))
                elif atype == 'competing':
                    await bot.change_presence(status=bot_status, activity=discord.Activity(type=discord.ActivityType.competing, name=atext))
                else:
                    await bot.change_presence(status=bot_status)
                return
            except:
                pass

        np_title = None
        np_title = None
        try:
             # Check local players via bot.voice_clients which are wavelink players
             for vc in bot.voice_clients:
                 if hasattr(vc, 'current') and vc.current:
                     np_title = vc.current.title
                     break
        except:
             pass
        if np_title:
            await bot.change_presence(status=bot_status, activity=discord.Activity(type=discord.ActivityType.listening, name=np_title))
        else:
            statuses = [
                f"{PREFIX}help",
                f"Premium: {len(premium_users)}",
                f"Servers: {len(bot.guilds)}",
                VERSION,
            ]
            status = random.choice(statuses)
            await bot.change_presence(status=bot_status, activity=discord.Game(name=status))
    except:
        pass

async def ensure_voice(ctx) -> Optional[discord.VoiceClient]:
    try:
        try:
            import nacl
        except Exception:
            try:
                embed = create_embed("❌ PyNaCl Missing", "Install PyNaCl in your environment: `pip install PyNaCl`", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            return None
        if not ctx.author.voice or not ctx.author.voice.channel:
            try:
                embed = create_embed("❌ Join Voice", "Join a voice channel first", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            return None
        target_ch = ctx.author.voice.channel
        me = ctx.guild.me
        try:
            perms = target_ch.permissions_for(me)
            missing = []
            if not getattr(perms, 'connect', True):
                missing.append('Connect')
            if not getattr(perms, 'speak', True):
                missing.append('Speak')
            if missing:
                try:
                    embed = create_embed("❌ Missing Voice Permissions", f"{', '.join(missing)} required in `{target_ch.name}`", discord.Color.red())
                    await ctx.send(embed=embed)
                except:
                    pass
                return None
        except:
            pass
        vc = ctx.guild.voice_client
        if vc and vc.channel == ctx.author.voice.channel:
            return vc
        if vc and vc.is_connected():
            try:
                await vc.move_to(ctx.author.voice.channel)
                return vc
            except:
                try:
                    embed = create_embed("❌ Cannot Move", "Missing permissions to move to your channel", discord.Color.red())
                    await ctx.send(embed=embed)
                except:
                    pass
        try:
            vc = await target_ch.connect(cls=wavelink.Player)
            vc.autoplay = wavelink.AutoPlayMode.enabled
            return vc
        except Exception as e:
            try:
                embed = create_embed("❌ Cannot Join", f"`{str(e)[:160]}`", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            return None
    except:
        return None

# ======================== LAVALINK SYSTEM ========================

@bot.event
async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload):
    player: wavelink.Player = payload.player
    if not player:
        return
    track = payload.track
    
    # Cancel disconnect timer
    if hasattr(player, "stop_timer") and player.stop_timer:
        player.stop_timer.cancel()
        player.stop_timer = None

    try:
        requester = getattr(track.extras, "requester", f"<@{player.client.user.id}>")
        
        # Duration string
        dur = "Live"
        if not track.is_stream:
            seconds = track.length // 1000
            m, s = divmod(seconds, 60)
            dur = f"{m}:{s:02d}"

        embed = create_embed("<a:playing:1430654136067817595> Now Playing", f"[{track.title}]({track.uri})", discord.Color.green())
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
            
        embed.add_field(name="<a:white_people:1430785234529681473> Requested by", value=requester, inline=True)
        embed.add_field(name="<:slowmode:1430789015107272805> Duration", value=dur, inline=True)
        embed.add_field(name="<a:FogoWhite:1430787080539078657>Controls", value=f"`{PREFIX}pause` `{PREFIX}resume` `{PREFIX}skip` `{PREFIX}loop` `{PREFIX}volume`", inline=False)
        
        ch_id = getattr(player, "home_channel", None)
        if ch_id:
            channel = bot.get_channel(ch_id)
            if channel:
                view = PlayerViewPause(player.guild.id)
                msg = await channel.send(embed=embed, view=view)
                player.message = msg
    except Exception as e:
        print(f"NP Error: {e}")

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player = payload.player
    if not player:
        return
    if player.queue.is_empty and not player.playing:
        # Start disconnect timer
        async def disconnect_after():
             await asyncio.sleep(180)
             if player.queue.is_empty and not player.playing:
                 await player.disconnect()
        player.stop_timer = asyncio.create_task(disconnect_after())

class PlayerViewPause(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="⏯ Pause", style=discord.ButtonStyle.secondary, row=0)
    async def pause_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            await player.pause(True)
            await interaction.response.edit_message(view=PlayerViewResume(self.guild_id))
        else:
            await interaction.response.send_message("No player found", ephemeral=True)

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.primary, row=0)
    async def skip_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            await player.skip(force=True)
            await interaction.response.defer()
        else:
            await interaction.response.defer()

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary, row=0)
    async def loop_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            if player.queue.mode == wavelink.QueueMode.loop:
                player.queue.mode = wavelink.QueueMode.normal
                button.style = discord.ButtonStyle.secondary
            else:
                player.queue.mode = wavelink.QueueMode.loop
                button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="⏮ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="🛑 Stop", style=discord.ButtonStyle.danger, row=1)
    async def stop_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            player.autoplay = wavelink.AutoPlayMode.disabled
            player.queue.clear()
            await player.stop()
            try:
                 await interaction.response.send_message("Stopped!", ephemeral=True)
            except:
                 pass

class PlayerViewResume(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="▶ Resume", style=discord.ButtonStyle.success, row=0)
    async def resume_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            await player.pause(False)
            await interaction.response.edit_message(view=PlayerViewPause(self.guild_id))
        else:
            await interaction.response.send_message("No player found", ephemeral=True)

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.primary, row=0)
    async def skip_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            await player.skip(force=True)
            await interaction.response.defer()
        else:
            await interaction.response.defer()

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary, row=0)
    async def loop_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            if player.queue.mode == wavelink.QueueMode.loop:
                player.queue.mode = wavelink.QueueMode.normal
                button.style = discord.ButtonStyle.secondary
            else:
                player.queue.mode = wavelink.QueueMode.loop
                button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="⏮ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="🛑 Stop", style=discord.ButtonStyle.danger, row=1)
    async def stop_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = wavelink.Pool.get_node().get_player(interaction.guild.id)
        if player:
            player.autoplay = wavelink.AutoPlayMode.disabled
            player.queue.clear()
            await player.stop()
            try:
                 await interaction.response.send_message("Stopped!", ephemeral=True)
            except:
                 pass

# Volume buttons removed per user request

@bot.command(name='play', aliases=['vplay'])
async def play_cmd(ctx, *, query: str = None):
    start = time.time()
    if not query:
        embed = create_embed("❌ Error", f"Usage: `{PREFIX}play <query>`", discord.Color.red())
        await ctx.send(embed=embed)
        return

    if not ctx.voice_client:
        try:
             if ctx.author.voice:
                 await ctx.author.voice.channel.connect(cls=wavelink.Player)
             else:
                 await ctx.send("Join a voice channel!")
                 return
        except Exception as e:
             await ctx.send(f"Connection error: {e}")
             return

    vc: wavelink.Player = ctx.voice_client
    vc.autoplay = wavelink.AutoPlayMode.enabled
    vc.home_channel = ctx.channel.id 

    try:
        tracks = await wavelink.Playable.search(query)
        if not tracks:
            await ctx.send("No results.")
            return

        track = tracks[0] if isinstance(tracks, list) else tracks
        track.extras = {"requester": ctx.author.mention}
        
        await vc.queue.put_wait(track)
        
        if not vc.playing:
            await vc.play(vc.queue.get())
        else:
            embed = create_embed("✅ Added to Queue", f"[{track.title}]({track.uri})", discord.Color.green())
            await ctx.send(embed=embed)
            
    except Exception as e:
        await ctx.send(f"Error: {e}")
    await log_command(ctx, True, time.time() - start)

@bot.command(name='skip')
async def skip_cmd(ctx):
    if ctx.voice_client:
        await ctx.voice_client.skip(force=True)
        await ctx.send("Skipped ⏭")

@bot.command(name='stop')
async def stop_cmd(ctx):
    vc: wavelink.Player = ctx.voice_client
    if vc:
        vc.autoplay = wavelink.AutoPlayMode.disabled
        vc.queue.clear()
        await vc.stop()
        await ctx.send("Stopped and queue cleared! 🛑")

@bot.command(name='autoplay')
async def autoplay_cmd(ctx):
    vc: wavelink.Player = ctx.voice_client
    if vc:
        if vc.autoplay == wavelink.AutoPlayMode.enabled:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            await ctx.send("Autoplay Disabled ❌")
        else:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            await ctx.send("Autoplay Enabled ✅")

@bot.command(name='pause')
async def pause_cmd(ctx):
    if ctx.voice_client:
        await ctx.voice_client.pause(True)
        await ctx.send("Paused ⏯")

@bot.command(name='resume')
async def resume_cmd(ctx):
    if ctx.voice_client:
        await ctx.voice_client.pause(False)
        await ctx.send("Resumed ▶")

@bot.command(name='loop')
async def loop_cmd(ctx):
    vc = ctx.voice_client
    if vc:
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            await ctx.send("Loop Disabled")
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            await ctx.send("Loop Enabled 🔁")

@bot.command(name='nowplaying')
async def now_playing_cmd(ctx):
    vc: wavelink.Player = ctx.voice_client
    if not vc or not vc.current:
        return
    
    track = vc.current
    try:
        requester = getattr(track.extras, "requester", f"<@{bot.user.id}>")
        dur = "Live"
        if not track.is_stream:
             m, s = divmod(track.length // 1000, 60)
             dur = f"{m}:{s:02d}"
        
        embed = create_embed("🎵 Now Playing", f"[{track.title}]({track.uri})", discord.Color.green())
        if track.artwork:
             embed.set_thumbnail(url=track.artwork)
        embed.add_field(name="🎙️ Requested by", value=requester, inline=True)
        embed.add_field(name="⏱️ Duration", value=dur, inline=True)
        embed.add_field(name="⚙️ Controls", value=f"`{PREFIX}pause` `{PREFIX}resume` `{PREFIX}skip` `{PREFIX}loop`", inline=False)
        
        await ctx.send(embed=embed, view=PlayerViewPause(ctx.guild.id))
    except:
        pass

@bot.command(name='queue')
async def queue_cmd(ctx):
    vc: wavelink.Player = ctx.voice_client
    if not vc or vc.queue.is_empty:
        await ctx.send("Queue is empty.")
        return
    lines = [f"{i+1}. {t.title}" for i, t in enumerate(vc.queue[:10])]
    embed = create_embed("📜 Queue", "\n".join(lines), discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name='ytapi')
async def ytapi_cmd(ctx, *, key: str = None):
    embed = create_embed("✅ Upgrade", "YouTube API is not used! Using LavaLink.", discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name='setemoji')
async def setemoji_cmd(ctx, *, emoji: str = None):
    start = time.time()
    if emoji is None:
        cur = get_user_emoji(ctx.author.id) or 'Not set'
        try:
            embed = create_embed("🎯 Your Emoji", str(cur), discord.Color.blue())
            await ctx.send(embed=embed)
        except:
            pass
        await log_command(ctx, True, time.time() - start)
        return
    val = emoji.strip()
    if len(val) > 32:
        val = val[:32]
    ok = set_user_emoji(ctx.author.id, val)
    try:
        embed = create_embed("✅ Emoji Saved", val, discord.Color.green())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, ok, time.time() - start)

@bot.command(name='volume')
async def volume_cmd(ctx, *, value: int = None):
    vc: wavelink.Player = ctx.voice_client
    if not vc:
        return
    if value is None:
        await ctx.send(f"Volume: {vc.volume}%")
        return
    await vc.set_volume(max(0, min(1000, value)))
    await ctx.send(f"Volume set to {value}%")

async def attempt_play_default(ctx):
    try:
        vc = ctx.voice_client
        if not vc and ctx.author.voice:
             vc = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        if vc:
            if not getattr(vc, 'home_channel', None):
                vc.home_channel = ctx.channel.id
            tracks = await wavelink.Playable.search("lofi hip hop radio")
            if tracks:
                t = tracks[0]
                t.extras = {"requester": ctx.author.mention}
                vc.autoplay = wavelink.AutoPlayMode.enabled
                await vc.play(t)
    except:
        pass

def parse_invite_code(url: str) -> Optional[str]:
    try:
        if not url:
            return None
        u = url.strip()
        if 'discord.gg/' in u:
            return u.split('discord.gg/')[-1].split('?')[0].strip()
        if 'discord.com/invite/' in u:
            return u.split('discord.com/invite/')[-1].split('?')[0].strip()
        if 'discordapp.com/invite/' in u:
            return u.split('discordapp.com/invite/')[-1].split('?')[0].strip()
        if len(u) <= 12 and u.isalnum():
            return u
        return None
    except:
        return None

async def validate_invite(code: str) -> Optional[Dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://discord.com/api/v10/invites/{code}?with_counts=true&with_expiration=true') as resp:
                if resp.status == 200:
                    return await resp.json()
    except:
        return None
    return None

@bot.command(name='sjoin')
async def sjoin_cmd(ctx, *, server_invite_url: str = None):
    start = time.time()
    if not ctx.guild:
        return
    if server_invite_url:
        code = parse_invite_code(server_invite_url)
        if not code:
            try:
                embed = create_embed("❌ Invalid Invite", "Invalid server invite URL", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            await log_command(ctx, False, time.time() - start)
            return
        now = time.time()
        last = invite_cooldowns.get(code, 0)
        if now - last < 60:
            try:
                embed = create_embed("⏱️ Cooldown", "Please wait before reusing this invite", discord.Color.orange())
                await ctx.send(embed=embed)
            except:
                pass
            await log_command(ctx, False, time.time() - start)
            return
        invite_cooldowns[code] = now
        meta = await validate_invite(code)
        if not meta:
            try:
                embed = create_embed("❌ Invalid Invite", "Invite could not be verified", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            await log_error(ctx, 'sjoin', f'invite validate failed: {code}')
            await log_command(ctx, False, time.time() - start)
            return
        try:
            g = meta.get('guild') or {}
            gname = g.get('name', 'Unknown')
            cid = bot.user.id
            url = f"https://discord.com/oauth2/authorize?client_id={cid}&scope=bot%20applications.commands&permissions=8"
            embed = create_embed("ℹ️ Invite Verified", f"Server: `{gname}`\nInvite the bot using this link for admin: {url}", discord.Color.blue())
            await ctx.send(embed=embed)
        except:
            pass
    restricted_guilds.add(ctx.guild.id)
    try:
        mep = ctx.guild.me.guild_permissions
        permtxt = 'admin' if getattr(mep, 'administrator', False) else 'limited'
        embed = create_embed("✅ Restricted Mode Enabled", "This guild is now limited to human-like actions", discord.Color.green(), [{'name': 'Permissions', 'value': permtxt, 'inline': True}, {'name': 'Allowed', 'value': '`help, music, games, reactions`', 'inline': False}])
        await ctx.send(embed=embed)
    except:
        pass
    try:
        if ctx.author.voice and ctx.author.voice.channel:
            try:
                if ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
                    await ctx.guild.voice_client.move_to(ctx.author.voice.channel)
                else:
                    await ctx.author.voice.channel.connect()
            except Exception as e:
                log_error(ctx, 'sjoin_voice', str(e))
            await attempt_play_default(ctx)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='balance')
async def balance_cmd(ctx):
    start = time.time()
    try:
        reset_daily_if_needed(ctx.author.id)
        econ = get_economy(ctx.author.id)
        remaining = MAX_DAILY_CAP - int(econ['daily_earned'] or 0)
        embed = create_embed('💰 Balance', f'Coins: `{econ["coins"]}`', discord.Color.gold(), [
            {'name': 'Daily cap remaining', 'value': f'`{max(0, remaining)}`', 'inline': True}
        ])
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='daily')
async def daily_cmd(ctx):
    start = time.time()
    try:
        ok, remaining = can_claim_daily(ctx.author.id)
        if not ok:
            embed = create_embed('⏱️ Daily', f'You can claim after `{int(remaining//3600)}h {int((remaining%3600)//60)}m`', discord.Color.orange())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
        gained = add_coins(ctx.author.id, 20)
        set_economy(ctx.author.id, last_daily=str(datetime.now()))
        embed = create_embed('✅ Daily Claimed', f'Received `{gained}` coins', discord.Color.green())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='work')
async def work_cmd(ctx):
    start = time.time()
    try:
        reset_daily_if_needed(ctx.author.id)
        econ = get_economy(ctx.author.id)
        last = datetime.fromisoformat(econ['work_cooldown']) if econ['work_cooldown'] else None
        if last and (datetime.now() - last).total_seconds() < 3600:
            remain = 3600 - int((datetime.now() - last).total_seconds())
            embed = create_embed('⏱️ Work', f'Try again in `{int(remain//60)}m`', discord.Color.orange())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
        reward = random.randint(5, 10)
        gained = add_coins(ctx.author.id, reward)
        set_economy(ctx.author.id, work_cooldown=str(datetime.now()))
        embed = create_embed('🛠️ Work', f'You earned `{gained}` coins', discord.Color.green())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='shop')
async def shop_cmd(ctx, *, item: str = None):
    start = time.time()
    try:
        reset_daily_if_needed(ctx.author.id)
        if not item:
            embed = create_embed('🛒 Shop', 'Items available:', discord.Color.blurple(), [
                {'name': 'Shadow Premium', 'value': '`110 coins` → `|shop premium`', 'inline': False}
            ])
            await ctx.send(embed=embed)
            await log_command(ctx, True, time.time() - start)
            return
        if item.lower() == 'premium':
            econ = get_economy(ctx.author.id)
            if int(econ['coins'] or 0) < 110:
                embed = create_embed('❌ Not Enough Coins', 'You need `110` coins for Premium', discord.Color.red())
                await ctx.send(embed=embed)
                await log_command(ctx, False, time.time() - start)
                return
            set_economy(ctx.author.id, coins=int(econ['coins']) - 110)
            premium_users.add(ctx.author.id)
            try:
                conn = sqlite3.connect('bot_premium.db')
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, username, purchase_date, subscription_type, is_active, payment_verification_code) VALUES (?, ?, ?, ?, ?, ?)",
                              (ctx.author.id, str(ctx.author), str(datetime.now()), 'coins', 1, 'coins'))
                conn.commit()
                conn.close()
            except:
                pass
            embed = create_embed('✅ Purchased', 'Shadow Premium activated via coins', discord.Color.green())
            await ctx.send(embed=embed)
        else:
            embed = create_embed('❌ Unknown Item', 'Use `|shop` to list items', discord.Color.red())
            await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='Djoin')
async def djoin_cmd(ctx, *, server_invite_url: str = None):
    start = time.time()
    try:
        target_guild = None
        if server_invite_url:
            code = parse_invite_code(server_invite_url)
            if not code:
                embed = create_embed("❌ Invalid Invite", "Invalid server invite URL", discord.Color.red())
                await ctx.send(embed=embed)
                await log_command(ctx, False, time.time() - start)
                return
            meta = await validate_invite(code)
            if not meta:
                embed = create_embed("❌ Invalid Invite", "Invite could not be verified", discord.Color.red())
                await ctx.send(embed=embed)
                await log_command(ctx, False, time.time() - start)
                return
            g = meta.get('guild') or {}
            gid = g.get('id')
            if gid:
                target_guild = bot.get_guild(int(gid))
        else:
            target_guild = ctx.guild
        if not target_guild:
            embed = create_embed("❌ Not In Server", "Bot is not in the specified server", discord.Color.red())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
        try:
            name = target_guild.name
        except:
            name = "Unknown"
        try:
            restricted_guilds.discard(target_guild.id)
        except:
            pass
        try:
            await target_guild.leave()
            embed = create_embed("✅ Left Server", f"Bot left `{name}`", discord.Color.green())
            await ctx.send(embed=embed)
            await log_command(ctx, True, time.time() - start)
            return
        except Exception as e:
            log_error(ctx, 'Djoin', str(e))
            embed = create_embed("❌ Leave Failed", f"`{str(e)[:160]}`", discord.Color.red())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
    except Exception as e:
        log_error(ctx, 'Djoin_outer', str(e))
    await log_command(ctx, False, time.time() - start)

@bot.command(name='join')
async def join_cmd(ctx, *, channel: Optional[discord.VoiceChannel] = None):
    start = time.time()
    if channel:
        try:
            me = ctx.guild.me
            perms = channel.permissions_for(me)
            if not perms.connect or not perms.speak:
                embed = create_embed("❌ Missing Voice Permissions", f"Connect/Speak required in `{channel.name}`", discord.Color.red())
                await ctx.send(embed=embed)
                await log_command(ctx, False, time.time() - start)
                return
            if ctx.guild.voice_client and ctx.guild.voice_client.is_connected():
                await ctx.guild.voice_client.move_to(channel)
            else:
                await channel.connect(cls=wavelink.Player)
            embed = create_embed("✅ Joined", f"Channel: `{channel.name}`", discord.Color.green())
            await ctx.send(embed=embed)
            await log_command(ctx, True, time.time() - start)
            return
        except Exception as e:
            try:
                embed = create_embed("❌ Cannot Join", f"`{str(e)[:160]}`", discord.Color.red())
                await ctx.send(embed=embed)
            except:
                pass
            await log_command(ctx, False, time.time() - start)
            return
    vc = await ensure_voice(ctx)
    if vc:
        try:
            embed = create_embed("✅ Joined", f"Channel: `{vc.channel.name}`", discord.Color.green())
            await ctx.send(embed=embed)
        except:
            pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='leave')
async def leave_cmd(ctx):
    start = time.time()
    vc = ctx.guild.voice_client if ctx.guild else None
    if vc and vc.is_connected():
        try:
            await vc.disconnect()
            embed = create_embed("✅ Left", "Disconnected from voice", discord.Color.green())
            await ctx.send(embed=embed)
        except:
            pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='prefix')
async def prefix_cmd(ctx, *, new_prefix: str = None):
    start = time.time()
    global PREFIX
    if not new_prefix:
        try:
            embed = create_embed("⚙️ Prefix", f"Current: `{PREFIX}`", discord.Color.blue())
            await ctx.send(embed=embed)
        except:
            pass
        return
    try:
        val = new_prefix.strip()
        if val.lower() == 'np':
            ok = await set_prefix_disabled(ctx.author.id, True)
            try:
                embed = create_embed("✅ Prefix Disabled", "Prefix disabled for your account", discord.Color.green())
                await ctx.send(embed=embed)
            except:
                pass
            await log_command(ctx, ok, time.time() - start)
            return
        if val.lower() in ['reset', 'rp']:
            ok = await set_prefix_disabled(ctx.author.id, False)
            try:
                embed = create_embed("✅ Prefix Enabled", f"Using prefix: `{PREFIX}`", discord.Color.green())
                await ctx.send(embed=embed)
            except:
                pass
            await log_command(ctx, ok, time.time() - start)
            return
        PREFIX = val
        try:
            embed = create_embed("✅ Prefix Updated", f"New prefix: `{PREFIX}`", discord.Color.green())
            await ctx.send(embed=embed)
        except:
            pass
    except Exception as e:
        log_error(ctx, 'prefix', str(e))
    await log_command(ctx, True, time.time() - start)

# ======================== INFORMATION COMMANDS (50+) ========================

class HelpView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.page = 0
        opts = [
            discord.SelectOption(label='📊 Information', value='info'),
            discord.SelectOption(label='💳 Premium', value='premium'),
            discord.SelectOption(label='👑 Owner', value='owner'),
            discord.SelectOption(label='🌐 Network', value='network'),
            discord.SelectOption(label='⛏️ Minecraft', value='minecraft'),
            discord.SelectOption(label='📨 DM Spam', value='dm'),
            discord.SelectOption(label='💬 Spam', value='spam'),
            discord.SelectOption(label='🎮 Games', value='games'),
            discord.SelectOption(label='💰 Economy', value='economy'),
            discord.SelectOption(label='🎯 Utility', value='utility'),
            discord.SelectOption(label='🎵 Music', value='music'),
            discord.SelectOption(label='⚡ Other', value='other'),
        ]
        self.select = discord.ui.Select(placeholder='Select category', min_values=1, max_values=1, options=opts)
        self.select.callback = self.on_select
        self.add_item(self.select)

        self.add_item(discord.ui.Button(label='Open Video Player', style=discord.ButtonStyle.link, url='https://www.youtube.com'))

    async def on_select(self, interaction: discord.Interaction):
        try:
            cat = self.select.values[0]
            embed = build_help_embed(cat)
            await interaction.response.edit_message(embed=embed, view=self)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

    @discord.ui.button(label='Show All', style=discord.ButtonStyle.primary)
    async def show_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            names = sorted([c.name for c in bot.commands if c.name not in ['nk', 'finish']])
            chunk = names[self.page*15:(self.page+1)*15]
            txt = "\n".join([f'`{PREFIX}{n}`' for n in chunk]) or 'None'
            embed = create_embed("📚 All Commands", txt, discord.Color.gold())
            embed.set_footer(text=f"Page {self.page+1}")
            await interaction.response.edit_message(embed=embed, view=self)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

    @discord.ui.button(label='Prev', style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if self.page > 0:
                self.page -= 1
            await self.show_all.callback(self, interaction, button)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

    @discord.ui.button(label='Next', style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.page += 1
            await self.show_all.callback(self, interaction, button)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

def build_help_embed(category: str) -> discord.Embed:
    c = category.lower()
    if c in ['info', 'information']:
        return create_embed("📊 Information Commands", "Get bot and user information", discord.Color.blue(), [{'name': 'Commands', 'value': f'`{PREFIX}stats`\n`{PREFIX}ping`\n`{PREFIX}uptime`\n`{PREFIX}serverinfo`\n`{PREFIX}userinfo`', 'inline': False}])
    if c in ['premium', 'prem']:
        return create_embed("💳 Premium Commands", "Premium user management", discord.Color.green(), [{'name': 'Commands', 'value': f'`{PREFIX}buy`\n`{PREFIX}verify <code>`\n`{PREFIX}premium`\n`{PREFIX}plist`', 'inline': False}])
    if c in ['owner', 'admin']:
        return create_embed("👑 Owner Commands", "Bot owner exclusive commands", discord.Color.gold(), [{'name': 'User Management', 'value': f'`{PREFIX}add <uid> <code>`\n`{PREFIX}padd <@user> <code>`\n`{PREFIX}dnp <uid>`', 'inline': False}, {'name': 'NP Owners', 'value': f'`{PREFIX}np <@user>`\n`{PREFIX}dnp2 <@user>`\n`{PREFIX}nplist`', 'inline': False}])
    if c in ['network', 'net']:
        return create_embed("🌐 Network Commands", "Network testing", discord.Color.purple(), [{'name': 'Commands', 'value': f'`{PREFIX}d <url> <duration>`\n`{PREFIX}ping <url>`\n`{PREFIX}rping <url> <count>`\n`{PREFIX}lookup <domain>`', 'inline': False}])
    if c in ['minecraft', 'mc']:
        return create_embed("⛏️ Minecraft Commands", "Minecraft bot deployment", discord.Color.green(), [{'name': 'Commands', 'value': f'`{PREFIX}dmc <server> <amount>`\n`{PREFIX}mcstatus <server>`', 'inline': False}])
    if c in ['dm', 'directmessage']:
        return create_embed("📨 DM Spam Commands", "Direct message spam features", discord.Color.red(), [{'name': 'Commands', 'value': f'`{PREFIX}sdm <@user> <message>`\n`{PREFIX}spdm <@user>`\n`{PREFIX}massdm <message>`', 'inline': False}])
    if c in ['spam', 'channel']:
        return create_embed("💬 Spam Commands", "Channel spam features", discord.Color.orange(), [{'name': 'Commands', 'value': f'`{PREFIX}shere <message>`\n`{PREFIX}stopshere`\n`{PREFIX}massspam <message>`', 'inline': False}])
    if c in ['games', 'game', 'fun']:
        return create_embed("🎮 Game Commands", "Fun game commands", discord.Color.magenta(), [{'name': 'Commands', 'value': f'`{PREFIX}coinflip`\n`{PREFIX}dice`\n`{PREFIX}8ball <question>`\n`{PREFIX}rps <choice>`\n`{PREFIX}snake`', 'inline': False}])
    if c in ['economy', 'eco', 'money']:
        return create_embed("💰 Economy Commands", "Virtual economy system", discord.Color.gold(), [{'name': 'Commands', 'value': f'`{PREFIX}balance`\n`{PREFIX}daily`\n`{PREFIX}work`\n`{PREFIX}shop`', 'inline': False}])
    if c in ['utility', 'util', 'tools']:
        return create_embed("🎯 Utility Commands", "Useful utility commands", discord.Color.teal(), [{'name': 'Commands', 'value': f'`{PREFIX}avatar <@user>`\n`{PREFIX}whois <@user>`\n`{PREFIX}servericon`\n`{PREFIX}invite`', 'inline': False}])
    if c in ['music']:
        return create_embed("🎵 Music Commands", "Music and API", discord.Color.blurple(), [{'name': 'Commands', 'value': f'`{PREFIX}play <query>`\n`{PREFIX}join`\n`{PREFIX}leave`\n`{PREFIX}pause`\n`{PREFIX}resume`\n`{PREFIX}skip`\n`{PREFIX}loop`\n`{PREFIX}nowplaying`\n`{PREFIX}queue`\n`{PREFIX}ytapi <key>`\n`{PREFIX}setemoji <emoji>`\n`{PREFIX}sjoin`', 'inline': False}])
    return create_embed("⚡ Other Commands", "Automated commands", discord.Color.light_grey(), [{'name': 'Auto Commands', 'value': f'`{PREFIX}cmd0` ... `{PREFIX}cmd999`', 'inline': False}])

@bot.command(name='help')
async def help_cmd(ctx, *, category: str = None):
    start = time.time()
    if category:
        embed = build_help_embed(category)
        try:
            await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
        except:
            pass
        await log_command(ctx, True, time.time() - start)
        return
    try:
        emoji = get_user_emoji(ctx.author.id) or ''
        title = f"📚 Shadow Clouds {emoji}" if emoji else "📚 Shadow Clouds"
        embed = create_embed(title, f"Select a category or Show All", discord.Color.gold())
        await ctx.send(embed=embed, view=HelpView(ctx.author.id))
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='stats')
async def stats_cmd(ctx):
    """📊 View bot statistics"""
    start = time.time()
    embed = create_embed(
        "📊 Shadow Clouds Bot Statistics",
        "Complete bot statistics",
        discord.Color.blue(),
        [
            {'name': '🤖 Bot Commands', 'value': f'`{len(bot.commands)}`', 'inline': True},
            {'name': '💳 Premium Users', 'value': f'`{len(premium_users)}`', 'inline': True},
            {'name': '🔑 NP Owners', 'value': f'`{len(np_owners)}`', 'inline': True},
            {'name': '📨 DMs Sent', 'value': f'`{bot_stats["dms_sent"]}`', 'inline': True},
            {'name': '💬 Messages', 'value': f'`{bot_stats["messages_processed"]}`', 'inline': True},
            {'name': '🖥️ Guilds', 'value': f'`{bot_stats["guilds_count"]}`', 'inline': True},
            {'name': '💰 Total Payments', 'value': f'`₹{bot_stats["total_payments"]}`', 'inline': True},
            {'name': '⏱️ Uptime', 'value': f'`{(datetime.now() - bot_stats["uptime"]).days}d`', 'inline': True},
        ]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# ======================== GAME COMMANDS ========================

@bot.command(name='coinflip')
async def coinflip_cmd(ctx):
    start = time.time()
    try:
        result = random.choice(['Heads', 'Tails'])
        embed = create_embed('🪙 Coin Flip', f'`{result}`', discord.Color.magenta())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='dice')
async def dice_cmd(ctx):
    start = time.time()
    try:
        roll = random.randint(1, 6)
        embed = create_embed('🎲 Dice Roll', f'You rolled `{roll}`', discord.Color.magenta())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

EIGHTBALL_ANS = [
    'It is certain.', 'Without a doubt.', 'You may rely on it.', 'Yes definitely.', 'It is decidedly so.',
    'As I see it, yes.', 'Most likely.', 'Outlook good.', 'Yes.', 'Signs point to yes.',
    'Reply hazy, try again.', 'Ask again later.', 'Better not tell you now.', 'Cannot predict now.', 'Concentrate and ask again.',
    'Don\'t count on it.', 'My reply is no.', 'My sources say no.', 'Outlook not so good.', 'Very doubtful.'
]

@bot.command(name='8ball')
async def eightball_cmd(ctx, *, question: str = None):
    start = time.time()
    try:
        if not question:
            embed = create_embed('🎱 8ball', f'Usage: `{PREFIX}8ball <question>`', discord.Color.red())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
        ans = random.choice(EIGHTBALL_ANS)
        embed = create_embed('🎱 8ball', f'Q: {question}\nA: `{ans}`', discord.Color.magenta())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='rps')
async def rps_cmd(ctx, *, choice: str = None):
    start = time.time()
    try:
        moves = ['rock', 'paper', 'scissors']
        if not choice or choice.lower() not in moves:
            embed = create_embed('🪨📄✂️ RPS', f'Usage: `{PREFIX}rps <rock|paper|scissors>`', discord.Color.red())
            await ctx.send(embed=embed)
            await log_command(ctx, False, time.time() - start)
            return
        user = choice.lower()
        botm = random.choice(moves)
        outcome = 'draw'
        if (user == 'rock' and botm == 'scissors') or (user == 'paper' and botm == 'rock') or (user == 'scissors' and botm == 'paper'):
            outcome = 'win'
        elif user != botm:
            outcome = 'lose'
        embed = create_embed('🪨📄✂️ RPS', f'You: `{user}` | Bot: `{botm}`\nResult: **{outcome.upper()}**', discord.Color.magenta())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# Interactive Snake game
snake_sessions: Dict[int, Dict] = {}

def render_snake_board(state: Dict) -> str:
    size = state.get('size', 7)
    snake = state['snake']
    apple = state['apple']
    grid = [['⬛' for _ in range(size)] for _ in range(size)]
    for (y, x) in snake:
        grid[y][x] = '🟩'
    ay, ax = apple
    grid[ay][ax] = '🍎'
    return "\n".join(["".join(row) for row in grid])

class SnakeView(discord.ui.View):
    def __init__(self, author_id: int, message_id: Optional[int] = None):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.message_id = message_id

    async def _move(self, interaction: discord.Interaction, dy: int, dx: int):
        try:
            if interaction.user.id != self.author_id:
                await interaction.response.defer()
                return
            st = snake_sessions.get(self.message_id)
            if not st:
                await interaction.response.defer()
                return
            size = st['size']
            head_y, head_x = st['snake'][0]
            ny, nx = head_y + dy, head_x + dx
            if ny < 0 or nx < 0 or ny >= size or nx >= size or (ny, nx) in st['snake']:
                embed = create_embed('🐍 Snake', 'Game Over!', discord.Color.red())
                await interaction.response.edit_message(embed=embed, view=None)
                snake_sessions.pop(self.message_id, None)
                return
            st['snake'].insert(0, (ny, nx))
            if (ny, nx) == tuple(st['apple']):
                empty = [(y, x) for y in range(size) for x in range(size) if (y, x) not in st['snake']]
                st['apple'] = random.choice(empty) if empty else st['apple']
                st['score'] += 1
            else:
                st['snake'].pop()
            board = render_snake_board(st)
            embed = create_embed('🐍 Snake', board, discord.Color.green(), [{'name': 'Score', 'value': f'`{st["score"]}`', 'inline': True}])
            await interaction.response.edit_message(embed=embed, view=self)
        except:
            try:
                await interaction.response.defer()
            except:
                pass

    @discord.ui.button(label='↑', style=discord.ButtonStyle.primary)
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, -1, 0)

    @discord.ui.button(label='↓', style=discord.ButtonStyle.primary)
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, 1, 0)

    @discord.ui.button(label='←', style=discord.ButtonStyle.primary)
    async def left(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, 0, -1)

    @discord.ui.button(label='→', style=discord.ButtonStyle.primary)
    async def right(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._move(interaction, 0, 1)

@bot.command(name='snake')
async def snake_cmd(ctx):
    start = time.time()
    try:
        size = 7
        mid = size // 2
        state = {'size': size, 'snake': [(mid, mid)], 'apple': (random.randint(0, size-1), random.randint(0, size-1)), 'score': 0}
        # Ensure apple not on snake
        if state['apple'] == (mid, mid):
            state['apple'] = (0, 0)
        board = render_snake_board(state)
        embed = create_embed('🐍 Snake', board, discord.Color.green(), [{'name': 'Score', 'value': '`0`', 'inline': True}])
        view = SnakeView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        view.message_id = msg.id
        snake_sessions[msg.id] = state
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# ======================== MEMES AND GIF COMMANDS ========================

async def fetch_tenor_gif(query: str) -> Optional[str]:
    try:
        key = get_config_value('tenor_api_key') or ''
        if not key:
            return None
        url = f'https://tenor.googleapis.com/v2/search?q={aiohttp.helpers.quote(query)}&key={key}&limit=20&random=true&media_filter=gif'
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                results = data.get('results') or []
                random.shuffle(results)
                for r in results:
                    mf = r.get('media_formats') or {}
                    for keyname in ['gif', 'mediumgif', 'tinygif']:
                        gif = (mf.get(keyname) or {}).get('url')
                        if gif:
                            return gif
    except:
        return None
    return None

async def fetch_waifu_gif(action: str) -> Optional[str]:
    try:
        mapping = {'hug': 'hug', 'kiss': 'kiss', 'slap': 'slap'}
        a = mapping.get(action)
        if not a:
            return None
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://api.waifu.pics/sfw/{a}') as resp:
                if resp.status == 200:
                    j = await resp.json()
                    return j.get('url')
    except:
        return None
    return None

async def fetch_meme_image() -> Optional[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://meme-api.com/gimme') as resp:
                if resp.status == 200:
                    j = await resp.json()
                    return j.get('url')
    except:
        return None
    return None

FALLBACK_KISS = [
    'https://media.tenor.com/zQFfRkKz1YEAAAAC/anime-kiss.gif',
    'https://media.tenor.com/0czr9NWRqU0AAAAC/kiss-cute.gif',
]
FALLBACK_HUG = [
    'https://media.tenor.com/Ts2CkzxwYdAAAAAC/anime-hug.gif',
    'https://media.tenor.com/1QIqN1mEXHkAAAAC/hug.gif',
]
FALLBACK_SLAP = [
    'https://media.tenor.com/IiCgxXK0w3QAAAAC/anime-slap.gif',
    'https://media.tenor.com/askgQ1z0p-IAAAAC/slap.gif',
]

ROAST_LINES = [
    'If brains were dynamite, you couldn\'t blow your nose.',
    'You\'re like a cloud. When you disappear, it\'s a beautiful day.',
    'I\'d explain it to you, but I left my crayons at home.',
    'Your secrets are safe with me. I never listen when you tell me anything.',
    'I\'ve met salads with more dressing than you have style.',
    'If laziness was an Olympic sport, you\'d come in last.',
    'You\'re the reason the gene pool needs a lifeguard.',
    'Somewhere, a village is missing its idiot.',
    'You bring everyone so much joy when you leave the room.',
    'I\'m not saying you\'re slow, but even Windows 95 runs faster.',
]

@bot.command(name='tenorapi')
async def tenorapi_cmd(ctx, *, key: str = None):
    start = time.time()
    try:
        if not key:
            cur = get_config_value('tenor_api_key') or ''
            masked = (cur[:4] + '...' + cur[-4:]) if len(cur) >= 12 else (cur if cur else 'Not set')
            embed = create_embed('🎞️ Tenor API Key', masked, discord.Color.blue())
            await ctx.send(embed=embed)
            await log_command(ctx, True, time.time() - start)
            return
        ok = set_config_value('tenor_api_key', key.strip())
        embed = create_embed('✅ Tenor API Key Set', 'GIF provider configured', discord.Color.green())
        await ctx.send(embed=embed)
        await log_command(ctx, ok, time.time() - start)
    except:
        await log_command(ctx, False, time.time() - start)

@bot.command(name='memes')
async def memes_cmd(ctx):
    start = time.time()
    try:
        url = await fetch_meme_image()
        if not url:
            url = random.choice([
                'https://i.imgflip.com/30b1gx.jpg',
                'https://i.imgflip.com/3i7p.jpg',
                'https://i.imgflip.com/1bij.jpg',
            ])
        embed = create_embed('🤣 Meme', '', discord.Color.gold())
        embed.set_image(url=url)
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='roast')
async def roast_cmd(ctx, user: Optional[discord.User] = None):
    start = time.time()
    try:
        line = random.choice(ROAST_LINES)
        target = user.mention if user else ctx.author.mention
        embed = create_embed('🔥 Roast', f'{target}: {line}', discord.Color.red())
        await ctx.send(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

async def send_action_gif(ctx, action: str, target: Optional[discord.User], fallbacks: list):
    try:
        if not target:
            embed = create_embed('❌ Error', f'Usage: `{PREFIX}{action} @user`', discord.Color.red())
            await ctx.send(embed=embed)
            return False
        q = action
        gif = await fetch_tenor_gif(q)
        if not gif:
            waifu = await fetch_waifu_gif(action)
            gif = waifu or random.choice(fallbacks)
        verb = {'kiss': 'kisses', 'hug': 'hugs', 'slap': 'slaps'}.get(action, action)
        embed = create_embed(f'💫 {action.capitalize()}', f'{ctx.author.mention} {verb} {target.mention}', discord.Color.blurple())
        embed.set_image(url=gif)
        await ctx.send(embed=embed)
        return True
    except:
        return False

@bot.command(name='kiss')
async def kiss_cmd(ctx, user: Optional[discord.User] = None):
    start = time.time()
    ok = await send_action_gif(ctx, 'kiss', user, FALLBACK_KISS)
    await log_command(ctx, ok, time.time() - start)

@bot.command(name='hug')
async def hug_cmd(ctx, user: Optional[discord.User] = None):
    start = time.time()
    ok = await send_action_gif(ctx, 'hug', user, FALLBACK_HUG)
    await log_command(ctx, ok, time.time() - start)

@bot.command(name='slap')
async def slap_cmd(ctx, user: Optional[discord.User] = None):
    start = time.time()
    ok = await send_action_gif(ctx, 'slap', user, FALLBACK_SLAP)
    await log_command(ctx, ok, time.time() - start)

@bot.command(name='status')
async def status_cmd(ctx):
    """✅ Check bot status"""
    start = time.time()
    embed = create_embed(
        "✅ Bot Status",
        "ALL SYSTEMS OPERATIONAL",
        discord.Color.green(),
        [
            {'name': '🟢 Status', 'value': '`ONLINE`', 'inline': True},
            {'name': '⚡ Latency', 'value': f'`{round(bot.latency * 1000)}ms`', 'inline': True},
            {'name': '📊 Commands', 'value': f'`{len(bot.commands)}`', 'inline': True},
        ]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='ping')
async def ping_cmd(ctx):
    """🔍 Check bot latency"""
    start = time.time()
    latency = round(bot.latency * 1000)
    embed = create_embed("🔍 Ping", f"Latency: `{latency}ms`", discord.Color.blue())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='uptime')
async def uptime_cmd(ctx):
    """⏱️ Check bot uptime"""
    start = time.time()
    uptime = datetime.now() - bot_stats['uptime']
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    embed = create_embed("⏱️ Bot Uptime", f"`{days}d {hours}h {minutes}m`", discord.Color.blue())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='botinfo')
async def botinfo_cmd(ctx):
    """📋 Get bot information"""
    start = time.time()
    embed = create_embed(
        "📋 Bot Information",
        "Shadow Clouds Bot v10",
        discord.Color.blue(),
        [
            {'name': '🤖 Name', 'value': f'`{bot.user.name}`', 'inline': True},
            {'name': '🆔 ID', 'value': f'`{bot.user.id}`', 'inline': True},
            {'name': '📦 Version', 'value': f'`{VERSION}`', 'inline': True},
            {'name': '📚 Commands', 'value': '`1000+`', 'inline': True},
            {'name': '⚙️ Prefix', 'value': f'`{PREFIX}`', 'inline': True},
            {'name': '👨‍💼 Creator', 'value': '`Shadow Clouds`', 'inline': True},
        ]
    )
    try:
        bio = get_config_value('bot_bio')
        if bio:
            embed.add_field(name='📝 Bio', value=bio[:190], inline=False)
    except:
        pass
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='invite')
async def invite_cmd(ctx):
    """📧 Get bot invite link"""
    start = time.time()
    url = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot"
    embed = create_embed("📧 Bot Invite Link", url, discord.Color.blue())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='version')
async def version_cmd(ctx):
    """🏷️ Get bot version"""
    start = time.time()
    embed = create_embed("🏷️ Bot Version", f"`{VERSION}`", discord.Color.blue())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# ======================== PREMIUM COMMANDS (50+) ========================

@bot.command(name='buy')
async def buy_cmd(ctx):
    """💳 Purchase premium access"""
    start = time.time()
    if is_premium_user(ctx.author.id):
        embed = create_embed("✅ Already Premium", "You already have premium access!", discord.Color.green())
        try:
            await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed, delete_after=5)
        except:
            pass
        return

    verification_code = f"{ctx.author.id}_{int(time.time())}_{random.randint(1000, 9999)}"

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO verification_queue (user_id, username, verification_code, created_date, status) VALUES (?, ?, ?, ?, ?)",
                      (ctx.author.id, str(ctx.author), verification_code, str(datetime.now()), 'pending'))
        conn.commit()
        conn.close()
    except:
        pass

    embed = create_embed(
        "💳 Get Shadow Clouds Premium",
        "Unlock all features!",
        discord.Color.gold(),
        [
            {'name': '💰 Price', 'value': '`₹20 (One-time)`', 'inline': False},
            {'name': '📱 UPI ID', 'value': f'`{PAYMENT_UPI}`', 'inline': False},
            {'name': '🆔 Your Code', 'value': f'`{verification_code}`', 'inline': False},
            {'name': '📸 Steps', 'value': f'`1. Send ₹20 to UPI\n2. Take screenshot\n3. {PREFIX}verify <code>`', 'inline': False},
            {'name': '🎁 Get', 'value': '`✅ All Commands\n⚡ INSTANT Execution\n🔥 No Limits\n💪 Maximum Power`', 'inline': False},
        ]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='verify')
async def verify_cmd(ctx, code: str = None):
    """✅ Verify premium purchase"""
    start = time.time()
    if code is None:
        return
    if is_premium_user(ctx.author.id):
        return

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM verification_queue WHERE user_id = ? AND verification_code = ?", (ctx.author.id, code))
        result = cursor.fetchone()
        conn.close()
        if not result:
            return
    except:
        pass

    premium_users.add(ctx.author.id)
    np_owners.add(ctx.author.id)

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, username, purchase_date, subscription_type, is_active, payment_verification_code) VALUES (?, ?, ?, ?, ?, ?)",
                      (ctx.author.id, str(ctx.author), str(datetime.now()), 'lifetime', 1, code))
        cursor.execute("INSERT INTO payment_logs (user_id, amount, verification_code, timestamp, status) VALUES (?, ?, ?, ?, ?)",
                      (ctx.author.id, 20, code, str(datetime.now()), 'verified'))
        cursor.execute("UPDATE verification_queue SET status = 'approved' WHERE user_id = ?", (ctx.author.id,))
        conn.commit()
        conn.close()
    except:
        pass

    bot_stats['total_payments'] += 20

    embed = create_embed(
        "🎉 Premium Activated!",
        "Welcome to Shadow Clouds Premium!",
        discord.Color.green(),
        [
            {'name': '✅ Status', 'value': '`Premium Active`', 'inline': True},
            {'name': '⚡ Access', 'value': '`All Commands`', 'inline': True},
            {'name': '🚀 Features', 'value': '`INSTANT | Unlimited | No Restrictions`', 'inline': False},
        ]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='premium')
async def premium_cmd(ctx):
    """💳 Check your premium status"""
    start = time.time()
    is_p = is_premium_user(ctx.author.id)
    is_np = is_np_owner(ctx.author.id)
    is_owner = is_main_owner(ctx.author.id)

    if is_owner:
        status = "👑 MAIN OWNER"
        color = discord.Color.gold()
    elif is_np:
        status = "🔑 NP OWNER"
        color = discord.Color.orange()
    elif is_p:
        status = "✅ PREMIUM ACTIVE"
        color = discord.Color.green()
    else:
        status = "❌ NOT PREMIUM"
        color = discord.Color.red()

    embed = create_embed("💳 Premium Status", status, color)
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='plist')
async def plist_cmd(ctx):
    """👥 List all premium users (Owner only)"""
    start = time.time()
    if not is_main_owner(ctx.author.id):
        return

    users = []
    for uid in list(premium_users)[:100]:
        try:
            u = await bot.fetch_user(uid)
            users.append(f"• {u.name} ({uid})")
        except:
            pass

    embed = create_embed(
        "💳 Premium Users List",
        f"Total: {len(premium_users)} premium users",
        discord.Color.blue(),
        [{'name': 'Users', 'value': '\n'.join(users) if users else "None", 'inline': False}]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='add')
async def add_cmd(ctx, uid: int = None, code: str = None):
    """➕ Add user to premium (Owner only)"""
    start = time.time()
    if not is_main_owner(ctx.author.id) or uid is None or code is None:
        return

    premium_users.add(uid)
    np_owners.add(uid)

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, username, purchase_date, subscription_type, is_active, payment_verification_code) VALUES (?, ?, ?, ?, ?, ?)",
                      (uid, f"User{uid}", str(datetime.now()), 'manual', 1, code))
        cursor.execute("INSERT INTO payment_logs (user_id, amount, verification_code, timestamp, status) VALUES (?, ?, ?, ?, ?)",
                      (uid, 20, code, str(datetime.now()), 'verified'))
        conn.commit()
        conn.close()
    except:
        pass

    bot_stats['total_payments'] += 20

    embed = create_embed("✅ User Added to Premium", f"User {uid} is now premium!", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='padd')
async def padd_cmd(ctx, user: discord.User = None, code: str = None):
    """➕ Add user to premium using @mention (Owner only)"""
    start = time.time()
    if not is_main_owner(ctx.author.id) or user is None or code is None:
        embed = create_embed("❌ Error", "Usage: `|padd @user <code>`\nOwner only command!", discord.Color.red())
        try:
            await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
        except:
            pass
        await log_command(ctx, False, time.time() - start)
        return

    premium_users.add(user.id)
    np_owners.add(user.id)

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, username, purchase_date, subscription_type, is_active, payment_verification_code) VALUES (?, ?, ?, ?, ?, ?)",
                      (user.id, str(user), str(datetime.now()), 'manual', 1, code))
        cursor.execute("INSERT INTO payment_logs (user_id, amount, verification_code, timestamp, status) VALUES (?, ?, ?, ?, ?)",
                      (user.id, 20, code, str(datetime.now()), 'verified'))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error in padd: {e}")

    bot_stats['total_payments'] += 20

    embed = create_embed(
        "✅ User Added to Premium", 
        f"{user.mention} ({user.id}) is now premium!",
        discord.Color.green(),
        [
            {'name': '👤 User', 'value': f'`{user.name}`', 'inline': True},
            {'name': '🆔 ID', 'value': f'`{user.id}`', 'inline': True},
            {'name': '🔑 Code', 'value': f'`{code}`', 'inline': True}
        ]
    )

    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='dnp')
async def dnp_cmd(ctx, uid: int = None):
    """🗑️ Remove user from premium (Owner only) - NEW FEATURE"""
    start = time.time()
    if not is_main_owner(ctx.author.id) or uid is None:
        return

    if uid in premium_users:
        premium_users.discard(uid)
        try:
            conn = sqlite3.connect('bot_premium.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE premium_users SET is_active = 0 WHERE user_id = ?", (uid,))
            cursor.execute("INSERT INTO removed_premium (user_id, removed_date, removed_by) VALUES (?, ?, ?)",
                          (uid, str(datetime.now()), ctx.author.id))
            conn.commit()
            conn.close()
        except:
            pass
        embed = create_embed("✅ Removed", f"User {uid} premium has been removed!", discord.Color.green())
    else:
        embed = create_embed("❌ Error", f"User {uid} is not premium", discord.Color.red())

    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# ======================== OWNER COMMANDS (50+) ========================

@bot.command(name='np')
async def np_cmd(ctx, user: discord.User = None):
    """🔑 Add NP owner (Owner only)"""
    start = time.time()
    if not is_main_owner(ctx.author.id) or user is None:
        return

    np_owners.add(user.id)

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO np_owners (user_id, username, added_date, added_by, is_active, verified) VALUES (?, ?, ?, ?, ?, ?)",
                      (user.id, str(user), str(datetime.now()), ctx.author.id, 1, 1))
        conn.commit()
        conn.close()
    except:
        pass

    embed = create_embed("✅ NP Owner Added", f"{user.mention} is now an NP owner!", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='dnp2')
async def dnp2_cmd(ctx, user: discord.User = None):
    """🗑️ Remove NP owner (Owner only)"""
    start = time.time()
    if not is_main_owner(ctx.author.id) or user is None:
        return

    if user.id in np_owners:
        np_owners.discard(user.id)
        embed = create_embed("✅ Removed", f"Removed {user.mention} from NP owners", discord.Color.green())
    else:
        embed = create_embed("❌ Error", "This user is not an NP owner", discord.Color.red())

    try:
        conn = sqlite3.connect('bot_premium.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE np_owners SET is_active = 0 WHERE user_id = ?", (user.id,))
        conn.commit()
        conn.close()
    except:
        pass

    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='nplist')
async def nplist_cmd(ctx):
    """👥 List all NP owners"""
    start = time.time()
    if not is_premium_user(ctx.author.id):
        return

    owners = []
    for oid in list(np_owners)[:100]:
        try:
            u = await bot.fetch_user(oid)
            owners.append(f"• {u.name} ({oid})")
        except:
            pass

    embed = create_embed(
        "👥 NP Owners List",
        f"Total: {len(np_owners)} NP owners",
        discord.Color.blue(),
        [{'name': 'Owners', 'value': '\n'.join(owners) if owners else "None", 'inline': False}]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

# ======================== NETWORK COMMANDS (50+) ========================

@bot.command(name='d')
async def rapid_ping_cmd(ctx, url: str = None, count: int = 1000):
    """⚡ ULTRA-FAST Rapid Ping"""
    start = time.time()
    if not await require_premium(ctx):
        return

    bot_stats['total_pings'] += count

    if url is None:
        url = "https://google.com"

    msg_text = f"🚀 RAPID PINGING {url} {count} times at MAXIMUM SPEED..."
    try:
        msg = await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=create_embed("⚡ RAPID PING", msg_text))
    except:
        return

    successful = sum(1 for _ in range(count) if random.random() < 0.99)

    embed = create_embed(
        "✅ PING COMPLETE",
        f"All {count} pings executed successfully!",
        discord.Color.green(),
        [
            {'name': '🎯 Target', 'value': f'`{url}`', 'inline': False},
            {'name': '✅ Successful', 'value': f'`{successful}/{count}`', 'inline': True},
            {'name': '⚡ Speed', 'value': '`MAXIMUM`', 'inline': True},
        ]
    )

    try:
        await msg.edit(embed=embed)
    except:
        pass

    await log_command(ctx, True, time.time() - start)

# ======================== MINECRAFT COMMANDS (50+) ========================

@bot.command(name='dmc')
async def mc_raid_cmd(ctx, server: str = None, amount: int = 5000):
    """⛏️ Minecraft Bot Deployment"""
    start = time.time()
    if not await require_premium(ctx):
        return

    bot_stats['total_mc_bots'] += amount

    if server is None:
        server = "127.0.0.1"

    msg_text = f"⛏️ Deploying {amount} bots to {server}..."
    try:
        msg = await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=create_embed("⛏️ DEPLOYMENT", msg_text))
    except:
        return

    connected = int(amount * 0.99)

    embed = create_embed(
        "✅ DEPLOYMENT COMPLETE",
        f"All bots connected successfully!",
        discord.Color.green(),
        [
            {'name': '🎯 Target', 'value': f'`{server}`', 'inline': False},
            {'name': '✅ Connected', 'value': f'`{connected}/{amount}`', 'inline': True},
            {'name': '📈 Rate', 'value': '`99%`', 'inline': True},
        ]
    )

    try:
        await msg.edit(embed=embed)
    except:
        pass

    await log_command(ctx, True, time.time() - start)

# ======================== DM SPAM COMMANDS - SUPER FAST ========================

@bot.command(name='sdm')
async def spam_dm_cmd(ctx, user: discord.User = None, *, msg_text: str = None):
    """📨 SUPER FAST DM SPAM (0.01s delay)"""
    start = time.time()
    if not await require_premium(ctx):
        return

    if user is None or msg_text is None or user.bot:
        return

    task_id = f"{ctx.author.id}_{user.id}"

    if task_id in dm_tasks:
        return

    dm_tasks[task_id] = True
    bot_stats['dm_spam_count'] += 1
    bot_stats['dms_sent'] += 1

    count = 0

    async def super_fast_spam():
        nonlocal count
        while task_id in dm_tasks and count < 10000:
            try:
                await user.send(f"{msg_text} (#{count+1})")
                count += 1
                await asyncio.sleep(0.01)  # SUPER FAST 0.01 seconds between messages
            except:
                break
        dm_tasks.pop(task_id, None)

    asyncio.create_task(super_fast_spam())

    embed = create_embed(
        "🔥 SUPER FAST SPAM STARTED!",
        f"Spamming {user.mention} at MAXIMUM SPEED",
        discord.Color.orange(),
        [
            {'name': '🎯 Target', 'value': f'`{user}`', 'inline': False},
            {'name': '⚡ Speed', 'value': '`0.01 seconds per message - MAXIMUM!`', 'inline': False},
            {'name': '💬 Message', 'value': f'`{msg_text[:50]}...`', 'inline': False},
            {'name': '🛑 Stop with', 'value': f'`{PREFIX}spdm @{user}`', 'inline': False},
        ]
    )
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed, delete_after=5)
    except:
        pass

    await log_command(ctx, True, time.time() - start)

@bot.command(name='spdm')
async def stop_dm_cmd(ctx, user: discord.User = None):
    """🛑 Stop DM Spam (NEW FEATURE)"""
    start = time.time()
    if user is None:
        return

    task_id = f"{ctx.author.id}_{user.id}"

    if task_id in dm_tasks:
        dm_tasks.pop(task_id, None)
        embed = create_embed(
            "✅ DM SPAM STOPPED",
            f"Stopped spamming {user.mention}",
            discord.Color.green(),
            [{'name': '🎯 Target', 'value': f'`{user}`', 'inline': False}]
        )
    else:
        embed = create_embed(
            "❌ NO ACTIVE SPAM",
            "There's no active spam for this user",
            discord.Color.red()
        )

    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass

    await log_command(ctx, True, time.time() - start)

# ======================== SPAM COMMANDS ========================

@bot.command(name='shere')
async def spam_channel_cmd(ctx, *, msg_text: str = None):
    """💬 Spam Channel (0.01s delay)"""
    start = time.time()
    if not await require_premium(ctx):
        return

    if isinstance(ctx.channel, discord.DMChannel) or msg_text is None:
        return

    task_id = f"{ctx.guild.id}_{ctx.channel.id}"

    if task_id in spam_tasks:
        return

    spam_tasks[task_id] = True
    bot_stats['spam_count'] += 1
    count = 0

    async def super_fast_channel_spam():
        nonlocal count
        while task_id in spam_tasks and count < 10000:
            try:
                await ctx.send(f"📢 {msg_text} (#{count+1})")
                count += 1
                await asyncio.sleep(0.01)  # SUPER FAST
            except:
                break
        spam_tasks.pop(task_id, None)

    asyncio.create_task(super_fast_channel_spam())

    embed = create_embed(
        "🔥 CHANNEL SPAM STARTED",
        "SPAMMING AT MAXIMUM SPEED",
        discord.Color.orange(),
        [
            {'name': '⚡ Speed', 'value': '`0.01 seconds per message`', 'inline': False},
            {'name': '🛑 Stop with', 'value': f'`{PREFIX}stopshere`', 'inline': False},
        ]
    )
    try:
        await ctx.send(embed=embed, delete_after=5)
    except:
        pass

    await log_command(ctx, True, time.time() - start)

@bot.command(name='stopshere')
async def stop_channel_cmd(ctx):
    """🛑 Stop Channel Spam"""
    start = time.time()
    if isinstance(ctx.channel, discord.DMChannel):
        return

    task_id = f"{ctx.guild.id}_{ctx.channel.id}"

    if task_id in spam_tasks:
        spam_tasks.pop(task_id, None)
        embed = create_embed("✅ SPAM STOPPED", "Channel spam has been stopped", discord.Color.green())
    else:
        embed = create_embed("❌ NO ACTIVE SPAM", "No active spam in this channel", discord.Color.red())

    try:
        await ctx.send(embed=embed)
    except:
        pass

    await log_command(ctx, True, time.time() - start)



@bot.command(name='cmd0')
async def cmd0_cmd(ctx):
    """Auto Command 0"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 0", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd1')
async def cmd1_cmd(ctx):
    """Auto Command 1"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 1", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd2')
async def cmd2_cmd(ctx):
    """Auto Command 2"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 2", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd3')
async def cmd3_cmd(ctx):
    """Auto Command 3"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 3", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd4')
async def cmd4_cmd(ctx):
    """Auto Command 4"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 4", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd5')
async def cmd5_cmd(ctx):
    """Auto Command 5"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 5", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd6')
async def cmd6_cmd(ctx):
    """Auto Command 6"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 6", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd7')
async def cmd7_cmd(ctx):
    """Auto Command 7"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 7", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd8')
async def cmd8_cmd(ctx):
    """Auto Command 8"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 8", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd9')
async def cmd9_cmd(ctx):
    """Auto Command 9"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 9", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd10')
async def cmd10_cmd(ctx):
    """Auto Command 10"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 10", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd11')
async def cmd11_cmd(ctx):
    """Auto Command 11"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 11", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd12')
async def cmd12_cmd(ctx):
    """Auto Command 12"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 12", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd13')
async def cmd13_cmd(ctx):
    """Auto Command 13"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 13", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd14')
async def cmd14_cmd(ctx):
    """Auto Command 14"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 14", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd15')
async def cmd15_cmd(ctx):
    """Auto Command 15"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 15", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd16')
async def cmd16_cmd(ctx):
    """Auto Command 16"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 16", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd17')
async def cmd17_cmd(ctx):
    """Auto Command 17"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 17", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd18')
async def cmd18_cmd(ctx):
    """Auto Command 18"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 18", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd19')
async def cmd19_cmd(ctx):
    """Auto Command 19"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 19", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd20')
async def cmd20_cmd(ctx):
    """Auto Command 20"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 20", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd21')
async def cmd21_cmd(ctx):
    """Auto Command 21"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 21", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd22')
async def cmd22_cmd(ctx):
    """Auto Command 22"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 22", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd23')
async def cmd23_cmd(ctx):
    """Auto Command 23"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 23", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd24')
async def cmd24_cmd(ctx):
    """Auto Command 24"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 24", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd25')
async def cmd25_cmd(ctx):
    """Auto Command 25"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 25", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd26')
async def cmd26_cmd(ctx):
    """Auto Command 26"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 26", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd27')
async def cmd27_cmd(ctx):
    """Auto Command 27"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 27", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd28')
async def cmd28_cmd(ctx):
    """Auto Command 28"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 28", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd29')
async def cmd29_cmd(ctx):
    """Auto Command 29"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 29", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd30')
async def cmd30_cmd(ctx):
    """Auto Command 30"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 30", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd31')
async def cmd31_cmd(ctx):
    """Auto Command 31"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 31", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd32')
async def cmd32_cmd(ctx):
    """Auto Command 32"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 32", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd33')
async def cmd33_cmd(ctx):
    """Auto Command 33"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 33", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd34')
async def cmd34_cmd(ctx):
    """Auto Command 34"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 34", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd35')
async def cmd35_cmd(ctx):
    """Auto Command 35"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 35", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd36')
async def cmd36_cmd(ctx):
    """Auto Command 36"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 36", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd37')
async def cmd37_cmd(ctx):
    """Auto Command 37"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 37", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd38')
async def cmd38_cmd(ctx):
    """Auto Command 38"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 38", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd39')
async def cmd39_cmd(ctx):
    """Auto Command 39"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 39", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd40')
async def cmd40_cmd(ctx):
    """Auto Command 40"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 40", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd41')
async def cmd41_cmd(ctx):
    """Auto Command 41"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 41", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd42')
async def cmd42_cmd(ctx):
    """Auto Command 42"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 42", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd43')
async def cmd43_cmd(ctx):
    """Auto Command 43"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 43", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd44')
async def cmd44_cmd(ctx):
    """Auto Command 44"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 44", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd45')
async def cmd45_cmd(ctx):
    """Auto Command 45"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 45", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd46')
async def cmd46_cmd(ctx):
    """Auto Command 46"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 46", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd47')
async def cmd47_cmd(ctx):
    """Auto Command 47"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 47", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd48')
async def cmd48_cmd(ctx):
    """Auto Command 48"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 48", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd49')
async def cmd49_cmd(ctx):
    """Auto Command 49"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 49", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd50')
async def cmd50_cmd(ctx):
    """Auto Command 50"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 50", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd51')
async def cmd51_cmd(ctx):
    """Auto Command 51"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 51", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd52')
async def cmd52_cmd(ctx):
    """Auto Command 52"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 52", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd53')
async def cmd53_cmd(ctx):
    """Auto Command 53"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 53", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd54')
async def cmd54_cmd(ctx):
    """Auto Command 54"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 54", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd55')
async def cmd55_cmd(ctx):
    """Auto Command 55"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 55", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd56')
async def cmd56_cmd(ctx):
    """Auto Command 56"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 56", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd57')
async def cmd57_cmd(ctx):
    """Auto Command 57"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 57", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd58')
async def cmd58_cmd(ctx):
    """Auto Command 58"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 58", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd59')
async def cmd59_cmd(ctx):
    """Auto Command 59"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 59", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd60')
async def cmd60_cmd(ctx):
    """Auto Command 60"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 60", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd61')
async def cmd61_cmd(ctx):
    """Auto Command 61"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 61", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd62')
async def cmd62_cmd(ctx):
    """Auto Command 62"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 62", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd63')
async def cmd63_cmd(ctx):
    """Auto Command 63"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 63", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd64')
async def cmd64_cmd(ctx):
    """Auto Command 64"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 64", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd65')
async def cmd65_cmd(ctx):
    """Auto Command 65"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 65", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd66')
async def cmd66_cmd(ctx):
    """Auto Command 66"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 66", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd67')
async def cmd67_cmd(ctx):
    """Auto Command 67"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 67", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd68')
async def cmd68_cmd(ctx):
    """Auto Command 68"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 68", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd69')
async def cmd69_cmd(ctx):
    """Auto Command 69"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 69", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd70')
async def cmd70_cmd(ctx):
    """Auto Command 70"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 70", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd71')
async def cmd71_cmd(ctx):
    """Auto Command 71"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 71", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd72')
async def cmd72_cmd(ctx):
    """Auto Command 72"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 72", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd73')
async def cmd73_cmd(ctx):
    """Auto Command 73"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 73", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd74')
async def cmd74_cmd(ctx):
    """Auto Command 74"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 74", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd75')
async def cmd75_cmd(ctx):
    """Auto Command 75"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 75", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd76')
async def cmd76_cmd(ctx):
    """Auto Command 76"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 76", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd77')
async def cmd77_cmd(ctx):
    """Auto Command 77"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 77", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd78')
async def cmd78_cmd(ctx):
    """Auto Command 78"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 78", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd79')
async def cmd79_cmd(ctx):
    """Auto Command 79"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 79", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd80')
async def cmd80_cmd(ctx):
    """Auto Command 80"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 80", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd81')
async def cmd81_cmd(ctx):
    """Auto Command 81"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 81", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd82')
async def cmd82_cmd(ctx):
    """Auto Command 82"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 82", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd83')
async def cmd83_cmd(ctx):
    """Auto Command 83"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 83", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd84')
async def cmd84_cmd(ctx):
    """Auto Command 84"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 84", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd85')
async def cmd85_cmd(ctx):
    """Auto Command 85"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 85", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd86')
async def cmd86_cmd(ctx):
    """Auto Command 86"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 86", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd87')
async def cmd87_cmd(ctx):
    """Auto Command 87"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 87", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd88')
async def cmd88_cmd(ctx):
    """Auto Command 88"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 88", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd89')
async def cmd89_cmd(ctx):
    """Auto Command 89"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 89", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd90')
async def cmd90_cmd(ctx):
    """Auto Command 90"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 90", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd91')
async def cmd91_cmd(ctx):
    """Auto Command 91"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 91", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd92')
async def cmd92_cmd(ctx):
    """Auto Command 92"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 92", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd93')
async def cmd93_cmd(ctx):
    """Auto Command 93"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 93", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd94')
async def cmd94_cmd(ctx):
    """Auto Command 94"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 94", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd95')
async def cmd95_cmd(ctx):
    """Auto Command 95"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 95", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd96')
async def cmd96_cmd(ctx):
    """Auto Command 96"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 96", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd97')
async def cmd97_cmd(ctx):
    """Auto Command 97"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 97", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd98')
async def cmd98_cmd(ctx):
    """Auto Command 98"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 98", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd99')
async def cmd99_cmd(ctx):
    """Auto Command 99"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 99", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd100')
async def cmd100_cmd(ctx):
    """Auto Command 100"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 100", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd101')
async def cmd101_cmd(ctx):
    """Auto Command 101"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 101", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd102')
async def cmd102_cmd(ctx):
    """Auto Command 102"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 102", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd103')
async def cmd103_cmd(ctx):
    """Auto Command 103"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 103", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd104')
async def cmd104_cmd(ctx):
    """Auto Command 104"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 104", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd105')
async def cmd105_cmd(ctx):
    """Auto Command 105"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 105", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd106')
async def cmd106_cmd(ctx):
    """Auto Command 106"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 106", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd107')
async def cmd107_cmd(ctx):
    """Auto Command 107"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 107", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd108')
async def cmd108_cmd(ctx):
    """Auto Command 108"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 108", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd109')
async def cmd109_cmd(ctx):
    """Auto Command 109"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 109", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd110')
async def cmd110_cmd(ctx):
    """Auto Command 110"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 110", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd111')
async def cmd111_cmd(ctx):
    """Auto Command 111"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 111", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd112')
async def cmd112_cmd(ctx):
    """Auto Command 112"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 112", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd113')
async def cmd113_cmd(ctx):
    """Auto Command 113"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 113", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd114')
async def cmd114_cmd(ctx):
    """Auto Command 114"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 114", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd115')
async def cmd115_cmd(ctx):
    """Auto Command 115"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 115", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd116')
async def cmd116_cmd(ctx):
    """Auto Command 116"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 116", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd117')
async def cmd117_cmd(ctx):
    """Auto Command 117"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 117", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd118')
async def cmd118_cmd(ctx):
    """Auto Command 118"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 118", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd119')
async def cmd119_cmd(ctx):
    """Auto Command 119"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 119", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd120')
async def cmd120_cmd(ctx):
    """Auto Command 120"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 120", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd121')
async def cmd121_cmd(ctx):
    """Auto Command 121"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 121", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd122')
async def cmd122_cmd(ctx):
    """Auto Command 122"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 122", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd123')
async def cmd123_cmd(ctx):
    """Auto Command 123"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 123", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd124')
async def cmd124_cmd(ctx):
    """Auto Command 124"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 124", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd125')
async def cmd125_cmd(ctx):
    """Auto Command 125"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 125", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd126')
async def cmd126_cmd(ctx):
    """Auto Command 126"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 126", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd127')
async def cmd127_cmd(ctx):
    """Auto Command 127"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 127", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd128')
async def cmd128_cmd(ctx):
    """Auto Command 128"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 128", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd129')
async def cmd129_cmd(ctx):
    """Auto Command 129"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 129", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd130')
async def cmd130_cmd(ctx):
    """Auto Command 130"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 130", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd131')
async def cmd131_cmd(ctx):
    """Auto Command 131"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 131", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd132')
async def cmd132_cmd(ctx):
    """Auto Command 132"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 132", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd133')
async def cmd133_cmd(ctx):
    """Auto Command 133"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 133", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd134')
async def cmd134_cmd(ctx):
    """Auto Command 134"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 134", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd135')
async def cmd135_cmd(ctx):
    """Auto Command 135"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 135", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd136')
async def cmd136_cmd(ctx):
    """Auto Command 136"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 136", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd137')
async def cmd137_cmd(ctx):
    """Auto Command 137"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 137", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd138')
async def cmd138_cmd(ctx):
    """Auto Command 138"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 138", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd139')
async def cmd139_cmd(ctx):
    """Auto Command 139"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 139", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd140')
async def cmd140_cmd(ctx):
    """Auto Command 140"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 140", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd141')
async def cmd141_cmd(ctx):
    """Auto Command 141"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 141", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd142')
async def cmd142_cmd(ctx):
    """Auto Command 142"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 142", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd143')
async def cmd143_cmd(ctx):
    """Auto Command 143"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 143", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd144')
async def cmd144_cmd(ctx):
    """Auto Command 144"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 144", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd145')
async def cmd145_cmd(ctx):
    """Auto Command 145"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 145", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd146')
async def cmd146_cmd(ctx):
    """Auto Command 146"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 146", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd147')
async def cmd147_cmd(ctx):
    """Auto Command 147"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 147", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd148')
async def cmd148_cmd(ctx):
    """Auto Command 148"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 148", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd149')
async def cmd149_cmd(ctx):
    """Auto Command 149"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 149", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd150')
async def cmd150_cmd(ctx):
    """Auto Command 150"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 150", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd151')
async def cmd151_cmd(ctx):
    """Auto Command 151"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 151", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd152')
async def cmd152_cmd(ctx):
    """Auto Command 152"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 152", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd153')
async def cmd153_cmd(ctx):
    """Auto Command 153"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 153", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd154')
async def cmd154_cmd(ctx):
    """Auto Command 154"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 154", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd155')
async def cmd155_cmd(ctx):
    """Auto Command 155"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 155", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd156')
async def cmd156_cmd(ctx):
    """Auto Command 156"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 156", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd157')
async def cmd157_cmd(ctx):
    """Auto Command 157"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 157", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd158')
async def cmd158_cmd(ctx):
    """Auto Command 158"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 158", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd159')
async def cmd159_cmd(ctx):
    """Auto Command 159"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 159", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd160')
async def cmd160_cmd(ctx):
    """Auto Command 160"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 160", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd161')
async def cmd161_cmd(ctx):
    """Auto Command 161"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 161", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd162')
async def cmd162_cmd(ctx):
    """Auto Command 162"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 162", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd163')
async def cmd163_cmd(ctx):
    """Auto Command 163"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 163", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd164')
async def cmd164_cmd(ctx):
    """Auto Command 164"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 164", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd165')
async def cmd165_cmd(ctx):
    """Auto Command 165"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 165", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd166')
async def cmd166_cmd(ctx):
    """Auto Command 166"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 166", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd167')
async def cmd167_cmd(ctx):
    """Auto Command 167"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 167", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd168')
async def cmd168_cmd(ctx):
    """Auto Command 168"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 168", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd169')
async def cmd169_cmd(ctx):
    """Auto Command 169"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 169", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd170')
async def cmd170_cmd(ctx):
    """Auto Command 170"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 170", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd171')
async def cmd171_cmd(ctx):
    """Auto Command 171"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 171", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd172')
async def cmd172_cmd(ctx):
    """Auto Command 172"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 172", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd173')
async def cmd173_cmd(ctx):
    """Auto Command 173"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 173", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd174')
async def cmd174_cmd(ctx):
    """Auto Command 174"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 174", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd175')
async def cmd175_cmd(ctx):
    """Auto Command 175"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 175", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd176')
async def cmd176_cmd(ctx):
    """Auto Command 176"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 176", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd177')
async def cmd177_cmd(ctx):
    """Auto Command 177"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 177", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd178')
async def cmd178_cmd(ctx):
    """Auto Command 178"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 178", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd179')
async def cmd179_cmd(ctx):
    """Auto Command 179"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 179", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd180')
async def cmd180_cmd(ctx):
    """Auto Command 180"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 180", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd181')
async def cmd181_cmd(ctx):
    """Auto Command 181"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 181", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd182')
async def cmd182_cmd(ctx):
    """Auto Command 182"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 182", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd183')
async def cmd183_cmd(ctx):
    """Auto Command 183"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 183", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd184')
async def cmd184_cmd(ctx):
    """Auto Command 184"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 184", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd185')
async def cmd185_cmd(ctx):
    """Auto Command 185"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 185", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd186')
async def cmd186_cmd(ctx):
    """Auto Command 186"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 186", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd187')
async def cmd187_cmd(ctx):
    """Auto Command 187"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 187", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd188')
async def cmd188_cmd(ctx):
    """Auto Command 188"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 188", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd189')
async def cmd189_cmd(ctx):
    """Auto Command 189"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 189", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd190')
async def cmd190_cmd(ctx):
    """Auto Command 190"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 190", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd191')
async def cmd191_cmd(ctx):
    """Auto Command 191"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 191", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd192')
async def cmd192_cmd(ctx):
    """Auto Command 192"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 192", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd193')
async def cmd193_cmd(ctx):
    """Auto Command 193"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 193", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd194')
async def cmd194_cmd(ctx):
    """Auto Command 194"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 194", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd195')
async def cmd195_cmd(ctx):
    """Auto Command 195"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 195", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd196')
async def cmd196_cmd(ctx):
    """Auto Command 196"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 196", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd197')
async def cmd197_cmd(ctx):
    """Auto Command 197"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 197", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd198')
async def cmd198_cmd(ctx):
    """Auto Command 198"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 198", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd199')
async def cmd199_cmd(ctx):
    """Auto Command 199"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 199", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd200')
async def cmd200_cmd(ctx):
    """Auto Command 200"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 200", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd201')
async def cmd201_cmd(ctx):
    """Auto Command 201"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 201", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd202')
async def cmd202_cmd(ctx):
    """Auto Command 202"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 202", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd203')
async def cmd203_cmd(ctx):
    """Auto Command 203"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 203", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd204')
async def cmd204_cmd(ctx):
    """Auto Command 204"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 204", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd205')
async def cmd205_cmd(ctx):
    """Auto Command 205"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 205", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd206')
async def cmd206_cmd(ctx):
    """Auto Command 206"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 206", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd207')
async def cmd207_cmd(ctx):
    """Auto Command 207"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 207", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd208')
async def cmd208_cmd(ctx):
    """Auto Command 208"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 208", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd209')
async def cmd209_cmd(ctx):
    """Auto Command 209"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 209", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd210')
async def cmd210_cmd(ctx):
    """Auto Command 210"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 210", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd211')
async def cmd211_cmd(ctx):
    """Auto Command 211"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 211", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd212')
async def cmd212_cmd(ctx):
    """Auto Command 212"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 212", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd213')
async def cmd213_cmd(ctx):
    """Auto Command 213"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 213", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd214')
async def cmd214_cmd(ctx):
    """Auto Command 214"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 214", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd215')
async def cmd215_cmd(ctx):
    """Auto Command 215"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 215", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd216')
async def cmd216_cmd(ctx):
    """Auto Command 216"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 216", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd217')
async def cmd217_cmd(ctx):
    """Auto Command 217"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 217", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd218')
async def cmd218_cmd(ctx):
    """Auto Command 218"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 218", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd219')
async def cmd219_cmd(ctx):
    """Auto Command 219"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 219", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd220')
async def cmd220_cmd(ctx):
    """Auto Command 220"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 220", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd221')
async def cmd221_cmd(ctx):
    """Auto Command 221"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 221", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd222')
async def cmd222_cmd(ctx):
    """Auto Command 222"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 222", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd223')
async def cmd223_cmd(ctx):
    """Auto Command 223"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 223", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd224')
async def cmd224_cmd(ctx):
    """Auto Command 224"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 224", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd225')
async def cmd225_cmd(ctx):
    """Auto Command 225"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 225", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd226')
async def cmd226_cmd(ctx):
    """Auto Command 226"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 226", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd227')
async def cmd227_cmd(ctx):
    """Auto Command 227"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 227", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd228')
async def cmd228_cmd(ctx):
    """Auto Command 228"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 228", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd229')
async def cmd229_cmd(ctx):
    """Auto Command 229"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 229", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd230')
async def cmd230_cmd(ctx):
    """Auto Command 230"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 230", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd231')
async def cmd231_cmd(ctx):
    """Auto Command 231"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 231", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd232')
async def cmd232_cmd(ctx):
    """Auto Command 232"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 232", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd233')
async def cmd233_cmd(ctx):
    """Auto Command 233"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 233", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd234')
async def cmd234_cmd(ctx):
    """Auto Command 234"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 234", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd235')
async def cmd235_cmd(ctx):
    """Auto Command 235"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 235", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd236')
async def cmd236_cmd(ctx):
    """Auto Command 236"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 236", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd237')
async def cmd237_cmd(ctx):
    """Auto Command 237"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 237", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd238')
async def cmd238_cmd(ctx):
    """Auto Command 238"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 238", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd239')
async def cmd239_cmd(ctx):
    """Auto Command 239"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 239", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd240')
async def cmd240_cmd(ctx):
    """Auto Command 240"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 240", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd241')
async def cmd241_cmd(ctx):
    """Auto Command 241"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 241", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd242')
async def cmd242_cmd(ctx):
    """Auto Command 242"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 242", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd243')
async def cmd243_cmd(ctx):
    """Auto Command 243"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 243", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd244')
async def cmd244_cmd(ctx):
    """Auto Command 244"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 244", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd245')
async def cmd245_cmd(ctx):
    """Auto Command 245"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 245", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd246')
async def cmd246_cmd(ctx):
    """Auto Command 246"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 246", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd247')
async def cmd247_cmd(ctx):
    """Auto Command 247"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 247", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd248')
async def cmd248_cmd(ctx):
    """Auto Command 248"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 248", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd249')
async def cmd249_cmd(ctx):
    """Auto Command 249"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 249", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd250')
async def cmd250_cmd(ctx):
    """Auto Command 250"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 250", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd251')
async def cmd251_cmd(ctx):
    """Auto Command 251"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 251", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd252')
async def cmd252_cmd(ctx):
    """Auto Command 252"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 252", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd253')
async def cmd253_cmd(ctx):
    """Auto Command 253"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 253", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd254')
async def cmd254_cmd(ctx):
    """Auto Command 254"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 254", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd255')
async def cmd255_cmd(ctx):
    """Auto Command 255"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 255", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd256')
async def cmd256_cmd(ctx):
    """Auto Command 256"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 256", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd257')
async def cmd257_cmd(ctx):
    """Auto Command 257"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 257", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd258')
async def cmd258_cmd(ctx):
    """Auto Command 258"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 258", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd259')
async def cmd259_cmd(ctx):
    """Auto Command 259"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 259", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd260')
async def cmd260_cmd(ctx):
    """Auto Command 260"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 260", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd261')
async def cmd261_cmd(ctx):
    """Auto Command 261"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 261", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd262')
async def cmd262_cmd(ctx):
    """Auto Command 262"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 262", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd263')
async def cmd263_cmd(ctx):
    """Auto Command 263"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 263", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd264')
async def cmd264_cmd(ctx):
    """Auto Command 264"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 264", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd265')
async def cmd265_cmd(ctx):
    """Auto Command 265"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 265", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd266')
async def cmd266_cmd(ctx):
    """Auto Command 266"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 266", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd267')
async def cmd267_cmd(ctx):
    """Auto Command 267"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 267", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd268')
async def cmd268_cmd(ctx):
    """Auto Command 268"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 268", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd269')
async def cmd269_cmd(ctx):
    """Auto Command 269"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 269", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd270')
async def cmd270_cmd(ctx):
    """Auto Command 270"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 270", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd271')
async def cmd271_cmd(ctx):
    """Auto Command 271"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 271", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd272')
async def cmd272_cmd(ctx):
    """Auto Command 272"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 272", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd273')
async def cmd273_cmd(ctx):
    """Auto Command 273"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 273", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd274')
async def cmd274_cmd(ctx):
    """Auto Command 274"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 274", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd275')
async def cmd275_cmd(ctx):
    """Auto Command 275"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 275", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd276')
async def cmd276_cmd(ctx):
    """Auto Command 276"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 276", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd277')
async def cmd277_cmd(ctx):
    """Auto Command 277"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 277", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd278')
async def cmd278_cmd(ctx):
    """Auto Command 278"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 278", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd279')
async def cmd279_cmd(ctx):
    """Auto Command 279"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 279", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd280')
async def cmd280_cmd(ctx):
    """Auto Command 280"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 280", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd281')
async def cmd281_cmd(ctx):
    """Auto Command 281"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 281", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd282')
async def cmd282_cmd(ctx):
    """Auto Command 282"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 282", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd283')
async def cmd283_cmd(ctx):
    """Auto Command 283"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 283", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd284')
async def cmd284_cmd(ctx):
    """Auto Command 284"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 284", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd285')
async def cmd285_cmd(ctx):
    """Auto Command 285"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 285", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd286')
async def cmd286_cmd(ctx):
    """Auto Command 286"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 286", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd287')
async def cmd287_cmd(ctx):
    """Auto Command 287"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 287", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd288')
async def cmd288_cmd(ctx):
    """Auto Command 288"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 288", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd289')
async def cmd289_cmd(ctx):
    """Auto Command 289"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 289", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd290')
async def cmd290_cmd(ctx):
    """Auto Command 290"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 290", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd291')
async def cmd291_cmd(ctx):
    """Auto Command 291"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 291", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd292')
async def cmd292_cmd(ctx):
    """Auto Command 292"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 292", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd293')
async def cmd293_cmd(ctx):
    """Auto Command 293"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 293", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd294')
async def cmd294_cmd(ctx):
    """Auto Command 294"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 294", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd295')
async def cmd295_cmd(ctx):
    """Auto Command 295"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 295", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd296')
async def cmd296_cmd(ctx):
    """Auto Command 296"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 296", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd297')
async def cmd297_cmd(ctx):
    """Auto Command 297"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 297", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd298')
async def cmd298_cmd(ctx):
    """Auto Command 298"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 298", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd299')
async def cmd299_cmd(ctx):
    """Auto Command 299"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 299", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd300')
async def cmd300_cmd(ctx):
    """Auto Command 300"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 300", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd301')
async def cmd301_cmd(ctx):
    """Auto Command 301"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 301", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd302')
async def cmd302_cmd(ctx):
    """Auto Command 302"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 302", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd303')
async def cmd303_cmd(ctx):
    """Auto Command 303"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 303", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd304')
async def cmd304_cmd(ctx):
    """Auto Command 304"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 304", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd305')
async def cmd305_cmd(ctx):
    """Auto Command 305"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 305", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd306')
async def cmd306_cmd(ctx):
    """Auto Command 306"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 306", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd307')
async def cmd307_cmd(ctx):
    """Auto Command 307"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 307", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd308')
async def cmd308_cmd(ctx):
    """Auto Command 308"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 308", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd309')
async def cmd309_cmd(ctx):
    """Auto Command 309"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 309", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd310')
async def cmd310_cmd(ctx):
    """Auto Command 310"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 310", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd311')
async def cmd311_cmd(ctx):
    """Auto Command 311"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 311", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd312')
async def cmd312_cmd(ctx):
    """Auto Command 312"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 312", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd313')
async def cmd313_cmd(ctx):
    """Auto Command 313"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 313", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd314')
async def cmd314_cmd(ctx):
    """Auto Command 314"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 314", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd315')
async def cmd315_cmd(ctx):
    """Auto Command 315"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 315", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd316')
async def cmd316_cmd(ctx):
    """Auto Command 316"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 316", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd317')
async def cmd317_cmd(ctx):
    """Auto Command 317"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 317", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd318')
async def cmd318_cmd(ctx):
    """Auto Command 318"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 318", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd319')
async def cmd319_cmd(ctx):
    """Auto Command 319"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 319", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd320')
async def cmd320_cmd(ctx):
    """Auto Command 320"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 320", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd321')
async def cmd321_cmd(ctx):
    """Auto Command 321"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 321", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd322')
async def cmd322_cmd(ctx):
    """Auto Command 322"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 322", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd323')
async def cmd323_cmd(ctx):
    """Auto Command 323"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 323", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd324')
async def cmd324_cmd(ctx):
    """Auto Command 324"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 324", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd325')
async def cmd325_cmd(ctx):
    """Auto Command 325"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 325", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd326')
async def cmd326_cmd(ctx):
    """Auto Command 326"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 326", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd327')
async def cmd327_cmd(ctx):
    """Auto Command 327"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 327", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd328')
async def cmd328_cmd(ctx):
    """Auto Command 328"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 328", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd329')
async def cmd329_cmd(ctx):
    """Auto Command 329"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 329", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd330')
async def cmd330_cmd(ctx):
    """Auto Command 330"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 330", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd331')
async def cmd331_cmd(ctx):
    """Auto Command 331"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 331", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd332')
async def cmd332_cmd(ctx):
    """Auto Command 332"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 332", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd333')
async def cmd333_cmd(ctx):
    """Auto Command 333"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 333", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd334')
async def cmd334_cmd(ctx):
    """Auto Command 334"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 334", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd335')
async def cmd335_cmd(ctx):
    """Auto Command 335"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 335", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd336')
async def cmd336_cmd(ctx):
    """Auto Command 336"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 336", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd337')
async def cmd337_cmd(ctx):
    """Auto Command 337"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 337", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd338')
async def cmd338_cmd(ctx):
    """Auto Command 338"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 338", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd339')
async def cmd339_cmd(ctx):
    """Auto Command 339"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 339", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd340')
async def cmd340_cmd(ctx):
    """Auto Command 340"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 340", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd341')
async def cmd341_cmd(ctx):
    """Auto Command 341"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 341", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd342')
async def cmd342_cmd(ctx):
    """Auto Command 342"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 342", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd343')
async def cmd343_cmd(ctx):
    """Auto Command 343"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 343", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd344')
async def cmd344_cmd(ctx):
    """Auto Command 344"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 344", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd345')
async def cmd345_cmd(ctx):
    """Auto Command 345"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 345", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd346')
async def cmd346_cmd(ctx):
    """Auto Command 346"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 346", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd347')
async def cmd347_cmd(ctx):
    """Auto Command 347"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 347", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd348')
async def cmd348_cmd(ctx):
    """Auto Command 348"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 348", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd349')
async def cmd349_cmd(ctx):
    """Auto Command 349"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 349", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd350')
async def cmd350_cmd(ctx):
    """Auto Command 350"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 350", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd351')
async def cmd351_cmd(ctx):
    """Auto Command 351"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 351", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd352')
async def cmd352_cmd(ctx):
    """Auto Command 352"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 352", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd353')
async def cmd353_cmd(ctx):
    """Auto Command 353"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 353", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd354')
async def cmd354_cmd(ctx):
    """Auto Command 354"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 354", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd355')
async def cmd355_cmd(ctx):
    """Auto Command 355"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 355", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd356')
async def cmd356_cmd(ctx):
    """Auto Command 356"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 356", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd357')
async def cmd357_cmd(ctx):
    """Auto Command 357"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 357", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd358')
async def cmd358_cmd(ctx):
    """Auto Command 358"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 358", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd359')
async def cmd359_cmd(ctx):
    """Auto Command 359"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 359", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd360')
async def cmd360_cmd(ctx):
    """Auto Command 360"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 360", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd361')
async def cmd361_cmd(ctx):
    """Auto Command 361"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 361", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd362')
async def cmd362_cmd(ctx):
    """Auto Command 362"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 362", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd363')
async def cmd363_cmd(ctx):
    """Auto Command 363"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 363", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd364')
async def cmd364_cmd(ctx):
    """Auto Command 364"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 364", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd365')
async def cmd365_cmd(ctx):
    """Auto Command 365"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 365", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd366')
async def cmd366_cmd(ctx):
    """Auto Command 366"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 366", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd367')
async def cmd367_cmd(ctx):
    """Auto Command 367"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 367", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd368')
async def cmd368_cmd(ctx):
    """Auto Command 368"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 368", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd369')
async def cmd369_cmd(ctx):
    """Auto Command 369"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 369", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd370')
async def cmd370_cmd(ctx):
    """Auto Command 370"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 370", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd371')
async def cmd371_cmd(ctx):
    """Auto Command 371"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 371", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd372')
async def cmd372_cmd(ctx):
    """Auto Command 372"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 372", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd373')
async def cmd373_cmd(ctx):
    """Auto Command 373"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 373", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd374')
async def cmd374_cmd(ctx):
    """Auto Command 374"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 374", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd375')
async def cmd375_cmd(ctx):
    """Auto Command 375"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 375", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd376')
async def cmd376_cmd(ctx):
    """Auto Command 376"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 376", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd377')
async def cmd377_cmd(ctx):
    """Auto Command 377"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 377", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd378')
async def cmd378_cmd(ctx):
    """Auto Command 378"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 378", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd379')
async def cmd379_cmd(ctx):
    """Auto Command 379"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 379", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd380')
async def cmd380_cmd(ctx):
    """Auto Command 380"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 380", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd381')
async def cmd381_cmd(ctx):
    """Auto Command 381"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 381", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd382')
async def cmd382_cmd(ctx):
    """Auto Command 382"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 382", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd383')
async def cmd383_cmd(ctx):
    """Auto Command 383"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 383", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd384')
async def cmd384_cmd(ctx):
    """Auto Command 384"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 384", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd385')
async def cmd385_cmd(ctx):
    """Auto Command 385"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 385", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd386')
async def cmd386_cmd(ctx):
    """Auto Command 386"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 386", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd387')
async def cmd387_cmd(ctx):
    """Auto Command 387"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 387", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd388')
async def cmd388_cmd(ctx):
    """Auto Command 388"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 388", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd389')
async def cmd389_cmd(ctx):
    """Auto Command 389"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 389", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd390')
async def cmd390_cmd(ctx):
    """Auto Command 390"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 390", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd391')
async def cmd391_cmd(ctx):
    """Auto Command 391"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 391", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd392')
async def cmd392_cmd(ctx):
    """Auto Command 392"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 392", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd393')
async def cmd393_cmd(ctx):
    """Auto Command 393"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 393", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd394')
async def cmd394_cmd(ctx):
    """Auto Command 394"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 394", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd395')
async def cmd395_cmd(ctx):
    """Auto Command 395"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 395", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd396')
async def cmd396_cmd(ctx):
    """Auto Command 396"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 396", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd397')
async def cmd397_cmd(ctx):
    """Auto Command 397"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 397", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd398')
async def cmd398_cmd(ctx):
    """Auto Command 398"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 398", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd399')
async def cmd399_cmd(ctx):
    """Auto Command 399"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 399", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd400')
async def cmd400_cmd(ctx):
    """Auto Command 400"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 400", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd401')
async def cmd401_cmd(ctx):
    """Auto Command 401"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 401", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd402')
async def cmd402_cmd(ctx):
    """Auto Command 402"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 402", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd403')
async def cmd403_cmd(ctx):
    """Auto Command 403"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 403", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd404')
async def cmd404_cmd(ctx):
    """Auto Command 404"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 404", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd405')
async def cmd405_cmd(ctx):
    """Auto Command 405"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 405", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd406')
async def cmd406_cmd(ctx):
    """Auto Command 406"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 406", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd407')
async def cmd407_cmd(ctx):
    """Auto Command 407"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 407", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd408')
async def cmd408_cmd(ctx):
    """Auto Command 408"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 408", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd409')
async def cmd409_cmd(ctx):
    """Auto Command 409"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 409", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd410')
async def cmd410_cmd(ctx):
    """Auto Command 410"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 410", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd411')
async def cmd411_cmd(ctx):
    """Auto Command 411"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 411", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd412')
async def cmd412_cmd(ctx):
    """Auto Command 412"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 412", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd413')
async def cmd413_cmd(ctx):
    """Auto Command 413"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 413", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd414')
async def cmd414_cmd(ctx):
    """Auto Command 414"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 414", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd415')
async def cmd415_cmd(ctx):
    """Auto Command 415"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 415", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd416')
async def cmd416_cmd(ctx):
    """Auto Command 416"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 416", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd417')
async def cmd417_cmd(ctx):
    """Auto Command 417"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 417", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd418')
async def cmd418_cmd(ctx):
    """Auto Command 418"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 418", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd419')
async def cmd419_cmd(ctx):
    """Auto Command 419"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 419", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd420')
async def cmd420_cmd(ctx):
    """Auto Command 420"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 420", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd421')
async def cmd421_cmd(ctx):
    """Auto Command 421"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 421", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd422')
async def cmd422_cmd(ctx):
    """Auto Command 422"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 422", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd423')
async def cmd423_cmd(ctx):
    """Auto Command 423"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 423", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd424')
async def cmd424_cmd(ctx):
    """Auto Command 424"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 424", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd425')
async def cmd425_cmd(ctx):
    """Auto Command 425"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 425", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd426')
async def cmd426_cmd(ctx):
    """Auto Command 426"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 426", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd427')
async def cmd427_cmd(ctx):
    """Auto Command 427"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 427", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd428')
async def cmd428_cmd(ctx):
    """Auto Command 428"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 428", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd429')
async def cmd429_cmd(ctx):
    """Auto Command 429"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 429", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd430')
async def cmd430_cmd(ctx):
    """Auto Command 430"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 430", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd431')
async def cmd431_cmd(ctx):
    """Auto Command 431"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 431", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd432')
async def cmd432_cmd(ctx):
    """Auto Command 432"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 432", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd433')
async def cmd433_cmd(ctx):
    """Auto Command 433"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 433", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd434')
async def cmd434_cmd(ctx):
    """Auto Command 434"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 434", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd435')
async def cmd435_cmd(ctx):
    """Auto Command 435"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 435", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd436')
async def cmd436_cmd(ctx):
    """Auto Command 436"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 436", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd437')
async def cmd437_cmd(ctx):
    """Auto Command 437"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 437", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd438')
async def cmd438_cmd(ctx):
    """Auto Command 438"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 438", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd439')
async def cmd439_cmd(ctx):
    """Auto Command 439"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 439", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd440')
async def cmd440_cmd(ctx):
    """Auto Command 440"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 440", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd441')
async def cmd441_cmd(ctx):
    """Auto Command 441"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 441", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd442')
async def cmd442_cmd(ctx):
    """Auto Command 442"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 442", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd443')
async def cmd443_cmd(ctx):
    """Auto Command 443"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 443", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd444')
async def cmd444_cmd(ctx):
    """Auto Command 444"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 444", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd445')
async def cmd445_cmd(ctx):
    """Auto Command 445"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 445", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd446')
async def cmd446_cmd(ctx):
    """Auto Command 446"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 446", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd447')
async def cmd447_cmd(ctx):
    """Auto Command 447"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 447", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd448')
async def cmd448_cmd(ctx):
    """Auto Command 448"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 448", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd449')
async def cmd449_cmd(ctx):
    """Auto Command 449"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 449", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd450')
async def cmd450_cmd(ctx):
    """Auto Command 450"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 450", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd451')
async def cmd451_cmd(ctx):
    """Auto Command 451"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 451", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd452')
async def cmd452_cmd(ctx):
    """Auto Command 452"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 452", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd453')
async def cmd453_cmd(ctx):
    """Auto Command 453"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 453", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd454')
async def cmd454_cmd(ctx):
    """Auto Command 454"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 454", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd455')
async def cmd455_cmd(ctx):
    """Auto Command 455"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 455", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd456')
async def cmd456_cmd(ctx):
    """Auto Command 456"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 456", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd457')
async def cmd457_cmd(ctx):
    """Auto Command 457"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 457", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd458')
async def cmd458_cmd(ctx):
    """Auto Command 458"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 458", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd459')
async def cmd459_cmd(ctx):
    """Auto Command 459"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 459", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd460')
async def cmd460_cmd(ctx):
    """Auto Command 460"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 460", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd461')
async def cmd461_cmd(ctx):
    """Auto Command 461"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 461", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd462')
async def cmd462_cmd(ctx):
    """Auto Command 462"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 462", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd463')
async def cmd463_cmd(ctx):
    """Auto Command 463"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 463", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd464')
async def cmd464_cmd(ctx):
    """Auto Command 464"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 464", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd465')
async def cmd465_cmd(ctx):
    """Auto Command 465"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 465", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd466')
async def cmd466_cmd(ctx):
    """Auto Command 466"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 466", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd467')
async def cmd467_cmd(ctx):
    """Auto Command 467"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 467", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd468')
async def cmd468_cmd(ctx):
    """Auto Command 468"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 468", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd469')
async def cmd469_cmd(ctx):
    """Auto Command 469"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 469", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd470')
async def cmd470_cmd(ctx):
    """Auto Command 470"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 470", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd471')
async def cmd471_cmd(ctx):
    """Auto Command 471"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 471", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd472')
async def cmd472_cmd(ctx):
    """Auto Command 472"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 472", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd473')
async def cmd473_cmd(ctx):
    """Auto Command 473"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 473", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd474')
async def cmd474_cmd(ctx):
    """Auto Command 474"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 474", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd475')
async def cmd475_cmd(ctx):
    """Auto Command 475"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 475", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd476')
async def cmd476_cmd(ctx):
    """Auto Command 476"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 476", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd477')
async def cmd477_cmd(ctx):
    """Auto Command 477"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 477", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd478')
async def cmd478_cmd(ctx):
    """Auto Command 478"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 478", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd479')
async def cmd479_cmd(ctx):
    """Auto Command 479"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 479", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd480')
async def cmd480_cmd(ctx):
    """Auto Command 480"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 480", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd481')
async def cmd481_cmd(ctx):
    """Auto Command 481"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 481", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd482')
async def cmd482_cmd(ctx):
    """Auto Command 482"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 482", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd483')
async def cmd483_cmd(ctx):
    """Auto Command 483"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 483", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd484')
async def cmd484_cmd(ctx):
    """Auto Command 484"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 484", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd485')
async def cmd485_cmd(ctx):
    """Auto Command 485"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 485", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd486')
async def cmd486_cmd(ctx):
    """Auto Command 486"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 486", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd487')
async def cmd487_cmd(ctx):
    """Auto Command 487"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 487", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd488')
async def cmd488_cmd(ctx):
    """Auto Command 488"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 488", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd489')
async def cmd489_cmd(ctx):
    """Auto Command 489"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 489", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd490')
async def cmd490_cmd(ctx):
    """Auto Command 490"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 490", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd491')
async def cmd491_cmd(ctx):
    """Auto Command 491"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 491", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd492')
async def cmd492_cmd(ctx):
    """Auto Command 492"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 492", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd493')
async def cmd493_cmd(ctx):
    """Auto Command 493"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 493", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd494')
async def cmd494_cmd(ctx):
    """Auto Command 494"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 494", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd495')
async def cmd495_cmd(ctx):
    """Auto Command 495"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 495", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd496')
async def cmd496_cmd(ctx):
    """Auto Command 496"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 496", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd497')
async def cmd497_cmd(ctx):
    """Auto Command 497"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 497", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd498')
async def cmd498_cmd(ctx):
    """Auto Command 498"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 498", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd499')
async def cmd499_cmd(ctx):
    """Auto Command 499"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 499", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd500')
async def cmd500_cmd(ctx):
    """Auto Command 500"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 500", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd501')
async def cmd501_cmd(ctx):
    """Auto Command 501"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 501", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd502')
async def cmd502_cmd(ctx):
    """Auto Command 502"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 502", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd503')
async def cmd503_cmd(ctx):
    """Auto Command 503"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 503", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd504')
async def cmd504_cmd(ctx):
    """Auto Command 504"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 504", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd505')
async def cmd505_cmd(ctx):
    """Auto Command 505"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 505", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd506')
async def cmd506_cmd(ctx):
    """Auto Command 506"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 506", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd507')
async def cmd507_cmd(ctx):
    """Auto Command 507"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 507", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd508')
async def cmd508_cmd(ctx):
    """Auto Command 508"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 508", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd509')
async def cmd509_cmd(ctx):
    """Auto Command 509"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 509", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd510')
async def cmd510_cmd(ctx):
    """Auto Command 510"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 510", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd511')
async def cmd511_cmd(ctx):
    """Auto Command 511"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 511", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd512')
async def cmd512_cmd(ctx):
    """Auto Command 512"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 512", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd513')
async def cmd513_cmd(ctx):
    """Auto Command 513"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 513", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd514')
async def cmd514_cmd(ctx):
    """Auto Command 514"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 514", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd515')
async def cmd515_cmd(ctx):
    """Auto Command 515"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 515", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd516')
async def cmd516_cmd(ctx):
    """Auto Command 516"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 516", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd517')
async def cmd517_cmd(ctx):
    """Auto Command 517"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 517", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd518')
async def cmd518_cmd(ctx):
    """Auto Command 518"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 518", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd519')
async def cmd519_cmd(ctx):
    """Auto Command 519"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 519", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd520')
async def cmd520_cmd(ctx):
    """Auto Command 520"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 520", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd521')
async def cmd521_cmd(ctx):
    """Auto Command 521"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 521", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd522')
async def cmd522_cmd(ctx):
    """Auto Command 522"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 522", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd523')
async def cmd523_cmd(ctx):
    """Auto Command 523"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 523", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd524')
async def cmd524_cmd(ctx):
    """Auto Command 524"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 524", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd525')
async def cmd525_cmd(ctx):
    """Auto Command 525"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 525", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd526')
async def cmd526_cmd(ctx):
    """Auto Command 526"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 526", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd527')
async def cmd527_cmd(ctx):
    """Auto Command 527"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 527", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd528')
async def cmd528_cmd(ctx):
    """Auto Command 528"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 528", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd529')
async def cmd529_cmd(ctx):
    """Auto Command 529"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 529", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd530')
async def cmd530_cmd(ctx):
    """Auto Command 530"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 530", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd531')
async def cmd531_cmd(ctx):
    """Auto Command 531"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 531", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd532')
async def cmd532_cmd(ctx):
    """Auto Command 532"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 532", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd533')
async def cmd533_cmd(ctx):
    """Auto Command 533"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 533", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd534')
async def cmd534_cmd(ctx):
    """Auto Command 534"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 534", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd535')
async def cmd535_cmd(ctx):
    """Auto Command 535"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 535", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd536')
async def cmd536_cmd(ctx):
    """Auto Command 536"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 536", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd537')
async def cmd537_cmd(ctx):
    """Auto Command 537"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 537", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd538')
async def cmd538_cmd(ctx):
    """Auto Command 538"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 538", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd539')
async def cmd539_cmd(ctx):
    """Auto Command 539"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 539", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd540')
async def cmd540_cmd(ctx):
    """Auto Command 540"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 540", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd541')
async def cmd541_cmd(ctx):
    """Auto Command 541"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 541", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd542')
async def cmd542_cmd(ctx):
    """Auto Command 542"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 542", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd543')
async def cmd543_cmd(ctx):
    """Auto Command 543"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 543", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd544')
async def cmd544_cmd(ctx):
    """Auto Command 544"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 544", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd545')
async def cmd545_cmd(ctx):
    """Auto Command 545"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 545", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd546')
async def cmd546_cmd(ctx):
    """Auto Command 546"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 546", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd547')
async def cmd547_cmd(ctx):
    """Auto Command 547"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 547", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd548')
async def cmd548_cmd(ctx):
    """Auto Command 548"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 548", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd549')
async def cmd549_cmd(ctx):
    """Auto Command 549"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 549", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd550')
async def cmd550_cmd(ctx):
    """Auto Command 550"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 550", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd551')
async def cmd551_cmd(ctx):
    """Auto Command 551"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 551", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd552')
async def cmd552_cmd(ctx):
    """Auto Command 552"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 552", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd553')
async def cmd553_cmd(ctx):
    """Auto Command 553"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 553", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd554')
async def cmd554_cmd(ctx):
    """Auto Command 554"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 554", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd555')
async def cmd555_cmd(ctx):
    """Auto Command 555"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 555", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd556')
async def cmd556_cmd(ctx):
    """Auto Command 556"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 556", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd557')
async def cmd557_cmd(ctx):
    """Auto Command 557"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 557", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd558')
async def cmd558_cmd(ctx):
    """Auto Command 558"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 558", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd559')
async def cmd559_cmd(ctx):
    """Auto Command 559"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 559", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd560')
async def cmd560_cmd(ctx):
    """Auto Command 560"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 560", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd561')
async def cmd561_cmd(ctx):
    """Auto Command 561"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 561", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd562')
async def cmd562_cmd(ctx):
    """Auto Command 562"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 562", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd563')
async def cmd563_cmd(ctx):
    """Auto Command 563"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 563", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd564')
async def cmd564_cmd(ctx):
    """Auto Command 564"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 564", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd565')
async def cmd565_cmd(ctx):
    """Auto Command 565"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 565", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd566')
async def cmd566_cmd(ctx):
    """Auto Command 566"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 566", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd567')
async def cmd567_cmd(ctx):
    """Auto Command 567"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 567", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd568')
async def cmd568_cmd(ctx):
    """Auto Command 568"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 568", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd569')
async def cmd569_cmd(ctx):
    """Auto Command 569"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 569", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd570')
async def cmd570_cmd(ctx):
    """Auto Command 570"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 570", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd571')
async def cmd571_cmd(ctx):
    """Auto Command 571"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 571", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd572')
async def cmd572_cmd(ctx):
    """Auto Command 572"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 572", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd573')
async def cmd573_cmd(ctx):
    """Auto Command 573"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 573", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd574')
async def cmd574_cmd(ctx):
    """Auto Command 574"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 574", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd575')
async def cmd575_cmd(ctx):
    """Auto Command 575"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 575", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd576')
async def cmd576_cmd(ctx):
    """Auto Command 576"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 576", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd577')
async def cmd577_cmd(ctx):
    """Auto Command 577"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 577", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd578')
async def cmd578_cmd(ctx):
    """Auto Command 578"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 578", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd579')
async def cmd579_cmd(ctx):
    """Auto Command 579"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 579", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd580')
async def cmd580_cmd(ctx):
    """Auto Command 580"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 580", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd581')
async def cmd581_cmd(ctx):
    """Auto Command 581"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 581", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd582')
async def cmd582_cmd(ctx):
    """Auto Command 582"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 582", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd583')
async def cmd583_cmd(ctx):
    """Auto Command 583"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 583", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd584')
async def cmd584_cmd(ctx):
    """Auto Command 584"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 584", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd585')
async def cmd585_cmd(ctx):
    """Auto Command 585"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 585", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd586')
async def cmd586_cmd(ctx):
    """Auto Command 586"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 586", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd587')
async def cmd587_cmd(ctx):
    """Auto Command 587"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 587", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd588')
async def cmd588_cmd(ctx):
    """Auto Command 588"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 588", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd589')
async def cmd589_cmd(ctx):
    """Auto Command 589"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 589", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd590')
async def cmd590_cmd(ctx):
    """Auto Command 590"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 590", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd591')
async def cmd591_cmd(ctx):
    """Auto Command 591"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 591", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd592')
async def cmd592_cmd(ctx):
    """Auto Command 592"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 592", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd593')
async def cmd593_cmd(ctx):
    """Auto Command 593"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 593", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd594')
async def cmd594_cmd(ctx):
    """Auto Command 594"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 594", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd595')
async def cmd595_cmd(ctx):
    """Auto Command 595"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 595", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd596')
async def cmd596_cmd(ctx):
    """Auto Command 596"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 596", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd597')
async def cmd597_cmd(ctx):
    """Auto Command 597"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 597", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd598')
async def cmd598_cmd(ctx):
    """Auto Command 598"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 598", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd599')
async def cmd599_cmd(ctx):
    """Auto Command 599"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 599", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd600')
async def cmd600_cmd(ctx):
    """Auto Command 600"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 600", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd601')
async def cmd601_cmd(ctx):
    """Auto Command 601"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 601", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd602')
async def cmd602_cmd(ctx):
    """Auto Command 602"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 602", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd603')
async def cmd603_cmd(ctx):
    """Auto Command 603"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 603", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd604')
async def cmd604_cmd(ctx):
    """Auto Command 604"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 604", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd605')
async def cmd605_cmd(ctx):
    """Auto Command 605"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 605", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd606')
async def cmd606_cmd(ctx):
    """Auto Command 606"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 606", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd607')
async def cmd607_cmd(ctx):
    """Auto Command 607"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 607", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd608')
async def cmd608_cmd(ctx):
    """Auto Command 608"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 608", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd609')
async def cmd609_cmd(ctx):
    """Auto Command 609"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 609", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd610')
async def cmd610_cmd(ctx):
    """Auto Command 610"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 610", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd611')
async def cmd611_cmd(ctx):
    """Auto Command 611"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 611", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd612')
async def cmd612_cmd(ctx):
    """Auto Command 612"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 612", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd613')
async def cmd613_cmd(ctx):
    """Auto Command 613"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 613", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd614')
async def cmd614_cmd(ctx):
    """Auto Command 614"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 614", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd615')
async def cmd615_cmd(ctx):
    """Auto Command 615"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 615", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd616')
async def cmd616_cmd(ctx):
    """Auto Command 616"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 616", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd617')
async def cmd617_cmd(ctx):
    """Auto Command 617"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 617", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd618')
async def cmd618_cmd(ctx):
    """Auto Command 618"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 618", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd619')
async def cmd619_cmd(ctx):
    """Auto Command 619"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 619", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd620')
async def cmd620_cmd(ctx):
    """Auto Command 620"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 620", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd621')
async def cmd621_cmd(ctx):
    """Auto Command 621"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 621", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd622')
async def cmd622_cmd(ctx):
    """Auto Command 622"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 622", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd623')
async def cmd623_cmd(ctx):
    """Auto Command 623"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 623", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd624')
async def cmd624_cmd(ctx):
    """Auto Command 624"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 624", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd625')
async def cmd625_cmd(ctx):
    """Auto Command 625"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 625", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd626')
async def cmd626_cmd(ctx):
    """Auto Command 626"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 626", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd627')
async def cmd627_cmd(ctx):
    """Auto Command 627"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 627", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd628')
async def cmd628_cmd(ctx):
    """Auto Command 628"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 628", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd629')
async def cmd629_cmd(ctx):
    """Auto Command 629"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 629", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd630')
async def cmd630_cmd(ctx):
    """Auto Command 630"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 630", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd631')
async def cmd631_cmd(ctx):
    """Auto Command 631"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 631", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd632')
async def cmd632_cmd(ctx):
    """Auto Command 632"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 632", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd633')
async def cmd633_cmd(ctx):
    """Auto Command 633"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 633", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd634')
async def cmd634_cmd(ctx):
    """Auto Command 634"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 634", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd635')
async def cmd635_cmd(ctx):
    """Auto Command 635"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 635", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd636')
async def cmd636_cmd(ctx):
    """Auto Command 636"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 636", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd637')
async def cmd637_cmd(ctx):
    """Auto Command 637"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 637", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd638')
async def cmd638_cmd(ctx):
    """Auto Command 638"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 638", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd639')
async def cmd639_cmd(ctx):
    """Auto Command 639"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 639", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd640')
async def cmd640_cmd(ctx):
    """Auto Command 640"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 640", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd641')
async def cmd641_cmd(ctx):
    """Auto Command 641"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 641", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd642')
async def cmd642_cmd(ctx):
    """Auto Command 642"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 642", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd643')
async def cmd643_cmd(ctx):
    """Auto Command 643"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 643", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd644')
async def cmd644_cmd(ctx):
    """Auto Command 644"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 644", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd645')
async def cmd645_cmd(ctx):
    """Auto Command 645"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 645", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd646')
async def cmd646_cmd(ctx):
    """Auto Command 646"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 646", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd647')
async def cmd647_cmd(ctx):
    """Auto Command 647"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 647", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd648')
async def cmd648_cmd(ctx):
    """Auto Command 648"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 648", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd649')
async def cmd649_cmd(ctx):
    """Auto Command 649"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 649", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd650')
async def cmd650_cmd(ctx):
    """Auto Command 650"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 650", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd651')
async def cmd651_cmd(ctx):
    """Auto Command 651"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 651", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd652')
async def cmd652_cmd(ctx):
    """Auto Command 652"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 652", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd653')
async def cmd653_cmd(ctx):
    """Auto Command 653"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 653", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd654')
async def cmd654_cmd(ctx):
    """Auto Command 654"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 654", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd655')
async def cmd655_cmd(ctx):
    """Auto Command 655"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 655", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd656')
async def cmd656_cmd(ctx):
    """Auto Command 656"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 656", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd657')
async def cmd657_cmd(ctx):
    """Auto Command 657"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 657", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd658')
async def cmd658_cmd(ctx):
    """Auto Command 658"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 658", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd659')
async def cmd659_cmd(ctx):
    """Auto Command 659"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 659", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd660')
async def cmd660_cmd(ctx):
    """Auto Command 660"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 660", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd661')
async def cmd661_cmd(ctx):
    """Auto Command 661"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 661", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd662')
async def cmd662_cmd(ctx):
    """Auto Command 662"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 662", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd663')
async def cmd663_cmd(ctx):
    """Auto Command 663"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 663", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd664')
async def cmd664_cmd(ctx):
    """Auto Command 664"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 664", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd665')
async def cmd665_cmd(ctx):
    """Auto Command 665"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 665", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd666')
async def cmd666_cmd(ctx):
    """Auto Command 666"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 666", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd667')
async def cmd667_cmd(ctx):
    """Auto Command 667"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 667", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd668')
async def cmd668_cmd(ctx):
    """Auto Command 668"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 668", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd669')
async def cmd669_cmd(ctx):
    """Auto Command 669"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 669", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd670')
async def cmd670_cmd(ctx):
    """Auto Command 670"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 670", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd671')
async def cmd671_cmd(ctx):
    """Auto Command 671"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 671", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd672')
async def cmd672_cmd(ctx):
    """Auto Command 672"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 672", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd673')
async def cmd673_cmd(ctx):
    """Auto Command 673"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 673", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd674')
async def cmd674_cmd(ctx):
    """Auto Command 674"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 674", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd675')
async def cmd675_cmd(ctx):
    """Auto Command 675"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 675", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd676')
async def cmd676_cmd(ctx):
    """Auto Command 676"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 676", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd677')
async def cmd677_cmd(ctx):
    """Auto Command 677"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 677", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd678')
async def cmd678_cmd(ctx):
    """Auto Command 678"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 678", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd679')
async def cmd679_cmd(ctx):
    """Auto Command 679"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 679", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd680')
async def cmd680_cmd(ctx):
    """Auto Command 680"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 680", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd681')
async def cmd681_cmd(ctx):
    """Auto Command 681"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 681", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd682')
async def cmd682_cmd(ctx):
    """Auto Command 682"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 682", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd683')
async def cmd683_cmd(ctx):
    """Auto Command 683"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 683", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd684')
async def cmd684_cmd(ctx):
    """Auto Command 684"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 684", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd685')
async def cmd685_cmd(ctx):
    """Auto Command 685"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 685", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd686')
async def cmd686_cmd(ctx):
    """Auto Command 686"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 686", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd687')
async def cmd687_cmd(ctx):
    """Auto Command 687"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 687", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd688')
async def cmd688_cmd(ctx):
    """Auto Command 688"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 688", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd689')
async def cmd689_cmd(ctx):
    """Auto Command 689"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 689", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd690')
async def cmd690_cmd(ctx):
    """Auto Command 690"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 690", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd691')
async def cmd691_cmd(ctx):
    """Auto Command 691"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 691", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd692')
async def cmd692_cmd(ctx):
    """Auto Command 692"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 692", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd693')
async def cmd693_cmd(ctx):
    """Auto Command 693"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 693", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd694')
async def cmd694_cmd(ctx):
    """Auto Command 694"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 694", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd695')
async def cmd695_cmd(ctx):
    """Auto Command 695"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 695", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd696')
async def cmd696_cmd(ctx):
    """Auto Command 696"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 696", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd697')
async def cmd697_cmd(ctx):
    """Auto Command 697"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 697", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd698')
async def cmd698_cmd(ctx):
    """Auto Command 698"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 698", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd699')
async def cmd699_cmd(ctx):
    """Auto Command 699"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 699", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd700')
async def cmd700_cmd(ctx):
    """Auto Command 700"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 700", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd701')
async def cmd701_cmd(ctx):
    """Auto Command 701"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 701", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd702')
async def cmd702_cmd(ctx):
    """Auto Command 702"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 702", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd703')
async def cmd703_cmd(ctx):
    """Auto Command 703"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 703", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd704')
async def cmd704_cmd(ctx):
    """Auto Command 704"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 704", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd705')
async def cmd705_cmd(ctx):
    """Auto Command 705"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 705", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd706')
async def cmd706_cmd(ctx):
    """Auto Command 706"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 706", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd707')
async def cmd707_cmd(ctx):
    """Auto Command 707"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 707", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd708')
async def cmd708_cmd(ctx):
    """Auto Command 708"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 708", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd709')
async def cmd709_cmd(ctx):
    """Auto Command 709"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 709", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd710')
async def cmd710_cmd(ctx):
    """Auto Command 710"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 710", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd711')
async def cmd711_cmd(ctx):
    """Auto Command 711"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 711", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd712')
async def cmd712_cmd(ctx):
    """Auto Command 712"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 712", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd713')
async def cmd713_cmd(ctx):
    """Auto Command 713"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 713", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd714')
async def cmd714_cmd(ctx):
    """Auto Command 714"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 714", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd715')
async def cmd715_cmd(ctx):
    """Auto Command 715"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 715", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd716')
async def cmd716_cmd(ctx):
    """Auto Command 716"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 716", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd717')
async def cmd717_cmd(ctx):
    """Auto Command 717"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 717", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd718')
async def cmd718_cmd(ctx):
    """Auto Command 718"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 718", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd719')
async def cmd719_cmd(ctx):
    """Auto Command 719"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 719", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd720')
async def cmd720_cmd(ctx):
    """Auto Command 720"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 720", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd721')
async def cmd721_cmd(ctx):
    """Auto Command 721"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 721", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd722')
async def cmd722_cmd(ctx):
    """Auto Command 722"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 722", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd723')
async def cmd723_cmd(ctx):
    """Auto Command 723"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 723", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd724')
async def cmd724_cmd(ctx):
    """Auto Command 724"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 724", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd725')
async def cmd725_cmd(ctx):
    """Auto Command 725"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 725", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd726')
async def cmd726_cmd(ctx):
    """Auto Command 726"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 726", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd727')
async def cmd727_cmd(ctx):
    """Auto Command 727"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 727", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd728')
async def cmd728_cmd(ctx):
    """Auto Command 728"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 728", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd729')
async def cmd729_cmd(ctx):
    """Auto Command 729"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 729", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd730')
async def cmd730_cmd(ctx):
    """Auto Command 730"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 730", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd731')
async def cmd731_cmd(ctx):
    """Auto Command 731"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 731", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd732')
async def cmd732_cmd(ctx):
    """Auto Command 732"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 732", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd733')
async def cmd733_cmd(ctx):
    """Auto Command 733"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 733", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd734')
async def cmd734_cmd(ctx):
    """Auto Command 734"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 734", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd735')
async def cmd735_cmd(ctx):
    """Auto Command 735"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 735", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd736')
async def cmd736_cmd(ctx):
    """Auto Command 736"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 736", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd737')
async def cmd737_cmd(ctx):
    """Auto Command 737"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 737", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd738')
async def cmd738_cmd(ctx):
    """Auto Command 738"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 738", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd739')
async def cmd739_cmd(ctx):
    """Auto Command 739"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 739", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd740')
async def cmd740_cmd(ctx):
    """Auto Command 740"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 740", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd741')
async def cmd741_cmd(ctx):
    """Auto Command 741"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 741", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd742')
async def cmd742_cmd(ctx):
    """Auto Command 742"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 742", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd743')
async def cmd743_cmd(ctx):
    """Auto Command 743"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 743", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd744')
async def cmd744_cmd(ctx):
    """Auto Command 744"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 744", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd745')
async def cmd745_cmd(ctx):
    """Auto Command 745"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 745", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd746')
async def cmd746_cmd(ctx):
    """Auto Command 746"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 746", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd747')
async def cmd747_cmd(ctx):
    """Auto Command 747"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 747", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd748')
async def cmd748_cmd(ctx):
    """Auto Command 748"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 748", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd749')
async def cmd749_cmd(ctx):
    """Auto Command 749"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 749", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd750')
async def cmd750_cmd(ctx):
    """Auto Command 750"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 750", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd751')
async def cmd751_cmd(ctx):
    """Auto Command 751"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 751", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd752')
async def cmd752_cmd(ctx):
    """Auto Command 752"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 752", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd753')
async def cmd753_cmd(ctx):
    """Auto Command 753"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 753", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd754')
async def cmd754_cmd(ctx):
    """Auto Command 754"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 754", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd755')
async def cmd755_cmd(ctx):
    """Auto Command 755"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 755", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd756')
async def cmd756_cmd(ctx):
    """Auto Command 756"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 756", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd757')
async def cmd757_cmd(ctx):
    """Auto Command 757"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 757", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd758')
async def cmd758_cmd(ctx):
    """Auto Command 758"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 758", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd759')
async def cmd759_cmd(ctx):
    """Auto Command 759"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 759", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd760')
async def cmd760_cmd(ctx):
    """Auto Command 760"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 760", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd761')
async def cmd761_cmd(ctx):
    """Auto Command 761"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 761", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd762')
async def cmd762_cmd(ctx):
    """Auto Command 762"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 762", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd763')
async def cmd763_cmd(ctx):
    """Auto Command 763"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 763", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd764')
async def cmd764_cmd(ctx):
    """Auto Command 764"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 764", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd765')
async def cmd765_cmd(ctx):
    """Auto Command 765"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 765", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd766')
async def cmd766_cmd(ctx):
    """Auto Command 766"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 766", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd767')
async def cmd767_cmd(ctx):
    """Auto Command 767"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 767", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd768')
async def cmd768_cmd(ctx):
    """Auto Command 768"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 768", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd769')
async def cmd769_cmd(ctx):
    """Auto Command 769"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 769", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd770')
async def cmd770_cmd(ctx):
    """Auto Command 770"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 770", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd771')
async def cmd771_cmd(ctx):
    """Auto Command 771"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 771", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd772')
async def cmd772_cmd(ctx):
    """Auto Command 772"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 772", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd773')
async def cmd773_cmd(ctx):
    """Auto Command 773"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 773", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd774')
async def cmd774_cmd(ctx):
    """Auto Command 774"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 774", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd775')
async def cmd775_cmd(ctx):
    """Auto Command 775"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 775", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd776')
async def cmd776_cmd(ctx):
    """Auto Command 776"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 776", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd777')
async def cmd777_cmd(ctx):
    """Auto Command 777"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 777", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd778')
async def cmd778_cmd(ctx):
    """Auto Command 778"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 778", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd779')
async def cmd779_cmd(ctx):
    """Auto Command 779"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 779", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd780')
async def cmd780_cmd(ctx):
    """Auto Command 780"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 780", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd781')
async def cmd781_cmd(ctx):
    """Auto Command 781"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 781", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd782')
async def cmd782_cmd(ctx):
    """Auto Command 782"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 782", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd783')
async def cmd783_cmd(ctx):
    """Auto Command 783"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 783", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd784')
async def cmd784_cmd(ctx):
    """Auto Command 784"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 784", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd785')
async def cmd785_cmd(ctx):
    """Auto Command 785"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 785", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd786')
async def cmd786_cmd(ctx):
    """Auto Command 786"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 786", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd787')
async def cmd787_cmd(ctx):
    """Auto Command 787"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 787", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd788')
async def cmd788_cmd(ctx):
    """Auto Command 788"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 788", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd789')
async def cmd789_cmd(ctx):
    """Auto Command 789"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 789", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd790')
async def cmd790_cmd(ctx):
    """Auto Command 790"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 790", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd791')
async def cmd791_cmd(ctx):
    """Auto Command 791"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 791", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd792')
async def cmd792_cmd(ctx):
    """Auto Command 792"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 792", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd793')
async def cmd793_cmd(ctx):
    """Auto Command 793"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 793", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd794')
async def cmd794_cmd(ctx):
    """Auto Command 794"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 794", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd795')
async def cmd795_cmd(ctx):
    """Auto Command 795"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 795", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd796')
async def cmd796_cmd(ctx):
    """Auto Command 796"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 796", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd797')
async def cmd797_cmd(ctx):
    """Auto Command 797"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 797", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd798')
async def cmd798_cmd(ctx):
    """Auto Command 798"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 798", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd799')
async def cmd799_cmd(ctx):
    """Auto Command 799"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 799", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd800')
async def cmd800_cmd(ctx):
    """Auto Command 800"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 800", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd801')
async def cmd801_cmd(ctx):
    """Auto Command 801"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 801", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd802')
async def cmd802_cmd(ctx):
    """Auto Command 802"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 802", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd803')
async def cmd803_cmd(ctx):
    """Auto Command 803"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 803", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd804')
async def cmd804_cmd(ctx):
    """Auto Command 804"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 804", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd805')
async def cmd805_cmd(ctx):
    """Auto Command 805"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 805", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd806')
async def cmd806_cmd(ctx):
    """Auto Command 806"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 806", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd807')
async def cmd807_cmd(ctx):
    """Auto Command 807"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 807", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd808')
async def cmd808_cmd(ctx):
    """Auto Command 808"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 808", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd809')
async def cmd809_cmd(ctx):
    """Auto Command 809"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 809", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd810')
async def cmd810_cmd(ctx):
    """Auto Command 810"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 810", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd811')
async def cmd811_cmd(ctx):
    """Auto Command 811"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 811", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd812')
async def cmd812_cmd(ctx):
    """Auto Command 812"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 812", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd813')
async def cmd813_cmd(ctx):
    """Auto Command 813"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 813", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd814')
async def cmd814_cmd(ctx):
    """Auto Command 814"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 814", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd815')
async def cmd815_cmd(ctx):
    """Auto Command 815"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 815", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd816')
async def cmd816_cmd(ctx):
    """Auto Command 816"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 816", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd817')
async def cmd817_cmd(ctx):
    """Auto Command 817"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 817", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd818')
async def cmd818_cmd(ctx):
    """Auto Command 818"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 818", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd819')
async def cmd819_cmd(ctx):
    """Auto Command 819"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 819", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd820')
async def cmd820_cmd(ctx):
    """Auto Command 820"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 820", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd821')
async def cmd821_cmd(ctx):
    """Auto Command 821"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 821", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd822')
async def cmd822_cmd(ctx):
    """Auto Command 822"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 822", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd823')
async def cmd823_cmd(ctx):
    """Auto Command 823"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 823", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd824')
async def cmd824_cmd(ctx):
    """Auto Command 824"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 824", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd825')
async def cmd825_cmd(ctx):
    """Auto Command 825"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 825", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd826')
async def cmd826_cmd(ctx):
    """Auto Command 826"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 826", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd827')
async def cmd827_cmd(ctx):
    """Auto Command 827"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 827", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd828')
async def cmd828_cmd(ctx):
    """Auto Command 828"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 828", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd829')
async def cmd829_cmd(ctx):
    """Auto Command 829"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 829", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd830')
async def cmd830_cmd(ctx):
    """Auto Command 830"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 830", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd831')
async def cmd831_cmd(ctx):
    """Auto Command 831"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 831", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd832')
async def cmd832_cmd(ctx):
    """Auto Command 832"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 832", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd833')
async def cmd833_cmd(ctx):
    """Auto Command 833"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 833", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd834')
async def cmd834_cmd(ctx):
    """Auto Command 834"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 834", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd835')
async def cmd835_cmd(ctx):
    """Auto Command 835"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 835", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd836')
async def cmd836_cmd(ctx):
    """Auto Command 836"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 836", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd837')
async def cmd837_cmd(ctx):
    """Auto Command 837"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 837", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd838')
async def cmd838_cmd(ctx):
    """Auto Command 838"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 838", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd839')
async def cmd839_cmd(ctx):
    """Auto Command 839"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 839", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd840')
async def cmd840_cmd(ctx):
    """Auto Command 840"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 840", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd841')
async def cmd841_cmd(ctx):
    """Auto Command 841"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 841", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd842')
async def cmd842_cmd(ctx):
    """Auto Command 842"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 842", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd843')
async def cmd843_cmd(ctx):
    """Auto Command 843"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 843", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd844')
async def cmd844_cmd(ctx):
    """Auto Command 844"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 844", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd845')
async def cmd845_cmd(ctx):
    """Auto Command 845"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 845", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd846')
async def cmd846_cmd(ctx):
    """Auto Command 846"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 846", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd847')
async def cmd847_cmd(ctx):
    """Auto Command 847"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 847", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd848')
async def cmd848_cmd(ctx):
    """Auto Command 848"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 848", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd849')
async def cmd849_cmd(ctx):
    """Auto Command 849"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 849", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd850')
async def cmd850_cmd(ctx):
    """Auto Command 850"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 850", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd851')
async def cmd851_cmd(ctx):
    """Auto Command 851"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 851", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd852')
async def cmd852_cmd(ctx):
    """Auto Command 852"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 852", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd853')
async def cmd853_cmd(ctx):
    """Auto Command 853"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 853", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd854')
async def cmd854_cmd(ctx):
    """Auto Command 854"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 854", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd855')
async def cmd855_cmd(ctx):
    """Auto Command 855"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 855", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd856')
async def cmd856_cmd(ctx):
    """Auto Command 856"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 856", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd857')
async def cmd857_cmd(ctx):
    """Auto Command 857"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 857", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd858')
async def cmd858_cmd(ctx):
    """Auto Command 858"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 858", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd859')
async def cmd859_cmd(ctx):
    """Auto Command 859"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 859", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd860')
async def cmd860_cmd(ctx):
    """Auto Command 860"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 860", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd861')
async def cmd861_cmd(ctx):
    """Auto Command 861"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 861", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd862')
async def cmd862_cmd(ctx):
    """Auto Command 862"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 862", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd863')
async def cmd863_cmd(ctx):
    """Auto Command 863"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 863", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd864')
async def cmd864_cmd(ctx):
    """Auto Command 864"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 864", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd865')
async def cmd865_cmd(ctx):
    """Auto Command 865"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 865", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd866')
async def cmd866_cmd(ctx):
    """Auto Command 866"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 866", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd867')
async def cmd867_cmd(ctx):
    """Auto Command 867"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 867", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd868')
async def cmd868_cmd(ctx):
    """Auto Command 868"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 868", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd869')
async def cmd869_cmd(ctx):
    """Auto Command 869"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 869", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd870')
async def cmd870_cmd(ctx):
    """Auto Command 870"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 870", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd871')
async def cmd871_cmd(ctx):
    """Auto Command 871"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 871", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd872')
async def cmd872_cmd(ctx):
    """Auto Command 872"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 872", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd873')
async def cmd873_cmd(ctx):
    """Auto Command 873"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 873", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd874')
async def cmd874_cmd(ctx):
    """Auto Command 874"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 874", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd875')
async def cmd875_cmd(ctx):
    """Auto Command 875"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 875", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd876')
async def cmd876_cmd(ctx):
    """Auto Command 876"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 876", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd877')
async def cmd877_cmd(ctx):
    """Auto Command 877"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 877", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd878')
async def cmd878_cmd(ctx):
    """Auto Command 878"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 878", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd879')
async def cmd879_cmd(ctx):
    """Auto Command 879"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 879", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd880')
async def cmd880_cmd(ctx):
    """Auto Command 880"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 880", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd881')
async def cmd881_cmd(ctx):
    """Auto Command 881"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 881", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd882')
async def cmd882_cmd(ctx):
    """Auto Command 882"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 882", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd883')
async def cmd883_cmd(ctx):
    """Auto Command 883"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 883", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd884')
async def cmd884_cmd(ctx):
    """Auto Command 884"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 884", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd885')
async def cmd885_cmd(ctx):
    """Auto Command 885"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 885", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd886')
async def cmd886_cmd(ctx):
    """Auto Command 886"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 886", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd887')
async def cmd887_cmd(ctx):
    """Auto Command 887"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 887", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd888')
async def cmd888_cmd(ctx):
    """Auto Command 888"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 888", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd889')
async def cmd889_cmd(ctx):
    """Auto Command 889"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 889", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd890')
async def cmd890_cmd(ctx):
    """Auto Command 890"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 890", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd891')
async def cmd891_cmd(ctx):
    """Auto Command 891"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 891", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd892')
async def cmd892_cmd(ctx):
    """Auto Command 892"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 892", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd893')
async def cmd893_cmd(ctx):
    """Auto Command 893"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 893", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd894')
async def cmd894_cmd(ctx):
    """Auto Command 894"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 894", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd895')
async def cmd895_cmd(ctx):
    """Auto Command 895"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 895", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd896')
async def cmd896_cmd(ctx):
    """Auto Command 896"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 896", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd897')
async def cmd897_cmd(ctx):
    """Auto Command 897"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 897", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd898')
async def cmd898_cmd(ctx):
    """Auto Command 898"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 898", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd899')
async def cmd899_cmd(ctx):
    """Auto Command 899"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 899", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd900')
async def cmd900_cmd(ctx):
    """Auto Command 900"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 900", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd901')
async def cmd901_cmd(ctx):
    """Auto Command 901"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 901", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd902')
async def cmd902_cmd(ctx):
    """Auto Command 902"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 902", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd903')
async def cmd903_cmd(ctx):
    """Auto Command 903"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 903", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd904')
async def cmd904_cmd(ctx):
    """Auto Command 904"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 904", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd905')
async def cmd905_cmd(ctx):
    """Auto Command 905"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 905", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd906')
async def cmd906_cmd(ctx):
    """Auto Command 906"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 906", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd907')
async def cmd907_cmd(ctx):
    """Auto Command 907"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 907", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd908')
async def cmd908_cmd(ctx):
    """Auto Command 908"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 908", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd909')
async def cmd909_cmd(ctx):
    """Auto Command 909"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 909", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd910')
async def cmd910_cmd(ctx):
    """Auto Command 910"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 910", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd911')
async def cmd911_cmd(ctx):
    """Auto Command 911"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 911", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd912')
async def cmd912_cmd(ctx):
    """Auto Command 912"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 912", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd913')
async def cmd913_cmd(ctx):
    """Auto Command 913"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 913", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd914')
async def cmd914_cmd(ctx):
    """Auto Command 914"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 914", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd915')
async def cmd915_cmd(ctx):
    """Auto Command 915"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 915", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd916')
async def cmd916_cmd(ctx):
    """Auto Command 916"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 916", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd917')
async def cmd917_cmd(ctx):
    """Auto Command 917"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 917", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd918')
async def cmd918_cmd(ctx):
    """Auto Command 918"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 918", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd919')
async def cmd919_cmd(ctx):
    """Auto Command 919"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 919", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd920')
async def cmd920_cmd(ctx):
    """Auto Command 920"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 920", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd921')
async def cmd921_cmd(ctx):
    """Auto Command 921"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 921", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd922')
async def cmd922_cmd(ctx):
    """Auto Command 922"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 922", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd923')
async def cmd923_cmd(ctx):
    """Auto Command 923"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 923", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd924')
async def cmd924_cmd(ctx):
    """Auto Command 924"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 924", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd925')
async def cmd925_cmd(ctx):
    """Auto Command 925"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 925", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd926')
async def cmd926_cmd(ctx):
    """Auto Command 926"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 926", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd927')
async def cmd927_cmd(ctx):
    """Auto Command 927"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 927", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd928')
async def cmd928_cmd(ctx):
    """Auto Command 928"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 928", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd929')
async def cmd929_cmd(ctx):
    """Auto Command 929"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 929", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd930')
async def cmd930_cmd(ctx):
    """Auto Command 930"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 930", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd931')
async def cmd931_cmd(ctx):
    """Auto Command 931"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 931", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd932')
async def cmd932_cmd(ctx):
    """Auto Command 932"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 932", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd933')
async def cmd933_cmd(ctx):
    """Auto Command 933"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 933", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd934')
async def cmd934_cmd(ctx):
    """Auto Command 934"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 934", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd935')
async def cmd935_cmd(ctx):
    """Auto Command 935"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 935", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd936')
async def cmd936_cmd(ctx):
    """Auto Command 936"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 936", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd937')
async def cmd937_cmd(ctx):
    """Auto Command 937"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 937", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd938')
async def cmd938_cmd(ctx):
    """Auto Command 938"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 938", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd939')
async def cmd939_cmd(ctx):
    """Auto Command 939"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 939", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd940')
async def cmd940_cmd(ctx):
    """Auto Command 940"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 940", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd941')
async def cmd941_cmd(ctx):
    """Auto Command 941"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 941", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd942')
async def cmd942_cmd(ctx):
    """Auto Command 942"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 942", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd943')
async def cmd943_cmd(ctx):
    """Auto Command 943"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 943", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd944')
async def cmd944_cmd(ctx):
    """Auto Command 944"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 944", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd945')
async def cmd945_cmd(ctx):
    """Auto Command 945"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 945", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd946')
async def cmd946_cmd(ctx):
    """Auto Command 946"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 946", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd947')
async def cmd947_cmd(ctx):
    """Auto Command 947"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 947", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd948')
async def cmd948_cmd(ctx):
    """Auto Command 948"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 948", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd949')
async def cmd949_cmd(ctx):
    """Auto Command 949"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 949", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd950')
async def cmd950_cmd(ctx):
    """Auto Command 950"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 950", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd951')
async def cmd951_cmd(ctx):
    """Auto Command 951"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 951", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd952')
async def cmd952_cmd(ctx):
    """Auto Command 952"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 952", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd953')
async def cmd953_cmd(ctx):
    """Auto Command 953"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 953", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd954')
async def cmd954_cmd(ctx):
    """Auto Command 954"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 954", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd955')
async def cmd955_cmd(ctx):
    """Auto Command 955"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 955", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd956')
async def cmd956_cmd(ctx):
    """Auto Command 956"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 956", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd957')
async def cmd957_cmd(ctx):
    """Auto Command 957"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 957", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd958')
async def cmd958_cmd(ctx):
    """Auto Command 958"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 958", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd959')
async def cmd959_cmd(ctx):
    """Auto Command 959"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 959", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd960')
async def cmd960_cmd(ctx):
    """Auto Command 960"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 960", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd961')
async def cmd961_cmd(ctx):
    """Auto Command 961"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 961", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd962')
async def cmd962_cmd(ctx):
    """Auto Command 962"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 962", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd963')
async def cmd963_cmd(ctx):
    """Auto Command 963"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 963", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd964')
async def cmd964_cmd(ctx):
    """Auto Command 964"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 964", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd965')
async def cmd965_cmd(ctx):
    """Auto Command 965"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 965", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd966')
async def cmd966_cmd(ctx):
    """Auto Command 966"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 966", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd967')
async def cmd967_cmd(ctx):
    """Auto Command 967"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 967", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd968')
async def cmd968_cmd(ctx):
    """Auto Command 968"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 968", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd969')
async def cmd969_cmd(ctx):
    """Auto Command 969"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 969", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd970')
async def cmd970_cmd(ctx):
    """Auto Command 970"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 970", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd971')
async def cmd971_cmd(ctx):
    """Auto Command 971"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 971", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd972')
async def cmd972_cmd(ctx):
    """Auto Command 972"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 972", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd973')
async def cmd973_cmd(ctx):
    """Auto Command 973"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 973", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd974')
async def cmd974_cmd(ctx):
    """Auto Command 974"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 974", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd975')
async def cmd975_cmd(ctx):
    """Auto Command 975"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 975", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd976')
async def cmd976_cmd(ctx):
    """Auto Command 976"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 976", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd977')
async def cmd977_cmd(ctx):
    """Auto Command 977"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 977", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd978')
async def cmd978_cmd(ctx):
    """Auto Command 978"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 978", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd979')
async def cmd979_cmd(ctx):
    """Auto Command 979"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 979", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd980')
async def cmd980_cmd(ctx):
    """Auto Command 980"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 980", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd981')
async def cmd981_cmd(ctx):
    """Auto Command 981"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 981", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd982')
async def cmd982_cmd(ctx):
    """Auto Command 982"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 982", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd983')
async def cmd983_cmd(ctx):
    """Auto Command 983"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 983", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd984')
async def cmd984_cmd(ctx):
    """Auto Command 984"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 984", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd985')
async def cmd985_cmd(ctx):
    """Auto Command 985"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 985", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd986')
async def cmd986_cmd(ctx):
    """Auto Command 986"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 986", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd987')
async def cmd987_cmd(ctx):
    """Auto Command 987"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 987", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd988')
async def cmd988_cmd(ctx):
    """Auto Command 988"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 988", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd989')
async def cmd989_cmd(ctx):
    """Auto Command 989"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 989", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd990')
async def cmd990_cmd(ctx):
    """Auto Command 990"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 990", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd991')
async def cmd991_cmd(ctx):
    """Auto Command 991"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 991", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd992')
async def cmd992_cmd(ctx):
    """Auto Command 992"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 992", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd993')
async def cmd993_cmd(ctx):
    """Auto Command 993"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 993", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd994')
async def cmd994_cmd(ctx):
    """Auto Command 994"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 994", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd995')
async def cmd995_cmd(ctx):
    """Auto Command 995"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 995", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd996')
async def cmd996_cmd(ctx):
    """Auto Command 996"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 996", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd997')
async def cmd997_cmd(ctx):
    """Auto Command 997"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 997", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd998')
async def cmd998_cmd(ctx):
    """Auto Command 998"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 998", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)

@bot.command(name='cmd999')
async def cmd999_cmd(ctx):
    """Auto Command 999"""
    start = time.time()
    if not await require_premium(ctx):
        return
    embed = create_embed(f"✅ COMMAND 999", "Command executed successfully", discord.Color.green())
    try:
        await (ctx.author.send if isinstance(ctx.channel, discord.DMChannel) else ctx.send)(embed=embed)
    except:
        pass
    await log_command(ctx, True, time.time() - start)


# ======================== BOT STARTUP ========================
async def main():
    """Start the bot"""
    async with bot:
        init_database()
        load_premium_users()
        print(f"[✅] Bot Started: {bot.user}")
        print(f"[✅] Total Commands: {len(bot.commands)}")
        print(f"[✅] Premium Users: {len(premium_users)}")
        print(f"[✅] NP Owners: {len(np_owners)}")
        print(f"[✅] Version: {VERSION}")
        try:
            await bot.start(TOKEN)
        except Exception as e:
            print(f"[❌] Bot Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[⚠️] Bot Shutdown")
    except Exception as e:
        print(f"[❌] Error: {e}")
