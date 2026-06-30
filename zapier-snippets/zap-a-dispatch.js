// ─── ZAP A: dispara o GitHub Actions (substitui o código antigo do RapidAPI) ──

const GITHUB_TOKEN = 'COLOQUE_SEU_TOKEN_AQUI'; // token com permissão Contents: Read and write, escopado pro repo
const CALLBACK_URL = 'COLOQUE_A_URL_DO_CATCH_HOOK_DO_ZAP_B_AQUI'; // copia da Zap B depois de criar o trigger

const youtubeUrl = inputData.video;

if (!youtubeUrl || youtubeUrl === 'undefined') {
  throw new Error('video está vazio ou indefinido. Valor recebido: ' + JSON.stringify(inputData));
}

// job_id simples e único o suficiente pra correlacionar depois
const jobId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const response = await fetch('https://api.github.com/repos/waslacyy/yt-downloader/dispatches', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${GITHUB_TOKEN}`,
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    event_type: 'download-video',
    client_payload: {
      url: youtubeUrl,
      callback_url: CALLBACK_URL,
      job_id: jobId,
      // Qualquer coisa que o Zap B precise pra continuar a automação
      // (id de registro, canal do Slack, nome do cliente, etc.)
      // volta intacto no callback dentro de "metadata".
      metadata: {
        record_id: inputData.record_id || null,
        // adicione outros campos que o resto do seu Zap original usava
      },
    },
  }),
});

if (response.status !== 204) {
  const text = await response.text();
  throw new Error(`Falha ao disparar o GitHub Actions (status ${response.status}): ${text}`);
}

// Esse output não tem o resultado do download ainda — só confirma que disparou.
// O resultado real chega no Zap B via callback_url.
return { job_id: jobId, status: 'dispatched' };
