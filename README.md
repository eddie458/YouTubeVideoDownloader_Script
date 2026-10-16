# YouTube Video Downloader

A command-line script that downloads a YouTube video as a single **MP4 file with video and sound together**, or only its **audio** (MP3, M4A or WAV). It lists the resolutions the video is available in and lets you pick one.

It is built on [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Setup

You need Python 3.10 or newer.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

This installs everything the script needs, including a copy of **ffmpeg**, which merges the video and the audio into one file. If ffmpeg is already installed on your PATH, the script uses that one instead.

YouTube also needs a **JavaScript runtime** to unlock all of its formats: [Node.js](https://nodejs.org) or [Deno](https://deno.com). The script uses whichever one is installed. Without one, yt-dlp prints a warning and some resolutions may be missing.

## Usage

Put the link in quotes, because links that contain `&` are otherwise split up by the shell.

```powershell
python yt_download.py "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
```

```
Fetching video information...

Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film
  Blender  |  10:35

Available downloads:
   1)  2160p60     VP9 + AAC        ~1.3 GB
   2)  1440p60     VP9 + AAC      ~461.2 MB
   3)  1080p60     H.264 + AAC    ~255.5 MB
   4)  720p60      H.264 + AAC    ~153.3 MB
   5)  480p        H.264 + AAC     ~36.7 MB
   6)  360p        H.264 + AAC     ~27.2 MB
   7)  240p        H.264 + AAC     ~18.7 MB
   8)  144p        H.264 + AAC     ~13.9 MB
   a)  Audio only  MP3 192 kbps    ~14.5 MB

Choose a number, "a" for audio only or "q" to quit [1]:
```

Press Enter for the best quality, type a number for another resolution, or type `a` for the sound only. The file is saved in the current folder, named after the video, for example `Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film (1080p).mp4`.

If you'd rather not activate the virtual environment every time, run the script with its Python directly: `.venv\Scripts\python yt_download.py "LINK"`.

### Options

| Option | What it does |
| --- | --- |
| `-r 1080`, `--resolution 1080` | Download that resolution without showing the menu. If it isn't available, the closest lower one is used. `-r best` takes the highest. |
| `-a`, `--audio-only` | Download only the audio, without showing the menu. |
| `--audio-format mp3\|m4a\|wav` | File type for audio downloads. The default is `mp3` (192 kbps). `m4a` keeps YouTube's original AAC audio, without re-encoding. |
| `-o DIR`, `--output-dir DIR` | Folder to save the file in. |
| `-v`, `--verbose` | Show yt-dlp's full output, for troubleshooting. |

```powershell
python yt_download.py "https://youtu.be/VIDEO_ID" -r 720 -o "$HOME\Videos"
python yt_download.py "https://youtu.be/VIDEO_ID" -a --audio-format m4a
```

## How it picks the streams

YouTube stores the video and the audio of a video separately. For the resolution you choose, the script takes the best video stream and the best audio stream and has ffmpeg merge them into one MP4 file. When several streams have the same resolution and frame rate, it prefers the ones that play everywhere: H.264 video and AAC audio, and SDR over HDR. Above 1080p, YouTube only offers VP9 or AV1 video.

## Troubleshooting

- YouTube changes often, and yt-dlp is updated to keep up. If downloads start failing, update it first: `pip install -U "yt-dlp[default]"`.
- Run the script with `-v` to see what yt-dlp is doing.
- Playlists and channels aren't supported. Use the link of a single video.

Only download videos you have the right to download.
