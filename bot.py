
import os
import math
import random
import time
import io

import aiohttp
import discord
import aiosqlite

from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont

# ==============================
# SIAMUUU BOT CONFIGURATION
# ==============================

load_dotenv()

# Secure Discord Bot Token
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

if not TOKEN:
    raise ValueError(
        "Discord token not found! "
        "Please add DISCORD_TOKEN in your .env file."
    )

DATABASE = "siamuu_xp.db"

MESSAGE_XP_MIN = 5
MESSAGE_XP_MAX = 15
MESSAGE_COOLDOWN = 30

VOICE_XP_PER_MINUTE = 5
DAILY_XP = 50

LEVEL_UP_CHANNEL_ID = 1344642255415279656

ROLE_REWARDS = {
    5: 1572305312248111134,       # Bronze
    10: 1572305712309207040,      # Silver
    20: 1572306206012346448,      # Gold
    50: 1572306274924757002,      # Diamond
    100: 1572306323247206490      # Netherite
}

# ==============================
# BOT SETUP
# ==============================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

db = None


# ==============================
# DATABASE
# ==============================

async def setup_database():
    global db

    if db is None:
        db = await aiosqlite.connect(DATABASE)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                guild_id INTEGER,
                user_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                last_message REAL DEFAULT 0,
                last_daily REAL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        await db.commit()


async def get_user(guild_id, user_id):
    await setup_database()

    async with db.execute("""
        SELECT xp, level, last_message, last_daily
        FROM users
        WHERE guild_id=? AND user_id=?
    """, (guild_id, user_id)) as cursor:
        row = await cursor.fetchone()

    if row is None:
        await db.execute("""
            INSERT INTO users (guild_id, user_id)
            VALUES (?, ?)
        """, (guild_id, user_id))

        await db.commit()

        return (0, 0, 0, 0)

    return row


async def get_user_rank(guild_id, user_id):
    await setup_database()

    async with db.execute("""
        SELECT user_id FROM users
        WHERE guild_id=?
        ORDER BY xp DESC
    """, (guild_id,)) as cursor:
        rows = await cursor.fetchall()

    for index, row in enumerate(rows, start=1):
        if row[0] == user_id:
            return index

    return len(rows)


# ==============================
# LEVEL SYSTEM
# ==============================

def calculate_level(xp):
    return int(math.sqrt(xp / 100))


def xp_for_next_level(level):
    return 100 * ((level + 1) ** 2)


# ==============================
# AUTOMATIC RANK ROLES
# ==============================

async def update_rank_role(member, level):
    if member.bot:
        return

    eligible_levels = [
        lvl for lvl in ROLE_REWARDS
        if level >= lvl
    ]

    if not eligible_levels:
        return

    highest_level = max(eligible_levels)
    correct_role_id = ROLE_REWARDS[highest_level]

    correct_role = member.guild.get_role(correct_role_id)

    if correct_role is None:
        print(f"Rank role not found: {correct_role_id}")
        return

    all_reward_roles = []

    for role_id in ROLE_REWARDS.values():
        role = member.guild.get_role(role_id)

        if role:
            all_reward_roles.append(role)

    roles_to_remove = [
        role for role in all_reward_roles
        if role in member.roles and role.id != correct_role_id
    ]

    try:
        if roles_to_remove:
            await member.remove_roles(
                *roles_to_remove,
                reason="Automatic XP rank upgrade"
            )

        if correct_role not in member.roles:
            await member.add_roles(
                correct_role,
                reason=f"Reached level {highest_level}"
            )

    except discord.Forbidden:
        print("ERROR: Bot does not have permission to manage rank roles.")

    except discord.HTTPException as e:
        print(f"Role update error: {e}")


# ==============================
# LEVEL-UP PNG CARD
# ==============================

