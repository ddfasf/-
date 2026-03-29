import discord
from discord import app_commands
from discord.ext import tasks
import yt_dlp
import asyncio
import datetime

# ==========================
# 설정
# ==========================
TOKEN = "MTQ4NzM1NTkyNjcxNjYxNjgxNA.GoFZud.4yujM8tdXgYLpBZcuf9GoC6BWUSlG3e5BLToGA"
GUILD_ID = 1484915814187401259
FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"

# Intents 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Client 생성
client = discord.Client(intents=intents, application_id=1487355926716616814)
tree = app_commands.CommandTree(client)

# ==========================
# 글로벌 변수
# ==========================
queues = {}
current_song = {}
volume = {}
announcements = []  # 예약 공지 [(datetime, channel_id, message)]

# ==========================
# 음악 관련 함수
# ==========================
async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client
    if guild_id in queues and queues[guild_id]:
        title, url = queues[guild_id].pop(0)
        current_song[guild_id] = title
        # 상태 메시지 업데이트
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=f"▶️ {title}"))
        source = discord.FFmpegPCMAudio(url, executable=FFMPEG_PATH)
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), client.loop))
    else:
        current_song[guild_id] = None
        # 대기 상태 메시지로 변경
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="열공 중!"))

# ==========================
# 봇 준비
# ==========================
@client.event
async def setup_hook():
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    announcement_loop.start()
    print(f"✅ 봇 준비 완료: {client.user}")

@client.event
async def on_ready():
    # WebSocket 연결 완료 후 상태 메시지 설정
    await client.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, 
        name="열공 중!"
    ))
    print(f"✅ 봇 연결 완료: {client.user}")

# ==========================
# 음악 명령어
# ==========================
@tree.command(name="재생", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(검색어="노래 제목 또는 링크")
async def play(interaction: discord.Interaction, 검색어: str):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ 음성채널 먼저 들어가세요", ephemeral=True)
        return
    guild_id = interaction.guild.id
    if guild_id not in queues: queues[guild_id] = []
    await interaction.response.defer()
    with yt_dlp.YoutubeDL({'format': 'bestaudio'}) as ydl:
        info = ydl.extract_info(f"ytsearch:{검색어}" if not 검색어.startswith("http") else 검색어, download=False)
        if 'entries' in info: info = info['entries'][0]
        url = info['url']
        title = info['title']
    queues[guild_id].append((title, url))
    vc = interaction.guild.voice_client
    if not vc: vc = await interaction.user.voice.channel.connect()
    if not vc.is_playing(): await play_next(interaction)
    await interaction.followup.send(f"🎵 추가됨: {title}")

@tree.command(name="스킵", guild=discord.Object(id=GUILD_ID))
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        await interaction.response.send_message("❌ 재생중인 노래 없음", ephemeral=True)
        return
    vc.stop()
    await interaction.response.send_message("⏭️ 스킵 완료")

@tree.command(name="정지", guild=discord.Object(id=GUILD_ID))
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        queues[interaction.guild.id] = []
        current_song[interaction.guild.id] = None
        # 상태 메시지 초기화
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="/재생 | 민수봇"))
        await interaction.response.send_message("⏹️ 정지 완료")

