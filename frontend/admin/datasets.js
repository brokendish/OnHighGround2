/**
 * datasets.js — データ運用管理画面 フロントエンドロジック
 *
 * 設計方針:
 * - 依存ライブラリなし（バニラJS）
 * - API との通信は /api/admin/datasets/* エンドポイント
 * - ポーリングで状態を自動更新（3秒間隔、実行中ジョブがある場合）
 */

"use strict";

const API = "/api/admin";
const POLL_INTERVAL_MS = 3000;
const DETAIL_LOG_INTERVAL_MS = 3000;
const LIST_AUTO_REFRESH_INTERVAL_MS = 5000;
const LOGS_MAX_LINES = 1000;

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
let _logsStatus = { sources: [] };
let _configChangeEventSource = null; // Logs用SSEとは独立した接続

// ── 初期化 ────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([populateLayerTypeFilter(), populateRegionFilter()]);
  loadDatasets();
  _listRefreshTimer = setInterval(loadDatasets, LIST_AUTO_REFRESH_INTERVAL_MS);
  connectAdminConfigChangeSSE();
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
  const canDeploy = d.is_deployable && !isRunning;
  const canRollback = d.deploy_status === "deployed" && d.has_backup && !isRunning;
  const canOsrm = d.requires_osrm_rebuild && d.deploy_status === "deployed" && !isRunning;
  const canActivate = d.layer_type && d.deploy_status === "deployed" && !d.is_active && !isRunning;

  const fileInfo = d.current_file_name
    ? `<div class="file-name" title="${d.current_file_name}">${d.current_file_name}</div>
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

  return `<tr data-id="${d.dataset_id}" ${d.is_active ? 'class="row-active"' : ''}>
    <td><span style="font-size:11px;color:#64748b">${regionLabel(d.region)}</span></td>
    <td><span class="dataset-id">${d.dataset_id}</span></td>
    <td>
      <div class="dataset-name">${d.display_name}</div>
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
          onclick="openUpdateModal('${d.dataset_id}')"
          ${isRunning ? "disabled title='処理中'" : ""}>更新</button>
        <button class="btn btn-detail"
          onclick="openDetail('${d.dataset_id}')">詳細</button>
        <button class="btn btn-success"
          onclick="openDeployModal('${d.dataset_id}')"
          ${canDeploy ? "" : "disabled"}
          title="${canDeploy ? '実行環境へ反映' : deployBlockReason(d)}">反映</button>
        <button class="btn btn-secondary"
          onclick="openRollbackModal('${d.dataset_id}')"
          ${canRollback ? "" : "disabled"}
          title="${canRollback ? '1世代前に戻す' : (!d.has_backup ? 'バックアップがありません（初回デプロイ後に利用可）' : '処理中のため実行不可')}">戻す</button>
        ${d.layer_type ? `<button class="btn btn-activate"
          onclick="openActivateModal('${d.dataset_id}')"
          ${canActivate ? "" : "disabled"}
          title="${d.is_active ? '既に有効です' : (d.layer_type ? '有効データセットに設定' : 'レイヤー種別なし')}">有効化</button>` : ""}
        ${d.requires_osrm_rebuild ? `<button class="btn btn-osrm"
          onclick="openOsrmModal('${d.dataset_id}')"
          ${canOsrm ? "" : "disabled"}
          title="${canOsrm ? 'ルートエンジン再構築' : '先に反映を実行してください'}">OSRM</button>` : ""}
        ${d.last_job_id ? `<button class="btn btn-secondary"
          onclick="openLogModal('${d.last_job_id}')"
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
    detailRow("データセットID", `<span style="font-family:monospace;color:#6366f1">${defn.dataset_id}</span>`),
    detailRow("地域", regionLabel(defn.region)),
    defn.routing_profile
      ? detailRow("ルーティングプロファイル", `<span style="font-family:monospace">${defn.routing_profile}</span>`)
      : "",
    defn.osrm_stem
      ? detailRow("OSRMビルドベース名", `<span style="font-family:monospace;font-size:11px">${defn.osrm_stem}</span>`)
      : "",
    detailRow("説明", escHtml(defn.description)),
    detailRow("影響範囲", escHtml(defn.impact_scope)),
    detailRow("整形処理", defn.requires_normalize ? "あり" : "不要"),
    detailRow("内容確認", defn.requires_validation ? "あり" : "不要"),
    detailRow("対応形式", defn.accepted_extensions.join(", ")),
    detailRow("デプロイ先", `<span style="font-size:11px;font-family:monospace">${defn.runtime_path}</span>`),
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
      ? `<span style="font-family:monospace;color:#b91c1c">${job.error_code}</span> <span style="color:#92400e;font-size:0.85em">（アプリ再起動による中断）</span>`
      : `<span style="font-family:monospace;color:#b91c1c">${job.error_code}</span>`;
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
    document.getElementById("um-official-url").textContent = defn.official_source_url || "—";
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
    if (steps.length > 0) {
      pipelineNotice.style.display = "";
      pipelineDesc.textContent = ` 取り込み後、自動的に${steps.join(" → ")}が実行されます。`;
    } else {
      pipelineNotice.style.display = "none";
    }

    // タブ構築
    buildInputTabs(defn.accepted_input_modes);
  }).catch(err => {
    showNotice("error", "定義情報の取得に失敗しました");
  });

  document.getElementById("update-modal").classList.add("open");
}

function buildInputTabs(modes) {
  const tabsEl = document.getElementById("input-tabs");
  const labels = { upload: "📁 ファイル選択", fetch_url: "🔗 URL指定取得", fetch_official: "🌐 公式サイトから取得" };
  tabsEl.innerHTML = modes.map(m =>
    `<button class="tab-btn" id="tab-btn-${m}" onclick="switchInputTab('${m}')">${labels[m] || m}</button>`
  ).join("");

  // 全パネル非表示
  ["upload", "fetch_url", "fetch_official"].forEach(m => {
    const p = document.getElementById(`tab-${m}`);
    if (p) p.classList.remove("active");
  });

  // 最初のタブを選択
  if (modes.length > 0) switchInputTab(modes[0]);
}

function switchInputTab(mode) {
  _activeInputTab = mode;
  ["upload", "fetch_url", "fetch_official"].forEach(m => {
    const btn = document.getElementById(`tab-btn-${m}`);
    const panel = document.getElementById(`tab-${m}`);
    if (btn) btn.classList.toggle("active", m === mode);
    if (panel) panel.classList.toggle("active", m === mode);
  });
}

function closeUpdateModal() {
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
      if (!_selectedFiles.length) { showNotice("error", "ファイルを選択してください"); return; }
      const formData = new FormData();
      for (const f of _selectedFiles) {
        formData.append("files", f);
      }
      const res = await fetch(`${API}/datasets/${d.dataset_id}/upload`, {
        method: "POST", body: formData
      });
      const json = await res.json();
      if (!res.ok || !json.accepted) {
        throw new Error(json.user_message || json.detail || "アップロードに失敗しました");
      }
      job_id = json.job_id;

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
  const tbody = document.getElementById("config-tbody");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:#94a3b8"><div class="spinner"></div> 読み込み中...</td></tr>`;
  }
  try {
    _configItems = await fetchJSON(`${API}/config`);
    _configLoaded = true;
    renderConfigTable();
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:#b91c1c">設定の取得に失敗しました: ${escHtml(err.message)}</td></tr>`;
    }
    showNotice("error", "設定の取得に失敗しました: " + err.message);
  }
}

