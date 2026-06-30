import json
import os
import sys
import tempfile

import cloudinary
import cloudinary.uploader
import requests
import yt_dlp

VIDEO_URL = os.environ.get("VIDEO_URL")
CALLBACK_URL = os.environ.get("CALLBACK_URL")
JOB_ID = os.environ.get("JOB_ID", "sem-job-id")
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES")  # opcional

try:
    METADATA = json.loads(os.environ.get("METADATA_JSON") or "null") or {}
except Exception:
    METADATA = {}

cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True,
)


def notify(payload):
    """Avisa o n8n/Zapier que o job terminou (sucesso ou erro)."""
    payload["metadata"] = METADATA
    if not CALLBACK_URL:
        print("Sem CALLBACK_URL definido, não foi possível notificar.")
        return
    try:
        requests.post(CALLBACK_URL, json=payload, timeout=15)
    except Exception as e:
        print(f"Falha ao notificar callback: {e}")


def main():
    if not VIDEO_URL:
        notify({"job_id": JOB_ID, "status": "error", "error": "VIDEO_URL vazio"})
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_template = os.path.join(tmp_dir, f"{JOB_ID}.%(ext)s")

        ydl_opts = {
            "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "merge_output_format": "mp4",
            "outtmpl": output_template,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "verbose": True,
            # Tenta múltiplos clients em cascata — Shorts e alguns vídeos
            # restritos às vezes só expõem formatos completos em clients
            # específicos. "tv" costuma não exigir PO token.
            "extractor_args": {"youtube": {"player_client": ["tv", "android", "web"]}},
        }

        if YOUTUBE_COOKIES:
            cookies_path = os.path.join(tmp_dir, "cookies.txt")
            with open(cookies_path, "w") as f:
                f.write(YOUTUBE_COOKIES)
            ydl_opts["cookiefile"] = cookies_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(VIDEO_URL, download=True)
        except Exception as e:
            notify({"job_id": JOB_ID, "status": "error", "error": f"erro no yt-dlp: {e}"})
            sys.exit(1)

        downloaded_file = None
        for fname in os.listdir(tmp_dir):
            if fname.startswith(JOB_ID):
                downloaded_file = os.path.join(tmp_dir, fname)
                break

        if not downloaded_file or not os.path.exists(downloaded_file):
            notify({"job_id": JOB_ID, "status": "error", "error": "arquivo não encontrado após yt-dlp"})
            sys.exit(1)

        try:
            upload_result = cloudinary.uploader.upload_large(
                downloaded_file,
                resource_type="video",
                public_id=f"youtube_downloads/{JOB_ID}",
                folder="youtube_downloads",
            )
        except Exception as e:
            notify({"job_id": JOB_ID, "status": "error", "error": f"erro no upload Cloudinary: {e}"})
            sys.exit(1)

    notify(
        {
            "job_id": JOB_ID,
            "status": "success",
            "cloudinary_url": upload_result.get("secure_url"),
            "public_id": upload_result.get("public_id"),
            "duration": info.get("duration"),
            "title": info.get("title"),
        }
    )


if __name__ == "__main__":
    main()
