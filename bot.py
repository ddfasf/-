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
start_time = {}
current_track = {}
loading_state = {}
next_source = {}

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'default_search': 'ytsearch',
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
    return "▰"*int(p*16)+"▱"*(16-int(p*16))

def get_lyrics():
    return "\n".join(random.sample([
        "🌙 이 밤을 따라 흘러가",
        "💫 너와 나의 멜로디",
        "🔥 심장이 뛰는 순간",
        "✨ 끝나지 않을 노래"
    ], 2))

def get_cover(state, thumb):
    if state == "play":
        return random.choice([
            "https://i.imgur.com/3ZQ3Z6K.gif",
            "https://i.imgur.com/lY2Z6sE.gif"
        ])
    elif state == "loading":
        return "https://i.imgur.com/LLF5iyg.gif"
    return thumb

# ================= 상태메세지 =================
async def update_status():
    while True:
        try:
            if current_track:
                any_key = list(current_track.keys())[0]
                title = current_track[any_key]['title'][:30]
                await client.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.listening,
                        name=f"{title}"
                    )
                )
            else:
                await client.change_presence(
                    activity=discord.Game("🎧 음악 대기중")
                )
        except:
            pass

        await asyncio.sleep(5)

# ================= 페이드 =================
async def fade_out(vc):
    if not vc or not vc.source: return
    for i in range(10,-1,-1):
        vc.source.volume=i/10
        await asyncio.sleep(0.08)

async def fade_in(vc):
    if not vc or not vc.source: return
    for i in range(11):
        vc.source.volume=i/10
        await asyncio.sleep(0.08)

# ================= 프리로드 =================
async def preload_next(i):
    key=get_key(i)
    if not queues.get(key): return

    info=queues[key][0]
    data=await safe_extract(info['webpage_url'])
    if not data: return

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'], executable=FFMPEG_PATH),
        volume=0.5
    )
    next_source[key]=(source,info)

# ================= 음악 =================
async def add_to_queue(i,q):
    key=get_key(i)
    queues.setdefault(key,[])

    data=await safe_extract(f"ytsearch1:{q}")
    if not data or not data.get("entries"):
        return await i.channel.send("❌ 검색 실패")

    queues[key].append(data["entries"][0])

async def play_next(i):
    key=get_key(i)
    vc=i.guild.voice_client

    if not queues.get(key):
        return

    loading_state[key]=True

    info=queues[key].pop(0)
    current_track[key]=info

    data=await safe_extract(info['webpage_url'])
    if not data:
        return await play_next(i)

    source=discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'], executable=FFMPEG_PATH),
        volume=0.0
    )

    vc.play(source,after=lambda e:asyncio.run_coroutine_threadsafe(play_next(i),client.loop))
    await fade_in(vc)

    start_time[key]=time.time()
    loading_state[key]=False

    asyncio.create_task(preload_next(i))

    msg=await i.channel.send(
        embed=build_embed(info,0,info.get("duration",180),"play"),
        view=ControlView("play")
    )
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

# ================= UI =================
def build_embed(info,el,dur,state):
    p=min(el/dur,1)

    queue_preview = "\n".join([
        f"{idx+1}. {q['title'][:30]}"
        for idx,q in enumerate(queues.get(next(iter(queues)),[])[:3])
    ]) or "없음"

    embed=discord.Embed(
        title="🎧 Spotify Premium UI",
        description=(
            f"```fix\n{info['title']}\n```\n"
            f"{make_bar(p)}\n"
            f"⏱ {format_time(el)} / {format_time(dur)}\n\n"
            f"{get_lyrics()}\n\n"
            f"📀 다음곡\n{queue_preview}"
        ),
        color=0x1DB954
    )

    embed.set_image(url=get_cover(state, info['thumbnail']))
    embed.set_footer(text=f"상태: {state.upper()} | Ultra Smooth")

    return embed

async def update_ui(i,info):
    key=get_key(i)
    dur=info.get("duration",180)

    while key in start_time:
        vc=i.guild.voice_client
        state="loading" if loading_state.get(key) else ("play" if vc and vc.is_playing() else "pause")

        el=int(time.time()-start_time[key])

        try:
            await player_message[key].edit(
                embed=build_embed(info,el,dur,state),
                view=ControlView(state)
            )
        except:
            pass

        await asyncio.sleep(1)

# ================= 컨트롤 =================
class ControlView(discord.ui.View):
    def __init__(self,state="play"):
        super().__init__(timeout=None)

        emoji="⏸️" if state=="play" else "▶️"
        if state=="loading": emoji="⏳"

        btn=discord.ui.Button(emoji=emoji,style=discord.ButtonStyle.success)
        btn.callback=self.pause
        self.add_item(btn)

        skip=discord.ui.Button(emoji="⏭️")
        skip.callback=self.skip
        self.add_item(skip)

    async def pause(self,i):
        vc=i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()
        await i.response.defer()

    async def skip(self,i):
        vc=i.guild.voice_client
        await fade_out(vc)
        vc.stop()
        await i.response.defer()

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
                await interaction.response.send_message("⏳ 로딩중...",ephemeral=True)
                await add_to_queue(interaction,r['title'])

                if not interaction.guild.voice_client:
                    await interaction.user.voice.channel.connect()

                if not interaction.guild.voice_client.is_playing():
                    await play_next(interaction)

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
        await i.response.send_message("🔥 추가됨",ephemeral=True)

    @discord.ui.button(label="⏹ 정지",style=discord.ButtonStyle.danger)
    async def stop(self,i,b):
        if i.guild.voice_client:
            await fade_out(i.guild.voice_client)
            i.guild.voice_client.stop()
        await i.response.defer()

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    embed=discord.Embed(
        title="🎧 ㅊ서버 음악봇",
        description="버튼 눌러서 바로 사용 ㄱㄱ",
        color=0x1DB954
    )
    await i.response.send_message(embed=embed,view=PanelView())

@client.event
async def setup_hook():
    await tree.sync(guild=discord.Object(id=GUILD_ID))

@client.event
async def on_ready():
    client.add_view(ControlView())
    client.add_view(PanelView())
    client.loop.create_task(update_status())
    print("🔥 Spotify UI 완전체 실행됨")

client.run(TOKEN)
