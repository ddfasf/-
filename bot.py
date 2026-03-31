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
preloaded = {}

# ================= yt-dlp =================
YDL_OPTS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True,
    'default_search': 'ytsearch',
    'ignoreerrors': True,
}

async def safe_extract(q):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            return ydl.extract_info(q, download=False)
    try:
        return await loop.run_in_executor(None, run)
    except:
        return None

# ================= 기본 =================
def get_key(i):
    return f"{i.guild.id}_{i.channel.id}"

def format_time(s):
    return f"{int(s//60):02}:{int(s%60):02}"

def bar(p):
    return "🟢"*int(p*10)+"⚫"*(10-int(p*10))

def lyrics():
    return random.choice([
        "🌙 감정이 흐르는 밤",
        "💫 너와 나의 멜로디",
        "🔥 심장이 반응해",
        "✨ 끝나지 않는 순간"
    ])

# ================= 페이드 =================
async def fade(vc, start, end):
    if not vc or not vc.source: return
    step = (end - start)/10
    vol = start
    for _ in range(10):
        vc.source.volume = vol
        vol += step
        await asyncio.sleep(0.1)

# ================= SEEK =================
async def seek(i, percent):
    key = get_key(i)
    vc = i.guild.voice_client
    if key not in current_track: return

    info = current_track[key]
    dur = info.get("duration", 180)
    t = int(dur * percent)

    data = await safe_extract(info['webpage_url'])
    if not data: return

    src = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(
            data['url'],
            executable=FFMPEG_PATH,
            before_options=f"-ss {t}"
        ), volume=0
    )

    await fade(vc, 1, 0)
    vc.stop()
    vc.play(src)
    await fade(vc, 0, 1)

    start_time[key] = time.time() - t

# ================= UI =================
class SeekUI(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="🎚 이동",
        options=[discord.SelectOption(label=f"{i*10}%",value=str(i/10)) for i in range(11)],
        custom_id="seek")

    async def callback(self,i):
        await i.response.defer()
        await seek(i,float(self.values[0]))

class ControlView(discord.ui.View):
    def __init__(self,state="play"):
        super().__init__(timeout=None)

        emoji = "⏸️" if state=="play" else "▶️"

        btn = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.success, custom_id="play")
        btn.callback = self.pause
        self.add_item(btn)

        for e,cb,cid in [
            ("⏮️",self.back,"back"),
            ("⏭️",self.skip,"skip")
        ]:
            b = discord.ui.Button(emoji=e,style=discord.ButtonStyle.secondary,custom_id=cid)
            b.callback = cb
            self.add_item(b)

        self.add_item(SeekUI())

    async def pause(self,i):
        vc=i.guild.voice_client
        vc.pause() if vc.is_playing() else vc.resume()
        await i.response.defer()

    async def skip(self,i):
        vc=i.guild.voice_client
        await fade(vc,1,0)
        vc.stop()
        await i.response.defer()

    async def back(self,i):
        await seek(i,0.1)

# ================= 프리로드 =================
async def preload_next(i):
    key = get_key(i)
    if not queues.get(key): return

    next_track = queues[key][0]
    data = await safe_extract(next_track['webpage_url'])
    if data:
        preloaded[key] = data

# ================= 음악 =================
async def add_queue(i,q):
    key=get_key(i)
    queues.setdefault(key,[])
    data=await safe_extract(f"ytsearch1:{q}")
    if not data: return
    queues[key].append(data['entries'][0])

async def play_next(i):
    key=get_key(i)
    if not queues.get(key):
        # 자동 추천
        await add_queue(i,"kpop playlist")
    
    info=queues[key].pop(0)
    current_track[key]=info
    vc=i.guild.voice_client

    data = preloaded.get(key) or await safe_extract(info['webpage_url'])

    src = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(data['url'], executable=FFMPEG_PATH),
        volume=0
    )

    vc.play(src,after=lambda e:asyncio.run_coroutine_threadsafe(play_next(i),client.loop))
    await fade(vc,0,1)

    start_time[key]=time.time()

    await preload_next(i)

    msg = await i.channel.send(embed=make_embed(info,i),view=ControlView())
    player_message[key]=msg

    asyncio.create_task(update_ui(i,info))

# ================= UI =================
def make_embed(info,i):
    key=get_key(i)

    queue_preview = ""
    if queues.get(key):
        queue_preview="\n".join([f"➡ {q['title'][:25]}" for q in queues[key][:3]])

    embed=discord.Embed(
        title="🎧 Spotify Player",
        description=f"""
**{info['title']}**

{bar(0)}

🎶 {lyrics()}

📀 다음곡:
{queue_preview if queue_preview else '없음'}
""",
        color=0x1DB954
    )

    embed.set_thumbnail(url=info['thumbnail'])
    embed.set_footer(text="🔥 Ultra Music System")

    return embed

async def update_ui(i,info):
    key=get_key(i)
    dur=info.get("duration",180)

    while key in start_time:
        vc=i.guild.voice_client
        state="play" if vc and vc.is_playing() else "pause"

        el=int(time.time()-start_time[key])
        p=min(el/dur,1)

        embed=make_embed(info,i)
        embed.description=embed.description.replace(bar(0),bar(p)) + f"\n⏱ {format_time(el)}/{format_time(dur)}"

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
        if not data: return

        results=data["entries"]

        embed=discord.Embed(title="🎬 검색 결과",
        description="\n".join([f"{idx+1}. {r['title']}" for idx,r in enumerate(results)]))

        view=discord.ui.View()

        for idx,r in enumerate(results):
            btn=discord.ui.Button(label=str(idx+1))

            async def cb(interaction,r=r):
                await add_queue(interaction,r['title'])
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

    @discord.ui.button(label="🔍 검색",style=discord.ButtonStyle.primary,custom_id="search")
    async def search(self,i,b):
        await i.response.send_modal(SearchModal())

    @discord.ui.button(label="🔥 인기곡",style=discord.ButtonStyle.success,custom_id="top")
    async def top(self,i,b):
        await add_queue(i,"kpop hits")
        await i.response.send_message("🔥 추가 완료")

    @discord.ui.button(label="📊 대기열",style=discord.ButtonStyle.secondary,custom_id="queue")
    async def queue_btn(self,i,b):
        key=get_key(i)
        q=queues.get(key,[])
        txt="\n".join([f"{idx+1}. {t['title']}" for idx,t in enumerate(q[:10])])
        await i.response.send_message(f"📀 대기열\n{txt if txt else '없음'}")

# ================= 실행 =================
@tree.command(name="셋업",guild=discord.Object(id=GUILD_ID))
async def setup(i:discord.Interaction):
    embed=discord.Embed(
        title="🎧 Spotify Ultra Player",
        description="""
🔥 완전 자동 음악 시스템

🎶 자동 추천
📀 앨범 UI
📊 대기열 관리
🎚 실시간 조작

버튼 눌러서 시작 ㄱㄱ
""",
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
    print("🔥 Spotify급 봇 실행 완료")

client.run(TOKEN)