function renderConfigTable() {
  const tbody = document.getElementById("config-tbody");
  if (!tbody) return;

  const mainItems = _configItems.filter(item => item.category !== "osrm");
  const osrmItems = _configItems.filter(item => item.category === "osrm");

  if (mainItems.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:#94a3b8">設定がありません</td></tr>`;
  } else {
    tbody.innerHTML = mainItems.map(item => renderConfigRow(item)).join("");
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
    <td><span class="config-default">${escHtml(formatConfigValue(item.default_value, item.type))}</span></td>
    <td><span style="font-size:12px;color:#475569">${escHtml(item.description || "—")}</span></td>
    <td>${updatedAt}</td>
    <td>
      <button class="btn btn-primary" onclick="saveConfigValue('${escAttr(item.key)}')" ${item.editable ? "" : "disabled"}>保存</button>
    </td>
  </tr>`;
}

function renderConfigInput(item) {
  const id = `config-input-${configDomId(item.key)}`;
  if (item.type === "string" && Array.isArray(item.options) && item.options.length > 0) {
    return `<select class="config-input" id="${id}" ${item.editable ? "" : "disabled"}>
      ${item.options.map(option => `
        <option value="${escAttr(option)}" ${item.current_value === option ? "selected" : ""}>${escHtml(option)}</option>
      `).join("")}
    </select>`;
  }
  if (item.type === "boolean") {
    return `<label class="config-checkbox"><input id="${id}" type="checkbox" ${item.current_value ? "checked" : ""} ${item.editable ? "" : "disabled"}> 有効</label>`;
  }
  if (item.type === "integer" || item.type === "float") {
    const step = item.type === "integer" ? "1" : "0.1";
    const min = item.min === null || item.min === undefined ? "" : ` min="${item.min}"`;
    const max = item.max === null || item.max === undefined ? "" : ` max="${item.max}"`;
    return `<input class="config-input" id="${id}" type="number" step="${step}"${min}${max} value="${escAttr(item.current_value)}" ${item.editable ? "" : "disabled"}>`;
  }
  return `<input class="config-input" id="${id}" type="text" value="${escAttr(item.current_value)}" ${item.editable ? "" : "disabled"}>`;
}

async function saveConfigValue(key) {
  const item = _configItems.find(config => config.key === key);
  if (!item) return;
  const input = document.getElementById(`config-input-${configDomId(key)}`);
  const status = document.getElementById(`config-status-${configDomId(key)}`);
  if (!input) return;

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
    renderConfigTable();
    showNotice("success", "設定を保存しました。反映には画面の再読み込みが必要です。");
  } catch (err) {
    if (status) {
      status.textContent = err.message;
      status.className = "config-save-status error";
    }
    showNotice("error", "設定の保存に失敗しました: " + err.message);
  }
}

async function triggerOsrmRebuild() {
  const btn = document.getElementById("osrm-rebuild-btn");
  const status = document.getElementById("osrm-rebuild-status");
  if (btn) btn.disabled = true;
  if (status) { status.textContent = "再ビルド中..."; status.style.color = "#f59e0b"; }

  try {
    const res = await fetch(`${API}/osrm/rebuild`, { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: "不明なエラー" }));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    if (status) { status.textContent = "✅ 再ビルド完了"; status.style.color = "#16a34a"; }
    showNotice("success", "OSRMの再ビルドが完了しました。");
  } catch (err) {
    if (status) { status.textContent = "❌ 失敗: " + err.message; status.style.color = "#b91c1c"; }
    showNotice("error", "OSRM再ビルドに失敗しました: " + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
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
    `).join("");
    select.value = _logsSource;
    select.disabled = false;
  }
}

