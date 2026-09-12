/**
 * datasets.js — データ運用管理画面 フロントエンドロジック
 *
 * 設計方針:
 * - 依存ライブラリなし（バニラJS）
 * - API との通信は /admin/api/admin/datasets/* エンドポイント
 * - ポーリングで状態を自動更新（3秒間隔、実行中ジョブがある場合）
 */

"use strict";

const API = "/admin/api/admin";
const POLL_INTERVAL_MS = 3000;
const DETAIL_LOG_INTERVAL_MS = 3000;
const LIST_AUTO_REFRESH_INTERVAL_MS = 5000;
const LOGS_MAX_LINES = 1000;
const VOICE_SOURCE_KEY = '__voice__';
const VOICE_LOG_STORAGE_KEY = 'ohg_voice_log';
const VOICE_LOG_MAX = 100;
const CONFIG_SOURCE_KEY = '__config__';
const CONFIG_LOG_MAX = 100;

const CONFIG_PRESETS = {
  standard: {
    label: "標準",
    values: {
      "navigation.arrival_distance_m":             12,
      "navigation.arrival_consecutive_count":      2,
      "navigation.off_route_distance_m":           15,
      "navigation.near_goal_off_route_distance_m": 18,
      "navigation.near_goal_distance_m":           15,
      "navigation.arrival_radius_min":             12,
      "navigation.arrival_radius_max":             25,
      "navigation.arrival_accuracy_multiplier":    0.8,
      "navigation.near_arrival_distance":          15,
      "navigation.final_reminder_distance":        5,
      "navigation.safe_crossing_search_radius":    50,
      "navigation.safe_crossing_detour_ratio":     1.5,
      "voice.cooldown_ms":                         10000,
      "voice.rate":                                1.1,
    },
  },
  safety: {
    label: "安全重視",
    values: {
      "navigation.arrival_distance_m":             12,
      "navigation.arrival_consecutive_count":      3,
      "navigation.off_route_distance_m":           20,
      "navigation.near_goal_off_route_distance_m": 25,
      "navigation.near_goal_distance_m":           20,
      "navigation.arrival_radius_min":             15,
      "navigation.arrival_radius_max":             30,
      "navigation.arrival_accuracy_multiplier":    1.0,
      "navigation.near_arrival_distance":          20,
      "navigation.final_reminder_distance":        6,
      "navigation.safe_crossing_search_radius":    50,
      "navigation.safe_crossing_detour_ratio":     1.5,
      "voice.cooldown_ms":                         8000,
      "voice.rate":                                1.05,
    },
  },
  fastest: {
    label: "最速最短",
    warning: "このモードは安全性を考慮しません。危険なルートが含まれる可能性があります。",
    values: {
      "navigation.arrival_distance_m":             15,
      "navigation.arrival_consecutive_count":      1,
      "navigation.off_route_distance_m":           40,
      "navigation.near_goal_off_route_distance_m": 30,
      "navigation.near_goal_distance_m":           30,
      "navigation.arrival_radius_min":             15,
      "navigation.arrival_radius_max":             35,
      "navigation.arrival_accuracy_multiplier":    1.2,
      "navigation.near_arrival_distance":          25,
      "navigation.final_reminder_distance":        4,
      "navigation.safe_crossing_search_radius":    0,
      "navigation.safe_crossing_detour_ratio":     1.0,
      "voice.cooldown_ms":                         12000,
      "voice.rate":                                1.2,
    },
  },
  urban_precision: {
    label: "高精度",
    warning: "高精度モードは判定が厳しめです。GPS精度が悪い場所では到着判定が遅れる場合があります。",
    values: {
      "navigation.arrival_distance_m":             8,
      "navigation.arrival_consecutive_count":      3,
      "navigation.off_route_distance_m":           20,
      "navigation.near_goal_off_route_distance_m": 12,
      "navigation.near_goal_distance_m":           30,
      "navigation.arrival_radius_min":             8,
      "navigation.arrival_radius_max":             18,
      "navigation.arrival_accuracy_multiplier":    0.6,
      "navigation.near_arrival_distance":          12,
      "navigation.final_reminder_distance":        4,
      "navigation.safe_crossing_search_radius":    40,
      "navigation.safe_crossing_detour_ratio":     1.3,
      "voice.cooldown_ms":                         9000,
      "voice.rate":                                1.1,
    },
  },
};

// ── グローバル状態 ─────────────────────────────────────
let _allDatasets = [];           // 最新のDatasetSummary[]
let _currentDatasetId = null;    // 詳細パネル表示中のdataset_id
let _currentDetail = null;       // 最新のDatasetDetail
let _updateModalDataset = null;  // 更新モーダル対象
let _deployModalDataset = null;  // 反映確認対象
let _rollbackModalDataset = null;// ロールバック確認対象
let _osrmModalDataset = null;    // OSRM再構築確認対象
let _logModalJobId = null;       // ジョブログモーダル対象
let _selectedFiles = [];         // アップロード選択ファイル（複数対応）
let _activeInputTab = null;      // 現在の投入方式タブ
let _chunkUploadMgr = null;      // チャンクアップロードマネージャ

let _listRefreshTimer = null;
let _detailRefreshTimer = null;
let _logRefreshTimer = null;
let _detailAutoRefresh = true;
let _logAutoRefresh = true;
let _activateModalDataset = null;  // 有効化確認対象
let _activeAdminTab = "datasets";
let _configItems = [];
let _configLoaded = false;
let _logSources = [];
let _logsLoaded = false;
let _logsSource = "app";
let _logsLines = [];
let _logsAutoScroll = true;
let _logsEventSource = null;
let _voiceChannel = null;
let _logsStatus = { sources: [] };
let _configChangeEventSource = null; // Logs用SSEとは独立した接続
let _configLogEntries = [];          // Config変更ログ（最大CONFIG_LOG_MAX件、セッション内）
const _configApplyStatus = {};       // key → { state, at, applyMode }
let _presetSkippedKeys = [];         // 直前のプリセット適用でスキップされたキー一覧

// ── 初期化 ────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([populateLayerTypeFilter(), populateRegionFilter()]);
  loadDatasets();
  _listRefreshTimer = setInterval(loadDatasets, LIST_AUTO_REFRESH_INTERVAL_MS);
  connectAdminConfigChangeSSE();
});

window.addEventListener("ohg:config-log", (e) => {
  if (!e.detail) return;
  const entry = e.detail;
  if (!_configLogEntries.includes(entry)) {
    _configLogEntries.push(entry);
    if (_configLogEntries.length > CONFIG_LOG_MAX) {
      _configLogEntries.splice(0, _configLogEntries.length - CONFIG_LOG_MAX);
    }
    if (getSelectedLogsSource() === CONFIG_SOURCE_KEY) {
      appendLogLine(_formatConfigLogLine(entry));
    }
  }
});

function connectAdminConfigChangeSSE() {
  if (_configChangeEventSource) return;
  try {
    const es = new EventSource(`${API}/config/stream`);
    _configChangeEventSource = es;

    es.addEventListener("config_updated", async (event) => {
      try {
        const { key } = JSON.parse(event.data);
        console.info("[admin] config_updated key=" + key + "; reloading config table");
      } catch (_) { /* parse失敗は無視 */ }
      // 既に読み込み済みのときだけ再取得（未表示のタブは開いたときに取得する）
      if (_configLoaded) {
        try {
          await loadConfig();
        } catch (err) {
          console.warn("[admin] config reload failed:", err);
        }
      }
    });

    es.addEventListener("heartbeat", () => {
      // 接続維持確認のみ。
    });

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        _configChangeEventSource = null;
        setTimeout(() => connectAdminConfigChangeSSE(), 5000);
      }
    };
  } catch (err) {
    console.warn("[admin] failed to connect config change SSE:", err);
  }
}

function switchAdminTab(tab) {
  if (tab !== "logs") {
    disconnectLogsStream({ preserveStatus: false });
  }
  _activeAdminTab = tab;
  ["datasets", "config", "logs"].forEach(name => {
    document.getElementById(`tab-btn-${name}`).classList.toggle("active", name === tab);
    document.getElementById(`tab-panel-${name}`).classList.toggle("active", name === tab);
  });
  if (tab === "config" && !_configLoaded) {
    loadConfig();
  }
  if (tab === "logs") {
    if (!_logsLoaded) {
      initializeLogsPanel();
    } else if (!_logsEventSource) {
      connectLogsStream();
    }
  }
}

async function populateLayerTypeFilter() {
  try {
    const layerTypes = await fetchJSON(`${API}/layer-types`);
    const sel = document.getElementById("layer-type-filter");
    layerTypes
      .sort((a, b) => a.sort_order - b.sort_order)
      .forEach(lt => {
        const opt = document.createElement("option");
        opt.value = lt.layer_type;
        opt.textContent = lt.display_name;
        sel.appendChild(opt);
      });
  } catch (err) {
    console.warn("Failed to load layer types:", err);
    // フォールバック: 静的オプション
    const fallback = [
      ["shelter","避難場所"],["tsunami","津波浸水想定"],["flood","洪水浸水想定"],
      ["storm_surge","高潮浸水想定"],["inland_flood","内水氾濫リスク"],
      ["landslide","土砂災害警戒"],["admin_boundary","行政区域境界"],
    ];
    const sel = document.getElementById("layer-type-filter");
    fallback.forEach(([v, t]) => {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = t;
      sel.appendChild(opt);
    });
  }
}

async function populateRegionFilter() {
  try {
    const datasets = await fetchJSON(`${API}/datasets`);
    const regions = [...new Set(datasets.map(d => d.region))].sort();
    const sel = document.getElementById("region-filter");
    regions.forEach(r => {
      const opt = document.createElement("option");
      opt.value = r;
      opt.textContent = regionLabel(r);
      sel.appendChild(opt);
    });
  } catch (err) {
    console.warn("Failed to load regions:", err);
    // フォールバック
    [["tokyo","東京都"],["kanagawa","神奈川県"]].forEach(([v, t]) => {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = t;
      document.getElementById("region-filter").appendChild(opt);
    });
  }
}

// ── データセット一覧ロード ─────────────────────────────
async function loadDatasets() {
  try {
    const region = document.getElementById("region-filter").value;
    const layerType = document.getElementById("layer-type-filter").value;
    const params = new URLSearchParams();
    if (region) params.set("region", region);
    if (layerType) params.set("layer_type", layerType);
    const url = `${API}/datasets${params.toString() ? "?" + params.toString() : ""}`;
    const data = await fetchJSON(url);
    _allDatasets = data;
    renderDatasetTable(data);
    // 詳細パネルが開いている場合は更新
    if (_currentDatasetId && _detailAutoRefresh) {
      await refreshDetail(_currentDatasetId);
    }
  } catch (err) {
    showNotice("error", "データセット一覧の取得に失敗しました: " + err.message);
  }
}

document.getElementById("region-filter").addEventListener("change", loadDatasets);
document.getElementById("layer-type-filter").addEventListener("change", loadDatasets);

// ── テーブル描画 ──────────────────────────────────────
function renderDatasetTable(datasets) {
  const tbody = document.getElementById("datasets-tbody");
  if (datasets.length === 0) {
    tbody.innerHTML = `<tr><td colspan="13" style="text-align:center;padding:30px;color:#94a3b8">データセットが見つかりません</td></tr>`;
    return;
  }
  tbody.innerHTML = datasets.map(d => renderDatasetRow(d)).join("");
}

