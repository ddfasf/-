import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import json

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
now_playing = {}
start_times = {}

# ================== 설정 ==================
SETTINGS_FILE = "settings.json"

def load_settings():
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)

settings = load_settings()

def get_settings(guild_id):
    return settings.setdefault(str(guild_id), {
        "volume": 100,
        "autoplay": False,
        "dj_role": None
    })

def is_dj(interaction):
    s = get_settings(interaction.guild.id)
    if s["dj_role"] is None:
        return True
    return any(role.id == s["dj_role"] for role in interaction.user.roles)

# ================== yt-dlp ==================
ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "http_headers": {"User-Agent": "Mozilla/5.0"},
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

async def extract(query):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(None, run)

# ================== UI ==================
def bar(cur, total, length=18):
    total = max(total, 1)
    filled = int(length * cur / total)
    return "▰"*filled + "▱"*(length-filled)

async def update_progress(msg, interaction):
    k = interaction.guild.id
    while k in now_playing:
        song = now_playing[k]
        elapsed = int(time.time() - start_times[k])
        dur = song.get("duration", 180)

        embed = discord.Embed(
            title="🎧 NOW PLAYING",
            description=f"{song['title']}\n\n{bar(elapsed,dur)}\n{elapsed}s/{dur}s",
            color=0x5865F2
        )
        try:
            await msg.edit(embed=embed)
        except:
            break
        await asyncio.sleep(2)

class Player(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.success)
    async def pause(self, i, b):
        vc = i.guild.voice_client
        if not is_dj(i):
            return await i.response.send_message("❌ DJ만 가능", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            b.label="▶️"
        else:
            vc.resume()
            b.label="⏸"
        await i.response.edit_message(view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.primary)
    async def skip(self, i, b):
        if not is_dj(i):
            return await i.response.send_message("❌ DJ만 가능", ephemeral=True)

        i.guild.voice_client.stop()
        await i.response.defer()

# ================== 재생 ==================
async def play_next(interaction):
    k = interaction.guild.id
    vc = interaction.guild.voice_client

    if not queues.get(k):
        return

    song = queues[k].pop(0)
    now_playing[k] = song
    start_times[k] = time.time()

    s = get_settings(k)

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(song["url"], executable="ffmpeg"),
        volume=s["volume"]/100
    )

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop)
        try: fut.result()
        except: pass

    vc.play(source, after=after)

    embed = discord.Embed(title="🎧 NOW PLAYING", description=song["title"])
    msg = await interaction.channel.send(embed=embed, view=Player())
    client.loop.create_task(update_progress(msg, interaction))

# ================== 검색 ==================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer()

        data = await extract(f"ytsearch5:{self.query}")
        results = data["entries"]

        view = discord.ui.View(timeout=None)

        for r in results:
            btn = discord.ui.Button(label=r["title"][:20])

            async def cb(inter, r=r):
                await inter.response.defer()

                if not inter.user.voice:
                    return await inter.followup.send("❌ 음성채널 들어가", ephemeral=True)

                k = inter.guild.id
                queues.setdefault(k, []).append(r)

                vc = inter.guild.voice_client
                if not vc:
                    vc = await inter.user.voice.channel.connect()

                if not vc.is_playing():
                    await play_next(inter)

                await inter.followup.send(f"✅ 추가: {r['title']}", ephemeral=True)

            btn.callback = cb
            view.add_item(btn)

        await i.followup.send("🎬 결과", view=view)

# ================== 패널 ==================
class Panel(discord.ui.View):
    @discord.ui.button(label="🎵 검색")
    async def search(self, i, b):
        await i.response.send_modal(Search())

# ================== 명령어 ==================
@tree.command(name="panel")
async def panel(i: discord.Interaction):
    await i.response.send_message("🎧 패널", view=Panel())

# 🔥 sync
@tree.command(name="sync")
async def sync_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ 관리자만", ephemeral=True)

    tree.clear_commands(guild=i.guild)
    await tree.sync(guild=i.guild)
    await i.response.send_message("✅ 동기화 완료", ephemeral=True)

# ⚙ 설정
@tree.command(name="config")
async def config(i: discord.Interaction, volume:int, autoplay:bool):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ 관리자만", ephemeral=True)

    settings[str(i.guild.id)] = {
        "volume": volume,
        "autoplay": autoplay,
        "dj_role": get_settings(i.guild.id)["dj_role"]
    }
    save_settings(settings)

    await i.response.send_message("✅ 저장됨", ephemeral=True)

# 🎧 DJ 설정
@tree.command(name="setdj")
async def setdj(i: discord.Interaction, role: discord.Role):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ 관리자만", ephemeral=True)

    s = get_settings(i.guild.id)
    s["dj_role"] = role.id
    save_settings(settings)

    await i.response.send_message(f"✅ DJ 역할: {role.name}", ephemeral=True)

# ================== 실행 ==================
@client.event
async def on_ready():
    print("🔥 서비스급 봇 실행됨")

client.run(os.environ.get("TOKEN"))
