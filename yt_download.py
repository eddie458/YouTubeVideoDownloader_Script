#!/usr/bin/env python3
"""Download a YouTube video as a single file (video + audio), or only its audio.

    python yt_download.py "https://www.youtube.com/watch?v=VIDEO_ID"           # pick from a menu
    python yt_download.py "https://www.youtube.com/watch?v=VIDEO_ID" -r 1080   # 1080p, no menu
    python yt_download.py "https://www.youtube.com/watch?v=VIDEO_ID" -a        # audio only (MP3)
"""

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:
    sys.exit("yt-dlp is not installed. Run:  pip install -r requirements.txt")

# The order yt-dlp uses to rank formats (it lists them from worst to best). The original
# audio language, resolution and frame rate matter most; among equal ones the most compatible
# streams win: SDR over HDR, H.264 video / AAC audio (they play almost everywhere) over
# VP9, AV1 and Opus.
FORMAT_SORT = ["lang", "quality", "res", "fps", "+hdr", "source", "+vcodec:avc", "channels", "+acodec:m4a"]

VIDEO_EXT = "mp4"
AUDIO_FORMATS = ("mp3", "m4a", "wav")
AUDIO_KBPS = 192  # used when the audio has to be re-encoded (MP3)

CODEC_NAMES = {
    "avc1": "H.264", "avc3": "H.264", "hev1": "H.265", "hvc1": "H.265",
    "vp09": "VP9", "vp9": "VP9", "av01": "AV1",
    "mp4a": "AAC", "opus": "Opus", "vorbis": "Vorbis",
}


@dataclass
class Choice:
    """One entry of the download menu."""

    label: str          # e.g. "1080p60" or "Audio only"
    codecs: str         # e.g. "H.264 + AAC"
    format: str         # yt-dlp format selector
    size: float | None  # estimated size of the final file, in bytes
    quality: int | None  # e.g. 1080; None for audio only


# --- Building the menu -------------------------------------------------------

def stream_size(fmt):
    return fmt.get("filesize") or fmt.get("filesize_approx")


def codec_name(codec):
    base = (codec or "?").split(".")[0]
    return CODEC_NAMES.get(base, base)


def quality_of(width, height):
    """Name a resolution the way YouTube does: after the 16:9 frame it fits in,
    so 1920x1080, 1920x800 (cinema) and 1080x1920 (vertical) are all 1080p."""
    if not width:
        return height
    short, long = sorted((width, height))
    return max(short, round(long * 9 / 16))


def build_choices(info, audio_format):
    """One menu entry per available resolution (best first), plus "audio only"."""
    best_audio = None
    video_only, with_audio = {}, {}
    # The formats are sorted from worst to best (see FORMAT_SORT): the last one seen wins.
    for fmt in info.get("formats") or []:
        if fmt.get("vcodec") == "none":
            if fmt.get("acodec") != "none":
                best_audio = fmt
        elif fmt.get("height"):
            streams = video_only if fmt.get("acodec") == "none" else with_audio
            streams[fmt["height"]] = fmt

    choices = []
    for height in sorted(video_only.keys() | with_audio.keys(), reverse=True):
        if height in video_only:
            # YouTube serves video and audio separately; ffmpeg merges them into one file.
            streams = [video_only[height]] + ([best_audio] if best_audio else [])
            fallback = f"bv[height={height}]+ba/b[height={height}]"
        else:
            streams = [with_audio[height]]
            fallback = f"b[height={height}]"
        choices.append(video_choice(streams, fallback))
    if best_audio:
        choices.append(audio_choice(best_audio, audio_format, info.get("duration")))
    return choices


def video_choice(streams, fallback):
    video, audio = streams[0], streams[-1]
    quality = quality_of(video.get("width"), video["height"])
    fps = round(video.get("fps") or 0)
    label = f"{quality}p{fps if fps > 30 else ''}"
    if video.get("dynamic_range") not in (None, "SDR"):
        label += " HDR"
    if "AI-upscaled" in (video.get("format_note") or ""):
        label += " (AI-upscaled)"
    sound = codec_name(audio["acodec"]) if audio.get("acodec") != "none" else "no audio"
    sizes = [stream_size(stream) for stream in streams]
    return Choice(
        label=label,
        codecs=f"{codec_name(video['vcodec'])} + {sound}",
        # Exact streams listed in the menu, with a fallback in case they changed meanwhile.
        format="+".join(stream["format_id"] for stream in streams) + "/" + fallback,
        size=sum(sizes) if all(sizes) else None,
        quality=quality,
    )


