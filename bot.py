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
volume_level = {}
start_time = {}
current_track = {}
loading_state = {}
next_source = {}  # 🔥 핵심

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'ignoreerrors': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'cookiefile': 'cookies.txt',
    'http_headers': {'User-Agent': 'Mozilla/5.0'}
}

async def safe_extract(query):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(query, download=False)
    try:
        return await loop.run_in_executor(None, run)
    except:
        return None

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(sec):
    return f"{int(sec//60):02}:{int(sec%60):02}"

def make_bar(p):
    return "▰"*int(p*12)+"▱"*(12-int(p*12))

def get_lyrics():
    return "\n".join(random.sample([
        "🌙 이 밤을 따라 흘러가",
        "💫 너와 나의 멜로디",
        "🔥 심장이 뛰는 순간",
        "✨ 끝나지 않을 노래"
    ], 3))

# ================= 페이드 =================
async def fade_out(vc):
    if not vc or not vc.source: return
    for i in range(10,-1,-1):
        vc.source.volume=i/10
        await asyncio.sleep(0.1)

async def fade_in(vc):
    if not vc or not vc.source: return
    for i in range(11):
        vc.source.volume=i/10
        await asyncio.sleep(0.1)

# ================= 프리로드 =================
async def preload_next(i):
    key = get_key(i)

    if not queues.get(key):
        return

    next_info = queues[key][0]

    data = await safe_extract(next_info['webpage_url'])
    if not data:
        return

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'], executable=FFMPEG_PATH),
        volume=volume_level.get(key, 0.5)
    )

    next_source[key] = (source, next_info)

# ================= SEEK =================
async def seek_to(i, percent):
    key=get_key(i)
    vc=i.guild.voice_client
    if not vc or key not in current_track: return

    info=current_track[key]
    dur=info.get("duration",180)
    t=int(dur*percent)

    data=await safe_extract(info['webpage_url'])
    if not data: return

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(
            data['url'],
            executable=FFMPEG_PATH,
            before_options=f"-ss {t}"
        ), volume=0.0)

    await fade_out(vc)
    vc.stop()
    vc.play(source)
    await fade_in(vc)

    start_time[key]=time.time()-t

# ================= UI =================
class SeekSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="🎛 Seek",
        options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(11)])

    async def callback(self,i):
        await i.response.defer()
        await seek_to(i,float(self.values[0]))

class VolumeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="🎚 Volume",
        options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(1,11)])

    async def callback(self,i):
        key=get_key(i)
        vol=float(self.values[0])
        volume_level[key]=vol
        if i.guild.voice_client and i.guild.voice_client.source:
            i.guild.voice_client.source.volume=vol
        await i.response.send_message(f"🔊 {int(vol*100)}%",ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self,state="play"):
        super().__init__(timeout=None)

        emoji="⏸️" if state=="play" else "▶️"
        if state=="loading": emoji="⏳"

        btn=discord.ui.Button(emoji=emoji,style=discord.ButtonStyle.success)
        btn.callback=self.pause
        self.add_item(btn)

        for e,cb in [("⏮️",self.back),("⏭️",self.skip)]:
            b=discord.ui.Button(emoji=e,style=discord.ButtonStyle.secondary)
            b.callback=cb
            self.add_item(b)

        self.add_item(SeekSelect())
        self.add_item(VolumeSelect())

    async def pause(self,i):
        vc=i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()
        await i.response.defer()

    async def skip(self,i):
        vc=i.guild.voice_client
        await fade_out(vc)
        vc.stop()
        await i.response.defer()

    async def back(self,i):
        await seek_to(i,0.1)

# ================= 음악 =================
async def add_to_queue(i,q):
    key=get_key(i)
    queues.setdefault(key,[])

    data=await safe_extract(f"ytsearch1:{q}")
    if not data or not data.get("entries"):
        return await i.channel.send("❌ 검색 실패")

    queues[key].append(data["entries"][0])

    if len(queues[key]) == 1:
        asyncio.create_task(preload_next(i))

async def play_next(i):
    key=get_key(i)
    vc=i.guild.voice_client

    if not queues.get(key) and key not in next_source:
        return

    # 🔥 프리로드 사용
    if key in next_source:
        source, info = next_source.pop(key)
    else:
        info=queues[key].pop(0)
        data=await safe_extract(info['webpage_url'])
        if not data:
            return await play_next(i)

        source=discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(data['url'],executable=FFMPEG_PATH),
            volume=0.0)

    current_track[key]=info

    vc.play(
        source,
        after=lambda e:asyncio.run_coroutine_threadsafe(play_next(i),client.loop)
    )

    await fade_in(vc)
    start_time[key]=time.time()

    asyncio.create_task(preload_next(i))  # 🔥 다음곡 미리 로딩

    msg=await i.channel.send(
        embed=discord.Embed(title="🎧 Now Playing",description=info['title'],color=0x1DB954),
        view=ControlView("play")
    )
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

# ================= UI 업데이트 =================
async def update_ui(i,info):
    key=get_key(i)
    dur=info.get("duration",180)

    while key in start_time:
        vc=i.guild.voice_client
        state="play" if vc and vc.is_playing() else "pause"

        el=int(time.time()-start_time[key])
        p=min(el/dur,1)

        embed=discord.Embed(
            title="🎧 Now Playing",
            description=f"{info['title']}\n{make_bar(p)}\n⏱ {format_time(el)}/{format_time(dur)}\n\n{get_lyrics()}",
            color=0x1DB954
        )
        embed.set_image(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed,view=ControlView(state))
        except:
            pass

        await asyncio.sleep(1)

# ================= 검색 =================
class SearchModal(discord.ui.Modal,title="🎵 검색"):
    query=discord.ui.TextInput(label="노래")

    async def on_submit(self,i):
        await i.response.defer()

        data=await safe_extract(f"ytsearch5:{self.query}")
        if not data:
            return await i.followup.send("❌ 검색 실패")

        results=data["entries"]

        embed=discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx,r in enumerate(results)]),
            color=0xFF0000
        )
        embed.set_image(url=results[0]['thumbnail'])

        view=discord.ui.View()

        for idx,r in enumerate(results):
            btn=discord.ui.Button(label=str(idx+1))

            async def cb(interaction,r=r):
                await add_to_queue(interaction,r['title'])
                if not interaction.guild.voice_client:
                    await interaction.user.voice.channel.connect()
                if not interaction.guild.voice_client.is_playing():
                    await play_next(interaction)
                await interaction.response.defer()

            btn.callback=cb
            view.add_item(btn)

        await i.followup.send(embed=embed,view=view)

# ================= 패널 =================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색",style=discord.ButtonStyle.primary)
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="🔥 인기곡",style=discord.ButtonStyle.success)
    async def top(self,i,b):
        await add_to_queue(i,"kpop hits")
        await i.response.send_message("🔥 추가됨")

    @discord.ui.button(label="⏹ 정지",style=discord.ButtonStyle.danger)
    async def stop(self,i,b):
        if i.guild.voice_client:
            await fade_out(i.guild.voice_client)
            i.guild.voice_client.stop()
        await i.response.defer()

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    await i.response.send_message("🎧 Spotify급 음악봇 준비 완료",view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 완전체 실행됨 (프리로드 ON)")

client.run(TOKEN)