async def generate_level_up_card(
    member,
    old_level,
    new_level,
    rank_num,
    current_xp
):
    width, height = 750, 210

    card = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(card)

    radius = 30

    draw.rounded_rectangle(
        [(2, 2), (width - 3, height - 3)],
        radius,
        fill=(15, 15, 22, 255)
    )

    draw.rounded_rectangle(
        [(2, 2), (width - 3, height - 3)],
        radius,
        outline=(0, 180, 255, 120),
        width=2
    )

    avatar_url = member.display_avatar.replace(
        size=128,
        format="png"
    ).url

    avatar_img = None

    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(avatar_url) as resp:
                if resp.status == 200:
                    avatar_bytes = await resp.read()

                    avatar_img = Image.open(
                        io.BytesIO(avatar_bytes)
                    ).convert("RGBA")

    except Exception as e:
        print(f"Avatar error: {e}")

    if avatar_img:
        avatar_img = avatar_img.resize(
            (130, 130),
            Image.Resampling.LANCZOS
        )

        mask = Image.new("L", (130, 130), 0)

        mask_draw = ImageDraw.Draw(mask)

        mask_draw.ellipse(
            (0, 0, 130, 130),
            fill=255
        )

        card.paste(
            avatar_img,
            (35, 40),
            mask
        )

        draw.ellipse(
            (33, 38, 166, 172),
            outline=(0, 162, 255),
            width=4
        )

    try:
        font_title = ImageFont.truetype("arial.ttf", 32)
        font_name = ImageFont.truetype("arial.ttf", 22)
        font_med = ImageFont.truetype("arial.ttf", 24)
        font_bold = ImageFont.truetype("arialbd.ttf", 42)

    except IOError:
        font_title = ImageFont.load_default()
        font_name = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    username = member.display_name

    if len(username) > 15:
        username = username[:15] + "..."

    draw.text(
        (185, 38),
        "LEVEL UP!",
        fill=(0, 220, 255),
        font=font_title
    )

    draw.text(
        (185, 80),
        username,
        fill=(200, 200, 210),
        font=font_name
    )

    # Level Box
    draw.rounded_rectangle(
        [(430, 25), (600, 115)],
        20,
        fill=(25, 25, 35, 255)
    )

    draw.text(
        (445, 48),
        str(old_level),
        fill=(130, 130, 140),
        font=font_bold
    )

    draw.text(
        (495, 52),
        "->",
        fill=(0, 162, 255),
        font=font_med
    )

    draw.text(
        (535, 42),
        str(new_level),
        fill=(0, 255, 120),
        font=font_bold
    )

    # Rank Box
    draw.rounded_rectangle(
        [(615, 25), (725, 115)],
        20,
        fill=(35, 25, 45, 255)
    )

    draw.text(
        (638, 42),
        f"#{rank_num}",
        fill=(255, 180, 0),
        font=font_bold
    )

    # Progress Bar
    bar_x, bar_y = 185, 145
    bar_w, bar_h = 530, 18

    draw.rounded_rectangle(
        [(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)],
        9,
        fill=(30, 30, 40, 255)
    )

    curr_lvl_xp = 100 * (new_level ** 2)
    next_lvl_xp = xp_for_next_level(new_level)

    needed = next_lvl_xp - curr_lvl_xp
    gained = current_xp - curr_lvl_xp

    pct = max(
        0.0,
        min(1.0, gained / needed if needed > 0 else 1.0)
    )

    filled_w = int(bar_w * pct)

    if filled_w > 0:
        draw.rounded_rectangle(
            [(bar_x, bar_y), (bar_x + filled_w, bar_y + bar_h)],
            9,
            fill=(0, 162, 255, 255)
        )

    draw.text(
        (185, 175),
        f"Total XP: {current_xp:,}",
        fill=(150, 150, 160),
        font=font_name
    )

    buffer = io.BytesIO()

    card.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


# ==============================
# AWARD XP
# ==============================

async def award_xp(member, amount):
    if member.bot or member.guild is None:
        return None

    await setup_database()

    old_xp, old_level, last_message, last_daily = await get_user(
        member.guild.id,
        member.id
    )

    new_xp = old_xp + amount
    new_level = calculate_level(new_xp)

    await db.execute("""
        UPDATE users
        SET xp=?, level=?
        WHERE guild_id=? AND user_id=?
    """, (
        new_xp,
        new_level,
        member.guild.id,
        member.id
    ))

    await db.commit()

    # Always check the highest eligible rank.
    await update_rank_role(member, new_level)

    if new_level > old_level:
        channel = member.guild.get_channel(
            LEVEL_UP_CHANNEL_ID
        )

        if channel:
            try:
                rank_num = await get_user_rank(
                    member.guild.id,
                    member.id
                )

                card_buffer = await generate_level_up_card(
                    member,
                    old_level,
                    new_level,
                    rank_num,
                    new_xp
                )

                file = discord.File(
                    card_buffer,
                    filename="levelup.png"
                )

                await channel.send(
                    content=f"🎉 Congratulations {member.mention}!",
                    file=file
                )

            except Exception as e:
                print(f"Level-up announcement error: {e}")

    return new_xp, new_level