function renderDatasetRow(d) {
  const isRunning = d.has_running_job;
  const isRailwayPmtiles = d.source_type === "railway_pmtiles";
  const canDeploy = d.is_deployable && !isRunning && !isRailwayPmtiles;
  const canRollback = d.deploy_status === "deployed" && d.has_backup && !isRunning && !isRailwayPmtiles;
  const canOsrm = d.requires_osrm_rebuild && d.deploy_status === "deployed" && !isRunning;
  const canActivate = d.layer_type && d.deploy_status === "deployed" && !d.is_active && !isRunning;

  const fileInfo = d.current_file_name
    ? `<div class="file-name" title="${escAttr(d.current_file_name)}">${escHtml(d.current_file_name)}</div>
       <div class="file-size">${formatBytes(d.current_file_size)}</div>`
    : `<span style="color:#cbd5e1;font-size:12px">なし</span>`;

  const updatedAt = d.updated_at
    ? `<div style="font-size:12px">${formatDate(d.updated_at)}</div>`
    : `<span style="color:#cbd5e1;font-size:11px">—</span>`;

  const osrmCell = d.requires_osrm_rebuild
    ? badgeHtml(osrmBadgeClass(d.osrm_rebuild_status), osrmLabel(d.osrm_rebuild_status))
    : `<span style="color:#cbd5e1;font-size:11px">—</span>`;

  const activeCell = d.layer_type
    ? (d.is_active
        ? `<span class="badge badge-active" title="このレイヤー種別+地域の有効データセット">有効</span>`
        : `<span style="color:#cbd5e1;font-size:11px">—</span>`)
    : `<span style="color:#e2e8f0;font-size:11px">対象外</span>`;

  return `<tr data-id="${escAttr(d.dataset_id)}" ${d.is_active ? 'class="row-active"' : ''}>
    <td><span style="font-size:11px;color:#64748b">${regionLabel(d.region)}</span></td>
    <td><span class="dataset-id">${escHtml(d.dataset_id)}</span></td>
    <td>
      <div class="dataset-name">${escHtml(d.display_name)}</div>
    </td>
    <td>
      <span class="hint-icon">?
        <span class="tooltip-text">${escHtml(d.hint_text)}</span>
      </span>
    </td>
    <td><span style="font-size:11px;color:#475569">${escHtml(d.impact_scope)}</span></td>
    <td>${fileInfo}</td>
    <td>${updatedAt}</td>
    <td>${badgeHtml(storageBadgeClass(d.storage_status), storageLabel(d.storage_status))}</td>
    <td>${badgeHtml(normalizeBadgeClass(d.normalize_status), normalizeLabel(d.normalize_status))}</td>
    <td>${badgeHtml(validationBadgeClass(d.validation_status), validationLabel(d.validation_status))}</td>
    <td>${badgeHtml(deployBadgeClass(d.deploy_status), deployLabel(d.deploy_status))}</td>
    <td>${osrmCell}</td>
    <td>${activeCell}</td>
    <td>
      <div class="action-group">
        <button class="btn btn-primary"
          onclick="openUpdateModal('${escAttr(escJs(d.dataset_id))}')"
          ${isRunning ? "disabled title='処理中'" : ""}>更新</button>
        <button class="btn btn-detail"
          onclick="openDetail('${escAttr(escJs(d.dataset_id))}')">詳細</button>
        ${!isRailwayPmtiles ? `<button class="btn btn-success"
          onclick="openDeployModal('${escAttr(escJs(d.dataset_id))}')"
          ${canDeploy ? "" : "disabled"}
          title="${canDeploy ? '実行環境へ反映' : escAttr(deployBlockReason(d))}">反映</button>` : ""}
        ${!isRailwayPmtiles ? `<button class="btn btn-secondary"
          onclick="openRollbackModal('${escAttr(escJs(d.dataset_id))}')"
          ${canRollback ? "" : "disabled"}
          title="${canRollback ? '1世代前に戻す' : (!d.has_backup ? 'バックアップがありません（初回デプロイ後に利用可）' : '処理中のため実行不可')}">戻す</button>` : ""}
        ${d.layer_type ? `<button class="btn btn-activate"
          onclick="openActivateModal('${escAttr(escJs(d.dataset_id))}')"
          ${canActivate ? "" : "disabled"}
          title="${d.is_active ? '既に有効です' : (d.layer_type ? '有効データセットに設定' : 'レイヤー種別なし')}">有効化</button>` : ""}
        ${d.requires_osrm_rebuild ? `<button class="btn btn-osrm"
          onclick="openOsrmModal('${escAttr(escJs(d.dataset_id))}')"
          ${canOsrm ? "" : "disabled"}
          title="${canOsrm ? 'ルートエンジン再構築' : '先に反映を実行してください'}">OSRM</button>` : ""}
        ${d.last_job_id ? `<button class="btn btn-secondary"
          onclick="openLogModal('${escAttr(escJs(d.last_job_id))}')"
          style="font-size:11px">ログ</button>` : ""}
      </div>
    </td>
  </tr>`;
}

function deployBlockReason(d) {
  if (d.has_running_job) return "処理が実行中です";
  if (!d.is_deployable) {
    if (d.validation_status !== "pass" && d.validation_status !== "not_required") {
      return "内容確認が完了していません";
    }
    return "取り込みが完了していません";
  }
  return "";
}

// ── 詳細パネル ────────────────────────────────────────
async function openDetail(datasetId) {
  _currentDatasetId = datasetId;
  document.getElementById("detail-panel").classList.add("visible");
  document.getElementById("detail-panel").scrollIntoView({ behavior: "smooth" });
  await refreshDetail(datasetId);

  if (_detailRefreshTimer) clearInterval(_detailRefreshTimer);
  _detailRefreshTimer = setInterval(async () => {
    if (_currentDatasetId && _detailAutoRefresh) {
      await refreshDetail(_currentDatasetId);
    }
  }, DETAIL_LOG_INTERVAL_MS);
}

async function refreshDetail(datasetId) {
  try {
    const detail = await fetchJSON(`${API}/datasets/${datasetId}`);
    _currentDetail = detail;
    renderDetail(detail);
  } catch (err) {
    console.warn("Detail refresh failed:", err);
  }
}

function renderDetail(detail) {
  const defn = detail.definition;
  const state = detail.state;
  const job = detail.last_job;

  document.getElementById("detail-title").textContent = defn.display_name;

  // 基本情報
  document.getElementById("detail-info").innerHTML = [
    detailRow("データセットID", `<span style="font-family:monospace;color:#6366f1">${escHtml(defn.dataset_id)}</span>`),
    detailRow("地域", regionLabel(defn.region)),
    defn.routing_profile
      ? detailRow("ルーティングプロファイル", `<span style="font-family:monospace">${escHtml(defn.routing_profile)}</span>`)
      : "",
    defn.osrm_stem
      ? detailRow("OSRMビルドベース名", `<span style="font-family:monospace;font-size:11px">${escHtml(defn.osrm_stem)}</span>`)
      : "",
    detailRow("説明", escHtml(defn.description)),
    detailRow("影響範囲", escHtml(defn.impact_scope)),
    detailRow("整形処理", defn.requires_normalize ? "あり" : "不要"),
    detailRow("内容確認", defn.requires_validation ? "あり" : "不要"),
    detailRow("対応形式", defn.accepted_extensions.join(", ")),
    detailRow("デプロイ先", `<span style="font-size:11px;font-family:monospace">${escHtml(defn.runtime_path)}</span>`),
  ].join("");

  // 状態
  document.getElementById("detail-status").innerHTML = [
    detailRow("現在のファイル", state.current_file_name
      ? `${escHtml(state.current_file_name)} (${formatBytes(state.current_file_size)})`
      : "なし"),
    detailRow("最終更新", state.updated_at ? formatDate(state.updated_at) : "—"),
    detailRow("最終反映", state.deployed_at ? formatDate(state.deployed_at) : "—"),
    detailRow("保管状態", badgeHtml(storageBadgeClass(state.storage_status), storageLabel(state.storage_status))),
    detailRow("整形状態", badgeHtml(normalizeBadgeClass(state.normalize_status), normalizeLabel(state.normalize_status))),
    detailRow("内容確認", badgeHtml(validationBadgeClass(state.validation_status), validationLabel(state.validation_status))),
    detailRow("反映状態", badgeHtml(deployBadgeClass(state.deploy_status), deployLabel(state.deploy_status))),
    state.osrm_rebuild_status !== "not_applicable"
      ? detailRow("OSRM状態", badgeHtml(osrmBadgeClass(state.osrm_rebuild_status), osrmLabel(state.osrm_rebuild_status)))
      : "",
    state.backup_path
      ? detailRow("バックアップ", `<span style="font-size:11px;color:#166534">✅ あり（ロールバック可）</span>`)
      : detailRow("バックアップ", `<span style="font-size:11px;color:#94a3b8">なし</span>`),
  ].join("");

  // エラー情報
  const errorSection = document.getElementById("detail-error-section");
  if (job && job.error_code) {
    errorSection.style.display = "";
    // INTERNAL_ERROR かつ exit_code がない場合はサーバ再起動による中断と判定
    const isRestartInterrupt = job.error_code === "INTERNAL_ERROR" && job.exit_code == null;
    const errorCodeLabel = isRestartInterrupt
      ? `<span style="font-family:monospace;color:#b91c1c">${escHtml(job.error_code)}</span> <span style="color:#92400e;font-size:0.85em">（アプリ再起動による中断）</span>`
      : `<span style="font-family:monospace;color:#b91c1c">${escHtml(job.error_code)}</span>`;
    document.getElementById("detail-error").innerHTML = [
      detailRow("エラーコード", errorCodeLabel),
      detailRow("内容", `<span style="color:#b91c1c">${escHtml(job.user_message || "")}</span>`),
      detailRow("対応方法", escHtml(job.action_message || "")),
    ].join("");
  } else {
    errorSection.style.display = "none";
  }

  // ジョブID表示
  if (job) {
    document.getElementById("detail-log-job-id").textContent = `job: ${job.job_id.substring(0, 8)}...`;
    loadDetailLog(job.job_id);
  }

  // 履歴
  renderDetailHistory(detail.history || []);
}

async function loadDetailLog(jobId) {
  try {
    const r = await fetchJSON(`${API}/jobs/${jobId}/log`);
    const area = document.getElementById("detail-log-area");
    area.innerHTML = r.lines.map(line => colorLogLine(line)).join("\n") || "ログなし";
    area.scrollTop = area.scrollHeight;
  } catch (err) {
    // quiet fail
  }
}

function renderDetailHistory(history) {
  const el = document.getElementById("detail-history");
  if (history.length === 0) {
    el.innerHTML = `<span style="color:#94a3b8;font-size:12px">履歴なし</span>`;
    return;
  }
  el.innerHTML = history.map(h => `
    <div style="padding:4px 0;border-bottom:1px solid #f1f5f9;display:flex;gap:8px;align-items:baseline">
      <span style="font-family:monospace;font-size:10px;color:#94a3b8">${formatDate(h.executed_at)}</span>
      <span style="color:#475569">${operationLabel(h.operation_type)}</span>
      <span class="badge ${h.result === 'success' ? 'badge-success' : 'badge-fail'}" style="font-size:10px">${h.result === 'success' ? '成功' : '失敗'}</span>
      ${h.source_file_name ? `<span style="font-size:10px;color:#94a3b8">${escHtml(h.source_file_name)}</span>` : ""}
    </div>`).join("");
}

function closeDetail() {
  document.getElementById("detail-panel").classList.remove("visible");
  _currentDatasetId = null;
  if (_detailRefreshTimer) { clearInterval(_detailRefreshTimer); _detailRefreshTimer = null; }
}

function toggleDetailAutoRefresh() {
  _detailAutoRefresh = !_detailAutoRefresh;
  document.getElementById("detail-auto-label").textContent = `自動更新 ${_detailAutoRefresh ? "ON" : "OFF"}`;
}

