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

async function loadRuntimeConfig() {
    try {
        const response = await apiFetch('/api/admin/config');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const items = await response.json();
        appRuntimeConfig = Object.fromEntries(
            items.map(item => [item.key, item.current_value])
        );
        appRuntimeConfigLoaded = true;
        appRuntimeConfigError = null;
        console.info('[config] runtime config loaded', appRuntimeConfig);
    } catch (error) {
        appRuntimeConfig = {};
        appRuntimeConfigLoaded = false;
        appRuntimeConfigError = error;
        console.warn('[config] runtime config load failed; using built-in defaults', error);
    }
}

function getRuntimeConfigValue(key, fallback) {
    return Object.prototype.hasOwnProperty.call(appRuntimeConfig, key)
        ? appRuntimeConfig[key]
        : fallback;
}

// ── Config変更SSE ────────────────────────────────────────────────
// バックエンドのPUT /api/admin/config/{key} 成功後に config_updated イベントが届く。
// 受信したら loadRuntimeConfig() で全件再取得し appRuntimeConfig を更新する。
// navigation.js 等は次回判定から自動的に新値を参照する。

let _configChangeEventSource = null;

function initConfigChangeSSE() {
    if (_configChangeEventSource) return;
    const url = '/api/admin/config/stream';
    try {
        const es = new EventSource(url);
        _configChangeEventSource = es;

        es.addEventListener('config_updated', async (event) => {
            let updatedKey = null;
            try {
                const { key } = JSON.parse(event.data);
                updatedKey = key;
                console.info('[config] SSE config_updated key=' + key + '; reloading runtime config');
            } catch (_) { /* parse失敗は無視 */ }
            try {
                await loadRuntimeConfig();
                if (updatedKey) {
                    window.dispatchEvent(new CustomEvent('ohg:runtime-config-updated', {
                        detail: { key: updatedKey }
                    }));
                }
            } catch (err) {
                console.warn('[config] runtime config reload failed; keeping existing values', err);
            }
        });

        es.addEventListener('heartbeat', () => {
            // 接続維持確認のみ。ログには出さない。
        });

        es.onerror = () => {
            // readyState が CLOSED の場合はブラウザが自動再接続を諦めた状態。
            // 参照をリセットして 5 秒後に再接続を試みる。
            if (es.readyState === EventSource.CLOSED) {
                _configChangeEventSource = null;
                setTimeout(() => initConfigChangeSSE(), 5000);
            }
            // CONNECTING/OPEN の場合はブラウザが自動再接続するため何もしない。
        };

        console.info('[config] config change SSE connected:', url);
    } catch (err) {
        console.warn('[config] failed to connect config change SSE:', err);
    }
}

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