def audio_choice(audio, audio_format, duration):
    if audio_format == "m4a" and (audio.get("acodec") or "").startswith("mp4a"):
        size = stream_size(audio)  # AAC is kept as is, without re-encoding
    elif duration and audio_format == "wav":
        size = duration * (audio.get("asr") or 48000) * (audio.get("audio_channels") or 2) * 2
    elif duration:
        size = duration * AUDIO_KBPS * 1000 / 8
    else:
        size = None
    target = f"MP3 {AUDIO_KBPS} kbps" if audio_format == "mp3" else audio_format.upper()
    return Choice("Audio only", target, f"{audio['format_id']}/ba/b", size, quality=None)


# --- Talking to the user -----------------------------------------------------

def human_size(num_bytes):
    if num_bytes is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def format_seconds(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def show_video_details(info):
    print(f"\n{info.get('title') or info.get('id')}")
    duration = info.get("duration")
    details = [info.get("channel") or info.get("uploader"), duration and format_seconds(duration)]
    if any(details):
        print("  " + "  |  ".join(filter(None, details)))


def show_menu(choices):
    """Print the choices and return them keyed by what the user types to pick them."""
    keys, number = {}, 0
    for choice in choices:
        if choice.quality is None:
            keys["a"] = choice
        else:
            number += 1
            keys[str(number)] = choice

    label_width = max(len(choice.label) for choice in choices)
    codecs_width = max(len(choice.codecs) for choice in choices)
    print("\nAvailable downloads:")
    for key, choice in keys.items():
        size = f"~{human_size(choice.size)}" if choice.size else ""
        print(f"  {key:>2})  {choice.label:<{label_width}}  {choice.codecs:<{codecs_width}}  {size:>10}")
    return keys


def ask_choice(keys):
    default = next(iter(keys))
    prompt = "\nChoose a number" + (', "a" for audio only' if "a" in keys else "")
    prompt += f' or "q" to quit [{default}]: '
    while True:
        try:
            answer = input(prompt).strip().lower() or default
        except EOFError:
            print()
            return None
        if answer in ("q", "quit"):
            return None
        if answer in keys:
            return keys[answer]
        print(f'"{answer}" is not one of the options.')


def choose_resolution(choices, wanted):
    """The requested resolution, or the closest lower one (the lowest if all are higher)."""
    videos = [choice for choice in choices if choice.quality is not None]
    if not videos:
        return None
    if wanted == "best":
        return videos[0]
    choice = next((video for video in videos if video.quality <= wanted), videos[-1])
    if choice.quality != wanted:
        print(f"{wanted}p is not available, using {choice.label} instead.")
    return choice


class Progress:
    """yt-dlp hooks that print one self-updating progress line per downloaded stream."""

    def __init__(self, audio_format):
        self.downloaded_anything = False
        self._steps = {
            "Merger": "Merging video and audio into one file...",
            "ExtractAudio": f"Saving the audio as {audio_format.upper()}...",
        }
        self._last_update = 0.0
        self._line_length = 0

    def on_download(self, status):
        self.downloaded_anything = True
        stream = "audio" if status["info_dict"].get("vcodec") == "none" else "video"
        if status["status"] == "downloading":
            now = time.monotonic()
            if now - self._last_update < 0.1:
                return
            self._last_update = now
            done = status.get("downloaded_bytes") or 0
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            line = f"  Downloading {stream}: "
            line += f"{done / total:.1%} of {human_size(total)}" if total else human_size(done)
            if status.get("speed"):
                line += f" at {human_size(status['speed'])}/s"
            if status.get("eta") is not None:
                line += f", {format_seconds(status['eta'])} left"
            self._print(line)
        elif status["status"] == "finished":
            size = status.get("total_bytes") or status.get("downloaded_bytes")
            self._print(f"  Downloaded {stream}: {human_size(size)}", final=True)

    def on_postprocess(self, status):
        # pop(): yt-dlp may report the same step more than once.
        if status["status"] == "started" and (message := self._steps.pop(status["postprocessor"], None)):
            print(f"  {message}")

    def _print(self, line, final=False):
        # "\r" goes back to the start of the line, so each update replaces the previous one.
        print("\r" + line.ljust(self._line_length), end="\n" if final else "", flush=True)
        self._line_length = 0 if final else len(line)


class QuietLogger:
    """Hides yt-dlp's status lines but keeps its warnings and errors."""

    def debug(self, message):
        pass

    info = debug

    def warning(self, message):
        print(f"Warning: {message}", file=sys.stderr)

    def error(self, message):
        print(message, file=sys.stderr)


# --- Downloading -------------------------------------------------------------

def find_ffmpeg():
    """ffmpeg from the PATH, else the copy that comes with the imageio-ffmpeg package."""
    if path := shutil.which("ffmpeg"):
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def find_js_runtimes():
    """yt-dlp needs a JavaScript runtime to get every YouTube format. It only looks for
    Deno by default, so also enable Node.js and Bun when they are installed."""
    return {name: {} for name in ("deno", "node", "bun") if shutil.which(name)}


def download(url, choice, options, audio_format, show_progress):
    """Download `choice` and return the path of the finished file."""
    options = dict(options, format=choice.format)
    if choice.quality is None:
        options.update(
            outtmpl="%(title)s.%(ext)s",
            final_ext=audio_format,
            postprocessors=[
                {"key": "FFmpegExtractAudio", "preferredcodec": audio_format,
                 "preferredquality": str(AUDIO_KBPS)},
                {"key": "FFmpegMetadata"},
            ],
        )
    else:
        options.update(
            outtmpl=f"%(title)s ({choice.quality}p).%(ext)s",
            merge_output_format=VIDEO_EXT,
            final_ext=VIDEO_EXT,
            postprocessors=[
                # Only does something when a single stream was downloaded in another container.
                {"key": "FFmpegVideoRemuxer", "preferedformat": VIDEO_EXT},
                {"key": "FFmpegMetadata"},
            ],
        )
    progress = Progress(audio_format)
    if show_progress:
        options.update(noprogress=True, progress_hooks=[progress.on_download],
                       postprocessor_hooks=[progress.on_postprocess])

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
    if show_progress and not progress.downloaded_anything:
        print("  The file was already downloaded.")
    return Path(info["requested_downloads"][0]["filepath"]).resolve()


def resolution(text):
    """argparse type for --resolution: "1080", "1080p" or "best"."""
    text = text.strip().lower()
    if text in ("best", "max"):
        return "best"
    try:
        return int(text.removesuffix("p"))
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected a resolution like 1080 or "best", got "{text}"') from None


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Download a YouTube video (video and audio in one file) or only its audio.")
    parser.add_argument("url", help="link of the YouTube video (put it in quotes)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-a", "--audio-only", action="store_true",
                      help="download only the audio, without showing the menu")
    mode.add_argument("-r", "--resolution", type=resolution, metavar="RES",
                      help='download this resolution (e.g. 1080, or "best") without showing the menu; '
                           "if it is not available, the closest lower one is used")
    parser.add_argument("--audio-format", choices=AUDIO_FORMATS, default="mp3",
                        help="file type for audio-only downloads (default: %(default)s)")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("."), metavar="DIR",
                        help="folder to save the file in (default: the current folder)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show yt-dlp's full output, for troubleshooting")
    return parser.parse_args(argv)


