/**
 * state.js — グローバル状態変数
 *
 * アプリケーション全体で共有するミュータブルな状態を一元管理する。
 * 各モジュールはこれらの変数を直接参照・更新する（グローバルスコープ共有）。
 */

// ── 現在地 ────────────────────────────────────────────────────────────────
let currentLocation = null;       // { lat, lon, accuracyMeters }
let currentMarker = null;         // Leaflet CircleMarker
let currentAccuracyCircle = null; // Leaflet Circle（GPS 精度圏）

// ── 避難先候補 ────────────────────────────────────────────────────────────
let destinationMarkers = [];
let destinationMarkerBaseStyles = []; // 意味色を保持（案内中でも基本色が消えないように）

// ── 指定緊急避難場所 ──────────────────────────────────────────────────────
let emergencyShelterMarkers = [];
let selectedEmergencyShelterSite   = null; // 現在選択中の避難場所（サイトデータ）
let selectedEmergencyShelterMarker = null; // 現在選択中の避難場所（Leafletマーカー）

// ── ルーティング ──────────────────────────────────────────────────────────
let routingControl = null;
let selectedRouteHighlightLayers = [];
let routeCandidateLayers = [];
let routeStepFocusMarker = null;

// ── 検索結果 ──────────────────────────────────────────────────────────────
let destinations = [];
let hasSearchedDestinations = false;
let evacuationRecommended = null;
let evacuationHazardStatus = null;
let evacuationMeta = null;
let activeNavigatingIndex = null;

// ── UI 状態 ───────────────────────────────────────────────────────────────
let isManualLocationMode = false;
let isAutoRefreshOnManualUpdate = true;
let isEmergencyShelterVisible = true;
let isEmergencyEvacuationSiteVisible = true; // 指定緊急避難場所（赤）の表示フラグ
let shelterRefreshTimer = null;
let suppressNextManualLocationClick = false;

// ── RSA（到達可能安全エリア） ─────────────────────────────────────────────
let reachableSafeAreaLayer = null;

// ── ルートカラーパレット ──────────────────────────────────────────────────
const ROUTE_COLOR_PALETTE = ['#ff9800', '#1e88e5', '#43a047', '#8e24aa', '#fb8c00'];

// ── 日常目的地 ────────────────────────────────────────────────────────────
let userDestination                = null;  // 確定済み目的地 { lat, lon, name, type, source }
let userDestinationCandidate       = null;  // 仮目的地 { lat, lon, name }
let userDestinationMarker          = null;  // Leaflet marker（確定）
let userDestinationCandidateMarker = null;  // Leaflet marker（仮）
let userDestinationSearchResults   = [];    // 検索候補 [{ lat, lon, name }]
let userDestinationSearchLoading   = false;
let userDestinationSearchError     = null;

// ── ナビゲーションモード ──────────────────────────────────────────────────
let navigationMode = 'browse'; // browse | route_preview | navigation_active | navigation_warning | navigation_paused | navigation_finished
let navWatchId     = null;     // watchPosition の ID
let navOffRouteCount = 0;      // 連続逸脱カウント
let navIsAutoFollow  = true;   // 地図自動追従フラグ
let navActiveRoute          = null;  // 現在案内中のルートオブジェクト { coordinates: [{lat,lng}] }
let navDestination          = null;  // 現在の目的地 { lat, lon }
let navOriginalDestination  = null;  // 最初に選んだ目的地（再検索後も保持）
let navRerouteInProgress    = false; // 再ルート処理中フラグ
let navLastRerouteAt        = 0;     // 最後に再ルートした時刻（ms）

// ── オート再ルート ─────────────────────────────────────────────────────────
let navAutoRerouteEnabled         = true;  // 自動再ルート ON/OFF
let navAutoRerouteInProgress      = false; // 自動再ルート処理中
let navLastAutoRerouteAt          = 0;     // 最終自動再ルート時刻（ms）
let navAutoRerouteCount           = 0;     // ウィンドウ内回数カウント
let navAutoRerouteWindowStartedAt = 0;     // 回数ウィンドウ開始時刻（ms）
let navAutoRerouteSuspended       = false; // 暴走防止で一時停止中
let navLastKnownAccuracy          = null;  // 直近GPS精度（m）
let navStartElevation             = null;  // ナビ開始地点の標高（m）
let navCurrentElevation           = null;  // 現在地の標高（m、ナビ中随時更新）
let navLastElevFetchPos           = null;  // 最後に標高取得した座標
let navLastHazardFetchPos         = null;  // 最後に現在地ハザード取得した座標

// ── 前方ブロック再ルート ───────────────────────────────────────────────────
let navBlockAheadInProgress = false; // 前方回避再ルート処理中フラグ
