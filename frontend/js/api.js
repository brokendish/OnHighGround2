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

function normalizeApiPath(path) {
    if (typeof path !== 'string' || path.length === 0) {
        return path;
    }
    if (path === '/api') {
        return '';
    }
    if (path.startsWith('/api/')) {
        return path.slice(4);
    }
    return path;
}

async function apiFetch(path, options = {}) {
    let lastError = null;
    const normalizedPath = normalizeApiPath(path);

    for (const baseUrl of API_BASE_URL_CANDIDATES) {
        try {
            const response = await fetch(`${baseUrl}${normalizedPath}`, options);
            const contentType = (response.headers.get('content-type') || '').toLowerCase();

            // API でない HTML レスポンス（index.html 等）をつかんだ場合は次候補へ
            // application/geo+json も GeoJSON エンドポイントで使われるため許可する
            const isApiResponse = contentType.includes('application/json') || contentType.includes('application/geo+json');
            if (!isApiResponse) {
                logApiFetch('warn', `[apiFetch] rejected candidate: ${baseUrl}${normalizedPath} (content-type: ${contentType || 'unknown'})`);
                lastError = new Error(
                    `API候補 ${baseUrl} がJSONを返しませんでした (content-type: ${contentType || 'unknown'})`
                );
                continue;
            }

            logApiFetch('info', `[apiFetch] using candidate: ${baseUrl}${normalizedPath}`);
            return response;
        } catch (error) {
            logApiFetch('warn', `[apiFetch] candidate failed: ${baseUrl}${normalizedPath}`, error);
            lastError = error;
        }
    }

    throw lastError || new Error('APIに接続できませんでした');
}