@tree.command(name="대기열", guild=discord.Object(id=GUILD_ID))
async def queue_list(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in queues or not queues[guild_id]:
        await interaction.response.send_message("📭 대기열 비어있음")
        return
    msg = "\n".join(f"{i+1}. {title}" for i, (title, _) in enumerate(queues[guild_id]))
    await interaction.response.send_message(f"📜 대기열:\n{msg}")

@tree.command(name="볼륨", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(레벨="0~200")
async def set_volume(interaction: discord.Interaction, 레벨: int):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client
    if not vc or not vc.is_playing():
        await interaction.response.send_message("❌ 재생중인 노래 없음", ephemeral=True)
        return
    레벨 = max(0, min(레벨, 200))
    vc.source = discord.PCMVolumeTransformer(vc.source, volume=레벨/100)
    volume[guild_id] = 레벨
    await interaction.response.send_message(f"🔊 볼륨: {레벨}%")

@tree.command(name="현재곡", guild=discord.Object(id=GUILD_ID))
async def now_playing(interaction: discord.Interaction):
    title = current_song.get(interaction.guild.id)
    if title:
        await interaction.response.send_message(f"▶️ 현재 재생중: {title}")
    else:
        await interaction.response.send_message("❌ 현재 재생 중인 곡 없음")

# ==========================
# 서버 관리 명령어
# ==========================
@tree.command(name="밴", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(대상="밴할 멤버", 이유="사유")
async def ban(interaction: discord.Interaction, 대상: discord.Member, 이유: str = "없음"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ 권한 없음", ephemeral=True)
        return
    await 대상.ban(reason=이유)
    await interaction.response.send_message(f"🔨 {대상} 밴됨 | 이유: {이유}")

@tree.command(name="킥", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(대상="킥할 멤버", 이유="사유")
async def kick(interaction: discord.Interaction, 대상: discord.Member, 이유: str = "없음"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ 권한 없음", ephemeral=True)
        return
    await 대상.kick(reason=이유)
    await interaction.response.send_message(f"👢 {대상} 킥됨 | 이유: {이유}")

# ==========================
# 공지 명령어
# ==========================
@tree.command(name="공지", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(채널="공지 채널", 메시지="공지 내용")
async def announce(interaction: discord.Interaction, 채널: discord.TextChannel, 메시지: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return
    await 채널.send(f"📢 {메시지}")
    await interaction.response.send_message("✅ 공지 완료")

@tree.command(name="임베드공지", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(채널="공지 채널", 제목="제목", 내용="내용")
async def embed_announce(interaction: discord.Interaction, 채널: discord.TextChannel, 제목: str, 내용: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return
    embed = discord.Embed(title=제목, description=내용, color=discord.Color.blue())
    await 채널.send(embed=embed)
    await interaction.response.send_message("✅ 임베드 공지 완료")

@tree.command(name="예약공지", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(채널="채널", 메시지="메시지", 시각="YYYY-MM-DD HH:MM")
async def schedule_announce(interaction: discord.Interaction, 채널: discord.TextChannel, 메시지: str, 시각: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return
    dt = datetime.datetime.strptime(시각, "%Y-%m-%d %H:%M")
    announcements.append((dt, 채널.id, 메시지))
    await interaction.response.send_message(f"🕒 {시각} 예약됨")

@tree.command(name="dm공지", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(메시지="DM으로 보낼 내용")
async def dm_announce(interaction: discord.Interaction, 메시지: str):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ 관리자만 가능", ephemeral=True)
        return
    for member in interaction.guild.members:
        try:
            await member.send(f"📩 {메시지}")
        except:
            continue
    await interaction.response.send_message("✅ DM 전송 완료")

# ==========================
# 투표 명령어
# ==========================
@tree.command(name="투표", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(제목="투표 제목", 옵션1="옵션1", 옵션2="옵션2", 옵션3="옵션3")
async def poll(interaction: discord.Interaction, 제목: str, 옵션1: str, 옵션2: str, 옵션3: str = None):
    embed = discord.Embed(title=f"📊 {제목}", color=discord.Color.green())
    embed.add_field(name="1️⃣", value=옵션1, inline=False)
    embed.add_field(name="2️⃣", value=옵션2, inline=False)
    if 옵션3: embed.add_field(name="3️⃣", value=옵션3, inline=False)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("1️⃣")
    await msg.add_reaction("2️⃣")
    if 옵션3: await msg.add_reaction("3️⃣")
    await interaction.response.send_message("✅ 투표 생성 완료", ephemeral=True)

# ==========================
# 예약 공지 루프
# ==========================
@tasks.loop(seconds=30)
async def announcement_loop():
    now = datetime.datetime.now()
    for ann in announcements[:]:
        dt, channel_id, msg = ann
        if now >= dt:
            channel = client.get_channel(channel_id)
            if channel: await channel.send(f"📢 {msg}")
            announcements.remove(ann)

# ==========================
# 봇 실행
# ==========================
client.run(TOKEN)