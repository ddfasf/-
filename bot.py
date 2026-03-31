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

# ================= yt-dlp (🔥 안정화 버전) =================
ydl_opts = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "default_search": "ytsearch",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"]
        }
    },
    "retries": 5,
}

async def extract(q):
    loop = asyncio.get_event_loop()

    def run():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(q, download=False)
        except Exception as e:
            print("❌ yt-dlp 에러:", e)
            return None

    return await loop.run_in_executor(None, run)

# ================= 패널 =================
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색", style=discord.ButtonStyle.success, custom_id="search_btn")
    async def search(self, i: discord.Interaction, b):
        await i.response.send_modal(Search())

    @discord.ui.button(label="📀 큐", style=discord.ButtonStyle.primary, custom_id="queue_btn")
    async def queue(self, i: discord.Interaction, b):
        q = queues.get(i.guild.id, [])
        if not q:
            return await i.response.send_message("없음", ephemeral=True)

        txt = "\n".join([x["title"] for x in q[:10]])
        await i.response.send_message(txt, ephemeral=True)

# ================= 검색 =================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)

        data = await extract(f"ytsearch5:{self.query}")

        if not data or "entries" not in data:
            return await i.followup.send("❌ 검색 실패", ephemeral=True)

        res = [r for r in data["entries"] if r]

        if not res:
            return await i.followup.send("❌ 결과 없음", ephemeral=True)

        v = discord.ui.View(timeout=60)

        for r in res:
            title = r.get("title", "제목없음")[:20]
            b = discord.ui.Button(label=title)

            async def cb(inter: discord.Interaction, r=r):
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

                await inter.followup.send(f"✅ {r.get('title','')}", ephemeral=True)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("🎬 검색 결과", view=v, ephemeral=True)

# ================= 재생 =================
async def play_next(i: discord.Interaction):
    k = i.guild.id
    vc = i.guild.voice_client

    if not queues.get(k):
        return

    song = queues[k].pop(0)

    data = await extract(song["webpage_url"])
    if not data:
        return await play_next(i)

    stream_url = data.get("url")
    if not stream_url:
        return await play_next(i)

    now_playing[k] = song
    start_times[k] = time.time()

    ffmpeg_options = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn"
    }

    source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_options)

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(i), client.loop)
        try:
            fut.result()
        except:
            pass

    vc.play(source, after=after)

    emb = discord.Embed(
        title="🎧 NOW PLAYING",
        description=f"[{song.get('title','')}]({song.get('webpage_url','')})",
        color=0x1DB954
    )

    emb.set_thumbnail(url=song.get("thumbnail"))
    await i.channel.send(embed=emb)

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
        description="버튼으로 음악 재생",
        color=0x1DB954
    )

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
        await tree.sync()
        print("✅ 명령어 등록 완료")
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
