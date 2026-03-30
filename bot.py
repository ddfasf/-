import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import json
import requests

TOKEN = "MTQ4ODE4MjA4OTk3MDA5MDE0NQ.GJ13QV.G-FTejkv4V6nWdvOOWlZ6xcYCwUNW10_TDt388"
GUILD_ID = 1484915814187401259
FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
GENIUS_TOKEN = "여기에_Genius_API"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
player_message = {}
panel_message = {}
volume_level = {}
start_time = {}

MELON = ["아이유 Love wins all","NewJeans Hype Boy"]
BILLBOARD = ["Taylor Swift Cruel Summer","Doja Cat Paint The Town Red"]
MAD = ["valorant montage","gaming montage"]

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def make_bar(progress):
    total = 15
    filled = int(progress * total)
    return "▰"*filled + "▱"*(total-filled)

def reset_player(key):
    start_time.pop(key, None)
    if key in player_message:
        try:
            asyncio.create_task(player_message[key].delete())
        except:
            pass
        player_message.pop(key, None)

# ================= 권한 =================
def is_same_voice(i):
    vc = i.guild.voice_client
    if not vc:
        return True
    return i.user.voice and i.user.voice.channel == vc.channel

# ================= 가사 =================
def get_lyrics(query):
    try:
        headers = {"Authorization": f"Bearer {GENIUS_TOKEN}"}
        res = requests.get(f"https://api.genius.com/search?q={query}", headers=headers)
        data = res.json()
        return data["response"]["hits"][0]["result"]["url"]
    except:
        return "가사 없음"

# ================= 플레이리스트 =================
def save_playlist(user_id, song):
    try:
        with open("playlist.json","r") as f:
            data=json.load(f)
    except:
        data={}
    data.setdefault(str(user_id),[]).append(song)
    with open("playlist.json","w") as f:
        json.dump(data,f)

def load_playlist(user_id):
    try:
        with open("playlist.json","r") as f:
            return json.load(f).get(str(user_id),[])
    except:
        return []

# ================= 자동 추천 =================
def auto_recommend(title):
    return f"{title} playlist"

# ================= 패널 =================
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔍 검색", style=discord.ButtonStyle.green, custom_id="panel_search")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="🍈 멜론", style=discord.ButtonStyle.blurple, custom_id="panel_melon")
    async def melon(self,i,b):
        await i.response.defer()
        for s in MELON:
            await add_and_play(i,s)

    @discord.ui.button(label="📊 빌보드", style=discord.ButtonStyle.blurple, custom_id="panel_billboard")
    async def bill(self,i,b):
        await i.response.defer()
        for s in BILLBOARD:
            await add_and_play(i,s)

    @discord.ui.button(label="🎬 매드무비", style=discord.ButtonStyle.gray, custom_id="panel_mad")
    async def mad(self,i,b):
        await i.response.defer()
        for s in MAD:
            await add_and_play(i,s)

# ================= 플레이어 =================
class PlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def check(self, i):
        if not is_same_voice(i):
            asyncio.create_task(i.response.send_message("❌ 같은 음성채널만 조작 가능", ephemeral=True))
            return False
        return True

    @discord.ui.button(label="⏯", custom_id="player_pause")
    async def pause(self,i,b):
        if not self.check(i): return
        vc=i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()
        await i.response.defer()

    @discord.ui.button(label="⏭", custom_id="player_skip")
    async def skip(self,i,b):
        if not self.check(i): return
        key=get_key(i)
        reset_player(key)
        i.guild.voice_client.stop()
        await i.response.defer()

    @discord.ui.button(label="⏹", style=discord.ButtonStyle.red, custom_id="player_stop")
    async def stop(self,i,b):
        if not self.check(i): return
        key=get_key(i)
        vc=i.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        reset_player(key)
        await show_panel(i)
        await i.response.defer()

    @discord.ui.button(label="🔍", style=discord.ButtonStyle.green, custom_id="player_search")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="📃", custom_id="player_queue")
    async def queue(self,i,b):
        key=get_key(i)
        q=queues.get(key,[])
        text="\n".join([f"{idx+1}. {x['title']}" for idx,x in enumerate(q[:10])]) or "없음"
        await i.response.send_message(text,ephemeral=True)

    @discord.ui.button(label="🎤", custom_id="player_lyrics")
    async def lyrics(self,i,b):
        msg=player_message.get(get_key(i))
        if msg:
            title=msg.embeds[0].description
            await i.response.send_message(get_lyrics(title),ephemeral=True)

    @discord.ui.button(label="❤️", custom_id="player_like")
    async def like(self,i,b):
        msg=player_message.get(get_key(i))
        if msg:
            title=msg.embeds[0].description
            save_playlist(i.user.id,title)
            await i.response.send_message("저장됨",ephemeral=True)

