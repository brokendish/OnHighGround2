/**
 * api.js — API 通信ユーティリティ
 *
 * API_BASE_URL_CANDIDATES（config.js で定義）を順に試みるフェッチラッパー。
 * JSON レスポンスを返さない候補は自動的にスキップする。
 */

function logApiFetch(level, ...args) {
    if (!DEBUG_API_FETCH) {
        return;
    }
    console[level](...args);
}

async function apiFetch(path, options = {}) {
    let lastError = null;

    for (const baseUrl of API_BASE_URL_CANDIDATES) {
        try {
            const response = await fetch(`${baseUrl}${path}`, options);
            const contentType = (response.headers.get('content-type') || '').toLowerCase();

            // API でない HTML レスポンス（index.html 等）をつかんだ場合は次候補へ
            if (!contentType.includes('application/json')) {
                logApiFetch('warn', `[apiFetch] rejected candidate: ${baseUrl}${path} (content-type: ${contentType || 'unknown'})`);
                lastError = new Error(
                    `API候補 ${baseUrl} がJSONを返しませんでした (content-type: ${contentType || 'unknown'})`
                );
                continue;
            }

            logApiFetch('info', `[apiFetch] using candidate: ${baseUrl}${path}`);
            return response;
        } catch (error) {
            logApiFetch('warn', `[apiFetch] candidate failed: ${baseUrl}${path}`, error);
            lastError = error;
        }
    }

    throw lastError || new Error('APIに接続できませんでした');
}