# ==============================
# MESSAGE XP
# ==============================

@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    await setup_database()

    user_data = await get_user(
        message.guild.id,
        message.author.id
    )

    last_message = user_data[2]
    current_time = time.time()

    if current_time - last_message >= MESSAGE_COOLDOWN:

        amount = random.randint(
            MESSAGE_XP_MIN,
            MESSAGE_XP_MAX
        )

        await db.execute("""
            UPDATE users
            SET last_message=?
            WHERE guild_id=? AND user_id=?
        """, (
            current_time,
            message.guild.id,
            message.author.id
        ))

        await db.commit()

        await award_xp(
            message.author,
            amount
        )

    await bot.process_commands(message)


# ==============================
# VOICE XP
# ==============================

@tasks.loop(minutes=1)
async def voice_xp_loop():

    for guild in bot.guilds:

        for channel in guild.voice_channels:

            for member in channel.members:

                if member.bot:
                    continue

                if member.voice is None:
                    continue

                if member.voice.self_deaf or member.voice.deaf:
                    continue

                if member.voice.self_mute or member.voice.mute:
                    continue

                if channel.id in [
                    member.guild.afk_channel.id
                    if member.guild.afk_channel else None
                ]:
                    continue

                await award_xp(
                    member,
                    VOICE_XP_PER_MINUTE
                )


@voice_xp_loop.before_loop
async def before_voice_xp():
    await bot.wait_until_ready()


# ==============================
# AUTOMATIC DAILY XP
# ==============================

@tasks.loop(hours=1)
async def automatic_daily_xp():

    await setup_database()

    current_time = time.time()

    for guild in bot.guilds:

        async with db.execute("""
            SELECT user_id, last_message, last_daily
            FROM users
            WHERE guild_id=?
        """, (guild.id,)) as cursor:

            users = await cursor.fetchall()

        for user_id, last_message, last_daily in users:

            if current_time - last_message > 86400:
                continue

            if current_time - last_daily < 86400:
                continue

            member = guild.get_member(user_id)

            if member is None or member.bot:
                continue

            await db.execute("""
                UPDATE users
                SET last_daily=?
                WHERE guild_id=? AND user_id=?
            """, (
                current_time,
                guild.id,
                user_id
            ))

            await db.commit()

            await award_xp(
                member,
                DAILY_XP
            )

            print(
                f"Automatic daily XP: "
                f"{member.name} received {DAILY_XP} XP"
            )


@automatic_daily_xp.before_loop
async def before_automatic_daily_xp():
    await bot.wait_until_ready()


# ==============================
# RANK COMMAND
# ==============================