def main(argv=None):
    # Don't crash on titles with emoji etc. when the output is redirected to a file.
    sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("ffmpeg is needed to put video and audio in one file. Install it with:\n"
              "  pip install imageio-ffmpeg\n"
              "or install ffmpeg itself (e.g. 'winget install ffmpeg') and add it to your PATH.",
              file=sys.stderr)
        return 1

    options = {
        "noplaylist": True,  # for a "watch?v=...&list=..." link, get only the video
        "format_sort": FORMAT_SORT,
        "ffmpeg_location": ffmpeg,
        "paths": {"home": str(args.output_dir)},
    }
    if js_runtimes := find_js_runtimes():
        options["js_runtimes"] = js_runtimes
    if args.verbose:
        options["verbose"] = True
    else:
        options["logger"] = QuietLogger()

    try:
        print("Fetching video information...", flush=True)
        # "in_playlist": if the link is a playlist, don't look up every video in it.
        with yt_dlp.YoutubeDL(dict(options, extract_flat="in_playlist")) as ydl:
            info = ydl.extract_info(args.url, download=False)
        if info.get("_type") in ("playlist", "multi_video"):
            print("This link is a playlist or a channel. Please use the link of a single video.",
                  file=sys.stderr)
            return 1

        show_video_details(info)
        choices = build_choices(info, args.audio_format)
        if not choices:
            print("No downloadable video or audio was found for this link.", file=sys.stderr)
            return 1
        if args.audio_only:
            choice = next((choice for choice in choices if choice.quality is None), None)
        elif args.resolution is not None:
            choice = choose_resolution(choices, args.resolution)
        else:
            choice = ask_choice(show_menu(choices))
            if choice is None:
                return 0
        if choice is None:
            print("This video has no " + ("audio." if args.audio_only else "video streams."),
                  file=sys.stderr)
            return 1

        print(f"\nDownloading: {choice.label} ({choice.codecs})")
        path = download(info.get("webpage_url") or args.url, choice, options,
                        args.audio_format, show_progress=not args.verbose)
    except DownloadError:
        return 1  # yt-dlp has already printed the reason
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    print(f"\nSaved to: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
