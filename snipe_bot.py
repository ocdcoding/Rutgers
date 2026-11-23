"""
Rutgers Snipe Bot (Discord)
---------------------------
Slash commands in your Discord server:
  /snipe 12345          watch a section (several: /snipe 12345 67890)
  /unsnipe 12345        stop watching a section
  /list                 your watched sections + open/closed status
  /clear                remove all your watched sections
  /status               bot health, last check time, semester

Checks Rutgers every few seconds. When a section you watch opens, it DMs you
with a one-click WebReg button (and pings the alert channel if you set one).

Setup: see README_BOT.md.  Run:  python snipe_bot.py
"""

import asyncio
import json
import os
import time
from datetime import datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

# ============================ SETTINGS ============================

TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"   # keep this secret

YEAR = 2027          # semester year
TERM = 1             # 1 = Spring, 7 = Summer, 9 = Fall, 0 = Winter
CAMPUS = "NB"        # NB = New Brunswick, NK = Newark, CM = Camden

POLL_SECONDS = 5     # how often to check Rutgers. Don't go below 3.

# Optional: a channel ID to also post alerts in (0 = DMs only).
# Right-click a channel -> Copy Channel ID (turn on Developer Mode first).
ALERT_CHANNEL_ID = 0

# ==================================================================

BASE = "https://classes.rutgers.edu/soc/api"
QUERY = f"year={YEAR}&term={TERM}&campus={CAMPUS}"
SEMESTER_CODE = f"{TERM}{YEAR}"
TERM_NAMES = {1: "Spring", 7: "Summer", 9: "Fall", 0: "Winter"}
HEADERS = {"User-Agent": "rutgers-snipe-bot (personal use)"}
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")


def now():
    return datetime.now().strftime("%H:%M:%S")


def webreg_link(idx):
    return ("https://sims.rutgers.edu/webreg/editSchedule.htm?login=cas"
            f"&semesterSelection={SEMESTER_CODE}&indexList={idx}")


class SnipeBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.session = None
        self.watches = {}          # index -> set of user ids
        self.notified = set()      # (index, user_id) already alerted while open
        self.open_now = set()
        self.names = {}            # index -> "Course Title (01:198:111) sec 05"
        self.last_ok = None
        self.last_ms = None
        self.fail_streak = 0
        self.load()

    # ---------- storage ----------
    def load(self):
        try:
            raw = json.load(open(DATA_FILE))
            self.watches = {k: set(v) for k, v in raw.items() if v}
        except Exception:
            self.watches = {}

    def save(self):
        with open(DATA_FILE, "w") as f:
            json.dump({k: sorted(v) for k, v in self.watches.items() if v}, f, indent=1)

    def user_indexes(self, uid):
        return sorted(i for i, users in self.watches.items() if uid in users)

    # ---------- Rutgers ----------
    async def get_json(self, path):
        async with self.session.get(f"{BASE}/{path}?{QUERY}") as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def refresh_names(self):
        try:
            names = {}
            for c in await self.get_json("courses.json"):
                for s in c.get("sections", []):
                    if s.get("index"):
                        names[s["index"]] = (f"{c.get('title', '').title()} "
                                             f"({c.get('courseString', '')}) sec {s.get('number', '')}")
            if names:
                self.names = names
                print(f"[{now()}] loaded {len(names)} sections for {SEMESTER_CODE} {CAMPUS}")
        except Exception as e:
            print(f"[{now()}] couldn't load course names: {e}")

    # ---------- lifecycle ----------
    async def setup_hook(self):
        self.session = aiohttp.ClientSession(headers=HEADERS,
                                             timeout=aiohttp.ClientTimeout(total=20))
        await self.refresh_names()
        self.poll.start()
        self.names_loop.start()

    async def on_ready(self):
        for g in self.guilds:           # instant slash commands in every server the bot is in
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
        print(f"[{now()}] logged in as {self.user} | watching {len(self.watches)} section(s)")

    async def on_guild_join(self, guild):
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    # ---------- loops ----------
    @tasks.loop(hours=6)
    async def names_loop(self):
        if self.names_loop.current_loop:   # skip the first run (already loaded)
            await self.refresh_names()

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        if not self.watches:
            return
        t0 = time.perf_counter()
        try:
            open_all = set(await self.get_json("openSections.json"))
        except Exception as e:
            self.fail_streak += 1
            if self.fail_streak in (1, 5) or self.fail_streak % 60 == 0:
                print(f"[{now()}] check failed ({self.fail_streak}x): {e}")
            return
        self.fail_streak = 0
        self.last_ok = time.time()
        self.last_ms = int((time.perf_counter() - t0) * 1000)
        self.open_now = open_all

        # closed again -> allow a fresh alert next time it opens
        self.notified = {(i, u) for (i, u) in self.notified if i in open_all}

        for idx, users in list(self.watches.items()):
            if idx not in open_all:
                continue
            for uid in list(users):
                if (idx, uid) not in self.notified:
                    self.notified.add((idx, uid))
                    asyncio.create_task(self.alert(idx, uid))

    @poll.before_loop
    async def before_poll(self):
        await self.wait_until_ready()

    # ---------- alerts ----------
    async def alert(self, idx, uid):
        label = self.names.get(idx, f"Index {idx}")
        embed = discord.Embed(title="Section OPEN", description=f"**{label}**\nIndex **{idx}**",
                              color=0x2ECC71)
        embed.set_footer(text=f"{TERM_NAMES.get(TERM, TERM)} {YEAR} · {CAMPUS} · {now()}")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Register on WebReg", url=webreg_link(idx)))
        print(f"[{now()}] OPEN {idx} -> alerting {uid}")
        dm_ok = False
        try:
            user = self.get_user(uid) or await self.fetch_user(uid)
            await user.send(embed=embed, view=view)
            dm_ok = True
        except Exception as e:
            print(f"[{now()}] DM to {uid} failed: {e}")
        if ALERT_CHANNEL_ID:
            try:
                ch = self.get_channel(ALERT_CHANNEL_ID) or await self.fetch_channel(ALERT_CHANNEL_ID)
                note = "" if dm_ok else " (couldn't DM you — check your privacy settings)"
                await ch.send(f"<@{uid}>{note}", embed=embed, view=view)
            except Exception as e:
                print(f"[{now()}] channel alert failed: {e}")


