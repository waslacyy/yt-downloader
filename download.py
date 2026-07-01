import base64
import json
import os
import subprocess
import sys
import tempfile

import cloudinary
import cloudinary.uploader
import requests
from playwright.sync_api import sync_playwright

VIDEO_URL = os.environ.get("VIDEO_URL")
CALLBACK_URL = os.environ.get("CALLBACK_URL")
JOB_ID = os.environ.get("JOB_ID", "sem-job-id")
YOUTUBE_COOKIES = os.environ.get("YOUTUBE_COOKIES")  # opcional, formato Netscape

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
    """Avisa o n8n/Zapier que o job terminou (sucesso ou erro). Também
    imprime no log do Actions, já que o payload de erro às vezes só ia
    pro webhook e ficava invisível no log."""
    payload["metadata"] = METADATA
    print(f"── Payload do callback ── {json.dumps(payload, ensure_ascii=False)}")
    if not CALLBACK_URL:
        print("Sem CALLBACK_URL definido, não foi possível notificar.")
        return
    try:
        requests.post(CALLBACK_URL, json=payload, timeout=15)
    except Exception as e:
        print(f"Falha ao notificar callback: {e}")


def parse_netscape_cookies(cookie_text):
    """Converte cookies.txt formato Netscape pro formato que o Playwright espera."""
    cookies = []
    for line in cookie_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, path, secure, expiration, name, value = parts
        try:
            expires = int(expiration) if expiration and expiration != "0" else -1
        except ValueError:
            expires = -1
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": expires,
                "httpOnly": False,
                "secure": secure.upper() == "TRUE",
                "sameSite": "Lax",
            }
        )
    return cookies


# JS injetado na página: acopla um MediaRecorder direto na saída do <video>
# e manda cada pedaço gravado de volta pro Python via callback exposto.
# Isso grava o que está sendo REPRODUZIDO na tela, então funciona
# independente de qual protocolo o YouTube usa para entregar os bytes
# por baixo (SABR, DASH, HLS, o que for) — se o navegador consegue tocar,
# a gente consegue gravar.
RECORDER_JS = """
async () => {
  function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  }

  const video = document.querySelector('video');
  video.muted = false;
  video.volume = 1.0;

  const stream = video.captureStream ? video.captureStream() : video.mozCaptureStream();
  const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus' });

  recorder.ondataavailable = async (e) => {
    if (e.data && e.data.size > 0) {
      const buffer = await e.data.arrayBuffer();
      window.sendChunkToPython(arrayBufferToBase64(buffer));
    }
  };

  window.__recorder = recorder;
  recorder.start(1000); // timeslice de 1s — chega em pedaços, não tudo no final
  await video.play();
}
"""


def skip_ads_if_present(page, max_wait_seconds=25):
    """Espera anúncios pré-roll passarem (ou clica em "Pular") antes de
    começar a gravação, pra não gravar o anúncio junto com o vídeo."""
    for _ in range(max_wait_seconds):
        is_ad = page.evaluate(
            "() => !!document.querySelector('.ad-showing') || "
            "!!document.querySelector('.ytp-ad-player-overlay')"
        )
        if not is_ad:
            return
        try:
            page.click(".ytp-ad-skip-button, .ytp-skip-ad-button", timeout=1000)
        except Exception:
            pass
        page.wait_for_timeout(1000)


def get_video_duration_seconds(page, max_wait_seconds=15):
    """Espera os metadados do vídeo carregarem pra saber a duração real."""
    for _ in range(max_wait_seconds * 2):
        duration = page.evaluate(
            "() => { const v = document.querySelector('video'); "
            "return v && isFinite(v.duration) ? v.duration : null; }"
        )
        if duration and duration > 0:
            return duration
        page.wait_for_timeout(500)
    return None


def record_video(video_url, cookies, output_webm_path):
    """Abre o vídeo num Chromium headless, deixa reproduzir, e grava a
    saída real de áudio/vídeo pra um arquivo .webm."""
    chunks = []

    def handle_chunk(base64_data):
        chunks.append(base64_data)

    title = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )

        if cookies:
            context.add_cookies(cookies)

        page = context.new_page()
        page.expose_function("sendChunkToPython", handle_chunk)

        page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("video", state="attached", timeout=20000)

        # Fecha banner de consentimento/cookies se aparecer (best-effort)
        for text in ["Accept all", "Aceitar tudo", "I agree", "Concordo"]:
            try:
                page.click(f"button:has-text('{text}')", timeout=2000)
                break
            except Exception:
                continue

        title = page.evaluate(
            "() => document.querySelector('meta[name=\"title\"]')?.content || document.title"
        )

        skip_ads_if_present(page)

        duration = get_video_duration_seconds(page)
        if duration is None:
            duration = 60  # fallback conservador se não conseguir ler a duração

        page.evaluate(RECORDER_JS)

        # Espera o vídeo acabar (ou timeout de segurança = duração + margem)
        try:
            page.wait_for_function(
                "() => document.querySelector('video').ended",
                timeout=int((duration + 20) * 1000),
            )
        except Exception:
            print(f"Timeout esperando o vídeo terminar (duração esperada: {duration}s) — seguindo com o que foi gravado.")

        page.evaluate("() => { if (window.__recorder) window.__recorder.stop(); }")
        page.wait_for_timeout(1500)  # tempo pro último chunk chegar

        browser.close()

    with open(output_webm_path, "wb") as f:
        for chunk_b64 in chunks:
            f.write(base64.b64decode(chunk_b64))

    return title, duration


def convert_webm_to_mp4(webm_path, mp4_path):
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", webm_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            mp4_path,
        ],
        check=True,
        capture_output=True,
    )


def main():
    if not VIDEO_URL:
        notify({"job_id": JOB_ID, "status": "error", "error": "VIDEO_URL vazio"})
        sys.exit(1)

    cookies = []
    if YOUTUBE_COOKIES:
        cookies = parse_netscape_cookies(YOUTUBE_COOKIES)

    with tempfile.TemporaryDirectory() as tmp_dir:
        webm_path = os.path.join(tmp_dir, f"{JOB_ID}.webm")
        mp4_path = os.path.join(tmp_dir, f"{JOB_ID}.mp4")

        try:
            title, duration = record_video(VIDEO_URL, cookies, webm_path)
        except Exception as e:
            notify({"job_id": JOB_ID, "status": "error", "error": f"erro na gravação via Playwright: {e}"})
            sys.exit(1)

        if not os.path.exists(webm_path) or os.path.getsize(webm_path) == 0:
            notify({"job_id": JOB_ID, "status": "error", "error": "gravação vazia — nenhum chunk foi capturado"})
            sys.exit(1)

        try:
            convert_webm_to_mp4(webm_path, mp4_path)
        except subprocess.CalledProcessError as e:
            notify({"job_id": JOB_ID, "status": "error", "error": f"erro no ffmpeg ao converter pra mp4: {e.stderr.decode(errors='ignore')[:500]}"})
            sys.exit(1)

        try:
            upload_result = cloudinary.uploader.upload_large(
                mp4_path,
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
            "duration": duration,
            "title": title,
        }
    )


if __name__ == "__main__":
    main()