async function reloadLogs() {
  const viewer = document.getElementById("logs-viewer");
  if (viewer) viewer.textContent = "ログを読み込み中...";

  const source = getSelectedLogsSource();
  await loadLogsStatus();
  const data = await fetchJSON(`${API}/logs?source=${encodeURIComponent(source)}&limit=200`);
  _logsSource = source;
  _logsLines = Array.isArray(data.lines) ? data.lines.slice(-LOGS_MAX_LINES) : [];
  renderLogsViewer();
  updateLogsMeta();
}

async function loadLogsStatus() {
  _logsStatus = await fetchJSON(`${API}/logs/status`);
  updateLogsMeta();
}

async function handleLogsSourceChange() {
  const wasConnected = !!_logsEventSource;
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

function disconnectLogsStream(options = {}) {
  if (_logsEventSource) {
    _logsEventSource.close();
    _logsEventSource = null;
  }
  if (!options.preserveStatus) {
    setLogsConnectionStatus("disconnected", "未接続");
  }
  updateLogsControls();
}

function clearLogsViewer() {
  _logsLines = [];
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
  const lineCount = document.getElementById("logs-line-count");
  const sizeMeta = document.getElementById("logs-size-meta");
  if (sourceMeta) {
    sourceMeta.textContent = `source: ${_logsSource || "—"}`;
  }
  if (lineCount) {
    lineCount.textContent = `${_logsLines.length} / ${LOGS_MAX_LINES} lines`;
  }
  if (sizeMeta) {
    const source = (_logsStatus.sources || []).find(item => item.key === _logsSource);
    sizeMeta.textContent = `size: ${formatBytes(source ? source.size_bytes : 0)}`;
  }
}

function updateLogsControls() {
  const connectBtn = document.getElementById("logs-connect-btn");
  const disconnectBtn = document.getElementById("logs-disconnect-btn");
  if (connectBtn) connectBtn.disabled = !!_logsEventSource;
  if (disconnectBtn) disconnectBtn.disabled = !_logsEventSource;
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
    ingest: "取り込み", normalize: "整形", validate: "内容確認",
    deploy: "反映", rollback: "ロールバック", osrm_rebuild: "OSRM再構築"
  };
  return map[op] || op;
}

function jobTypeLabel(t) {
  const map = {
    ingest_upload: "ファイル取り込み", ingest_fetch_url: "URL取得",
    ingest_fetch_official: "公式取得", normalize: "整形処理",
    validate: "内容確認", deploy: "反映", rollback: "ロールバック", osrm_rebuild: "OSRM再構築"
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