# ================= 검색 =================
class SearchModal(discord.ui.Modal,title="🎵 음악 검색"):
    query=discord.ui.TextInput(label="노래 입력")

    async def on_submit(self,i):
        await i.response.defer()
        await add_and_play(i,self.query)

# ================= 음악 =================
async def add_and_play(i,query):
    key=get_key(i)
    queues.setdefault(key,[])

    with yt_dlp.YoutubeDL({'format':'bestaudio'}) as ydl:
        data=ydl.extract_info(f"ytsearch:{query}",download=False)
        info=data['entries'][0]

    queues[key].append(info)

    vc=i.guild.voice_client

    if vc and vc.is_playing():
        return

    if not vc:
        await i.user.voice.channel.connect()

    await play_next(i)

async def play_next(i):
    key=get_key(i)

    # 🔥 패널 제거
    if key in panel_message:
        try: await panel_message[key].delete()
        except: pass
        panel_message.pop(key,None)

    reset_player(key)

    if not queues.get(key):
        await show_panel(i)
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

    embed=discord.Embed(title="🎶 Now Playing",description=info['title'],color=0x1DB954)
    embed.set_image(url=info['thumbnail'])

    msg=await i.channel.send(embed=embed,view=PlayerView())
    player_message[key]=msg

    asyncio.create_task(update_bar(i,info))

# ================= 진행바 =================
async def update_bar(i,info):
    key=get_key(i)
    duration=info.get('duration',180)

    while key in start_time:
        elapsed=int(time.time()-start_time[key])
        progress=min(elapsed/duration,1)

        embed=discord.Embed(
            title="🎶 Now Playing",
            description=f"{info['title']}\n{make_bar(progress)}",
            color=0x1DB954
        )
        embed.set_image(url=info['thumbnail'])

        try:
            await player_message[key].edit(embed=embed,view=PlayerView())
        except:
            pass

        await asyncio.sleep(1)

# ================= 패널 =================
async def show_panel(i):
    embed=discord.Embed(
        title="🎧 귀여운 음악봇",
        description="🔍 검색 | 🍈 멜론 | 📊 빌보드 | 🎬 매드무비",
        color=0xFFB6C1
    )
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1484934261160153109/1488251973290557672/content.png?ex=69cc1a28&is=69cac8a8&hm=1221fc03ba8817ad0445d14383e2775766f3070cee28e09c6a59c295e5c1c961&=&format=webp&quality=lossless&width=385&height=385")
    embed.set_image(url="https://media.discordapp.net/attachments/1484934261160153109/1488251902394110022/content.png?ex=69cc1a17&is=69cac897&hm=8d26ff637fc9367f069efc314d1e24ddd514f23ae167ca99ff88760c22af5569&=&format=webp&quality=lossless&width=578&height=385")

    msg=await i.channel.send(embed=embed,view=PanelView())
    panel_message[get_key(i)]=msg

# ================= 명령어 (관리자 전용) =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(administrator=True)
async def setup(i:discord.Interaction):
    await show_panel(i)
    await i.response.defer()

@setup.error
async def setup_error(i: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await i.response.send_message("❌ 관리자만 사용 가능", ephemeral=True)

# ================= 실행 =================
@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(PanelView())
    client.add_view(PlayerView())
    print("🔥 REAL FINAL COMPLETE")

client.run(TOKEN)
