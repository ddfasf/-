import discord
from discord import app_commands
import yt_dlp
import asyncio
import time
import os

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

queues = {}
now_playing = {}
start_times = {}

def key(interaction):
    return interaction.guild.id

# 🔥 yt-dlp 안정화 (쿠키 넣으면 더 좋음)
ydl_opts = {
    "format": "bestaudio/best",
    "quiet": True,
    "http_headers": {"User-Agent": "Mozilla/5.0"},
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    # "cookiefile": "cookies.txt"  # 🔥 필요하면 활성화
}

async def extract(query):
    loop = asyncio.get_event_loop()
    def run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(query, download=False)
    return await loop.run_in_executor(None, run)

# 🎨 진행바
def fancy_bar(current, total, length=18):
    total = max(total, 1)
    filled = int(length * current / total)
    return "▰" * filled + "▱" * (length - filled)

# 🎬 플레이어 UI
async def send_player(interaction):
    k = key(interaction)
    song = now_playing[k]

    embed = discord.Embed(
        title="🎧 NOW PLAYING",
        description=f"✨ **{song['title']}** ✨",
        color=0x5865F2
    )

    if song.get("thumbnail"):
        embed.set_thumbnail(url=song["thumbnail"])

    embed.set_image(url="https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif")

    embed.add_field(name="💿 상태", value="▶️ 재생중", inline=True)
    embed.add_field(name="🎶 요청자", value=interaction.user.mention, inline=True)

    view = PlayerView()
    msg = await interaction.channel.send(embed=embed, view=view)

    client.loop.create_task(update_progress(msg, interaction))

# ⏱ 진행바 업데이트
async def update_progress(msg, interaction):
    k = key(interaction)

    while k in now_playing:
        song = now_playing[k]
        elapsed = int(time.time() - start_times[k])
        duration = song.get("duration", 180)

        bar = fancy_bar(elapsed, duration)

        embed = discord.Embed(
            title="🎧 NOW PLAYING",
            description=f"✨ **{song['title']}** ✨\n\n{bar}\n⏱ {elapsed}s / {duration}s",
            color=0x5865F2
        )

        embed.set_image(url="https://media.giphy.com/media/3o7aD2saalBwwftBIY/giphy.gif")

        try:
            await msg.edit(embed=embed)
        except:
            break

        await asyncio.sleep(2)

# 🎛 컨트롤 UI
class PlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏪", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await interaction.response.defer()
        start_times[key(interaction)] -= 10

    @discord.ui.button(label="⏯", style=discord.ButtonStyle.success)
    async def pause(self, interaction, button):
        vc = interaction.guild.voice_client

        if vc and vc.is_playing():
            vc.pause()
            button.label = "▶️"
        elif vc:
            vc.resume()
            button.label = "⏸"

        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="⏩", style=discord.ButtonStyle.secondary)
    async def forward(self, interaction, button):
        await interaction.response.defer()
        start_times[key(interaction)] += 10

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.primary)
    async def skip(self, interaction, button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()

# 🎵 재생
async def play_next(interaction):
    k = key(interaction)
    vc = interaction.guild.voice_client

    if not queues.get(k):
        return

    song = queues[k].pop(0)
    now_playing[k] = song
    start_times[k] = time.time()

    source = discord.FFmpegPCMAudio(
        song["url"],
        executable="ffmpeg"
    )

    def after(e):
        fut = asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop)
        try:
            fut.result()
        except:
            pass

    vc.play(source, after=after)
    await send_player(interaction)

# 🔍 검색 모달
class SearchModal(discord.ui.Modal, title="🎵 검색"):
    query = discord.ui.TextInput(label="검색어")

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer()

        try:
            data = await extract(f"ytsearch5:{self.query}")
            results = data["entries"]
        except Exception as e:
            return await i.followup.send(f"❌ 검색 실패: {e}")

        embed = discord.Embed(
            title="🎬 검색 결과",
            description="\n".join([f"{idx+1}. {r['title']}" for idx, r in enumerate(results)]),
            color=0xFF0000
        )

        view = discord.ui.View(timeout=None)

        for idx, r in enumerate(results):
            btn = discord.ui.Button(label=f"{idx+1}번")

            async def cb(interaction, r=r):
                await interaction.response.defer()

                if not interaction.user.voice:
                    return await interaction.followup.send("❌ 음성채널 먼저 들어가", ephemeral=True)

                k = key(interaction)
                queues.setdefault(k, []).append(r)

                vc = interaction.guild.voice_client
                if not vc:
                    vc = await interaction.user.voice.channel.connect()

                if not vc.is_playing():
                    await play_next(interaction)

                embed2 = discord.Embed(
                    title="📀 QUEUE ADD",
                    description=f"🎵 **{r['title']}**\n✨ 대기열 추가 완료",
                    color=0x00FFAA
                )

                if r.get("thumbnail"):
                    embed2.set_thumbnail(url=r["thumbnail"])

                await interaction.followup.send(embed=embed2, ephemeral=True)

            btn.callback = cb
            view.add_item(btn)

        await i.followup.send(embed=embed, view=view)

# 🎛 패널
class Panel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎵 검색", style=discord.ButtonStyle.success)
    async def search(self, interaction, button):
        await interaction.response.send_modal(SearchModal())

@client.event
GUILD_ID = 1484915814187401259  # 너 서버 ID

@client.event
async def on_ready():
    print("🔥 완전체 실행됨")
    await tree.sync(guild=discord.Object(id=GUILD_ID))


@tree.command(name="panel")
async def panel(interaction: discord.Interaction):
    await interaction.response.send_message("🎧 음악 패널", view=Panel())


@tree.error
async def on_app_command_error(interaction, error):
    print("🔥 에러:", error)

# 🔥 토큰 (환경변수)
client.run(os.environ.get("TOKEN"))
