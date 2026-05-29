/**
 * e2e/helpers/server.js
 *
 * テスト用に frontend/ を静的配信する最小 HTTP サーバー。
 * playwright.config.js の globalSetup / globalTeardown から呼び出す。
 *
 * 起動ポート: 8787（本番 nginx 8080 と被らない）
 */

'use strict';

const http = require('http');
const fs   = require('fs');
const path = require('path');

const PORT        = 8787;
const FRONTEND_DIR = path.resolve(__dirname, '../../frontend');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.svg':  'image/svg+xml',
  '.ico':  'image/x-icon',
};

let _server = null;

function start() {
  return new Promise((resolve, reject) => {
    _server = http.createServer((req, res) => {
      let urlPath = req.url.split('?')[0];
      if (urlPath === '/') urlPath = '/index.html';
      if (urlPath === '/live') urlPath = '/live.html';
      const filePath = path.join(FRONTEND_DIR, urlPath);

      fs.readFile(filePath, (err, data) => {
        if (err) {
          res.writeHead(404);
          res.end('Not found');
          return;
        }
        const ext  = path.extname(filePath);
        const mime = MIME[ext] || 'application/octet-stream';
        res.writeHead(200, { 'Content-Type': mime });
        res.end(data);
      });
    });

    _server.on('error', reject);
    _server.listen(PORT, '127.0.0.1', () => {
      console.log(`[e2e server] http://127.0.0.1:${PORT}  (frontend: ${FRONTEND_DIR})`);
      resolve();
    });
  });
}

function stop() {
  return new Promise((resolve) => {
    if (!_server) { resolve(); return; }
    _server.close(() => resolve());
    _server = null;
  });
}

module.exports = { start, stop, PORT };