// ── 更新モーダル ──────────────────────────────────────
function openUpdateModal(datasetId) {
  const d = _allDatasets.find(x => x.dataset_id === datasetId);
  if (!d) return;
  _updateModalDataset = d;
  _selectedFiles = [];
  document.getElementById("upload-selected").classList.remove("visible");
  document.getElementById("upload-file-list").classList.remove("visible");
  document.getElementById("upload-file-list").innerHTML = "";
  const uploadInput = document.getElementById("upload-input");
  if (uploadInput) uploadInput.value = "";

  // 情報セット
  document.getElementById("um-name").textContent = d.display_name;
  // 説明はAPIの詳細を持っていないのでhint_textで代用
  document.getElementById("um-desc").textContent = d.hint_text;
  document.getElementById("um-scope").textContent = d.impact_scope;
  document.getElementById("um-current").textContent = d.current_file_name || "なし";

  // 詳細定義を取得してタブ構築
  fetchJSON(`${API}/datasets/${datasetId}`).then(detail => {
    const defn = detail.definition;
    document.getElementById("um-exts").textContent = defn.accepted_extensions.join(", ");
    document.getElementById("um-official-url").textContent =
      defn.official_source_url ||
      (defn.downloader_name ? `一括取得スクリプト: ${defn.downloader_name}` : "—");
    document.getElementById("um-size-limit").textContent =
      defn.max_browser_upload_mb > 0
        ? `最大ファイルサイズ: ${defn.max_browser_upload_mb} MB`
        : "このデータはブラウザアップロード非対応です";

    // アップロード無効表示
    const uploadDisabled = document.getElementById("upload-disabled-notice");
    const uploadZone = document.getElementById("upload-zone");
    if (defn.max_browser_upload_mb === 0 || !defn.accepted_input_modes.includes("upload")) {
      uploadDisabled.style.display = "block";
      uploadZone.style.pointerEvents = "none";
      uploadZone.style.opacity = "0.5";
    } else {
      uploadDisabled.style.display = "none";
      uploadZone.style.pointerEvents = "";
      uploadZone.style.opacity = "1";
    }

    // パイプライン説明
    const pipelineNotice = document.getElementById("um-post-ingest-notice");
    const pipelineDesc = document.getElementById("um-pipeline-desc");
    let steps = [];
    if (defn.requires_normalize) steps.push("整形処理");
    if (defn.requires_validation) steps.push("内容確認");
    if (defn.auto_deploy) steps.push("反映");
    if (steps.length > 0) {
      pipelineNotice.style.display = "";
      pipelineDesc.textContent = ` 取り込み後、自動的に${steps.join(" → ")}が実行されます。`;
    } else {
      pipelineNotice.style.display = "none";
    }

    // タブ構築
    buildInputTabs(defn.accepted_input_modes, defn.source_type);
  }).catch(err => {
    showNotice("error", "定義情報の取得に失敗しました");
  });

  document.getElementById("update-modal").classList.add("open");
}

function buildInputTabs(modes, sourceType) {
  const tabsEl = document.getElementById("input-tabs");

  // source_type="generated": ファイル入力不要の自動生成タブを表示
  if (sourceType === "generated") {
    tabsEl.innerHTML = `<button class="tab-btn" id="tab-btn-generate" onclick="switchInputTab('generate')">⚙️ 自動生成</button>`;
    ["upload", "fetch_url", "fetch_official", "railway_pmtiles"].forEach(m => {
      const p = document.getElementById(`tab-${m}`);
      if (p) p.classList.remove("active");
    });
    switchInputTab("generate");
    return;
  }

  // source_type="railway_pmtiles": ワンクリック更新タブを表示
  if (sourceType === "railway_pmtiles") {
    tabsEl.innerHTML = `<button class="tab-btn active" id="tab-btn-railway_pmtiles" onclick="switchInputTab('railway_pmtiles')">🚄 鉄道路線データ更新</button>`;
    ["upload", "fetch_url", "fetch_official", "generate"].forEach(m => {
      const p = document.getElementById(`tab-${m}`);
      if (p) p.classList.remove("active");
    });
    const rp = document.getElementById("tab-railway_pmtiles");
    if (rp) rp.classList.add("active");
    switchInputTab("railway_pmtiles");
    return;
  }

  const labels = { upload: "📁 ファイル選択", fetch_url: "🔗 URL指定取得", fetch_official: "🌐 公式サイトから取得" };
  tabsEl.innerHTML = modes.map(m =>
    `<button class="tab-btn" id="tab-btn-${m}" onclick="switchInputTab('${m}')">${labels[m] || m}</button>`
  ).join("");

  // 全パネル非表示
  ["upload", "fetch_url", "fetch_official", "generate", "railway_pmtiles"].forEach(m => {
    const p = document.getElementById(`tab-${m}`);
    if (p) p.classList.remove("active");
  });

  // 最初のタブを選択
  if (modes.length > 0) switchInputTab(modes[0]);
}

function switchInputTab(mode) {
  _activeInputTab = mode;
  ["upload", "fetch_url", "fetch_official", "generate", "railway_pmtiles"].forEach(m => {
    const btn = document.getElementById(`tab-btn-${m}`);
    const panel = document.getElementById(`tab-${m}`);
    if (btn) btn.classList.toggle("active", m === mode);
    if (panel) panel.classList.toggle("active", m === mode);
  });
}

function closeUpdateModal() {
  if (_chunkUploadMgr) {
    _chunkUploadMgr.cancel();
    _chunkUploadMgr = null;
  }
  _hideChunkProgress();
  document.getElementById("update-modal").classList.remove("open");
  _updateModalDataset = null;
  _selectedFiles = [];
}

// ── ファイル選択 ──────────────────────────────────────
function handleFileSelect(input) {
  if (input.files && input.files.length > 0) {
    setSelectedFiles(Array.from(input.files));
  }
}

function handleDrop(event) {
  event.preventDefault();
  document.getElementById("upload-zone").classList.remove("dragover");
  const files = Array.from(event.dataTransfer.files);
  if (files.length > 0) setSelectedFiles(files);
}

function setSelectedFiles(files) {
  _selectedFiles = files;
  const totalBytes = files.reduce((s, f) => s + f.size, 0);
  const summaryEl = document.getElementById("upload-selected");
  const listEl    = document.getElementById("upload-file-list");

  if (files.length === 1) {
    document.getElementById("upload-file-name").textContent = files[0].name;
    document.getElementById("upload-file-size").textContent = formatBytes(files[0].size);
    listEl.classList.remove("visible");
    listEl.innerHTML = "";
  } else {
    document.getElementById("upload-file-name").textContent = `${files.length} ファイル選択済み`;
    document.getElementById("upload-file-size").textContent = `合計 ${formatBytes(totalBytes)}`;
    listEl.innerHTML = files.map((f) =>
      `<div class="upload-file-list-item">
        <span class="fname" title="${escHtml(f.name)}">${escHtml(f.name)}</span>
        <span class="fsize">${formatBytes(f.size)}</span>
      </div>`
    ).join("");
    listEl.classList.add("visible");
  }
  summaryEl.classList.add("visible");
}

// ── チャンクアップロード進捗表示 ─────────────────────
function _showChunkProgress(file) {
  const el = document.getElementById("chunk-progress");
  document.getElementById("cp-filename").textContent = file.name;
  document.getElementById("cp-size").textContent = formatBytes(file.size);
  document.getElementById("cp-percent").textContent = "0%";
  document.getElementById("cp-speed").textContent = "—";
  document.getElementById("cp-eta").textContent = "—";
  document.getElementById("cp-bar").style.width = "0%";
  el.style.display = "block";
  document.getElementById("upload-zone").style.display = "none";
  document.getElementById("upload-selected").classList.remove("visible");
}

function _updateChunkProgress({ percent, speed, etaSec }) {
  document.getElementById("cp-percent").textContent = `${percent}%`;
  document.getElementById("cp-speed").textContent = _formatSpeed(speed);
  document.getElementById("cp-eta").textContent = etaSec != null ? `残り ${_formatEta(etaSec)}` : "—";
  document.getElementById("cp-bar").style.width = `${percent}%`;
}

function _hideChunkProgress() {
  const el = document.getElementById("chunk-progress");
  if (el) el.style.display = "none";
  const zone = document.getElementById("upload-zone");
  if (zone) zone.style.display = "";
}

function _formatSpeed(bps) {
  if (!bps || bps < 1) return "—";
  if (bps >= 1024 * 1024) return `${(bps / 1024 / 1024).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${bps.toFixed(0)} B/s`;
}

function _formatEta(sec) {
  if (sec < 60) return `${Math.ceil(sec)}秒`;
  if (sec < 3600) return `${Math.ceil(sec / 60)}分`;
  return `${(sec / 3600).toFixed(1)}時間`;
}

function cancelChunkUpload() {
  if (_chunkUploadMgr) {
    _chunkUploadMgr.cancel();
    _chunkUploadMgr = null;
  }
  _hideChunkProgress();
  const btn = document.getElementById("um-execute-btn");
  if (btn) { btn.disabled = false; btn.textContent = "処理を開始する"; }
  showNotice("info", "アップロードをキャンセルしました");
}

