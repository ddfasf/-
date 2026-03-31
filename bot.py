import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import requests
import os
import random
import base64

# ================= 환경 =================
TOKEN = os.environ.get("TOKEN")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_ID")
SPOTIFY_SECRET = os.environ.get("SPOTIFY_SECRET")
MUSIXMATCH_KEY = os.environ.get("LYRICS_KEY")
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

def get_playlist_tracks(url):
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    playlist_id = url.split("/")[-1].split("?")[0]

    r = requests.get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
        headers=headers
    )

    items = r.json()["items"]
    return [f"{t['track']['name']} {t['track']['artists'][0]['name']}" for t in items]

def smart_recommend(title):
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(
        f"https://api.spotify.com/v1/search?q={title}&type=track&limit=1",
        headers=headers
    )
    track = r.json()["tracks"]["items"][0]

    rec = requests.get(
        f"https://api.spotify.com/v1/recommendations?seed_tracks={track['id']}&limit=5",
        headers=headers
    )

    return [f"{t['name']} {t['artists'][0]['name']}" for t in rec.json()["tracks"]]

# ================= GPT 감정 =================
def analyze_mood(text):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "happy, sad, chill, angry 중 하나로 답해"},
            {"role": "user", "content": text}
        ]
    }

    res = requests.post(url, headers=headers, json=data)
    return res.json()["choices"][0]["message"]["content"].strip()

def mood_to_query(mood):
    return {
        "happy": "kpop upbeat",
        "sad": "sad ballad",
        "chill": "lofi chill",
        "angry": "phonk aggressive"
    }.get(mood, "kpop playlist")

# ================= 가사 =================
def get_lyrics(title):
    try:
        url = "https://api.musixmatch.com/ws/1.1/matcher.lyrics.get"
        params = {"q_track": title, "apikey": MUSIXMATCH_KEY}
        res = requests.get(url, params=params)
        return res.json()["message"]["body"]["lyrics"]["lyrics_body"][:500]
    except:
        return "가사 없음"

def fake_sync():
    return [
        (0, "🎶 시작"),
        (10, "💫 분위기"),
        (20, "🔥 클라이맥스"),
        (30, "✨ 후렴"),
    ]

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(sec):
    return f"{int(sec//60):02}:{int(sec%60):02}"

def make_bar(p):
    return "▰"*int(p*12)+"▱"*(12-int(p*12))

# ================= 볼륨 =================
class VolumeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🎚 Volume",
            options=[discord.SelectOption(label=f"{i*10}%", value=str(i/10)) for i in range(1,11)]
        )

    async def callback(self, i):
        key = get_key(i)
        vol = float(self.values[0])
        volume_level[key] = vol

        if i.guild.voice_client:
            i.guild.voice_client.source.volume = vol

        await i.response.send_message(f"🔊 {int(vol*100)}%", ephemeral=True)

# ================= 컨트롤 =================
class ControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(VolumeSelect())

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
        await i.response.send_message(f"DJ {'ON' if dj_mode[key] else 'OFF'}",ephemeral=True)

    @discord.ui.button(label="🧠 추천")
    async def mood(self,i,b):
        await i.response.send_message("기분 입력해줘",ephemeral=True)
        msg=await client.wait_for("message",check=lambda m:m.author==i.user)
        mood=analyze_mood(msg.content)
        await add_and_play(i,mood_to_query(mood))

    @discord.ui.button(label="📀 Playlist")
    async def playlist(self,i,b):
        await i.response.send_message("링크 보내",ephemeral=True)
        msg=await client.wait_for("message",check=lambda m:m.author==i.user)
        tracks=get_playlist_tracks(msg.content)
        for t in tracks:
            await add_to_queue(i,t)
        await i.channel.send("추가 완료")

# ================= 음악 =================
async def add_to_queue(i,q):
    key=get_key(i)
    queues.setdefault(key,[])

    with yt_dlp.YoutubeDL({'format':'bestaudio'}) as ydl:
        info=ydl.extract_info(f"ytsearch:{q}",download=False)['entries'][0]

    queues[key].append(info)

async def add_and_play(i,q):
    await add_to_queue(i,q)
    if not i.guild.voice_client:
        await i.user.voice.channel.connect()
    if not i.guild.voice_client.is_playing():
        await play_next(i)

async def play_next(i):
    key=get_key(i)

    if not queues.get(key):
        if dj_mode.get(key):
            for r in smart_recommend("kpop"):
                await add_to_queue(i,r)
            return await play_next(i)
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

    msg=await i.channel.send(embed=discord.Embed(title="🎧 Now Playing",description=info['title'],color=0x1DB954),view=ControlView())
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

# ================= UI =================
async def update_ui(i,info):
    key=get_key(i)
    dur=info.get('duration',180)
    lyrics=get_lyrics(info['title'])
    sync=fake_sync()

    while key in start_time:
        el=int(time.time()-start_time[key])
        p=min(el/dur,1)

        line=""
        for t,l in sync:
            if el>=t:
                line=l

        embed=discord.Embed(
            title="🎧 Now Playing",
            description=f"{info['title']}\n{make_bar(p)}\n⏱ {format_time(el)}/{format_time(dur)}\n\n🎤 {line}\n\n{lyrics[:200]}",
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
        tracks=spotify_search(self.query)

        embed=discord.Embed(
            title="📀 선택",
            description="\n".join([f"{idx+1}. {t['name']} - {t['artists'][0]['name']}" for idx,t in enumerate(tracks)]),
            color=0x1DB954
        )
        embed.set_thumbnail(url=tracks[0]['album']['images'][0]['url'])

        await i.response.send_message(embed=embed)

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
        title="🎧 Spotify급 음악봇",
        description="검색 → 재생 → AI 추천",
        color=0xFFB6C1
    )
    await i.response.send_message(embed=embed,view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    print("🔥 끝판왕 실행됨")

client.run(TOKEN)
