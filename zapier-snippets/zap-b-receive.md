# Zap B — recebe o resultado do download

Esse Zap não tem código nenhum pra você escrever — é configuração de trigger.

## 1. Criar o Zap B primeiro (antes de preencher o Zap A)

1. Cria um Zap novo
2. Trigger: app **Webhooks by Zapier** → evento **Catch Hook**
3. Continua o setup (ele vai gerar uma URL única, algo como
   `https://hooks.zapier.com/hooks/catch/123456/abcdef/`)
4. **Copia essa URL** — é o valor que entra em `CALLBACK_URL` no código do
   Zap A (`zap-a-dispatch.js`)

## 2. Testar o trigger

Pra fazer o "Find Data" funcionar (o Zapier precisa de um exemplo de payload
pra mapear os campos), dispare um teste manual primeiro:

```bash
curl -X POST \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/waslacyy/yt-downloader/dispatches \
  -d '{
    "event_type": "download-video",
    "client_payload": {
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "callback_url": "URL_DO_CATCH_HOOK_AQUI",
      "job_id": "teste-zap-b",
      "metadata": {"record_id": "123"}
    }
  }'
```

Espera o workflow rodar (aba Actions do repo), aí volta no Zapier e clica em
"Find new records" / "Test trigger" no Zap B — ele deve achar o payload que
o GitHub Actions mandou.

## 3. Campos disponíveis depois do trigger

O payload que chega tem essa forma:

```json
{
  "job_id": "teste-zap-b",
  "status": "success",
  "cloudinary_url": "https://res.cloudinary.com/...",
  "public_id": "youtube_downloads/teste-zap-b",
  "duration": 123,
  "title": "Título do vídeo",
  "metadata": { "record_id": "123" }
}
```

Use `status` num filtro/step condicional pra tratar erro vs sucesso (o
`download.py` manda `status: "error"` com um campo `error` quando algo dá
errado no yt-dlp ou no upload).

## 4. Continuar o resto da automação

A partir daqui, monta os steps que antes vinham *depois* do download no seu
Zap original (ex: postar no Slack, salvar em planilha, etc.), usando
`cloudinary_url` no lugar do `download_url` antigo, e `metadata.record_id`
pra recuperar contexto do registro original se precisar.
