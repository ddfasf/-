import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import json
import random

# ================= 기본 =================
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
now_playing = {}
start_times = {}
paused = {}
loop_state = {}
history = {}

SETTINGS_FILE = "settings.json"

# ================= 설정 =================
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

def get_settings(gid):
    return settings.setdefault(str(gid), {
        "music_channel": None,
        "panel_msg": None
    })

# ================= yt-dlp =================
ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "ignoreerrors": True,
    "http_headers": {"User-Agent": "Mozilla/5.0"},
    "extractor_args": {"youtube": {"player_client": ["web"]}}
}

async def extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(q, download=False)
    return await loop.run_in_executor(None, run)

# ================= UI =================
def make_player_embed(song, elapsed, user):
    d = song.get("duration", 180)
    bar = f"{elapsed//60}:{elapsed%60:02d} ━━━━━━━ {d//60}:{d%60:02d}"

    emb = discord.Embed(
        title="🎧 음악 재생 중",
        description=f"**{song['title']}**",
        color=0x2b2d31
    )

    emb.add_field(name="⏱ 진행", value=bar, inline=False)
    emb.set_image(url=song.get("thumbnail"))
    emb.set_footer(text=f"요청자: {user}")

    return emb

def make_panel_embed():
    emb = discord.Embed(
        title="🎧 MUSIC PANEL",
        description="🎵 원하는 음악을 선택하세요",
        color=0x2b2d31
    )
    return emb

# ================= Player UI =================
class PlayerUI(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="⏹ 정지", style=discord.ButtonStyle.danger)
    async def stop(self, i, b):
        vc = i.guild.voice_client
        if vc:
            vc.stop()
        now_playing.pop(i.guild.id, None)
        await i.response.send_message("정지됨", ephemeral=True)

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.primary)
    async def pause(self, i, b):
        vc = i.guild.voice_client
        if vc.is_playing():
            vc.pause()
        else:
            vc.resume()
        await i.response.defer()

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.primary)
    async def skip(self, i, b):
        vc = i.guild.voice_client
        if vc:
            vc.stop()
        await i.response.defer()

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def prev(self, i, b):
        k = i.guild.id
        if history.get(k):
            queues.setdefault(k, []).insert(0, history[k].pop())
            i.guild.voice_client.stop()
        await i.response.defer()

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(self, i, b):
        random.shuffle(queues.get(i.guild.id, []))
        await i.response.send_message("셔플됨", ephemeral=True)

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, i, b):
        gid = i.guild.id
        loop_state[gid] = not loop_state.get(gid, False)
        await i.response.send_message(f"반복 {'ON' if loop_state[gid] else 'OFF'}", ephemeral=True)

# ================= Panel =================
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색", style=discord.ButtonStyle.success, custom_id="search")
    async def search(self, i, b):
        await i.response.send_modal(Search())

    @discord.ui.button(label="🔥 인기", style=discord.ButtonStyle.secondary, custom_id="chart")
    async def chart(self, i, b):
        await send_chart(i, "kpop")

    @discord.ui.button(label="🏆 빌보드", style=discord.ButtonStyle.secondary, custom_id="billboard")
    async def billboard(self, i, b):
        await send_chart(i, "billboard")

    @discord.ui.button(label="🎬 매드무비", style=discord.ButtonStyle.secondary, custom_id="mad")
    async def mad(self, i, b):
        await send_chart(i, "mad")

    @discord.ui.button(label="🆕 최신", style=discord.ButtonStyle.secondary, custom_id="latest")
    async def latest(self, i, b):
        await send_chart(i, "latest")

# ================= Search =================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        data = await extract(f"ytsearch5:{self.query}")

        v = discord.ui.View(timeout=60)

        for r in data["entries"]:
            b = discord.ui.Button(label=r["title"][:20])

            async def cb(inter, r=r):
                await start_music(inter, r)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("선택", view=v, ephemeral=True)

# ================= Chart =================
async def send_chart(i, mode):
    await i.response.defer(ephemeral=True)

    q = {
        "kpop": "ytsearch5:케이팝 인기차트",
        "billboard": "ytsearch5:billboard hot 100",
        "mad": "ytsearch5:mad movie music",
        "latest": "ytsearch5:최신 노래"
    }

    data = await extract(q[mode])
    v = discord.ui.View(timeout=60)

    for r in data["entries"]:
        b = discord.ui.Button(label=r["title"][:20])

        async def cb(inter, r=r):
            await start_music(inter, r)

        b.callback = cb
        v.add_item(b)

    await i.followup.send("🎬 선택", view=v, ephemeral=True)

# ================= 재생 =================
async def start_music(i, song):
    if not i.user.voice:
        return await i.followup.send("음성채널 들어가", ephemeral=True)

    k = i.guild.id
    queues.setdefault(k, []).append(song)

    vc = i.guild.voice_client
    if not vc:
        vc = await i.user.voice.channel.connect()

    if not vc.is_playing():
        await play_next(i)

    await i.followup.send(
        embed=make_player_embed(song, 0, i.user),
        view=PlayerUI(),
        ephemeral=True
    )

async def play_next(i):
    k = i.guild.id
    vc = i.guild.voice_client

    if not queues.get(k):
        now_playing.pop(k, None)
        return

    song = queues[k].pop(0)
    data = await extract(song["webpage_url"])

    if not data:
        return await play_next(i)

    stream = data["url"]

    history.setdefault(k, []).append(song)
    now_playing[k] = song
    start_times[k] = time.time()

    source = discord.FFmpegPCMAudio(stream)

    def after(e):
        if loop_state.get(k):
            queues.setdefault(k, []).insert(0, song)
        asyncio.run_coroutine_threadsafe(play_next(i), client.loop)

    vc.play(source, after=after)

# ================= Panel 생성 =================
async def send_panel(ch, gid):
    s = get_settings(gid)

    if s.get("panel_msg"):
        try:
            await ch.fetch_message(s["panel_msg"])
            return
        except:
            pass

    msg = await ch.send(embed=make_panel_embed(), view=Panel())
    s["panel_msg"] = msg.id
    save_settings(settings)

# ================= setup =================
@tree.command(name="setup")
async def setup(i: discord.Interaction):
    g = i.guild

    cat = discord.utils.get(g.categories, name="🎧 음악") or await g.create_category("🎧 음악")
    tc = discord.utils.get(g.text_channels, name="🎵-music") or await g.create_text_channel("🎵-music", category=cat)
    await g.create_voice_channel("🎧 Music", category=cat)

    s = get_settings(g.id)
    s["music_channel"] = tc.id
    save_settings(settings)

    await send_panel(tc, g.id)
    await i.response.send_message("완료", ephemeral=True)

# ================= 실행 =================
@client.event
async def on_ready():
    print("🔥 실행됨")

    client.add_view(Panel())

    await tree.sync()

    for gid, data in settings.items():
        ch = client.get_channel(data.get("music_channel"))
        if ch:
            await send_panel(ch, int(gid))

client.run(os.environ.get("TOKEN"))