@bot.tree.command(
    name="rank",
    description="Check your XP and level"
)
@app_commands.describe(
    member="Member whose rank you want to see"
)
async def rank(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    member = member or interaction.user

    xp, level, _, _ = await get_user(
        interaction.guild.id,
        member.id
    )

    next_level_xp = xp_for_next_level(level)
    current_level_xp = 100 * (level ** 2)

    progress = xp - current_level_xp
    required = next_level_xp - current_level_xp

    percentage = min(
        100,
        int(progress / required * 100)
    ) if required > 0 else 100

    filled = min(
        10,
        int(percentage / 10)
    )

    progress_bar = (
        "🟩" * filled +
        "⬛" * (10 - filled)
    )

    embed = discord.Embed(
        title="🏆 SIAMUUU RANK",
        color=discord.Color.dark_grey()
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    embed.add_field(
        name="Member",
        value=member.mention,
        inline=False
    )

    embed.add_field(
        name="Level",
        value=f"**{level}**",
        inline=True
    )

    embed.add_field(
        name="Total XP",
        value=f"**{xp:,}**",
        inline=True
    )

    embed.add_field(
        name="Progress",
        value=(
            f"{progress_bar}\n"
            f"{progress:,} / {required:,} XP ({percentage}%)"
        ),
        inline=False
    )

    embed.set_footer(
        text="SIAMUUU XP SYSTEM"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ==============================
# LEADERBOARD COMMAND
# ==============================

@bot.tree.command(
    name="leaderboard",
    description="See the server XP leaderboard"
)
async def leaderboard(interaction: discord.Interaction):

    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    await setup_database()

    async with db.execute("""
        SELECT user_id, xp, level
        FROM users
        WHERE guild_id=?
        ORDER BY xp DESC
        LIMIT 10
    """, (interaction.guild.id,)) as cursor:

        rows = await cursor.fetchall()

    if not rows:
        await interaction.response.send_message(
            "No XP data available yet!"
        )
        return

    description = ""

    for position, row in enumerate(rows, start=1):

        user_id, xp, level = row

        member = interaction.guild.get_member(user_id)

        username = (
            member.display_name
            if member else f"Unknown User ({user_id})"
        )

        description += (
            f"**#{position}** {username} — "
            f"Level **{level}** · **{xp:,} XP**\n"
        )

    embed = discord.Embed(
        title="🏆 SIAMUUU LEADERBOARD",
        description=description,
        color=discord.Color.gold()
    )

    embed.set_footer(
        text="Top 10 XP Members"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ==============================
# GIVE XP COMMAND (ADMIN ONLY)
# ==============================

@bot.tree.command(
    name="givexp",
    description="Give XP to a member (Admin Only)"
)
@app_commands.describe(
    member="The member to give XP to",
    amount="Amount of XP to give"
)
@app_commands.default_permissions(
    administrator=True
)
async def givexp(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: int
):

    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission!",
            ephemeral=True
        )
        return

    if amount <= 0:
        await interaction.response.send_message(
            "Please specify a positive XP amount!",
            ephemeral=True
        )
        return

    result = await award_xp(
        member,
        amount
    )

    if result is None:
        await interaction.response.send_message(
            "Could not give XP to this member.",
            ephemeral=True
        )
        return

    new_xp, new_level = result

    embed = discord.Embed(
        title="✨ XP ADDED SUCCESSFULLY",
        description=(
            f"Successfully gave **{amount:,} XP** "
            f"to {member.mention}!\n\n"
            f"• **New Total XP:** {new_xp:,}\n"
            f"• **Current Level:** {new_level}"
        ),
        color=discord.Color.green()
    )

    embed.set_footer(
        text="SIAMUUU XP SYSTEM"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ==============================
# TEST LEVEL CARD (ADMIN ONLY)
# ==============================

@bot.tree.command(
    name="testlevelcard",
    description="Preview the level-up announcement card"
)
@app_commands.describe(
    old_level="The previous level number",
    new_level="The new level number",
    member="Optional member to preview with"
)
@app_commands.default_permissions(
    administrator=True
)
async def testlevelcard(
    interaction: discord.Interaction,
    old_level: int,
    new_level: int,
    member: discord.Member = None
):

    if interaction.guild is None:
        await interaction.response.send_message(
            "Use this command inside a server.",
            ephemeral=True
        )
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ You do not have permission!",
            ephemeral=True
        )
        return

    if old_level < 0 or new_level <= old_level:
        await interaction.response.send_message(
            "New level must be higher than old level.",
            ephemeral=True
        )
        return

    target_member = member or interaction.user

    rank_num = await get_user_rank(
        interaction.guild.id,
        target_member.id
    )

    xp, _, _, _ = await get_user(
        interaction.guild.id,
        target_member.id
    )

    card_buffer = await generate_level_up_card(
        target_member,
        old_level,
        new_level,
        rank_num,
        xp
    )

    file = discord.File(
        card_buffer,
        filename="levelup.png"
    )

    await interaction.response.send_message(
        content=(
            f"🧪 **Enhanced Level-up Card Preview** "
            f"for {target_member.mention}:"
        ),
        file=file
    )


# ==============================
# BOT READY
# ==============================

@bot.event
async def on_ready():

    await setup_database()

    for guild in bot.guilds:

        try:
            bot.tree.copy_global_to(
                guild=guild
            )

            await bot.tree.sync(
                guild=guild
            )

            print(
                f"✅ Synced commands for guild: {guild.name}"
            )

        except Exception as e:
            print(
                f"❌ Failed to sync for {guild.name}: {e}"
            )

    if not voice_xp_loop.is_running():
        voice_xp_loop.start()

    if not automatic_daily_xp.is_running():
        automatic_daily_xp.start()

    print("=" * 40)
    print("SIAMUUU BOT IS ONLINE!")
    print(f"Bot: {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print("XP System: ACTIVE")
    print("=" * 40)


# ==============================
# START BOT
# ==============================

bot.run(TOKEN)