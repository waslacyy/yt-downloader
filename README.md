# YouTube Downloader via GitHub Actions (sem servidor, sem cartão)

Em vez de manter um servidor rodando 24/7, esse projeto usa o GitHub Actions
como "executor sob demanda": você dispara o workflow via API, ele baixa o
vídeo com `yt-dlp`, sobe pro Cloudinary, e **avisa de volta via webhook**
quando termina.

⚠️ **Diferença importante em relação ao Fly/Render:** isso é **assíncrono**.
Não tem como chamar e já receber a resposta na mesma requisição — o
GitHub Actions roda em background e leva ~30s a alguns minutos dependendo
do vídeo. Por isso o fluxo no n8n/Zapier muda um pouco (explicado abaixo).

## Como funciona

1. Seu n8n/Zapier chama a API do GitHub (`POST /repos/.../dispatches`)
   passando a URL do vídeo + uma `callback_url` (um webhook seu) + um `job_id`
2. Isso dispara o workflow `.github/workflows/download-video.yml`
3. O workflow baixa o vídeo, sobe pro Cloudinary, e faz um `POST` pra sua
   `callback_url` com o resultado (`cloudinary_url`, `title`, `duration`, etc.)
4. Seu n8n/Zapier recebe esse callback e continua o resto da automação

## Passo 1 — Criar o repositório no GitHub

```bash
cd yt-downloader-actions
git init
git add .
git commit -m "yt-downloader via github actions"
```
Crie um repo novo no GitHub (pode ser privado — Actions funciona igual e
ainda é grátis) e dê push:
```bash
git remote add origin https://github.com/SEU_USUARIO/yt-downloader-actions.git
git branch -M main
git push -u origin main
```

## Passo 2 — Configurar os secrets do Cloudinary no repositório

No GitHub: **Settings > Secrets and variables > Actions > New repository secret**

Adicione:
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

## Passo 3 — Criar um Personal Access Token (PAT)

Pra disparar o workflow via API, você precisa de um token. Vá em:
**GitHub > Settings (da sua conta) > Developer settings > Personal access
tokens > Fine-grained tokens > Generate new token**

- **Repository access:** só o repositório `yt-downloader-actions`
- **Permissions:** `Contents` → Read and write (necessário pro endpoint de
  dispatch funcionar)
- Defina uma validade (ex: 1 ano) e copie o token gerado — você só vê ele
  uma vez.

Guarde esse token com segurança (ex: como credencial no próprio n8n/Zapier).

## Passo 4 — Disparar o workflow

Chamada que seu n8n/Zapier vai fazer:

```bash
curl -X POST \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/SEU_USUARIO/yt-downloader-actions/dispatches \
  -d '{
    "event_type": "download-video",
    "client_payload": {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "callback_url": "https://SEU_WEBHOOK_AQUI",
      "job_id": "abc-123"
    }
  }'
```

Essa chamada retorna `204 No Content` na hora (só confirma que disparou —
não é o resultado do download).

## Passo 5 — Receber o resultado (a parte assíncrona)

### Se você usa n8n
Use o node **Wait** configurado em modo "Webhook" — ele pausa a execução do
workflow e gera uma URL única de retomada. Essa URL é a `callback_url` que
você manda no passo 4. Quando o GitHub Actions chamar essa URL de volta, o
workflow do n8n retoma exatamente de onde parou, com o resultado disponível
nos dados do node. É o jeito mais limpo de fazer isso no n8n.

### Se você usa Zapier
Zapier não tem um node de "esperar webhook" no meio do Zap, então o jeito é
dividir em dois Zaps:

1. **Zap A (dispara):** seu trigger atual → step que chama a API do GitHub
   (passo 4) com uma `callback_url` apontando pro Catch Hook do Zap B,
   incluindo um `job_id` que te ajude a correlacionar depois (ex: salvar
   numa planilha/Airtable junto com o `job_id` antes de disparar)
2. **Zap B (recebe):** trigger **Catch Hook** → recebe o payload com
   `cloudinary_url`, `title`, `job_id` etc. → continua o resto da automação
   que antes vinha depois do download (ex: postar no Slack, atualizar
   planilha usando o `job_id` pra achar a linha certa)

## Testando localmente (opcional)

Pra testar o `download.py` sem precisar do GitHub Actions:
```bash
pip install yt-dlp cloudinary requests
export CLOUDINARY_CLOUD_NAME=...
export CLOUDINARY_API_KEY=...
export CLOUDINARY_API_SECRET=...
export VIDEO_URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
export CALLBACK_URL="https://webhook.site/seu-id-de-teste"  # webhook.site é ótimo pra testar
export JOB_ID="teste-local"
python download.py
```

## Limites do plano grátis

- **2.000 minutos/mês** de Actions grátis em repositório privado (ilimitado
  em repositório público)
- Cada execução desse workflow consome só alguns minutos (download +
  upload), então pra automação semanal isso é mais do que suficiente
- `timeout-minutes: 15` no workflow evita que um job travado consuma minutos
  à toa — ajuste se precisar de mais tempo pra vídeos longos
