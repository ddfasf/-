import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import requests
import os
import random
import base64

TOKEN = os.environ.get("TOKEN")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_ID")
SPOTIFY_SECRET = os.environ.get("SPOTIFY_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_KEY")

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
dj_mode = {}
current_track = {}

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(sec):
    return f"{int(sec//60):02}:{int(sec%60):02}"

def make_bar(p):
    return "▰"*int(p*12)+"▱"*(12-int(p*12))

# ================= 가짜 가사 =================
def get_lyrics():
    return "\n".join(random.sample([
        "🌙 이 밤을 따라 흘러가",
        "💫 너와 나의 멜로디",
        "🔥 심장이 뛰는 순간",
        "✨ 끝나지 않을 노래"
    ], 3))

def fake_sync():
    return [(0,"🎶 시작"),(10,"💫 분위기"),(20,"🔥 클라이맥스"),(30,"✨ 후렴")]

# ================= SEEK =================
async def seek_to(i, percent):
    key = get_key(i)
    vc = i.guild.voice_client

    if not vc or key not in current_track:
        return

    info = current_track[key]
    duration = info.get("duration", 180)

    new_time = int(duration * percent)

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(
            info['url'],
            executable=FFMPEG_PATH,
            before_options=f"-ss {new_time}"
        ),
        volume=volume_level.get(key, 0.5)
    )

    vc.stop()
    vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(i), client.loop))

    start_time[key] = time.time() - new_time

# ================= UI =================
class SeekSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🎛 Seek 이동",
            custom_id="seek_select",
            options=[
                discord.SelectOption(label=f"{i*10}%", value=str(i/10))
                for i in range(0,11)
            ]
        )

    async def callback(self, i: discord.Interaction):
        percent = float(self.values[0])
        await seek_to(i, percent)
        await i.response.send_message(f"⏩ {int(percent*100)}% 이동", ephemeral=True)

class VolumeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🎚 Volume",
            custom_id="volume_select",
            options=[
                discord.SelectOption(label=f"{i*10}%", value=str(i/10))
                for i in range(1,11)
            ]
        )

    async def callback(self, i: discord.Interaction):
        key = get_key(i)
        vol = float(self.values[0])
        volume_level[key] = vol

        if i.guild.voice_client and i.guild.voice_client.source:
            i.guild.voice_client.source.volume = vol

        await i.response.send_message(f"🔊 {int(vol*100)}%", ephemeral=True)

# ================= 컨트롤 =================
class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VolumeSelect())
        self.add_item(SeekSelect())

    @discord.ui.button(label="⏯", custom_id="pause_btn")
    async def pause(self,i,b):
        vc=i.guild.voice_client
        if vc.is_playing(): vc.pause()
        else: vc.resume()
        await i.response.defer()

    @discord.ui.button(label="⏭", custom_id="skip_btn")
    async def skip(self,i,b):
        i.guild.voice_client.stop()
        await i.response.defer()

    @discord.ui.button(label="⏪", custom_id="back_btn")
    async def back(self,i,b):
        await seek_to(i, 0.1)  # 약간 뒤로

    @discord.ui.button(label="⏩", custom_id="forward_btn")
    async def forward(self,i,b):
        await seek_to(i, 0.9)  # 약간 앞으로

# ================= 유튜브 선택 =================
class YouTubeSelectView(discord.ui.View):
    def __init__(self, results):
        super().__init__(timeout=60)
        for idx,r in enumerate(results):
            self.add_item(YouTubeButton(idx,r))

class YouTubeButton(discord.ui.Button):
    def __init__(self, idx, info):
        super().__init__(label=str(idx+1),style=discord.ButtonStyle.green)
        self.info=info

    async def callback(self, i):
        key=get_key(i)
        queues.setdefault(key,[])
        queues[key].append(self.info)

        if not i.guild.voice_client:
            await i.user.voice.channel.connect()

        if not i.guild.voice_client.is_playing():
            await play_next(i)

        await i.response.defer()

# ================= 음악 =================
async def play_next(i):
    key=get_key(i)

    if not queues.get(key):
        return

    info=queues[key].pop(0)
    current_track[key]=info

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(info['url'],executable=FFMPEG_PATH),
        volume=volume_level.get(key,0.5)
    )

    vc=i.guild.voice_client
    vc.play(source,after=lambda e:asyncio.run_coroutine_threadsafe(play_next(i),client.loop))

    start_time[key]=time.time()

    msg=await i.channel.send(
        embed=discord.Embed(title="🎧 Now Playing",description=info['title']),
        view=ControlView()
    )
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

async def update_ui(i,info):
    key=get_key(i)
    dur=info.get('duration',180)

    while key in start_time:
        el=int(time.time()-start_time[key])
        p=min(el/dur,1)

        embed=discord.Embed(
            title="🎧 Now Playing",
            description=f"{info['title']}\n{make_bar(p)}\n⏱ {format_time(el)}/{format_time(dur)}\n\n{get_lyrics()}",
            color=0x1DB954
        )
        embed.set_image(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed,view=ControlView())
        except:
            pass

        await asyncio.sleep(1)

# ================= 검색 =================
class SearchModal(discord.ui.Modal,title="🎵 검색"):
    query=discord.ui.TextInput(label="노래")

    async def on_submit(self,i):
        await i.response.defer()

        with yt_dlp.YoutubeDL({'format':'bestaudio'}) as ydl:
            data=ydl.extract_info(f"ytsearch5:{self.query}",download=False)

        results=data["entries"]

        embed=discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx,r in enumerate(results)]),
            color=0xFF0000
        )
        embed.set_image(url=results[0]['thumbnail'])

        await i.followup.send(embed=embed,view=YouTubeSelectView(results))

# ================= 패널 =================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색",custom_id="search_btn")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    await i.response.send_message("🎧 음악봇 준비 완료",view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 완전체 실행됨")

client.run(TOKEN)
