/**
 * upload-manager.js — 大容量ファイル チャンクアップロード管理
 *
 * 使い方:
 *   const mgr = new UploadManager({ api: '/api/admin/upload' });
 *   const result = await mgr.upload(file, datasetId, {
 *     onProgress: ({ percent, speed, etaSec, receivedBytes, totalBytes }) => {},
 *     onError: (err) => {},
 *   });
 *   // result: { job_id, message }
 *
 *   mgr.cancel();  // アップロード中断
 */
class UploadManager {
  constructor({ api = '/api/admin/upload' } = {}) {
    this._api = api;
    this._cancelled = false;
    this._uploadId = null;
    this._datasetId = null;
    this._chunkSize = 8 * 1024 * 1024; // 8MB default, overridden by server
  }

  // ── public: upload ────────────────────────────────────────────────────────

  async upload(file, datasetId, { onProgress, onError } = {}) {
    this._cancelled = false;
    this._datasetId = datasetId;

    // 1. セッション開始
    let startData;
    try {
      startData = await this._post('/start', {
        filename: file.name,
        size: file.size,
        dataset_id: datasetId,
      });
    } catch (err) {
      onError && onError(err);
      throw err;
    }
    this._uploadId = startData.upload_id;
    this._chunkSize = startData.chunk_size || this._chunkSize;

    const totalChunks = Math.ceil(file.size / this._chunkSize);
    let uploadedBytes = 0;
    const startTime = Date.now();

    // 2. チャンク送信ループ
    for (let i = 0; i < totalChunks; i++) {
      if (this._cancelled) {
        await this._cancelSession();
        const err = new Error('アップロードがキャンセルされました');
        err.cancelled = true;
        onError && onError(err);
        throw err;
      }

      const offset = i * this._chunkSize;
      const chunk = file.slice(offset, offset + this._chunkSize);

      await this._sendChunk(chunk, i, offset);

      uploadedBytes = Math.min(offset + this._chunkSize, file.size);

      if (onProgress) {
        const elapsedMs = Date.now() - startTime;
        const speedBps = elapsedMs > 0 ? (uploadedBytes / elapsedMs) * 1000 : 0;
        const remainingBytes = file.size - uploadedBytes;
        const etaSec = speedBps > 0 ? remainingBytes / speedBps : null;
        onProgress({
          percent: Math.round((uploadedBytes / file.size) * 100),
          speed: speedBps,
          etaSec,
          receivedBytes: uploadedBytes,
          totalBytes: file.size,
        });
      }
    }

    // 3. 完了通知
    try {
      const result = await this._post('/finish', {
        upload_id: this._uploadId,
        dataset_id: datasetId,
        total_size: file.size,
      });
      this._uploadId = null;
      return result;
    } catch (err) {
      onError && onError(err);
      throw err;
    }
  }

  // ── public: cancel ────────────────────────────────────────────────────────

  cancel() {
    this._cancelled = true;
  }

  // ── private ───────────────────────────────────────────────────────────────

  async _sendChunk(chunk, chunkIndex, offset, retries = 3) {
    for (let attempt = 0; attempt < retries; attempt++) {
      try {
        const res = await fetch(`${this._api}/chunk`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/octet-stream',
            'X-Upload-Id': this._uploadId,
            'X-Chunk-Index': String(chunkIndex),
            'X-Chunk-Offset': String(offset),
          },
          body: chunk,
        });
        if (!res.ok) {
          const text = await res.text().catch(() => '');
          throw new Error(`chunk ${chunkIndex} failed (${res.status}): ${text}`);
        }
        return;
      } catch (err) {
        if (attempt < retries - 1) {
          const delay = Math.pow(2, attempt) * 1000; // 1s, 2s, 4s
          await new Promise(r => setTimeout(r, delay));
          continue;
        }
        throw err;
      }
    }
  }

  async _post(path, body) {
    const res = await fetch(`${this._api}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(json.detail || json.user_message || `HTTP ${res.status}`);
    }
    return json;
  }

  async _cancelSession() {
    if (!this._uploadId) return;
    try {
      await fetch(`${this._api}/cancel`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_id: this._uploadId }),
      });
    } catch (_) {}
    this._uploadId = null;
  }
}