// ── 更新実行 ──────────────────────────────────────────
async function executeUpdate() {
  const d = _updateModalDataset;
  if (!d) return;

  const btn = document.getElementById("um-execute-btn");
  btn.disabled = true;
  btn.textContent = "送信中...";

  try {
    let job_id;

    if (_activeInputTab === "upload") {
      if (!_selectedFiles.length) { showNotice("error", "ファイルを選択してください"); btn.disabled = false; btn.textContent = "処理を開始する"; return; }

      if (_selectedFiles.length === 1) {
        // 単一ファイル → チャンクアップロード（大容量対応）
        const file = _selectedFiles[0];
        _chunkUploadMgr = new UploadManager({ api: '/admin/api/admin/upload' });
        _showChunkProgress(file);
        btn.textContent = "アップロード中...";
        try {
          const result = await _chunkUploadMgr.upload(file, d.dataset_id, {
            onProgress: (p) => _updateChunkProgress(p),
          });
          _chunkUploadMgr = null;
          job_id = result.job_id;
        } catch (err) {
          _chunkUploadMgr = null;
          _hideChunkProgress();
          if (err.cancelled) { btn.disabled = false; btn.textContent = "処理を開始する"; return; }
          throw err;
        }
        _hideChunkProgress();
      } else {
        // 複数ファイル → 従来の FormData（サーバー側で bundle.zip に梱包）
        const formData = new FormData();
        for (const f of _selectedFiles) formData.append("files", f);
        const res = await fetch(`${API}/datasets/${d.dataset_id}/upload`, { method: "POST", body: formData });
        const json = await res.json();
        if (!res.ok || !json.accepted) throw new Error(json.user_message || json.detail || "アップロードに失敗しました");
        job_id = json.job_id;
      }

    } else if (_activeInputTab === "fetch_url") {
      const url = document.getElementById("fetch-url-input").value.trim();
      if (!url) { showNotice("error", "URLを入力してください"); return; }
      const json = await postJSON(`${API}/datasets/${d.dataset_id}/fetch-url`, { url });
      if (!json.accepted) throw new Error(json.user_message || "取得に失敗しました");
      job_id = json.job_id;

    } else if (_activeInputTab === "fetch_official") {
      const json = await postJSON(`${API}/datasets/${d.dataset_id}/fetch-official`, {});
      if (!json.accepted) throw new Error(json.user_message || "取得に失敗しました");
      job_id = json.job_id;

    } else if (_activeInputTab === "generate") {
      const json = await postJSON(`${API}/datasets/${d.dataset_id}/generate`, {});
      if (!json.accepted) throw new Error(json.user_message || "生成に失敗しました");
      job_id = json.job_id;

    } else if (_activeInputTab === "railway_pmtiles") {
      const json = await postJSON(`${API}/datasets/${d.dataset_id}/railway-pmtiles-update`, {});
      if (!json.accepted) throw new Error(json.user_message || "更新要求に失敗しました");
      job_id = json.job_id;
    }

    closeUpdateModal();
    showNotice("success", "処理を受け付けました。ログから進捗を確認できます。");
    await loadDatasets();
    if (job_id) openLogModal(job_id);

  } catch (err) {
    showNotice("error", err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "処理を開始する";
  }
}

// ── 反映モーダル ──────────────────────────────────────
function openDeployModal(datasetId) {
  const d = _allDatasets.find(x => x.dataset_id === datasetId);
  if (!d) return;
  _deployModalDataset = d;
  document.getElementById("dm-name").textContent = d.display_name;
  document.getElementById("dm-artifact").textContent = d.current_file_name || "—";
  document.getElementById("dm-validation").innerHTML =
    badgeHtml(validationBadgeClass(d.validation_status), validationLabel(d.validation_status));
  document.getElementById("dm-runtime").textContent = "実行環境 (data_runtime)";
  document.getElementById("deploy-modal").classList.add("open");
}

function closeDeployModal() {
  document.getElementById("deploy-modal").classList.remove("open");
  _deployModalDataset = null;
}

async function executeDeploy() {
  const d = _deployModalDataset;
  if (!d) return;
  try {
    const json = await postJSON(`${API}/datasets/${d.dataset_id}/deploy`, {});
    if (!json.accepted) throw new Error(json.user_message || "反映に失敗しました");
    closeDeployModal();
    showNotice("success", "実行環境への反映を開始しました。");
    await loadDatasets();
    openLogModal(json.job_id);
  } catch (err) {
    showNotice("error", err.message);
    closeDeployModal();
  }
}

// ── ロールバックモーダル ──────────────────────────────
function openRollbackModal(datasetId) {
  const d = _allDatasets.find(x => x.dataset_id === datasetId);
  if (!d) return;
  _rollbackModalDataset = d;
  document.getElementById("rm-name").textContent = d.display_name;
  document.getElementById("rm-current").textContent = d.current_file_name || "—";
  document.getElementById("rollback-modal").classList.add("open");
}

function closeRollbackModal() {
  document.getElementById("rollback-modal").classList.remove("open");
  _rollbackModalDataset = null;
}

async function executeRollback() {
  const d = _rollbackModalDataset;
  if (!d) return;
  try {
    const json = await postJSON(`${API}/datasets/${d.dataset_id}/rollback`, {});
    if (!json.accepted) throw new Error(json.user_message || "ロールバックに失敗しました");
    closeRollbackModal();
    showNotice("success", "ロールバックを開始しました。");
    await loadDatasets();
    openLogModal(json.job_id);
  } catch (err) {
    showNotice("error", err.message);
    closeRollbackModal();
  }
}

// ── 有効化モーダル ────────────────────────────────────
function openActivateModal(datasetId) {
  const d = _allDatasets.find(x => x.dataset_id === datasetId);
  if (!d) return;
  _activateModalDataset = d;
  document.getElementById("am-name").textContent = d.display_name;
  document.getElementById("am-layer-type").textContent = layerTypeLabel(d.layer_type);
  document.getElementById("am-region").textContent = regionLabel(d.region);
  document.getElementById("activate-modal").classList.add("open");
}

function closeActivateModal() {
  document.getElementById("activate-modal").classList.remove("open");
  _activateModalDataset = null;
}

async function executeActivate() {
  const d = _activateModalDataset;
  if (!d) return;
  try {
    const res = await fetch(`${API}/active-mappings/${d.layer_type}/${d.region}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dataset_id: d.dataset_id }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
    closeActivateModal();
    showNotice("success", json.message || "有効データセットを設定しました。");
    await loadDatasets();
  } catch (err) {
    showNotice("error", err.message);
    closeActivateModal();
  }
}

// ── OSRM 再構築モーダル ───────────────────────────────
function openOsrmModal(datasetId) {
  const d = _allDatasets.find(x => x.dataset_id === datasetId);
  if (!d) return;
  _osrmModalDataset = d;
  document.getElementById("om-name").textContent = d.display_name;
  document.getElementById("osrm-modal").classList.add("open");
}

function closeOsrmModal() {
  document.getElementById("osrm-modal").classList.remove("open");
  _osrmModalDataset = null;
}

async function executeOsrmRebuild() {
  const d = _osrmModalDataset;
  if (!d) return;
  try {
    const json = await postJSON(`${API}/datasets/${d.dataset_id}/rebuild-osrm`, {});
    if (!json.accepted) throw new Error(json.user_message || "再構築に失敗しました");
    closeOsrmModal();
    showNotice("success", "ルートエンジンの再構築を開始しました。完了まで数分かかります。");
    await loadDatasets();
    openLogModal(json.job_id);
  } catch (err) {
    showNotice("error", err.message);
    closeOsrmModal();
  }
}

// ── ジョブログモーダル ────────────────────────────────
async function openLogModal(jobId) {
  _logModalJobId = jobId;
  _logAutoRefresh = true;
  document.getElementById("log-auto-label").textContent = "自動更新 ON";
  document.getElementById("log-modal").classList.add("open");
  await refreshLogModal();

  if (_logRefreshTimer) clearInterval(_logRefreshTimer);
  _logRefreshTimer = setInterval(async () => {
    if (!_logAutoRefresh) return;
    const job = await fetchJSON(`${API}/jobs/${_logModalJobId}`).catch(() => null);
    if (job && (job.status === "success" || job.status === "failed" || job.status === "canceled")) {
      _logAutoRefresh = false;
      document.getElementById("log-auto-label").textContent = "自動更新 OFF（完了）";
      document.getElementById("log-refresh-status").textContent = "処理完了";
    }
    await refreshLogModal();
  }, POLL_INTERVAL_MS);
}

async function refreshLogModal() {
  if (!_logModalJobId) return;
  try {
    const [job, logData] = await Promise.all([
      fetchJSON(`${API}/jobs/${_logModalJobId}`),
      fetchJSON(`${API}/jobs/${_logModalJobId}/log`),
    ]);

    document.getElementById("lm-job-id").textContent = job.job_id.substring(0, 8) + "...";
    document.getElementById("lm-job-type").textContent = jobTypeLabel(job.job_type);
    document.getElementById("lm-step").textContent = stepLabel(job.step);

    const statusBadge = document.getElementById("lm-status-badge");
    statusBadge.className = `badge ${jobStatusBadgeClass(job.status)}`;
    statusBadge.textContent = jobStatusLabel(job.status);

    const progressEl = document.getElementById("lm-progress");
    if (job.progress_message) {
      progressEl.textContent = job.progress_message;
      progressEl.classList.add("visible");
    } else {
      progressEl.classList.remove("visible");
    }

    const logArea = document.getElementById("lm-log-area");
    logArea.innerHTML = logData.lines.map(line => colorLogLine(line)).join("\n") || "ログなし";
    logArea.scrollTop = logArea.scrollHeight;

  } catch (err) {
    console.warn("Log refresh failed:", err);
  }
}

function closeLogModal() {
  document.getElementById("log-modal").classList.remove("open");
  if (_logRefreshTimer) { clearInterval(_logRefreshTimer); _logRefreshTimer = null; }
  _logModalJobId = null;
}

function toggleLogAutoRefresh() {
  _logAutoRefresh = !_logAutoRefresh;
  document.getElementById("log-auto-label").textContent = `自動更新 ${_logAutoRefresh ? "ON" : "OFF"}`;
}

// ── Config 管理 ───────────────────────────────────────
async function loadConfig() {
  const container = document.getElementById("config-cards-container");
  if (container) {
    container.innerHTML = `<div class="config-cards-placeholder"><div class="spinner"></div> 読み込み中...</div>`;
  }
  try {
    _configItems = await fetchJSON(`${API}/config`);
    _configLoaded = true;
    renderConfigTable();
  } catch (err) {
    if (container) {
      container.innerHTML = `<div class="config-cards-placeholder error">設定の取得に失敗しました: ${escHtml(err.message)}</div>`;
    }
    showNotice("error", "設定の取得に失敗しました: " + err.message);
  }
}

const CONFIG_CATEGORY_LABELS = {
  navigation: 'Navigation — ナビゲーション',
  voice:      'Voice — 音声',
  system:     'System — システム',
};
const CONFIG_CATEGORY_ORDER = ['navigation', 'voice', 'system'];

const CONFIG_META = {
  'navigation.arrival_radius_min': {
    purpose: '到着と判断する最小距離を決めます。GPS精度に関わらずこの値が下限になります。',
    impact: ['小さくすると → 到着判定が遅れる（精度は上がる）', '大きくすると → 早く到着扱いになる（誤判定が増える）'],
    recommended: '10〜15m',
    caution: '5m未満は誤動作のリスクがあります。',
    riskCheck: v => v < 5,
  },
  'navigation.arrival_radius_max': {
    purpose: 'GPS誤差が大きいときの最大到着距離を決めます。この値を超えて判定半径が広がることはありません。',
    impact: ['大きくすると → 誤判定が増える', '小さくすると → 到着しにくくなる'],
    recommended: '20〜25m',
  },
  'navigation.arrival_accuracy_multiplier': {
    purpose: 'GPS精度（accuracy値）にこの係数を掛けて到着判定半径を自動調整します。',
    impact: ['大きくすると → 判定が緩くなる（精度悪いときも到着しやすい）', '小さくすると → 判定が厳しくなる'],
    recommended: '0.7〜1.0',
  },
  'navigation.near_arrival_distance': {
    purpose: '「まもなく到着」バナーを表示し始める距離です。',
    impact: ['大きくすると → 早めに案内される', '小さくすると → ギリギリで表示される'],
    recommended: '10〜20m',
  },
  'navigation.final_reminder_distance': {
    purpose: '曲がり角や横断手前で直前音声を出す距離です。',
    impact: ['大きくすると → 早めに案内', '小さくすると → ピンポイントになる'],
    recommended: '4〜6m',
  },
  'navigation.arrival_distance_m': {
    purpose: 'ルート終端からこの距離以内を到着候補とします。',
    impact: ['大きくすると → 早く到着と判断', '小さくすると → より精確な到着判定'],
    recommended: '10〜15m',
  },
  'navigation.arrival_consecutive_count': {
    purpose: '到着候補が何回連続したら到着確定にするかです。ブレを防ぐ安定化パラメータです。',
    impact: ['大きくすると → 誤判定が減る（到着が遅れる）', '小さくすると → 素早く到着確定'],
    recommended: '2〜3回',
  },
  'navigation.off_route_distance_m': {
    purpose: 'ルートからこの距離以上離れたら逸脱とみなします。',
    impact: ['大きくすると → 逸脱しにくくなる', '小さくすると → 細い路地でも逸脱判定'],
    recommended: '15m',
  },
  'navigation.near_goal_off_route_distance_m': {
    purpose: '目的地近くでの逸脱判定距離です。通常より厳しく設定します。',
    impact: ['大きくすると → 近くで逸脱しにくい', '小さくすると → 精確なルート追従'],
    recommended: '15〜20m',
  },
  'navigation.near_goal_distance_m': {
    purpose: '目的地近傍として扱う距離の閾値です。この範囲内では逸脱判定が厳しくなります。',
    impact: ['大きくすると → 広い範囲で近傍扱い', '小さくすると → 実際に近づいてから切り替わる'],
    recommended: '15m',
  },
  'navigation.safe_crossing_search_radius': {
    label: '安全横断探索半径',
    description: '安全に道路を渡れる地点を探す距離（m）。0で無効。',
    effect: '大きいほど安全な横断ルートが増える',
    purpose: '安全に道路を渡れる地点を探す距離です。0にすると安全横断ロジックを完全に無効化します。',
    impact: ['大きくすると → 安全な横断ルートが増える', '0にすると → 最短ルート優先で横断誘導を出さない'],
    recommended: '30〜80m',
  },
  'navigation.safe_crossing_detour_ratio': {
    label: '安全横断迂回許容係数',
    description: 'どれだけ遠回りして安全に渡るかの許容値',
    effect: '大きいほど安全優先、小さいほど最短優先',
    purpose: '安全な横断地点を使うために、最短距離からどれだけ遠回りを許容するかを決めます。',
    impact: ['大きくすると → 安全優先の候補が増える', '小さくすると → 最短ルートに近い候補だけ残る'],
    recommended: '1.2〜1.8',
  },
  'voice.cooldown_ms': {
    purpose: '音声案内の発話間隔です。同じ案内が連続して流れないよう制限します。',
    impact: ['短くすると → うるさくなる可能性', '長くすると → 必要な案内が省略される'],
    recommended: '8000〜12000ms',
    caution: '3000ms未満は音声が頻繁に鳴りすぎます。',
    riskCheck: v => v < 3000,
  },
  'voice.rate': {
    purpose: '音声の話す速さを設定します（1.0=標準速度）。',
    impact: ['速くすると → 聞き取りにくくなる', '遅くすると → テンポが悪くなる'],
    recommended: '1.0〜1.2',
  },
};

function renderConfigTable() {
  const container = document.getElementById("config-cards-container");
  if (!container) return;

  const mainItems = _configItems.filter(item => item.category !== "osrm");
  const osrmItems = _configItems.filter(item => item.category === "osrm");

  if (mainItems.length === 0) {
    container.innerHTML = `<div class="config-cards-placeholder">設定がありません</div>`;
  } else {
    const groups = {};
    for (const item of mainItems) {
      if (!groups[item.category]) groups[item.category] = [];
      groups[item.category].push(item);
    }
    for (const { key, entry } of getUnsupportedPresetKeys()) {
      const item = _makeUnsupportedItem(key, entry);
      if (!groups[item.category]) groups[item.category] = [];
      groups[item.category].push(item);
    }
    const orderedCats = [
      ...CONFIG_CATEGORY_ORDER.filter(c => groups[c]),
      ...Object.keys(groups).filter(c => !CONFIG_CATEGORY_ORDER.includes(c)),
    ];
    const sections = [];
    for (const cat of orderedCats) {
      const label = CONFIG_CATEGORY_LABELS[cat] || cat;
      const topHtml = cat === 'navigation' ? `
        <div class="config-preset-bar">
          <div id="preset-buttons" class="preset-buttons"></div>
          <div id="preset-indicator" class="preset-indicator"></div>
        </div>
        <div id="preset-warning-bar" class="preset-warning-bar" style="display:none"></div>` : '';
      const extraHtml = cat === 'navigation' ? `
        <div class="config-computed-banner">
          <span class="config-computed-icon">🎯</span>
          <div>
            <div class="config-computed-label">到着判定半径プレビュー（GPS精度 → 実際の判定半径）</div>
            <div class="config-computed-value" id="config-arrival-computed">-</div>
          </div>
        </div>` : '';
      sections.push(`
        <div class="config-section">
          <div class="config-section-title">
            <span class="config-section-dot cat-${escAttr(cat)}"></span>
            ${escHtml(label)}
          </div>
          ${topHtml}
          <div class="config-cards-group">
            ${groups[cat].map(item => renderConfigCard(item)).join("")}
          </div>
          ${extraHtml}
        </div>`);
    }
    container.innerHTML = sections.join("");
    initPresetBar();
    updatePresetIndicator();
    updateArrivalComputed();
  }

  const osrmCard = document.getElementById("osrm-rebuild-card");
  const osrmTbody = document.getElementById("osrm-config-tbody");
  if (osrmCard && osrmTbody) {
    if (osrmItems.length > 0) {
      osrmCard.style.display = "";
      osrmTbody.innerHTML = osrmItems.map(item => renderConfigRow(item)).join("");
    } else {
      osrmCard.style.display = "none";
    }
  }
}

function renderConfigCard(item) {
  const isUnsupported = !!item._unsupported;
  console.log("[config-render]", item.key);
  const meta  = CONFIG_META[item.key] || {
    label: item.label || item.key,
    description: item.description || "",
    effect: "",
    purpose: item.description || "",
    impact: [],
    recommended: "",
  };
  const domId = configDomId(item.key);
  const input = renderConfigInput(item);

  const updatedAt = item.updated_at
    ? `<span class="config-card-updated">${formatDate(item.updated_at)}</span>`
    : `<span class="config-card-updated muted">—</span>`;

  const range = (item.type === "integer" || item.type === "float") && (item.min != null || item.max != null)
    ? `<div class="config-range">範囲: ${item.min ?? "—"}〜${item.max ?? "—"}</div>`
    : "";

  const initialValue = parseFloat(item.current_value);
  const isRisky = meta.riskCheck ? meta.riskCheck(initialValue) : false;
  const riskWarningHtml = (!isUnsupported && meta.riskCheck)
    ? `<div class="config-card-warning" id="config-warning-${domId}"${isRisky ? "" : ' style="display:none"'}>
         ⚠️ この設定は誤動作の可能性があります${meta.caution ? "（" + escHtml(meta.caution) + "）" : ""}
       </div>`
    : "";

  const unsupportedBannerHtml = isUnsupported
    ? `<div class="config-unsupported-banner">⚠ この設定は現在無効です（バックエンド未対応）</div>`
    : "";

  const metaHtml = (meta.purpose || meta.impact || meta.recommended)
    ? `<div class="config-meta-section">
        ${meta.purpose ? `<div class="config-meta-row">
          <span class="config-meta-label">目的</span>
          <span class="config-meta-text">${escHtml(meta.purpose)}</span>
        </div>` : ""}
        ${meta.impact ? `<div class="config-meta-row">
          <span class="config-meta-label">影響</span>
          <div class="config-meta-impact">${meta.impact.map(l => `<div class="config-impact-line">${escHtml(l)}</div>`).join("")}</div>
        </div>` : ""}
        ${meta.recommended ? `<div class="config-meta-row">
          <span class="config-meta-label">推奨</span>
          <span class="config-meta-text config-meta-recommended">${escHtml(meta.recommended)}</span>
        </div>` : ""}
      </div>`
    : `<div class="config-meta-fallback">${escHtml(item.description || "—")}</div>`;

  const readonlyBadge = !item.editable
    ? `<span class="config-readonly-badge">${isUnsupported ? "未対応" : "読み取り専用"}</span>`
    : "";

  const initialApplyHtml = (() => {
    if (isUnsupported) return "";
    const s = _configApplyStatus[item.key];
    if (s) {
      const badge = s.state === "applied"
        ? `<span class="apply-badge applied">${s.applyMode === "live" ? "反映中" : "保存済"}</span>`
        : `<span class="apply-badge error">エラー</span>`;
      return `${badge} <span class="apply-time">${s.at}</span>`;
    }
    return item.updated_at
      ? `<span class="apply-time">${formatDate(item.updated_at)}</span>`
      : "";
  })();

  return `<div class="config-card cat-${escAttr(item.category)}${isUnsupported ? " config-card-unsupported" : ""}" data-config-key="${escAttr(item.key)}">
    <div class="config-card-header">
      <div class="config-card-header-top">
        <span class="config-cat-badge cat-${escAttr(item.category)}">${escHtml(item.category)}</span>
        ${readonlyBadge}
      </div>
      <div class="config-card-title">${escHtml(item.label)}</div>
      <div class="config-card-key">${escHtml(item.key)}</div>
    </div>
    <div class="config-card-body">
      ${unsupportedBannerHtml}
      <div class="config-card-value-row">
        <label class="config-card-value-label">現在値</label>
        ${input}
        <span class="config-card-default">初期値: <code>${escHtml(formatConfigValue(item.default_value))}</code></span>
      </div>
      ${riskWarningHtml}
      ${metaHtml}
    </div>
    <div class="config-card-footer">
      <div class="config-footer-actions">
        <button class="btn btn-primary" onclick="saveConfigValue('${escAttr(item.key)}')" ${item.editable ? "" : "disabled"}>保存</button>
        <button class="btn btn-secondary btn-sm" onclick="onResetToDefault('${escAttr(item.key)}')" ${item.editable ? "" : "disabled"}>初期値に戻す</button>
        <div class="config-save-status" id="config-status-${domId}"></div>
      </div>
      <div class="config-card-apply" id="config-apply-${domId}">${initialApplyHtml}</div>
    </div>
  </div>`;
}

function renderConfigRow(item) {
  const input = renderConfigInput(item);
  const updatedAt = item.updated_at
    ? `<span style="font-size:12px">${formatDate(item.updated_at)}</span>`
    : `<span style="color:#cbd5e1;font-size:11px">—</span>`;
  const range = item.type === "integer" || item.type === "float"
    ? `<div class="config-range">${item.min ?? "—"}〜${item.max ?? "—"}</div>`
    : "";

  return `<tr data-config-key="${escHtml(item.key)}">
    <td>
      <div class="dataset-name">${escHtml(item.label)}</div>
      <div class="dataset-hint">${escHtml(item.category)} / ${escHtml(item.apply_mode)}</div>
    </td>
    <td><span class="dataset-id">${escHtml(item.key)}</span></td>
    <td>${input}${range}<div class="config-save-status" id="config-status-${configDomId(item.key)}"></div></td>
    <td><span class="config-default">${escHtml(formatConfigValue(item.default_value))}</span></td>
    <td><span style="font-size:12px;color:#475569">${escHtml(item.description || "—")}</span></td>
    <td>${updatedAt}</td>
    <td>
      <button class="btn btn-primary" onclick="saveConfigValue('${escAttr(item.key)}')" ${item.editable ? "" : "disabled"}>保存</button>
    </td>
  </tr>`;
}

function renderConfigInput(item) {
  const id = `config-input-${configDomId(item.key)}`;
  const onInput = `onConfigInputChange('${escAttr(item.key)}')`;
  if (item.type === "string" && Array.isArray(item.options) && item.options.length > 0) {
    return `<select class="config-input" id="${id}" onchange="${onInput}" ${item.editable ? "" : "disabled"}>
      ${item.options.map(option => `
        <option value="${escAttr(option)}" ${item.current_value === option ? "selected" : ""}>${escHtml(option)}</option>
      `).join("")}
    </select>`;
  }
  if (item.type === "boolean") {
    return `<label class="config-checkbox"><input id="${id}" type="checkbox" onchange="${onInput}" ${item.current_value ? "checked" : ""} ${item.editable ? "" : "disabled"}> 有効</label>`;
  }
  if (item.type === "integer" || item.type === "float") {
    const step = item.type === "integer" ? "1" : "0.1";
    const min = item.min === null || item.min === undefined ? "" : ` min="${item.min}"`;
    const max = item.max === null || item.max === undefined ? "" : ` max="${item.max}"`;
    return `<input class="config-input" id="${id}" type="number" step="${step}"${min}${max} value="${escAttr(item.current_value)}" oninput="${onInput}" ${item.editable ? "" : "disabled"}>`;
  }
  return `<input class="config-input" id="${id}" type="text" value="${escAttr(item.current_value)}" oninput="${onInput}" ${item.editable ? "" : "disabled"}>`;
}

function onConfigInputChange(key) {
  const meta = CONFIG_META[key];
  const input = document.getElementById(`config-input-${configDomId(key)}`);
  if (!input) return;
  const value = input.type === "checkbox" ? (input.checked ? 1 : 0) : parseFloat(input.value);
  if (meta && meta.riskCheck) {
    const warningEl = document.getElementById(`config-warning-${configDomId(key)}`);
    if (warningEl) warningEl.style.display = meta.riskCheck(value) ? "" : "none";
  }
  const ARRIVAL_KEYS = [
    'navigation.arrival_radius_min',
    'navigation.arrival_radius_max',
    'navigation.arrival_accuracy_multiplier',
  ];
  if (ARRIVAL_KEYS.includes(key)) updateArrivalComputed();
}

function updateArrivalComputed() {
  const getVal = (key, fallback) => {
    const input = document.getElementById(`config-input-${configDomId(key)}`);
    if (!input) return fallback;
    const v = parseFloat(input.value);
    return isNaN(v) ? fallback : v;
  };
  const minR = getVal('navigation.arrival_radius_min', 12);
  const maxR = getVal('navigation.arrival_radius_max', 25);
  const mult = getVal('navigation.arrival_accuracy_multiplier', 0.8);
  const scenarios = [5, 10, 15, 20, 30];
  const results = scenarios.map(acc => {
    const r = Math.min(Math.max(acc * mult, minR), maxR);
    return `GPS ${acc}m → <strong>${r.toFixed(0)}m</strong>`;
  }).join("　");
  const el = document.getElementById('config-arrival-computed');
  if (el) el.innerHTML = results;
}

async function saveConfigValue(key) {
  const item = _configItems.find(config => config.key === key);
  if (!item) return;
  const input = document.getElementById(`config-input-${configDomId(key)}`);
  const status = document.getElementById(`config-status-${configDomId(key)}`);
  if (!input) return;

  const oldValue = item.current_value;

  let value;
  if (item.type === "boolean") {
    value = input.checked;
  } else if (item.type === "integer") {
    value = Number.parseInt(input.value, 10);
  } else if (item.type === "float") {
    value = Number.parseFloat(input.value);
  } else {
    value = input.value;
  }

  try {
    if (status) {
      status.textContent = "保存中...";
      status.className = "config-save-status";
    }
    const updated = await putJSON(`${API}/config/${encodeURIComponent(key)}`, { value });
    const idx = _configItems.findIndex(config => config.key === key);
    if (idx >= 0) _configItems[idx] = updated.item;
    _onConfigSaved(key, oldValue, value, updated.item.apply_mode);
    renderConfigTable();
  } catch (err) {
    if (status) {
      status.textContent = err.message;
      status.className = "config-save-status error";
    }
    _onConfigSaveError(key);
    showNotice("error", "設定の保存に失敗しました: " + err.message);
  }
}

function onResetToDefault(key) {
  const item = _configItems.find(c => c.key === key);
  if (!item || !item.editable) return;
  const input = document.getElementById(`config-input-${configDomId(key)}`);
  if (!input) return;
  if (item.type === "boolean") {
    input.checked = !!item.default_value;
  } else {
    input.value = item.default_value;
  }
  onConfigInputChange(key);
  saveConfigValue(key);
}

function _onConfigSaved(key, oldValue, newValue, applyMode) {
  const at = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  _configApplyStatus[key] = { state: "applied", at, applyMode };
  updateConfigApplyStatus(key);
  _dispatchConfigLog(key, oldValue, newValue);
  const notice = applyMode === "live"
    ? "設定を保存しました。即時反映されます。"
    : "設定を保存しました。反映には画面の再読み込みが必要です。";
  showNotice("success", notice);
}

function _onConfigSaveError(key) {
  const at = new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  _configApplyStatus[key] = { state: "error", at };
  updateConfigApplyStatus(key);
}

function updateConfigApplyStatus(key) {
  const el = document.getElementById(`config-apply-${configDomId(key)}`);
  if (!el) return;
  const s = _configApplyStatus[key];
  if (!s) { el.innerHTML = ""; return; }
  const badge = s.state === "applied"
    ? `<span class="apply-badge applied">${s.applyMode === "live" ? "反映中" : "保存済"}</span>`
    : `<span class="apply-badge error">エラー</span>`;
  el.innerHTML = `${badge} <span class="apply-time">${s.at}</span>`;
}

function _dispatchConfigLog(key, oldValue, newValue) {
  const entry = { ts: new Date().toISOString(), key, oldValue, newValue };
  _configLogEntries.push(entry);
  if (_configLogEntries.length > CONFIG_LOG_MAX) {
    _configLogEntries.splice(0, _configLogEntries.length - CONFIG_LOG_MAX);
  }
  try { window.dispatchEvent(new CustomEvent("ohg:config-log", { detail: entry })); } catch (_) {}
  if (getSelectedLogsSource() === CONFIG_SOURCE_KEY) {
    appendLogLine(_formatConfigLogLine(entry));
  }
}

function _formatConfigLogLine(entry) {
  const t = new Date(entry.ts);
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const ss = String(t.getSeconds()).padStart(2, "0");
  if (entry.key === "__preset__") {
    const label = CONFIG_PRESETS[entry.newValue]?.label || entry.newValue;
    return `${hh}:${mm}:${ss}  [config]  preset applied: ${entry.newValue}（${label}）`;
  }
  if (entry._type === "config_warning") {
    return `${hh}:${mm}:${ss}  [config_warning]  ${entry._message || entry.newValue}`;
  }
  return `${hh}:${mm}:${ss}  [config]  ${entry.key}: ${entry.oldValue} → ${entry.newValue}`;
}

function _reloadConfigLogs() {
  _logsSource = CONFIG_SOURCE_KEY;
  _logsLines = _configLogEntries.map(_formatConfigLogLine);
  renderLogsViewer();
  updateLogsMeta();
}

function getUnsupportedPresetKeys() {
  const defined = new Set(_configItems.map(i => i.key));
  const seen    = new Set();
  const result  = [];
  for (const preset of Object.values(CONFIG_PRESETS)) {
    for (const [key, entry] of Object.entries(preset.values)) {
      if (!seen.has(key) && entry !== null && typeof entry === "object" && entry.requiresBackend && !defined.has(key)) {
        seen.add(key);
        result.push({ key, entry });
      }
    }
  }
  return result;
}

function _makeUnsupportedItem(key, entry) {
  const category = key.split(".")[0];
  return {
    key,
    category,
    label:         entry.label       || key.split(".").pop().replace(/_/g, " "),
    description:   entry.description || "",
    type:          "float",
    default_value: entry.value,
    current_value: entry.value,
    editable:      false,
    apply_mode:    "live",
    ui_order:      999,
    updated_at:    null,
    _unsupported:  true,
  };
}

function _handleUndefinedKey(key, requiresBackend) {
  const msg = requiresBackend
    ? `未対応キー（バックエンド未定義）: ${key}`
    : `未対応キー: ${key}`;
  console.warn(`[config] ${msg}`);

  const t  = new Date();
  const hh = String(t.getHours()).padStart(2, "0");
  const mm = String(t.getMinutes()).padStart(2, "0");
  const ss = String(t.getSeconds()).padStart(2, "0");

  const entry = { ts: t.toISOString(), key: "__warning__", oldValue: null, newValue: key, _type: "config_warning", _message: msg };
  _configLogEntries.push(entry);
  if (_configLogEntries.length > CONFIG_LOG_MAX) {
    _configLogEntries.splice(0, _configLogEntries.length - CONFIG_LOG_MAX);
  }
  try { window.dispatchEvent(new CustomEvent("ohg:config-log", { detail: entry })); } catch (_) {}
  if (getSelectedLogsSource() === CONFIG_SOURCE_KEY) {
    appendLogLine(`${hh}:${mm}:${ss}  [config_warning]  ${msg}`);
  }
}

// ── プリセット ─────────────────────────────────────────
const _PRESET_EXTRA_CLASS = { fastest: "preset-btn-fastest", urban_precision: "preset-btn-urban_precision" };

function initPresetBar() {
  const container = document.getElementById("preset-buttons");
  if (!container) return;
  container.innerHTML = Object.entries(CONFIG_PRESETS).map(([key, preset]) => {
    const extra = _PRESET_EXTRA_CLASS[key] ? ` ${_PRESET_EXTRA_CLASS[key]}` : "";
    return `<button class="preset-btn${extra}" id="preset-btn-${escAttr(key)}" onclick="applyPreset('${escAttr(key)}')">${escHtml(preset.label)}</button>`;
  }).join("");
}

function detectCurrentPreset() {
  if (_configItems.length === 0) return null;
  const current = Object.fromEntries(_configItems.map(i => [i.key, i.current_value]));
  for (const [presetKey, preset] of Object.entries(CONFIG_PRESETS)) {
    const match = Object.entries(preset.values).every(([key, entry]) => {
      if (entry !== null && typeof entry === "object" && entry.requiresBackend) return true;
      const val = (entry !== null && typeof entry === "object") ? entry.value : entry;
      const c = current[key];
      return c !== undefined && Math.abs(parseFloat(c) - parseFloat(val)) < 0.0001;
    });
    if (match) return presetKey;
  }
  return "custom";
}

function updatePresetIndicator() {
  const indicator  = document.getElementById("preset-indicator");
  const warningBar = document.getElementById("preset-warning-bar");
  if (!indicator) return;

  const presetKey = detectCurrentPreset();
  const preset    = presetKey ? CONFIG_PRESETS[presetKey] : null;

  if (presetKey === null) {
    indicator.innerHTML = `<span class="preset-current-label">現在: </span><span class="preset-badge preset-badge-loading">—</span>`;
  } else if (presetKey === "custom") {
    indicator.innerHTML = `<span class="preset-current-label">現在: </span><span class="preset-badge preset-badge-custom">カスタム</span>`;
  } else if (presetKey === "fastest") {
    indicator.innerHTML = `<span class="preset-current-label">現在: </span><span class="preset-badge preset-badge-fastest">⚡ ${escHtml(preset.label)}</span>`;
  } else if (presetKey === "urban_precision") {
    indicator.innerHTML = `<span class="preset-current-label">現在: </span><span class="preset-badge preset-badge-urban">🏙 ${escHtml(preset.label)}</span>`;
  } else {
    indicator.innerHTML = `<span class="preset-current-label">現在: </span><span class="preset-badge preset-badge-matched">${escHtml(preset.label)}</span>`;
  }

  if (warningBar) {
    if (preset && preset.warning) {
      let msg = `⚠ ${preset.warning}`;
      if (_presetSkippedKeys.length > 0) {
        const names = _presetSkippedKeys.map(k => k.split(".").pop()).join(", ");
        msg += `　（未対応キー ${_presetSkippedKeys.length}件: ${names} — Logsに記録済み）`;
      }
      warningBar.textContent = msg;
      warningBar.style.display = "";
    } else {
      warningBar.style.display = "none";
    }
  }

  Object.keys(CONFIG_PRESETS).forEach(key => {
    const btn = document.getElementById(`preset-btn-${key}`);
    if (btn) btn.classList.toggle("active", key === presetKey);
  });
}

function setPresetButtonsDisabled(disabled) {
  Object.keys(CONFIG_PRESETS).forEach(key => {
    const btn = document.getElementById(`preset-btn-${key}`);
    if (btn) btn.disabled = disabled;
  });
}

async function _applyConfigValueDirect(key, value, requiresBackend = false) {
  const item = _configItems.find(c => c.key === key);
  if (!item) {
    _handleUndefinedKey(key, requiresBackend);
    return { ok: true, skipped: true };
  }
  const oldValue = item.current_value;
  try {
    const updated = await putJSON(`${API}/config/${encodeURIComponent(key)}`, { value });
    const idx = _configItems.findIndex(c => c.key === key);
    if (idx >= 0) _configItems[idx] = updated.item;
    _configApplyStatus[key] = {
      state: "applied",
      at: new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      applyMode: updated.item.apply_mode,
    };
    _dispatchConfigLog(key, oldValue, value);
    return { ok: true };
  } catch (err) {
    _configApplyStatus[key] = {
      state: "error",
      at: new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    };
    return { ok: false, error: err.message };
  }
}

async function applyPreset(presetKey) {
  const preset = CONFIG_PRESETS[presetKey];
  if (!preset) return;

  setPresetButtonsDisabled(true);
  const indicator = document.getElementById("preset-indicator");
  if (indicator) {
    indicator.innerHTML = `<span class="preset-current-label">適用中... </span><div class="spinner"></div>`;
  }

  const errors  = [];
  const skipped = [];
  for (const [key, entry] of Object.entries(preset.values)) {
    const value          = (entry !== null && typeof entry === "object") ? entry.value : entry;
    const requiresBackend = (entry !== null && typeof entry === "object") && !!entry.requiresBackend;
    const result = await _applyConfigValueDirect(key, value, requiresBackend);
    if (!result.ok)      errors.push(`${key}: ${result.error}`);
    if (result.skipped)  skipped.push(key);
  }

  _presetSkippedKeys = skipped;
  _dispatchConfigLog("__preset__", null, presetKey);
  renderConfigTable(); // updatePresetIndicator も内部で呼ぶ

  if (errors.length > 0) {
    showNotice("error", `「${preset.label}」の適用中にエラーが発生しました: ${errors.join(", ")}`);
  } else if (skipped.length > 0) {
    showNotice("success", `「${preset.label}」を適用しました（未対応キー ${skipped.length}件はスキップ — Logsに記録済み）`);
  } else {
    showNotice("success", `「${preset.label}」を適用しました`);
  }

  setPresetButtonsDisabled(false);
}

const _OSRM_PRESETS = {
  ohg:     { "osrm.trunk_penalty": 0.15, "osrm.primary_penalty": 0.25, "osrm.secondary_factor": 0.80 },
  default: { "osrm.trunk_penalty": 1.0,  "osrm.primary_penalty": 1.0,  "osrm.secondary_factor": 1.0  },
};

function fillOsrmPreset(preset) {
  const values = _OSRM_PRESETS[preset];
  if (!values) return;
  Object.entries(values).forEach(([key, val]) => {
    const el = document.getElementById(`config-input-${configDomId(key)}`);
    if (el) el.value = val;
  });
}

const _OSRM_STEP_LABELS = {
  accepted:         "受付済み",
  osrm_extract:     "osrm-extract 実行中...",
  osrm_partition:   "osrm-partition 実行中...",
  osrm_customize:   "osrm-customize / コンテナ再起動中...",
  completed:        "完了",
  failed:           "失敗",
};

async function triggerOsrmRebuild() {
  const btn    = document.getElementById("osrm-rebuild-btn");
  const status = document.getElementById("osrm-rebuild-status");
  if (btn) btn.disabled = true;
  if (status) { status.textContent = "再ビルドを開始中..."; status.style.color = "#f59e0b"; }

  let jobId = null;
  try {
    const res = await fetch(`${API}/osrm/rebuild`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (res.status === 409) {
      throw new Error(body.detail || "再ビルドが既に実行中です");
    }
    if (!res.ok) {
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    jobId = body.job_id;
  } catch (err) {
    if (status) { status.textContent = "❌ " + err.message; status.style.color = "#b91c1c"; }
    showNotice("error", "OSRM再ビルドの開始に失敗しました: " + err.message);
    if (btn) btn.disabled = false;
    return;
  }

  if (status) { status.textContent = "再ビルド中..."; status.style.color = "#f59e0b"; }
  await _pollOsrmRebuildJob(jobId, btn, status);
}

async function _pollOsrmRebuildJob(jobId, btn, status) {
  const MAX_POLLS = 360;   // 最大 30 分 (360 × 5s)
  const INTERVAL  = 5000;

  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, INTERVAL));

    let job;
    try {
      job = await fetchJSON(`/admin/api/admin/jobs/${jobId}`);
    } catch (_) {
      continue;  // ポーリング失敗は無視して継続
    }

    const stepLabel = _OSRM_STEP_LABELS[job.step] || job.progress_message || job.step;

    if (job.status === "success") {
      if (status) { status.textContent = "✅ 再ビルド完了"; status.style.color = "#16a34a"; }
      if (btn) btn.disabled = false;
      showNotice("success", "OSRMプロファイルの再ビルドが完了しました。");
      return;
    }

    if (job.status === "failed") {
      const msg = job.user_message || "再ビルドに失敗しました";
      if (status) { status.textContent = "❌ " + msg; status.style.color = "#b91c1c"; }
      if (btn) btn.disabled = false;
      showNotice("error", "OSRM再ビルドに失敗しました: " + msg);
      return;
    }

    if (status) {
      status.textContent = stepLabel;
      status.style.color = "#f59e0b";
    }
  }

  // タイムアウト
  if (status) { status.textContent = "タイムアウト（ジョブID: " + jobId + "）"; status.style.color = "#b91c1c"; }
  if (btn) btn.disabled = false;
  showNotice("error", "OSRM再ビルドの完了確認がタイムアウトしました。ジョブID: " + jobId);
}

async function openConfigHistoryModal() {
  const modal = document.getElementById("config-history-modal");
  const list = document.getElementById("config-history-list");
  modal.classList.add("open");
  list.textContent = "履歴を読み込み中...";
  try {
    const history = await fetchJSON(`${API}/config/history`);
    renderConfigHistory(history);
  } catch (err) {
    list.textContent = "履歴の取得に失敗しました: " + err.message;
  }
}

function renderConfigHistory(history) {
  const list = document.getElementById("config-history-list");
  if (!history.length) {
    list.innerHTML = `<div style="color:#94a3b8;font-size:13px">設定変更履歴はまだありません。</div>`;
    return;
  }
  list.innerHTML = history.map(entry => `
    <div class="config-history-entry">
      <div>
        <span class="dataset-id">${escHtml(entry.key)}</span>
        <div class="dataset-hint">${formatDate(entry.updated_at)}</div>
      </div>
      <div class="config-history-values">
        <span>${escHtml(formatConfigValue(entry.old_value))}</span>
        <span>→</span>
        <strong>${escHtml(formatConfigValue(entry.new_value))}</strong>
      </div>
    </div>
  `).join("");
}

function closeConfigHistoryModal() {
  document.getElementById("config-history-modal").classList.remove("open");
}

// ── Logs タブ ─────────────────────────────────────────
async function initializeLogsPanel() {
  try {
    await loadLogSources();
    await loadLogsStatus();
    await reloadLogs();
    _logsLoaded = true;
    connectLogsStream();
  } catch (err) {
    showNotice("error", "ログの初期化に失敗しました: " + err.message);
    setLogsConnectionStatus("error", "初期化失敗");
  }
}

async function loadLogSources() {
  const select = document.getElementById("logs-source-select");
  if (select) {
    select.innerHTML = `<option value="">読み込み中...</option>`;
    select.disabled = true;
  }

  const sources = await fetchJSON(`${API}/logs/sources`);
  _logSources = Array.isArray(sources) ? sources : [];

  if (_logSources.length === 0) {
    _logsSource = "app";
    if (select) {
      select.innerHTML = `<option value="app">Application</option>`;
      select.value = "app";
      select.disabled = false;
    }
    return;
  }

  if (!_logSources.some(source => source.key === _logsSource)) {
    _logsSource = _logSources[0].key;
  }

  if (select) {
    select.innerHTML = _logSources.map(source => `
      <option value="${escAttr(source.key)}">${escHtml(source.label)}</option>
    `).join("") + `<option value="${VOICE_SOURCE_KEY}">Voice（音声ナビ）</option>`
      + `<option value="${CONFIG_SOURCE_KEY}">Config（設定変更）</option>`;
    select.value = _logsSource;
    select.disabled = false;
  }
}

async function reloadLogs() {
  const viewer = document.getElementById("logs-viewer");
  if (viewer) viewer.textContent = "ログを読み込み中...";

  const source = getSelectedLogsSource();

  if (source === VOICE_SOURCE_KEY) {
    _reloadVoiceLogs();
    return;
  }

  if (source === CONFIG_SOURCE_KEY) {
    _reloadConfigLogs();
    return;
  }

  await loadLogsStatus();
  const data = await fetchJSON(`${API}/logs?source=${encodeURIComponent(source)}&limit=200`);
  _logsSource = source;
  _logsLines = Array.isArray(data.lines) ? data.lines.slice(-LOGS_MAX_LINES) : [];
  renderLogsViewer();
  updateLogsMeta();
}

function _reloadVoiceLogs() {
  _logsSource = VOICE_SOURCE_KEY;
  try {
    const stored = JSON.parse(localStorage.getItem(VOICE_LOG_STORAGE_KEY) || '[]');
    _logsLines = stored.slice(-VOICE_LOG_MAX).map(_formatVoiceLogLine);
  } catch (_) {
    _logsLines = [];
  }
  renderLogsViewer();
  updateLogsMeta();
}

function _formatVoiceLogLine(entry) {
  const t = new Date(entry.ts);
  const hh = String(t.getHours()).padStart(2, '0');
  const mm = String(t.getMinutes()).padStart(2, '0');
  const ss = String(t.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}  [${entry.type || 'voice'}]  ${entry.text}`;
}

async function loadLogsStatus() {
  _logsStatus = await fetchJSON(`${API}/logs/status`);
  updateLogsMeta();
}

async function handleLogsSourceChange() {
  const wasConnected = !!_logsEventSource || !!_voiceChannel;
  disconnectLogsStream({ preserveStatus: false });
  await reloadLogs();
  if (wasConnected) {
    connectLogsStream();
  }
}

function connectLogsStream() {
  const source = getSelectedLogsSource();
  disconnectLogsStream({ preserveStatus: false });
  _logsSource = source;

  if (source === VOICE_SOURCE_KEY) {
    _connectVoiceChannel();
    return;
  }

  if (source === CONFIG_SOURCE_KEY) {
    _logsSource = CONFIG_SOURCE_KEY;
    setLogsConnectionStatus("connected", "ライブ");
    updateLogsControls();
    return;
  }

  try {
    const es = new EventSource(`${API}/logs/stream?source=${encodeURIComponent(source)}`);
    _logsEventSource = es;
    setLogsConnectionStatus("connecting", "接続中");
    updateLogsControls();

    es.addEventListener("open", () => {
      setLogsConnectionStatus("connected", "接続中");
      updateLogsControls();
    });

    es.addEventListener("log", event => {
      const payload = JSON.parse(event.data);
      appendLogLine(payload.line || "");
      setLogsConnectionStatus("connected", "接続中");
      updateLogsControls();
    });

    es.addEventListener("heartbeat", () => {
      if (_logsEventSource === es) {
        setLogsConnectionStatus("connected", "接続中");
      }
    });

    es.onerror = () => {
      if (_logsEventSource === es) {
        setLogsConnectionStatus("error", "再接続中");
      }
    };
  } catch (err) {
    _logsEventSource = null;
    setLogsConnectionStatus("error", "接続失敗");
    updateLogsControls();
    showNotice("error", "ログストリームの接続に失敗しました: " + err.message);
  }
}

function _connectVoiceChannel() {
  try {
    _voiceChannel = new BroadcastChannel('ohg-voice-log');
    setLogsConnectionStatus('connected', 'ライブ');
    updateLogsControls();
    _voiceChannel.onmessage = (event) => {
      appendLogLine(_formatVoiceLogLine(event.data));
    };
    _voiceChannel.onmessageerror = () => {
      setLogsConnectionStatus('error', '受信エラー');
    };
  } catch (err) {
    _voiceChannel = null;
    setLogsConnectionStatus('error', '接続失敗');
    updateLogsControls();
  }
}

function disconnectLogsStream(options = {}) {
  if (_logsEventSource) {
    _logsEventSource.close();
    _logsEventSource = null;
  }
  if (_voiceChannel) {
    _voiceChannel.close();
    _voiceChannel = null;
  }
  if (!options.preserveStatus) {
    setLogsConnectionStatus("disconnected", "未接続");
  }
  updateLogsControls();
}

function clearLogsViewer() {
  _logsLines = [];
  if (getSelectedLogsSource() === VOICE_SOURCE_KEY) {
    try { localStorage.removeItem(VOICE_LOG_STORAGE_KEY); } catch (_) {}
  }
  renderLogsViewer();
  updateLogsMeta();
}

async function runLogsCleanup() {
  const button = document.getElementById("logs-cleanup-btn");
  if (button) {
    button.disabled = true;
    button.textContent = "実行中...";
  }
  try {
    const result = await postJSON(`${API}/logs/cleanup`, {});
    await loadLogsStatus();
    await reloadLogs();
    const cleaned = (result.sources || [])
      .map(source => `${source.key}:${formatBytes(source.size_bytes_after || 0)}`)
      .join(" ");
    showNotice("success", `ログクリーンアップを実行しました。${cleaned}`.trim());
  } catch (err) {
    showNotice("error", "ログクリーンアップに失敗しました: " + err.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "今すぐクリーンアップ";
    }
  }
}

function toggleLogsAutoScroll() {
  const checkbox = document.getElementById("logs-autoscroll-toggle");
  _logsAutoScroll = !checkbox || checkbox.checked;
  if (_logsAutoScroll) {
    scrollLogsViewerToBottom();
  }
}

function appendLogLine(line) {
  _logsLines.push(line);
  if (_logsLines.length > LOGS_MAX_LINES) {
    _logsLines.splice(0, _logsLines.length - LOGS_MAX_LINES);
  }
  renderLogsViewer();
  updateLogsMeta();
}

function renderLogsViewer() {
  const viewer = document.getElementById("logs-viewer");
  if (!viewer) return;

  if (_logsLines.length === 0) {
    viewer.textContent = "ログがありません";
  } else {
    viewer.innerHTML = _logsLines.map(line => colorLogLine(line)).join("\n");
  }

  if (_logsAutoScroll) {
    scrollLogsViewerToBottom();
  }
}

function scrollLogsViewerToBottom() {
  const viewer = document.getElementById("logs-viewer");
  if (viewer) {
    viewer.scrollTop = viewer.scrollHeight;
  }
}

function updateLogsMeta() {
  const sourceMeta = document.getElementById("logs-source-meta");
  const lineCount  = document.getElementById("logs-line-count");
  const sizeMeta   = document.getElementById("logs-size-meta");
  const isVoice    = getSelectedLogsSource() === VOICE_SOURCE_KEY;
  const isConfig   = getSelectedLogsSource() === CONFIG_SOURCE_KEY;
  if (sourceMeta) {
    const label = isVoice ? "Voice（音声ナビ）" : (isConfig ? "Config（設定変更）" : (_logsSource || "—"));
    sourceMeta.textContent = `source: ${label}`;
  }
  if (lineCount) {
    const maxLines = isVoice ? VOICE_LOG_MAX : (isConfig ? CONFIG_LOG_MAX : LOGS_MAX_LINES);
    lineCount.textContent = `${_logsLines.length} / ${maxLines} lines`;
  }
  if (sizeMeta) {
    if (isVoice || isConfig) {
      sizeMeta.textContent = "size: —";
    } else {
      const src = (_logsStatus.sources || []).find(item => item.key === _logsSource);
      sizeMeta.textContent = `size: ${formatBytes(src ? src.size_bytes : 0)}`;
    }
  }
}

function updateLogsControls() {
  const connectBtn    = document.getElementById("logs-connect-btn");
  const disconnectBtn = document.getElementById("logs-disconnect-btn");
  const cleanupBtn    = document.getElementById("logs-cleanup-btn");
  const isVoice       = getSelectedLogsSource() === VOICE_SOURCE_KEY;
  const isConfig      = getSelectedLogsSource() === CONFIG_SOURCE_KEY;
  const isConnected   = isVoice ? !!_voiceChannel : (isConfig ? true : !!_logsEventSource);
  if (connectBtn)    connectBtn.disabled    = isConnected;
  if (disconnectBtn) disconnectBtn.disabled = isConfig || !isConnected;
  if (cleanupBtn)    cleanupBtn.style.display = (isVoice || isConfig) ? "none" : "";
}

function setLogsConnectionStatus(state, label) {
  const el = document.getElementById("logs-connection-status");
  if (!el) return;
  el.className = `logs-status ${state}`;
  el.textContent = label;
}

function getSelectedLogsSource() {
  const select = document.getElementById("logs-source-select");
  return (select && select.value) || _logsSource || "app";
}

// ── ユーティリティ ────────────────────────────────────
async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.user_message || body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(json.user_message || json.detail || `HTTP ${res.status}`);
  }
  return json;
}

async function putJSON(url, body) {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(json.user_message || json.detail || `HTTP ${res.status}`);
  }
  return json;
}

