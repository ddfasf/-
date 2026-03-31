import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import random

TOKEN = os.environ.get("TOKEN")
GUILD_ID = 1484915814187401259

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
player_message = {}
start_time = {}
current_track = {}
loading = {}

# 🎬 GIF 리스트 (앨범 느낌)
GIFS = [
    "https://media.giphy.com/media/13HgwGsXF0aiGY/giphy.gif",
    "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif",
    "https://media.giphy.com/media/xT9IgzoKnwFNmISR8I/giphy.gif"
]

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'default_search': 'ytsearch',
}

async def extract(query):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(None, run)

# ================= 기본 =================
def key(i):
    return f"{i.guild.id}_{i.channel.id}"

def bar(p):
    return "▰"*int(p*12)+"▱"*(12-int(p*12))

def lyrics_anim():
    return random.choice([
        "🌙 이 밤을 따라 흘러가...",
        "💫 너와 나의 멜로디...",
        "🔥 심장이 뛰는 순간...",
        "✨ 끝나지 않을 노래..."
    ])

# ================= SEEK =================
async def seek(i, percent):
    k = key(i)
    vc = i.guild.voice_client
    info = current_track.get(k)

    if not vc or not info:
        return

    dur = info.get("duration", 180)
    t = int(dur * percent)

    data = await extract(info['webpage_url'])

    source = discord.FFmpegPCMAudio(
        data['url'],
        before_options=f"-ss {t}"
    )

    vc.stop()
    vc.play(source)
    start_time[k] = time.time() - t

# ================= UI =================
class PlayerUI(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="⏯", style=discord.ButtonStyle.success, custom_id="toggle")
    async def toggle(self, i: discord.Interaction, b: discord.ui.Button):
        vc = i.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
        elif vc:
            vc.resume()
        await i.response.defer()

    @discord.ui.button(emoji="⏮️", custom_id="back")
    async def back(self, i: discord.Interaction, b):
        await seek(i, 0.1)
        await i.response.defer()

    @discord.ui.button(emoji="⏭️", custom_id="skip")
    async def skip(self, i: discord.Interaction, b):
        vc = i.guild.voice_client
        if vc:
            vc.stop()
        await i.response.defer()

    @discord.ui.button(label="-10%", custom_id="rewind")
    async def rewind(self, i: discord.Interaction, b):
        await seek(i, 0.1)
        await i.response.defer()

    @discord.ui.button(label="+10%", custom_id="forward")
    async def forward(self, i: discord.Interaction, b):
        await seek(i, 0.9)
        await i.response.defer()

    @discord.ui.select(
        placeholder="🎚 정밀 이동",
        custom_id="seek_select",
        options=[discord.SelectOption(label=f"{i*10}%", value=str(i/10)) for i in range(11)]
    )
    async def select_seek(self, i: discord.Interaction, select: discord.ui.Select):
        percent = float(select.values[0])
        await seek(i, percent)
        await i.response.defer()

# ================= 재생 =================
async def play_next(i):
    k = key(i)

    if not queues.get(k):
        return

    loading[k] = True

    info = queues[k].pop(0)
    current_track[k] = info

    vc = i.guild.voice_client
    data = await extract(info['webpage_url'])

    source = discord.FFmpegPCMAudio(data['url'])
    vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(i), client.loop))

    start_time[k] = time.time()
    loading[k] = False

    msg = await i.channel.send(
        embed=discord.Embed(title="🎧 재생 시작", description=info['title'], color=0x1DB954),
        view=PlayerUI()
    )

    player_message[k] = msg
    asyncio.create_task(update_ui(i, info))

# ================= UI 업데이트 =================
async def update_ui(i, info):
    k = key(i)
    dur = info.get("duration", 180)

    while k in start_time:
        el = int(time.time() - start_time[k])
        p = min(el/dur, 1)

        next_q = queues.get(k, [])
        next_text = "\n".join([f"• {q['title']}" for q in next_q[:3]]) or "없음"

        embed = discord.Embed(
            title="🎧 Spotify Player",
            description=(
                f"🎶 **{info['title']}**\n\n"
                f"{bar(p)}\n"
                f"⏱ {el}s / {dur}s\n\n"
                f"🎤 {lyrics_anim()}\n\n"
                f"📀 다음곡\n{next_text}"
            ),
            color=0x1DB954
        )

        # 🎬 GIF 적용
        embed.set_image(url=random.choice(GIFS))

        try:
            await player_message[k].edit(embed=embed, view=PlayerUI())
        except:
            pass

        await asyncio.sleep(1)

# ================= 검색 =================
class SearchModal(discord.ui.Modal, title="🎵 검색"):
    query = discord.ui.TextInput(label="노래")

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer()

        data = await extract(f"ytsearch5:{self.query}")
        results = data["entries"]

        embed = discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx, r in enumerate(results)]),
            color=0xFF0000
        )

        view = discord.ui.View()

        for idx, r in enumerate(results):
            btn = discord.ui.Button(label=f"{idx+1}번 재생")

            async def cb(interaction, r=r):
                k = key(interaction)
                queues.setdefault(k, []).append(r)

                if not interaction.guild.voice_client:
                    await interaction.user.voice.channel.connect()

                if not interaction.guild.voice_client.is_playing():
                    await play_next(interaction)

                await interaction.response.defer()

            btn.callback = cb
            view.add_item(btn)

        await i.followup.send(embed=embed, view=view)

# ================= 패널 =================
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎵 검색", style=discord.ButtonStyle.success, custom_id="panel_search")
    async def search(self, i: discord.Interaction, b):
        await i.response.send_modal(SearchModal())

# ================= 셋업 =================
@tree.command(name="셋업", guild=discord.Object(id=GUILD_ID))
async def setup(i: discord.Interaction):
    channel = await i.guild.create_text_channel("🎧-music-player")

    embed = discord.Embed(
        title="🎧 Spotify UI Player",
        description="🎬 GIF + 🎚 슬라이더 + 🎶 가사 + 📀 큐 시스템",
        color=0x1DB954
    )

    await channel.send(embed=embed, view=Panel())
    await i.response.send_message("✅ 완료", ephemeral=True)

# ================= 실행 =================
@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(PlayerUI())
    client.add_view(Panel())
    print("🔥 완전체 실행됨")

client.run(TOKEN)
