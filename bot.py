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

GIFS = [
    "https://media.giphy.com/media/ZVik7pBtu9dNS/giphy.gif",
    "https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif",
    "https://media.giphy.com/media/l3vRlT2k2L35Cnn5C/giphy.gif"
]

# 🔥 핵심: 차단 우회 설정
ydl_opts = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "cookiefile": "cookies.txt",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "http_headers": {
        "User-Agent": "Mozilla/5.0"
    },
    "extractor_args": {
        "youtube": {
            "player_client": ["web"]
        }
    }
}

# 🔥 핵심: extract 강화
async def extract(q):
    loop = asyncio.get_event_loop()

    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(q, download=False)

            if not info:
                return None

            # 검색 결과
            if "entries" in info:
                return info

            # URL 보정
            if "url" not in info:
                formats = info.get("formats", [])
                for f in formats:
                    if f.get("url"):
                        info["url"] = f["url"]
                        break

            return info

    return await loop.run_in_executor(None, run)

# ================= UI =================
def make_embed(song, elapsed):
    d = song.get("duration", 180)

    bar_len = 18
    filled = int(bar_len * elapsed / max(d, 1))
    bar = "▰"*filled + "▱"*(bar_len-filled)

    emb = discord.Embed(
        title="🎧 NOW PLAYING",
        description=f"🎵 [{song['title']}]({song['webpage_url']})",
        color=0x1DB954
    )

    emb.add_field(name="⏱ 진행", value=f"{bar}\n{elapsed}/{d}s", inline=False)
    emb.set_thumbnail(url=song.get("thumbnail"))
    emb.set_image(url=random.choice(GIFS))
    emb.set_footer(text="🎶 Music Bot")

    return emb

async def update(msg, gid):
    while gid in now_playing:
        s = now_playing[gid]
        elapsed = int(time.time() - start_times[gid])

        try:
            await msg.edit(embed=make_embed(s, elapsed))
        except:
            break

        await asyncio.sleep(2)

# ================= 패널 =================
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎵 검색", style=discord.ButtonStyle.success, custom_id="search_btn")
    async def search(self, i, b):
        await i.response.send_modal(Search())

    @discord.ui.button(label="📀 큐", style=discord.ButtonStyle.primary, custom_id="queue_btn")
    async def queue(self, i, b):
        q = queues.get(i.guild.id, [])
        if not q:
            return await i.response.send_message("없음", ephemeral=True)

        txt = "\n".join([x["title"] for x in q[:10]])
        await i.response.send_message(txt, ephemeral=True)

# ================= 검색 =================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer()

        data = await extract(f"ytsearch5:{self.query}")
        if not data or not data.get("entries"):
            return await i.followup.send("❌ 검색 실패", ephemeral=True)

        res = data["entries"]

        v = discord.ui.View(timeout=60)

        for r in res:
            title = r.get("title", "제목없음")[:20]
            b = discord.ui.Button(label=title)

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

                await inter.followup.send(f"✅ {r.get('title','')}", ephemeral=True)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("🎬 검색 결과", view=v, ephemeral=True)

# ================= 재생 =================
async def play_next(i):
    k = i.guild.id
    vc = i.guild.voice_client

    if not queues.get(k):
        return

    song = queues[k].pop(0)

    data = await extract(song["webpage_url"])
    if not data or "url" not in data:
        return await i.channel.send("❌ 재생 실패 (차단됨)")

    stream_url = data["url"]

    now_playing[k] = song
    start_times[k] = time.time()

    # 🔥 핵심: FFmpeg 안정화
    source = discord.FFmpegPCMAudio(
        stream_url,
        before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        options="-vn"
    )

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(i), client.loop)
        try:
            fut.result()
        except:
            pass

    vc.play(source, after=after)

    msg = await i.channel.send(embed=make_embed(song, 0))
    client.loop.create_task(update(msg, k))

# ================= 패널 생성 =================
async def send_panel(ch, gid):
    s = get_settings(gid)

    if s.get("panel_msg"):
        try:
            await ch.fetch_message(s["panel_msg"])
            return
        except:
            pass

    emb = discord.Embed(
        title="🎧 MUSIC PANEL",
        description="🎵 버튼으로 음악 재생",
        color=0x1DB954
    )
    emb.set_image(url=random.choice(GIFS))

    msg = await ch.send(embed=emb, view=Panel())

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

    try:
        synced = await tree.sync()
        print(f"✅ 명령어 {len(synced)}개 등록됨")
    except Exception as e:
        print("❌", e)

    for gid, data in settings.items():
        ch_id = data.get("music_channel")
        if ch_id:
            ch = client.get_channel(ch_id)
            if ch:
                try:
                    await send_panel(ch, int(gid))
                except:
                    pass

client.run(os.environ.get("TOKEN"))
