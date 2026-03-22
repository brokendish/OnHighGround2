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
let shelterRefreshTimer = null;

// ── RSA（到達可能安全エリア） ─────────────────────────────────────────────
let reachableSafeAreaLayer = null;

// ── ルートカラーパレット ──────────────────────────────────────────────────
const ROUTE_COLOR_PALETTE = ['#ff9800', '#1e88e5', '#43a047', '#8e24aa', '#fb8c00'];

// ── ナビゲーションモード ──────────────────────────────────────────────────
let navigationMode = 'browse'; // browse | route_preview | navigation_active | navigation_warning | navigation_paused | navigation_finished
let navWatchId     = null;     // watchPosition の ID
let navOffRouteCount = 0;      // 連続逸脱カウント
let navIsAutoFollow  = true;   // 地図自動追従フラグ
let navActiveRoute   = null;   // 現在案内中のルートオブジェクト { coordinates: [{lat,lng}] }
let navDestination   = null;   // 目的地 { lat, lon }
