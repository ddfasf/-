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

# ================= Spotify =================
def get_spotify_token():
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    data = {"grant_type": "client_credentials"}
    r = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data)
    return r.json().get("access_token")

def spotify_search(query):
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"https://api.spotify.com/v1/search?q={query}&type=track&limit=5",
        headers=headers
    )
    return r.json()["tracks"]["items"]

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(sec):
    return f"{int(sec//60):02}:{int(sec%60):02}"

def make_bar(progress):
    total = 12
    filled = int(progress * total)
    return "▰"*filled + "▱"*(total-filled)

# ================= 볼륨 =================
class VolumeSelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(1,11)]
        super().__init__(placeholder="🎚 Volume",options=options)

    async def callback(self,i):
        key=get_key(i)
        vol=float(self.values[0])
        volume_level[key]=vol
        vc=i.guild.voice_client
        if vc and vc.source:
            vc.source.volume=vol
        await i.response.send_message(f"🔊 {int(vol*100)}%",ephemeral=True)

# ================= Spotify 하단 UI =================
class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VolumeSelect())

    @discord.ui.button(label="⏮")
    async def prev(self,i,b):
        await i.response.defer()

    @discord.ui.button(label="⏯")
    async def pause(self,i,b):
        vc=i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()
        await i.response.defer()

    @discord.ui.button(label="⏭")
    async def skip(self,i,b):
        i.guild.voice_client.stop()
        await i.response.defer()

    @discord.ui.button(label="🔁")
    async def dj(self,i,b):
        key=get_key(i)
        dj_mode[key]=not dj_mode.get(key,False)
        await i.response.send_message(f"🔁 DJ {'ON' if dj_mode[key] else 'OFF'}",ephemeral=True)

# ================= 앨범 UI =================
class AlbumView(discord.ui.View):
    def __init__(self, tracks):
        super().__init__(timeout=60)
        self.tracks = tracks

        for idx, t in enumerate(tracks):
            self.add_item(SongButton(idx, t))

        self.add_item(PlayAllButton(tracks))

class SongButton(discord.ui.Button):
    def __init__(self, index, track):
        super().__init__(label=f"{index+1}️⃣", style=discord.ButtonStyle.green)
        self.track = track

    async def callback(self, i):
        query = f"{self.track['name']} {self.track['artists'][0]['name']}"
        await add_and_play(i, query)
        await i.response.defer()

class PlayAllButton(discord.ui.Button):
    def __init__(self, tracks):
        super().__init__(label="▶️ 전체재생", style=discord.ButtonStyle.blurple)
        self.tracks = tracks

    async def callback(self, i):
        for t in self.tracks:
            query = f"{t['name']} {t['artists'][0]['name']}"
            await add_to_queue(i, query)
        await i.response.send_message("💿 앨범 전체 재생 시작!", ephemeral=True)

# ================= 음악 =================
async def add_to_queue(i, query):
    key=get_key(i)
    queues.setdefault(key,[])

    with yt_dlp.YoutubeDL({'format':'bestaudio'}) as ydl:
        data=ydl.extract_info(f"ytsearch:{query}",download=False)
        info=data['entries'][0]

    queues[key].append(info)

async def add_and_play(i,query):
    await add_to_queue(i,query)

    vc=i.guild.voice_client
    if not vc:
        await i.user.voice.channel.connect()

    if not vc.is_playing():
        await play_next(i)

async def play_next(i):
    key=get_key(i)

    if not queues.get(key):
        if dj_mode.get(key,False):
            await add_and_play(i,"kpop playlist")
            return
        return

    info=queues[key].pop(0)

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(info['url'],executable=FFMPEG_PATH),
        volume=volume_level.get(key,0.5)
    )

    vc=i.guild.voice_client

    def after(e):
        asyncio.run_coroutine_threadsafe(play_next(i),client.loop)

    vc.play(source,after=after)
    start_time[key]=time.time()

    embed=discord.Embed(
        title="🎧 Now Playing",
        description=f"{info['title']}",
        color=0x1DB954
    )
    embed.set_image(url=info['thumbnail'])

    msg=await i.channel.send(embed=embed,view=ControlView())
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

# ================= UI =================
async def update_ui(i,info):
    key=get_key(i)
    duration=info.get('duration',180)

    while key in start_time:
        elapsed=time.time()-start_time[key]
        progress=min(elapsed/duration,1)

        embed=discord.Embed(
            title="🎧 Now Playing",
            description=f"{info['title']}\n{make_bar(progress)}\n⏱ {format_time(elapsed)} / {format_time(duration)}",
            color=0x1DB954
        )
        embed.set_image(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed,view=ControlView())
        except:
            pass

        await asyncio.sleep(1)

# ================= 검색 =================
class SearchModal(discord.ui.Modal,title="🎵 Spotify 검색"):
    query=discord.ui.TextInput(label="노래")

    async def on_submit(self,i):
        tracks = spotify_search(self.query)

        embed = discord.Embed(
            title="💿 앨범 선택",
            description="\n".join([
                f"{idx+1}. {t['name']} - {t['artists'][0]['name']}"
                for idx, t in enumerate(tracks)
            ]),
            color=0x1DB954
        )
        embed.set_thumbnail(url=tracks[0]['album']['images'][0]['url'])

        await i.response.send_message(embed=embed, view=AlbumView(tracks))

# ================= 패널 =================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    embed=discord.Embed(
        title="🎧 Spotify 완전체 음악봇",
        description="🔍 검색 → 앨범 → 선택 or 전체재생",
        color=0xFFB6C1
    )
    embed.set_image(url="https://i.imgur.com/8Km9tLL.gif")
    await i.response.send_message(embed=embed, view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 진짜 끝판왕 실행됨")

client.run(TOKEN)
