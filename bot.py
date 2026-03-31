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

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'cookiefile': 'cookies.txt',
}

async def safe_extract(query):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(None, run)

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(sec):
    return f"{int(sec//60):02}:{int(sec%60):02}"

def make_bar(p):
    return "▰"*int(p*12)+"▱"*(12-int(p*12))

def volume_bar(v):
    return "🔊"+"▰"*int(v*10)+"▱"*(10-int(v*10))

lyrics_lines = [
    "🌙 이 밤을 따라 흘러가",
    "💫 너와 나의 멜로디",
    "🔥 심장이 뛰는 순간",
    "✨ 끝나지 않을 노래"
]

def animated_lyrics(step):
    return "\n".join(lyrics_lines[:step%4+1])

# ================= 페이드 =================
async def fade_out(vc):
    if not vc or not vc.source: return
    for i in range(10,-1,-1):
        vc.source.volume=i/10
        await asyncio.sleep(0.05)

async def fade_in(vc):
    if not vc or not vc.source: return
    for i in range(11):
        vc.source.volume=i/10
        await asyncio.sleep(0.05)

# ================= UI =================
class SeekSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🎛 이동",
            custom_id="seek_select",
            options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(11)]
        )

    async def callback(self,i):
        await i.response.defer()

class VolumeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🎚 볼륨",
            custom_id="volume_select",
            options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(1,11)]
        )

    async def callback(self,i):
        key=get_key(i)
        v=float(self.values[0])
        volume_level[key]=v

        if i.guild.voice_client and i.guild.voice_client.source:
            i.guild.voice_client.source.volume=v

        await i.response.send_message(volume_bar(v),ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(discord.ui.Button(emoji="⏯️",style=discord.ButtonStyle.success,custom_id="play"))
        self.children[-1].callback=self.pause

        self.add_item(discord.ui.Button(emoji="⏭️",style=discord.ButtonStyle.secondary,custom_id="skip"))
        self.children[-1].callback=self.skip

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

# ================= 음악 =================
async def play_next(i):
    key=get_key(i)
    if not queues.get(key): return

    info=queues[key].pop(0)
    current_track[key]=info

    vc=i.guild.voice_client
    data=await safe_extract(info['webpage_url'])

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'],executable=FFMPEG_PATH),
        volume=0.0
    )

    vc.play(source,after=lambda e:asyncio.run_coroutine_threadsafe(play_next(i),client.loop))
    await fade_in(vc)

    start_time[key]=time.time()

    msg=await i.channel.send(embed=discord.Embed(title="🎧 로딩중..."))
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

async def update_ui(i,info):
    key=get_key(i)
    dur=info.get("duration",180)
    step=0

    while key in start_time:
        el=int(time.time()-start_time[key])
        p=min(el/dur,1)

        embed=discord.Embed(
            title="🎧 Spotify Player",
            description=(
                f"🎵 **{info['title']}**\n\n"
                f"{make_bar(p)}\n"
                f"⏱ {format_time(el)} / {format_time(dur)}\n\n"
                f"{animated_lyrics(step)}\n\n"
                f"{volume_bar(volume_level.get(key,0.5))}"
            ),
            color=0x1DB954
        )

        # 🎬 블러 느낌 → 큰 이미지
        embed.set_image(url=info['thumbnail'])
        embed.set_thumbnail(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed,view=ControlView())
        except:
            pass

        step+=1
        await asyncio.sleep(1)

# ================= 검색 =================
class SearchModal(discord.ui.Modal,title="🎵 검색"):
    query=discord.ui.TextInput(label="노래")

    async def on_submit(self,i):
        await i.response.defer()

        data=await safe_extract(f"ytsearch5:{self.query}")
        results=data["entries"]

        embed=discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx,r in enumerate(results)]),
            color=0xFF0000
        )
        embed.set_image(url=results[0]['thumbnail'])

        view=discord.ui.View(timeout=None)

        for idx,r in enumerate(results):
            btn=discord.ui.Button(label=str(idx+1),custom_id=f"select_{idx}")

            async def cb(interaction,r=r):
                key=get_key(interaction)
                queues.setdefault(key,[])
                queues[key].append(r)

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

    @discord.ui.button(label="🔍 검색",style=discord.ButtonStyle.primary,custom_id="search_btn")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="🔥 인기곡",style=discord.ButtonStyle.success,custom_id="top_btn")
    async def top(self,i,b):
        queues.setdefault(get_key(i),[])
        queues[get_key(i)].append({'webpage_url':"ytsearch:kpop hits"})
        await i.response.send_message("🔥 시작",ephemeral=True)

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    await i.response.send_message("🎧 완전체 음악봇",view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 완전체 실행됨")

client.run(TOKEN)
