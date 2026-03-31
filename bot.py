import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os
import json

# ================= 기본 =================
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
now_playing = {}
start_times = {}

# ================= 설정 =================
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
        "volume": 100,
        "dj_role": None,
        "music_channel": None
    })

def is_dj(i):
    s = get_settings(i.guild.id)
    if s["dj_role"] is None:
        return True
    return any(r.id == s["dj_role"] for r in i.user.roles)

def check_channel(i):
    s = get_settings(i.guild.id)
    return not s["music_channel"] or i.channel.id == s["music_channel"]

# ================= yt-dlp =================
ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "http_headers": {"User-Agent": "Mozilla/5.0"},
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

async def extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(q, download=False)
    return await loop.run_in_executor(None, run)

# ================= UI =================
def bar(c, t, l=18):
    t = max(t, 1)
    f = int(l * c / t)
    return "▰"*f + "▱"*(l-f)

async def update(msg, i):
    k = i.guild.id
    while k in now_playing:
        s = now_playing[k]
        e = int(time.time() - start_times[k])
        d = s.get("duration", 180)

        emb = discord.Embed(
            title="🎧 NOW PLAYING",
            description=f"{s['title']}\n\n{bar(e,d)}\n⏱ {e}/{d}s",
            color=0x5865F2
        )

        try:
            await msg.edit(embed=emb)
        except:
            break

        await asyncio.sleep(2)

# ================= 플레이어 =================
class Player(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.success)
    async def pause(self, i, b):
        if not is_dj(i):
            return await i.response.send_message("❌ DJ만 가능", ephemeral=True)

        vc = i.guild.voice_client
        if vc.is_playing():
            vc.pause()
            b.label = "▶️"
        else:
            vc.resume()
            b.label = "⏸"

        await i.response.edit_message(view=self)

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.primary)
    async def skip(self, i, b):
        if not is_dj(i):
            return await i.response.send_message("❌ DJ만 가능", ephemeral=True)

        i.guild.voice_client.stop()
        await i.response.defer()

# ================= 재생 =================
async def play_next(i):
    k = i.guild.id
    vc = i.guild.voice_client

    if not queues.get(k):
        return

    song = queues[k].pop(0)

    # 🔥 스트림 URL 추출 (핵심)
    data = await extract(song["webpage_url"])
    stream_url = data["url"]

    now_playing[k] = song
    start_times[k] = time.time()

    vol = get_settings(k)["volume"] / 100

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(stream_url),
        volume=vol
    )

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(i), client.loop)
        try: fut.result()
        except: pass

    vc.play(source, after=after)

    emb = discord.Embed(title="🎧 NOW PLAYING", description=song["title"])
    msg = await i.channel.send(embed=emb, view=Player())
    client.loop.create_task(update(msg, i))

# ================= 검색 =================
class Search(discord.ui.Modal, title="검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i):
        await i.response.defer()

        if not check_channel(i):
            return await i.followup.send("🎧 음악 채널에서만 사용", ephemeral=True)

        data = await extract(f"ytsearch5:{self.query}")
        res = data["entries"]

        v = discord.ui.View(timeout=None)

        for r in res:
            b = discord.ui.Button(label=r["title"][:20])

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

                await inter.followup.send(f"✅ {r['title']}", ephemeral=True)

            b.callback = cb
            v.add_item(b)

        await i.followup.send("🎬 검색 결과", view=v)

# ================= 패널 =================
class Panel(discord.ui.View):
    @discord.ui.button(label="🎵 검색", style=discord.ButtonStyle.success)
    async def search(self, i, b):
        await i.response.send_modal(Search())

    @discord.ui.button(label="📀 큐", style=discord.ButtonStyle.primary)
    async def queue(self, i, b):
        q = queues.get(i.guild.id, [])
        if not q:
            return await i.response.send_message("없음", ephemeral=True)

        txt = "\n".join([x["title"] for x in q])
        await i.response.send_message(txt, ephemeral=True)

async def send_panel(ch):
    async for m in ch.history(limit=10):
        if m.author == client.user:
            return

    emb = discord.Embed(
        title="🎧 MUSIC PANEL",
        description="버튼으로 음악을 조작하세요",
        color=0x5865F2
    )
    emb.set_image(url="https://media.giphy.com/media/ZVik7pBtu9dNS/giphy.gif")

    await ch.send(embed=emb, view=Panel())

# ================= 명령어 =================
@tree.command(name="setup")
async def setup(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ 관리자만", ephemeral=True)

    g = i.guild

    cat = discord.utils.get(g.categories, name="🎧 음악") or await g.create_category("🎧 음악")
    tc = discord.utils.get(g.text_channels, name="🎵-music") or await g.create_text_channel("🎵-music", category=cat)
    await g.create_voice_channel("🎧 Music", category=cat)

    s = get_settings(g.id)
    s["music_channel"] = tc.id
    save_settings(settings)

    await send_panel(tc)
    await i.response.send_message("✅ 설치 완료", ephemeral=True)

# ================= 실행 =================
GUILD_ID = 1484915814187401259

@client.event
async def on_ready():
    print("🔥 완전체 실행됨")

    guild = discord.Object(id=GUILD_ID)

    try:
        tree.clear_commands(guild=guild)
        await tree.sync(guild=guild)
        print("✅ 명령어 동기화 완료")
    except Exception as e:
        print("❌ sync 에러:", e)

    # 패널 복구
    for gid, data in settings.items():
        ch_id = data.get("music_channel")
        if ch_id:
            ch = client.get_channel(ch_id)
            if ch:
                try:
                    await send_panel(ch)
                except:
                    pass

client.run(os.environ.get("TOKEN"))