function showNotice(type, message) {
  const el = document.getElementById("notice-bar");
  el.textContent = message;
  el.className = `notice-bar ${type}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.className = "notice-bar"; }, 6000);
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function escAttr(value) {
  return escHtml(value).replace(/'/g, "&#39;");
}

// inline onclick="fn('${value}')" のように、値を "HTML属性の中の
// 単一引用符で囲まれたJS文字列リテラル" へ埋め込む箇所専用のescape。
// HTML属性値はブラウザがentity decodeしてから inline event handlerの
// JSソースとして解釈するため、escAttr（'を&#39;にするだけ）単独では
// JS文字列の境界を破れてしまう（&#39;はdecodeされ生の'に戻ってから
// JSとして解釈されるため）。escJsで先にJS文字列として安全な形
// （\'・\\）へ変換してからescAttrへ通すことで、decode後もJS文字列
// リテラルの境界を破れない状態を保つ。使う場合は必ず
// escAttr(escJs(value)) の順で合成すること。
function escJs(str) {
  return String(str || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function configDomId(key) {
  return key.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function formatConfigValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function badgeHtml(cls, label) {
  return `<span class="badge ${cls}">${escHtml(label)}</span>`;
}

function detailRow(label, value) {
  return `<div class="detail-row"><span class="detail-label">${label}</span><span class="detail-value">${value}</span></div>`;
}

function colorLogLine(line) {
  const esc = escHtml(line);
  // Voice log: "HH:MM:SS  [type]  text" — type-based coloring
  const vm = line.match(/^(\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+(.+)$/);
  if (vm) {
    const type = vm[2];
    if (type === "config")         return `<span class="log-line-config">${esc}</span>`;
    if (type === "config_warning") return `<span class="log-line-config-warning">${esc}</span>`;
    let cls = "log-line-voice";
    if (/crossing/.test(type)) cls = "log-line-voice-crossing";
    else if (/turn|arrival/.test(type)) cls = "log-line-voice-turn";
    return `<span class="${cls}">${esc}</span>`;
  }
  if (/ERROR|FAILED|error|failed/.test(line)) return `<span class="log-line-error">${esc}</span>`;
  if (/success|completed|SUCCESS/.test(line)) return `<span class="log-line-success">${esc}</span>`;
  if (/WARNING|WARN|warn/.test(line)) return `<span class="log-line-warn">${esc}</span>`;
  return esc;
}

function formatBytes(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + " MB";
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + " GB";
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,"0")}/${String(d.getDate()).padStart(2,"0")} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

function regionLabel(r) {
  const map = {
    tokyo: "東京都",
    kanagawa: "神奈川県",
    kanto: "関東広域",
  };
  return map[r] || r;
}

function layerTypeLabel(lt) {
  const map = {
    shelter: "避難場所", tsunami: "津波浸水想定", flood: "洪水浸水想定",
    storm_surge: "高潮浸水想定", inland_flood: "内水氾濫リスク",
    landslide: "土砂災害警戒", admin_boundary: "行政区域境界",
  };
  return lt ? (map[lt] || lt) : "—";
}

function operationLabel(op) {
  const map = {
    ingest: "取り込み", normalize: "整形", validate: "内容確認", generate: "自動生成",
    deploy: "反映", rollback: "ロールバック", osrm_rebuild: "OSRM再構築"
  };
  return map[op] || op;
}

function jobTypeLabel(t) {
  const map = {
    ingest_upload: "ファイル取り込み", ingest_fetch_url: "URL取得",
    ingest_fetch_official: "公式取得", normalize: "整形処理",
    validate: "内容確認", generate: "自動生成", deploy: "反映",
    rollback: "ロールバック", osrm_rebuild: "OSRM再構築",
    railway_pmtiles_update: "鉄道路線PMTiles更新"
  };
  return map[t] || t;
}

function stepLabel(s) {
  const map = {
    accepted: "受付済み", download: "取得中", upload_store: "保管中",
    normalize: "整形中", validate: "確認中", backup: "バックアップ中",
    deploy: "反映中", rollback: "ロールバック中",
    osrm_extract: "データ展開中", osrm_partition: "ルート最適化中", osrm_customize: "インデックス構築中",
    completed: "完了", failed: "失敗"
  };
  return map[s] || s;
}

function jobStatusLabel(s) {
  const map = { queued: "待機中", running: "実行中", success: "成功", failed: "失敗", canceled: "キャンセル" };
  return map[s] || s;
}

function jobStatusBadgeClass(s) {
  const map = { queued: "badge-not-start", running: "badge-running", success: "badge-success", failed: "badge-fail", canceled: "badge-none" };
  return map[s] || "badge-none";
}

// ── バッジクラス / ラベル ─────────────────────────────
function storageBadgeClass(s) {
  return { none: "badge-none", stored: "badge-stored" }[s] || "badge-none";
}
function storageLabel(s) {
  return { none: "未取込", stored: "保管済" }[s] || s;
}

function normalizeBadgeClass(s) {
  return {
    not_required: "badge-not-req", not_started: "badge-not-start",
    running: "badge-running", success: "badge-success", failed: "badge-fail"
  }[s] || "badge-none";
}
function normalizeLabel(s) {
  return {
    not_required: "不要", not_started: "未実行",
    running: "整形中", success: "整形済", failed: "整形失敗"
  }[s] || s;
}

function validationBadgeClass(s) {
  return {
    not_required: "badge-not-req", not_started: "badge-not-start",
    running: "badge-running", pass: "badge-pass", fail: "badge-fail"
  }[s] || "badge-none";
}
function validationLabel(s) {
  return {
    not_required: "不要", not_started: "未確認",
    running: "確認中", pass: "確認済", fail: "確認失敗"
  }[s] || s;
}

function deployBadgeClass(s) {
  return {
    not_deployed: "badge-not-dep", deployable: "badge-deployable",
    deploying: "badge-deploying", deployed: "badge-success", failed: "badge-failed"
  }[s] || "badge-none";
}
function deployLabel(s) {
  return {
    not_deployed: "未反映", deployable: "反映可能",
    deploying: "反映中", deployed: "反映済", failed: "反映失敗"
  }[s] || s;
}

function osrmBadgeClass(s) {
  return {
    not_applicable: "badge-na", not_started: "badge-not-start",
    running: "badge-running", success: "badge-success", failed: "badge-fail"
  }[s] || "badge-na";
}
function osrmLabel(s) {
  return {
    not_applicable: "—", not_started: "未実行",
    running: "再構築中", success: "構築済", failed: "失敗"
  }[s] || s;
}