bot = SnipeBot()


def parse_indexes(text):
    parts = text.replace(",", " ").split()
    good = [p.zfill(5) for p in parts if p.isdigit() and len(p) <= 5]
    bad = [p for p in parts if not (p.isdigit() and len(p) <= 5)]
    return good, bad


@bot.tree.command(description="Watch one or more section index numbers (e.g. 12345 67890)")
@app_commands.describe(indexes="5-digit index numbers, separated by spaces")
async def snipe(interaction: discord.Interaction, indexes: str):
    good, bad = parse_indexes(indexes)
    uid = interaction.user.id
    added, unknown = [], []
    for idx in good:
        if bot.names and idx not in bot.names:
            unknown.append(idx)
            continue
        bot.watches.setdefault(idx, set()).add(uid)
        added.append(idx)
    bot.save()
    lines = []
    for idx in added:
        state = "OPEN now — alert coming" if idx in bot.open_now else "closed, watching"
        lines.append(f"`{idx}` {bot.names.get(idx, '')} — {state}")
    if unknown:
        lines.append(f"Not found for {TERM_NAMES.get(TERM)} {YEAR} {CAMPUS}: {', '.join(unknown)}")
    if bad:
        lines.append(f"Ignored (not index numbers): {', '.join(bad)}")
    await interaction.response.send_message("\n".join(lines) or "Nothing added.", ephemeral=True)


@bot.tree.command(description="Stop watching one or more sections")
@app_commands.describe(indexes="5-digit index numbers, separated by spaces")
async def unsnipe(interaction: discord.Interaction, indexes: str):
    good, _ = parse_indexes(indexes)
    uid = interaction.user.id
    removed = []
    for idx in good:
        if uid in bot.watches.get(idx, set()):
            bot.watches[idx].discard(uid)
            bot.notified.discard((idx, uid))
            removed.append(idx)
            if not bot.watches[idx]:
                del bot.watches[idx]
    bot.save()
    msg = f"Stopped watching: {', '.join(removed)}" if removed else "You weren't watching those."
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="list", description="Show the sections you're watching")
async def list_cmd(interaction: discord.Interaction):
    mine = bot.user_indexes(interaction.user.id)
    if not mine:
        await interaction.response.send_message("You're not watching anything. Use `/snipe 12345`.",
                                                ephemeral=True)
        return
    lines = [f"{'🟢 OPEN' if i in bot.open_now else '🔴 closed'}  `{i}`  {bot.names.get(i, '')}"
             for i in mine]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(description="Remove all the sections you're watching")
async def clear(interaction: discord.Interaction):
    uid = interaction.user.id
    mine = bot.user_indexes(uid)
    for idx in mine:
        bot.watches[idx].discard(uid)
        bot.notified.discard((idx, uid))
        if not bot.watches[idx]:
            del bot.watches[idx]
    bot.save()
    await interaction.response.send_message(f"Cleared {len(mine)} section(s).", ephemeral=True)


@bot.tree.command(description="Bot health and last Rutgers check")
async def status(interaction: discord.Interaction):
    if bot.last_ok:
        ago = int(time.time() - bot.last_ok)
        last = f"{ago}s ago ({bot.last_ms} ms)"
    else:
        last = "not yet (nothing watched, or still starting)"
    msg = (f"Semester: **{TERM_NAMES.get(TERM, TERM)} {YEAR}** · {CAMPUS}\n"
           f"Checking every **{POLL_SECONDS}s** · last check: {last}\n"
           f"Sections watched (all users): {len(bot.watches)} · course names loaded: {len(bot.names)}")
    if bot.fail_streak:
        msg += f"\n⚠️ Last {bot.fail_streak} check(s) failed — see the bot window."
    await interaction.response.send_message(msg, ephemeral=True)


if __name__ == "__main__":
    bot.run(TOKEN)
