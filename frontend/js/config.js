/**
 * config.js — OnHighGround2 フロントエンド設定定数
 *
 * index.html の <script> ブロックから切り出したアプリ設定。
 * API エンドポイント・デバッグフラグなど、環境依存の定数をここに集約する。
 *
 * Phase 1: 最小限の切り出し。バンドラなし。<script src="js/config.js"> で読み込む。
 */

// ── API 接続先候補 ──────────────────────────────────────────────
// nginx プロキシ経由 → backend の順に試みる。
// 同一オリジン環境（docker-compose / nginx）では最初の候補で解決される。
const API_BASE_URL_CANDIDATES = [
    `${window.location.origin}/api`,
    `${window.location.protocol}//${window.location.hostname}:8000/api`,
    'http://localhost:8000/api'
].filter((url, index, arr) => arr.indexOf(url) === index);

// ── OSRM ルーティングエンジン ────────────────────────────────────
// nginx が /osrm/driving/ → osrm-driving:5000 へプロキシする。
// 直接ポート参照は CORS エラーになるため、必ず nginx 経由で使うこと。
const OSRM_SERVICE_URLS = {
    driving: '/osrm/driving/route/v1',
    walking: '/osrm/walking/route/v1'
};

// ── デバッグ設定 ─────────────────────────────────────────────────
// true にすると apiFetch の試行ログをコンソールに出力する
const DEBUG_API_FETCH = true;

// ── レイヤーパス設定 ─────────────────────────────────────────────
// [Phase 1] 現在のハザードGeoJSONフォールバックパス。
// nginx が /hazard/ を frontend/hazard/ から配信中（legacy 扱い）。
//
// [移行予定] Phase 2 以降、frontend/layers/ を公式配置先とし、
// /layers/ パスへ統一する。以下の LAYER_BASE_PATH を切り替えることで移行する。
//
//   現在 (legacy):  LAYER_BASE_PATH = '/hazard'
//   移行後 (公式):  LAYER_BASE_PATH = '/layers'
//
// TODO: deploy_to_runtime.sh で frontend/layers/ にデータが配備されたら
//       LAYER_BASE_PATH を '/layers' へ変更し、/hazard/ を廃止する。
const LAYER_BASE_PATH = '/hazard'; // 今後 /layers に統一予定
