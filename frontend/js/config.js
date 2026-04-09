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

// ── 避難場所リージョン定義 ──────────────────────────────────────────
// 新しい都道府県を追加するときはここに1エントリ追加するだけでよい。
// state.js・map-overlay-ui.js・index.html の手動編集は不要になる。
//
// フィールド:
//   key        : shelterRegionVisible のキー（バックエンドの region フィールドと一致させる）
//   label      : UI に表示する都道府県名
//   dotColor   : オーバーレイパネルの識別ドット色
//   defaultOn  : 初期表示状態
//   panelId    : オーバーレイパネルのチェックボックス ID
//   sidebarId  : サイドバーのチェックボックス ID
const SHELTER_REGION_CONFIGS = [
    { key: 'tokyo',    label: '東京都',   dotColor: '#5c6bc0', defaultOn: true,  panelId: 'shelterPanel_tokyo',    sidebarId: 'showShelterTokyo'    },
    { key: 'kanagawa', label: '神奈川県', dotColor: '#26a69a', defaultOn: true,  panelId: 'shelterPanel_kanagawa', sidebarId: 'showShelterKanagawa' },
    // 将来の追加例:
    // { key: 'chiba',    label: '千葉県',   dotColor: '#ef6c00', defaultOn: false, panelId: 'shelterPanel_chiba',    sidebarId: 'showShelterChiba'    },
    // { key: 'saitama',  label: '埼玉県',   dotColor: '#6a1b9a', defaultOn: false, panelId: 'shelterPanel_saitama',  sidebarId: 'showShelterSaitama'  },
];

// ── レイヤーパス設定 ─────────────────────────────────────────────
// [Phase 2] frontend/layers/ を公式配置先として /layers/ に切替済み。
// nginx が /layers/ を frontend/layers/ から配信する。
// frontend/layers/ への配備は deploy_to_runtime.sh が実施する。
//
// /hazard/ は deprecated（後方互換として残すが新規参照はしない）。
// vector tiles (Martin /tiles/) が主配信。GeoJSON は vector tile 未整備時の fallback。
const LAYER_BASE_PATH = '/layers';
