# YouTube Downloader via GitHub Actions + Playwright (sem servidor, sem cartão)

Dispara via API, roda num Chromium headless que **reproduz o vídeo de
verdade** e grava a saída (áudio+vídeo) direto da tela — não extrai URL
nenhuma. Sobe o resultado pro Cloudinary e avisa via webhook quando termina.

## Por que gravar a reprodução em vez de extrair a URL do arquivo

O YouTube vem forçando um protocolo de streaming (SABR) que não expõe mais
uma URL simples de download em vários casos (Shorts, principalmente). Um
extrator como yt-dlp que tenta *pegar a URL e baixar* cai nesse bloqueio.

O Playwright não precisa de URL nenhuma: ele abre a página, deixa o
`<video>` tocar, e usa `captureStream()` + `MediaRecorder` pra gravar
exatamente o que está sendo reproduzido. Se o navegador consegue tocar o
vídeo, a gente consegue gravar — não importa qual protocolo o YouTube usa
por baixo.

**Trade-off:** a gravação é proporcional à duração real do vídeo (um Short
de 30s leva ~30s pra gravar; um vídeo de 5 min leva ~5 min). Bom pra
conteúdo curto, mais lento pra vídeo longo.

## Como funciona

1. Seu n8n/Zapier chama a API do GitHub (`POST /repos/.../dispatches`)
   passando a URL do vídeo + uma `callback_url` (webhook seu) + um `job_id`
2. Isso dispara o workflow `.github/workflows/download-video.yml`
3. O workflow abre um Chromium headless, carrega a página do vídeo, pula
   anúncio se aparecer, grava a reprodução real, converte pra mp4 (ffmpeg),
   sobe pro Cloudinary, e faz um `POST` pra sua `callback_url` com o
   resultado (`cloudinary_url`, `title`, `duration`, etc.)
4. Seu n8n/Zapier recebe esse callback e continua o resto da automação

⚠️ **Continua assíncrono**, igual antes — não tem resposta na hora, o
resultado chega via callback. Ver seção "Usando no Zapier / n8n" mais
abaixo (não mudou nada nessa parte).

## Passo 1 — Repositório e secrets do Cloudinary

Igual antes — se você já tem o repo criado com os secrets
`CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`,
pode pular pro passo 2.

Senão: crie o repositório no GitHub, dê push nesses arquivos, e configure
os secrets em `Settings > Secrets and variables > Actions`.

## Passo 2 — Cookies do YouTube (ainda necessário)

O Playwright "loga" o navegador usando esses cookies, do mesmo jeito que
antes:

1. Extensão **"Get cookies.txt LOCALLY"** no navegador
2. Loga no YouTube com uma conta secundária (não a principal — automação
   tem risco pequeno de flag na conta)
3. Exporta os cookies (formato Netscape) e copia o conteúdo
4. Cria/atualiza o secret `YOUTUBE_COOKIES` no repositório com esse conteúdo

## Passo 3 — Personal Access Token (PAT)

Mesmo processo de antes: fine-grained token, escopado pro repositório,
permissão `Contents: Read and write` — usado só para disparar o workflow
via API (não precisa de `Workflows` a menos que você vá dar push de novos
arquivos de workflow).

## Passo 4 — Disparar o workflow

```bash
curl -X POST \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/SEU_USUARIO/SEU_REPO/dispatches \
  -d '{
    "event_type": "download-video",
    "client_payload": {
      "url": "https://www.youtube.com/shorts/XXXXXXXXXXX",
      "callback_url": "https://SEU_WEBHOOK_AQUI",
      "job_id": "abc-123",
      "metadata": { "record_id": "opcional, qualquer coisa que queira recuperar depois" }
    }
  }'
```

## Usando no Zapier / n8n

Não mudou nada aqui em relação à versão anterior (baseada em yt-dlp) — o
formato do payload de disparo e do callback de resultado é o mesmo.

### n8n
Node **Wait** em modo webhook — gera uma URL de retomada, que é a
`callback_url` que você manda no disparo.

### Zapier
Dois Zaps — um que dispara (`zapier-snippets/zap-a-dispatch.js`), outro com
trigger **Catch Hook** que recebe o resultado
(`zapier-snippets/zap-b-receive.md`).

## Limites e ajustes

- **Timeout do job:** 15 minutos (`timeout-minutes` no workflow). Pra
  vídeos mais longos que ~10 min, aumente esse valor, já que a gravação é
  proporcional à duração real.
- **2.000 minutos/mês** de Actions grátis em repositório privado
  (ilimitado em público). Como a gravação agora leva o tempo real do
  vídeo (não é instantâneo como extração de URL), o consumo de minutos é
  maior que antes — vale monitorar se o volume crescer bastante.
- **Anúncios:** o script tenta detectar e pular anúncio pré-roll antes de
  começar a gravar. Se o YouTube mudar a estrutura HTML do botão de pular,
  esse detector pode precisar de ajuste.
- **Qualidade:** a gravação via `MediaRecorder` reproduz na resolução que
  o player carregar (tipicamente a que o YouTube entrega por padrão pro
  viewport configurado, 1280x720 aqui) — não é bit-exato ao arquivo
  original, é uma reconstrução via reprodução real.
