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
paused = {}
loop_state = {}

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

ydl_opts = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "retries": 10,
    "fragment_retries": 10,
    "sleep_interval_requests": 1,
    "sleep_interval": 1,
    "http_headers": {"User-Agent": "Mozilla/5.0"},
    "extractor_args": {"youtube": {"player_client": ["web"]}}
}

async def extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(q, download=False)
    return await loop.run_in_executor(None, run)

def make_embed(song, elapsed, gid, state="▶"):
    d = song.get("duration", 180)
    filled = int(18 * elapsed / max(d, 1))
    bar = "▰"*filled + "▱"*(18-filled)

    emb = discord.Embed(
        title="🎧 NOW PLAYING" if state=="▶" else "⏸ PAUSED",
        description=f"[{song['title']}]({song['webpage_url']})",
        color=0x1DB954
    )

    emb.add_field(name="⏱", value=f"{bar}\n{elapsed}/{d}s", inline=False)

    q = queues.get(gid, [])
    emb.add_field(name="📀 NEXT UP", value=q[0]["title"] if q else "없음", inline=False)

    emb.set_thumbnail(url=song.get("thumbnail"))
    emb.set_image(url=random.choice(GIFS))
    return emb

def panel_embed(state="대기중"):
    emb = discord.Embed(
        title="🎧 MUSIC PANEL",
        description="버튼으로 조작",
        color=0x1DB954
    )
    emb.add_field(name="상태", value=state)
    emb.set_image(url=random.choice(GIFS))
    return emb

async def update(msg, gid):
    while gid in now_playing:
        song = now_playing[gid]
        elapsed = int(time.time() - start_times[gid])

        state = "⏸" if paused.get(gid) else "▶"
        try:
            await msg.edit(embed=make_embed(song, elapsed, gid, state))
        except:
            break

        await asyncio.sleep(2)

# 🎨 버튼 애니메이션 UI
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def highlight(self, btn):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.style = discord.ButtonStyle.secondary
        btn.style = discord.ButtonStyle.success

    @discord.ui.button(label="검색", style=discord.ButtonStyle.secondary, custom_id="search")
    async def search(self, i, btn):
        self.highlight(btn)
        await i.response.edit_message(view=self)
        await i.followup.send_modal(Search())

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.secondary, custom_id="pause")
    async def pause(self, i, btn):
        vc = i.guild.voice_client
        gid = i.guild.id

        if not vc or gid not in now_playing:
            return await i.response.send_message("❌ 재생중 아님", ephemeral=True)

        self.highlight(btn)

        if vc.is_playing():
            vc.pause()
            paused[gid] = True
        else:
            vc.resume()
            paused[gid] = False
            start_times[gid] = time.time()

        await i.response.edit_message(view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary, custom_id="skip")
    async def skip(self, i, btn):
        self.highlight(btn)
        vc = i.guild.voice_client
        if vc:
            vc.stop()
        await i.response.edit_message(view=self)

    @discord.ui.button(label="큐", style=discord.ButtonStyle.secondary, custom_id="queue")
    async def queue(self, i, btn):
        self.highlight(btn)
        q = queues.get(i.guild.id, [])
        txt = "\n".join([x["title"] for x in q[:10]]) or "없음"
        await i.response.send_message(txt, ephemeral=True)

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary, custom_id="shuffle")
    async def shuffle(self, i, btn):
        self.highlight(btn)
        random.shuffle(queues.get(i.guild.id, []))
        await i.response.edit_message(view=self)

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary, custom_id="loop")
    async def loop(self, i, btn):
        self.highlight(btn)
        gid = i.guild.id
        loop_state[gid] = not loop_state.get(gid, False)
        await i.response.edit_message(view=self)

class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)

        data = await extract(f"ytsearch5:{self.query}")
        v = discord.ui.View(timeout=60)

        for r in data["entries"]:
            b = discord.ui.Button(label=r["title"][:20])

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

                await inter.followup.send(f"✅ {r['title']}", ephemeral=True)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("🎬 검색 결과", view=v, ephemeral=True)

async def play_next(i):
    k = i.guild.id
    vc = i.guild.voice_client
    ch = i.channel
    s = get_settings(k)
    msg = await ch.fetch_message(s["panel_msg"])

    if not queues.get(k):
        now_playing.pop(k, None)
        await msg.edit(embed=panel_embed(), view=Panel())
        return

    song = queues[k].pop(0)
    data = await extract(song["webpage_url"])
    if not data:
        return await play_next(i)

    stream_url = data["url"]

    now_playing[k] = song
    start_times[k] = time.time()
    paused[k] = False

    source = discord.FFmpegPCMAudio(stream_url, options="-vn -reconnect 1 -reconnect_streamed 1")

    def after(e):
        if loop_state.get(k):
            queues.setdefault(k, []).insert(0, song)
        asyncio.run_coroutine_threadsafe(play_next(i), client.loop)

    vc.play(source, after=after)

    await msg.edit(embed=make_embed(song, 0, k), view=Panel())
    client.loop.create_task(update(msg, k))

async def send_panel(ch, gid):
    s = get_settings(gid)
    emb = panel_embed()

    if s.get("panel_msg"):
        try:
            msg = await ch.fetch_message(s["panel_msg"])
            await msg.edit(embed=emb, view=Panel())
            return
        except:
            pass

    msg = await ch.send(embed=emb, view=Panel())
    s["panel_msg"] = msg.id
    save_settings(settings)

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
        ch = client.get_channel(data.get("music_channel"))
        if ch:
            await send_panel(ch, int(gid))

client.run(os.environ.get("TOKEN"))
