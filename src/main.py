"""
Simple music bot with queue + skip
Prefix commands:
  !play <url or search>     – enqueue / start playing
  !skip                     – skip current track
  !queue                    – show queued URLs
  !stop                     – clear queue + leave channel
"""

import os
import asyncio
from collections import deque
import discord
import discord.utils
from discord.ext import commands
import yt_dlp
from dotenv import load_dotenv
import logging

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!"

# Set up logging too see whats happening
discord.utils.setup_logging(level=logging.DEBUG)
discord_logger = logging.getLogger('discord')
file_handler = logging.FileHandler("discord.log", encoding="utf-8")
discord_logger.addHandler(file_handler)

# Needed to run youtube videos through ffmpeg
FFMPEG_EXE = r"C:\FFmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"

YTDL_OPTS = {"format": "bestaudio/best", "quiet": True, "noplaylist": True}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

FF_BEFORE = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FF_OPTS = {"before_options": FF_BEFORE, "options": "-vn"}


# A simple queue for songs, using deque for O(1) pop from left
class SongQueue:
    def __init__(self):
        self._q: deque[str] = deque()

    def put(self, url: str):
        self._q.append(url)

    def get(self) -> str | None:
        return self._q.popleft() if self._q else None

    def __len__(self): return len(self._q)

    def __iter__(self): return iter(self._q)

    def clear(self): self._q.clear()


queues: dict[int, SongQueue] = {}  # guild.id → SongQueue


def get_q(guild: discord.Guild) -> SongQueue:
    return queues.setdefault(guild.id, SongQueue())


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents,
                   description="Queue / skip demo bot")


async def fetch_stream(url: str) -> tuple[str, str]:
    """Return (stream_url, title).  Raises on failure."""
    info = await asyncio.to_thread(ytdl.extract_info, url, download=False)
    if "entries" in info: info = info["entries"][0]
    return info["url"], info.get("title", url)


async def ensure_voice(ctx: commands.Context) -> discord.VoiceClient:
    """Connect to the author’s channel if not already connected."""
    if ctx.author.voice is None:
        raise commands.CommandError("Join a voice channel first.")
    ch = ctx.author.voice.channel
    vc = ctx.voice_client or await ch.connect()
    if vc.channel != ch: await vc.move_to(ch)
    return vc


async def start_next(ctx: commands.Context):
    """Play next song in queue or disconnect."""
    q = get_q(ctx.guild)
    url = q.get()
    if url is None:
        await ctx.voice_client.disconnect()
        return

    try:
        stream_url, title = await fetch_stream(url)
    except Exception as e:
        await ctx.send(f"Error fetching {url!s}: {e}")
        return await start_next(ctx)

    src = discord.FFmpegPCMAudio(stream_url, executable=FFMPEG_EXE, **FF_OPTS)

    def after(err: Exception | None):
        if err: print("[player error]", err)
        fut = start_next(ctx)
        asyncio.run_coroutine_threadsafe(fut, bot.loop)

    ctx.voice_client.play(src, after=after)
    await ctx.send(f"▶  **{title}**")


# Command to play a song or queue it
@bot.command(name="play", help="Play / queue a YouTube URL or search")
async def play(ctx, *, search: str):
    q = get_q(ctx.guild)
    q.put(search)
    if ctx.voice_client and ctx.voice_client.is_playing():
        await ctx.send(f"Lagt i køen som #{len(q)}")
    else:
        await ensure_voice(ctx)
        await start_next(ctx)


# Command to skip the current song
@bot.command(name="skip", help="Skip current song")
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.message.add_reaction("⏭️")
    else:
        await ctx.send("Ingen sang å hoppe over.")


# Command to show the current queue
@bot.command(name="queue", help="Show queued URLs")
async def queue_cmd(ctx):
    q = get_q(ctx.guild)
    if not len(q):
        await ctx.send("Køen er tom.")
    else:
        msg = "\n".join(f"`{i + 1}.` {u}" for i, u in enumerate(q))
        await ctx.send(f"**{len(q)} i kø:**\n{msg}")


# Stop command to clear the queue and leave the voice channel
@bot.command(name="stop", help="Clear queue and leave channel")
async def stop(ctx):
    if ctx.voice_client:
        get_q(ctx.guild).clear()
        await ctx.voice_client.disconnect()
        await ctx.message.add_reaction("⏹️")
    else:
        await ctx.send("Jeg er ikke i en kanal.")


async def main():
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
