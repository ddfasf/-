import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import json
import random

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
now_playing = {}
start_times = {}
history = {}

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
}

async def extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(q, download=False)
    return await loop.run_in_executor(None, run)

# ================= 패널 UI =================
def make_panel_embed(gid):
    song = now_playing.get(gid)
    status = "⏹ 대기중"

    if song:
        status = "▶️ 재생중"

    emb = discord.Embed(
        title="🎧 MUSIC STATION",
        description="버튼으로 음악을 선택하세요",
        color=0x1DB954
    )

    emb.add_field(name="📡 상태", value=status, inline=True)
    emb.add_field(
        name="🎵 현재곡",
        value=song["title"] if song else "없음",
        inline=True
    )

    emb.add_field(name="🔎 검색", value="노래 찾기", inline=True)
    emb.add_field(name="🔥 인기", value="추천곡", inline=True)
    emb.add_field(name="🏆 빌보드", value="TOP 차트", inline=True)
    emb.add_field(name="🎬 매드무비", value="플레이리스트", inline=True)
    emb.add_field(name="🆕 최신곡", value="최근곡", inline=True)

    return emb

# ================= 플레이어 UI =================
def make_player_embed(song, elapsed):
    d = song.get("duration", 180)
    filled = int(18 * elapsed / max(d, 1))
    bar = "▰"*filled + "▱"*(18-filled)

    emb = discord.Embed(
        title="🎧 NOW PLAYING",
        description=f"[{song['title']}]({song['webpage_url']})",
        color=0x1DB954
    )

    emb.add_field(name="⏱", value=f"{bar}\n{elapsed}/{d}s", inline=False)

    if song.get("thumbnail"):
        emb.set_thumbnail(url=song["thumbnail"])

    return emb

# ================= 패널 =================
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔎 검색", style=discord.ButtonStyle.success, custom_id="search")
    async def search(self, i, b):
        await i.response.send_modal(Search())

# ================= 플레이어 =================
class Player(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏸", style=discord.ButtonStyle.primary, custom_id="pause")
    async def pause(self, i, b):
        vc = i.guild.voice_client
        if vc.is_playing():
            vc.pause()
            b.label = "▶️"
        else:
            vc.resume()
            b.label = "⏸"
        await i.response.edit_message(view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary, custom_id="skip")
    async def skip(self, i, b):
        i.guild.voice_client.stop()
        await i.response.defer()

# ================= 검색 =================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)

        data = await extract(f"ytsearch5:{self.query}")

        if not data or "entries" not in data:
            return await i.followup.send("❌ 검색 실패", ephemeral=True)

        v = discord.ui.View()

        for r in data["entries"]:
            if not r:
                continue

            title = r.get("title", "제목없음")

            b = discord.ui.Button(label=title[:20])

            async def cb(inter, r=r):
                await inter.response.defer(ephemeral=True)

                if not inter.user.voice:
                    return await inter.followup.send("❌ 음성채널 들어가", ephemeral=True)

                k = inter.guild.id
                queues.setdefault(k, []).append(r)

                vc = inter.guild.voice_client
                if not vc:
                    vc = await inter.user.voice.channel.connect()

                if not vc.is_playing():
                    await play_next(inter)

                await inter.followup.send(f"✅ 추가됨", ephemeral=True)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("🎬 검색 결과", view=v, ephemeral=True)

# ================= 재생 =================
async def play_next(i):
    k = i.guild.id
    vc = i.guild.voice_client

    if not queues.get(k):
        now_playing.pop(k, None)
        await update_panel(k)
        return

    song = queues[k].pop(0)

    data = await extract(song["webpage_url"])
    if not data:
        return await play_next(i)

    stream_url = data["url"]

    now_playing[k] = song
    start_times[k] = time.time()

    source = discord.FFmpegPCMAudio(stream_url)

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(i), client.loop)
        try: fut.result()
        except: pass

    vc.play(source, after=after)

    msg = await i.followup.send(embed=make_player_embed(song, 0), view=Player(), ephemeral=True)

    client.loop.create_task(update_player(msg, k))
    await update_panel(k)

# ================= 업데이트 =================
async def update_player(msg, gid):
    while gid in now_playing:
        s = now_playing[gid]
        e = int(time.time() - start_times[gid])
        try:
            await msg.edit(embed=make_player_embed(s, e))
        except:
            break
        await asyncio.sleep(2)

async def update_panel(gid):
    s = get_settings(gid)
    if not s.get("panel_msg"):
        return

    ch = client.get_channel(s["music_channel"])
    try:
        msg = await ch.fetch_message(s["panel_msg"])
        await msg.edit(embed=make_panel_embed(gid), view=Panel())
    except:
        pass

# ================= 패널 생성 =================
async def send_panel(ch, gid):
    s = get_settings(gid)

    if s.get("panel_msg"):
        try:
            msg = await ch.fetch_message(s["panel_msg"])
            await msg.edit(embed=make_panel_embed(gid), view=Panel())
            return
        except:
            s["panel_msg"] = None
            save_settings(settings)

    msg = await ch.send(embed=make_panel_embed(gid), view=Panel())

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
    await i.response.send_message("✅ 완료", ephemeral=True)

# ================= 실행 =================
@client.event
async def on_ready():
    print("🔥 실행됨")

    client.add_view(Panel())
    client.add_view(Player())

    await tree.sync()

    for gid, data in settings.items():
        ch_id = data.get("music_channel")
        if ch_id:
            ch = client.get_channel(ch_id)
            if ch:
                await send_panel(ch, int(gid))

client.run(os.environ.get("TOKEN"))
