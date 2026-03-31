import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import random

TOKEN = os.environ.get("TOKEN")
GUILD_ID = 1484915814187401259
FFMPEG_PATH = "ffmpeg"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
player_message = {}
panel_message = {}
start_time = {}
current_track = {}

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'cookiefile': 'cookies.txt',
    'ignoreerrors': True,
    'nocheckcertificate': True,
}

async def safe_extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(q, download=False)
    try:
        return await loop.run_in_executor(None, run)
    except:
        return None

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def progress_bar(p):
    return "▰"*int(p*14)+"▱"*(14-int(p*14))

# ================= 가사 =================
lyrics_pool = [
    "🌙 이 밤을 따라 흘러가",
    "💫 너와 나의 멜로디",
    "🔥 심장이 뛰는 순간",
    "✨ 끝나지 않을 노래"
]

async def animated_lyrics():
    line = random.choice(lyrics_pool)
    text = ""
    for c in line:
        text += c
        yield text
        await asyncio.sleep(0.04)

# ================= UI =================
async def hide_panel(i):
    key = get_key(i)
    if key in panel_message:
        try:
            await panel_message[key].delete()
        except:
            pass

async def show_panel(i):
    key = get_key(i)

    embed = discord.Embed(
        title="🎧 Spotify Ultra UI",
        description="""
🔥 자동 음악 시스템
🎶 AI 추천 + 대기열
🎚 실시간 컨트롤

👇 아래 버튼 클릭
""",
        color=0x1DB954
    )

    embed.set_image(url="https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif")

    msg = await i.channel.send(embed=embed, view=PanelView())
    panel_message[key] = msg

# ================= SEEK =================
async def seek_to(i, percent):
    key = get_key(i)
    vc = i.guild.voice_client

    if not vc or key not in current_track:
        return

    info = current_track[key]
    dur = info.get("duration", 180)
    t = int(dur * percent)

    data = await safe_extract(info['webpage_url'])
    if not data:
        return

    vc.stop()

    src = discord.FFmpegPCMAudio(
        data['url'],
        executable=FFMPEG_PATH,
        before_options=f"-ss {t}"
    )
    vc.play(discord.PCMVolumeTransformer(src, volume=0.7))

    start_time[key] = time.time() - t

# ================= 컨트롤 =================
class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        controls = [
            ("⏯️", self.toggle),
            ("⏭️", self.skip),
            ("⏮️", self.back),
        ]

        for e, cb in controls:
            b = discord.ui.Button(emoji=e)
            b.callback = self.loading_wrapper(cb)
            self.add_item(b)

        # 🎚 슬라이더 버튼
        for i in range(0, 101, 20):
            b = discord.ui.Button(label=f"{i}%")
            b.callback = self.seek_wrapper(i/100)
            self.add_item(b)

    def loading_wrapper(self, func):
        async def wrapper(i):
            await i.response.defer()
            await func(i)
        return wrapper

    def seek_wrapper(self, val):
        async def wrapper(i):
            await i.response.defer()
            await seek_to(i, val)
        return wrapper

    async def toggle(self, i):
        vc = i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()

    async def skip(self, i):
        i.guild.voice_client.stop()

    async def back(self, i):
        await seek_to(i, 0.1)

# ================= 음악 =================
async def play_next(i):
    key = get_key(i)

    if not queues.get(key):
        await show_panel(i)
        return

    info = queues[key].pop(0)
    current_track[key] = info

    vc = i.guild.voice_client
    data = await safe_extract(info['webpage_url'])

    if not data:
        return await play_next(i)

    src = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'], executable=FFMPEG_PATH),
        volume=0.7
    )

    vc.play(src, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(i), client.loop))

    start_time[key] = time.time()

    await hide_panel(i)

    msg = await i.channel.send("⏳ 로딩중...")
    player_message[key] = msg

    asyncio.create_task(update_ui(i, info))

# ================= UI 업데이트 =================
async def update_ui(i, info):
    key = get_key(i)
    dur = info.get("duration", 180)

    emojis = ["🎧", "🎶", "🔥"]
    idx = 0

    async for lyric in animated_lyrics():
        vc = i.guild.voice_client
        if not vc or not vc.is_playing():
            break

        elapsed = int(time.time() - start_time[key])
        p = min(elapsed / dur, 1)

        queue_preview = "\n".join([
            f"▶ {x['title'][:30]}" for x in queues.get(key, [])[:2]
        ]) or "없음"

        embed = discord.Embed(
            title=f"{emojis[idx%3]} Now Playing",
            description=f"""
🎶 **{info['title']}**

{progress_bar(p)}
⏱ {elapsed}s / {dur}s

🎤 {lyric}

📀 다음곡
{queue_preview}
""",
            color=0x1DB954
        )

        embed.set_image(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed, view=ControlView())
        except:
            pass

        idx += 1
        await asyncio.sleep(0.4)

# ================= 검색 =================
class SearchModal(discord.ui.Modal, title="🎵 검색"):
    query = discord.ui.TextInput(label="노래")

    async def on_submit(self, i):
        await i.response.defer()

        data = await safe_extract(f"ytsearch5:{self.query}")
        if not data:
            return await i.followup.send("❌ 검색 실패")

        results = data["entries"]

        embed = discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx, r in enumerate(results)]),
            color=0x5865F2
        )
        embed.set_image(url=results[0]['thumbnail'])

        view = discord.ui.View()

        for idx, r in enumerate(results):
            b = discord.ui.Button(label=str(idx+1))

            async def cb(interaction, r=r):
                key = get_key(interaction)
                queues.setdefault(key, []).append(r)

                if not interaction.guild.voice_client:
                    await interaction.user.voice.channel.connect()

                if not interaction.guild.voice_client.is_playing():
                    await play_next(interaction)

                await interaction.response.defer()

            b.callback = cb
            view.add_item(b)

        await i.followup.send(embed=embed, view=view)

# ================= 패널 =================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색", style=discord.ButtonStyle.primary)
    async def search(self, i, b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="🔥 인기곡", style=discord.ButtonStyle.success)
    async def top(self, i, b):
        key = get_key(i)
        queues.setdefault(key, [])
        data = await safe_extract("ytsearch1:kpop")
        if data:
            queues[key].append(data["entries"][0])

        if not i.guild.voice_client:
            await i.user.voice.channel.connect()

        if not i.guild.voice_client.is_playing():
            await play_next(i)

        await i.response.defer()

    @discord.ui.button(label="📀 대기열", style=discord.ButtonStyle.secondary)
    async def queue(self, i, b):
        key = get_key(i)
        q = queues.get(key, [])
        txt = "\n".join([f"{idx+1}. {x['title']}" for idx, x in enumerate(q)]) or "없음"
        await i.response.send_message(txt, ephemeral=True)

# ================= 실행 =================
@tree.command(name="셋업", guild=discord.Object(id=GUILD_ID))
async def setup(i: discord.Interaction):
    await show_panel(i)

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 초정밀 Spotify UI 실행됨")

client.run(TOKEN)
