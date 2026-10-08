/**
 * data-ops.js — Data Operations Console（取得 → 変換 → 公開 → 稼働 → 整合性）
 *
 * GET /admin/api/admin/data-ops                  一覧（hash しない）
 * GET /admin/api/admin/data-ops/{id}             詳細（反映元 sha256・tile 検査は初回のみ計算・キャッシュ）
 * GET /admin/api/admin/data-ops/{id}/acquisitions 取得履歴
 *
 * 値はすべて textContent で挿入する（file 名・URL 等は外部由来）。状態は色だけでなく文字でも表示する。
 * このページは read-only（取込・反映・削除の操作は置かない）。
 */
(function () {
  "use strict";

  const API = "/admin/api/admin/data-ops";
  const RUNTIME_LABELS = {
    published: "PUBLISHED", not_published: "NOT PUBLISHED", stale: "STALE", mismatch: "MISMATCH",
    unsupported: "UNSUPPORTED", legacy: "LEGACY", unknown: "UNKNOWN",
  };
  const METHOD_LABELS = {
    upload: "upload", url: "URL取得", api: "API取得", manual_import: "手動import",
    generated: "自動生成", legacy_unknown: "legacy_unknown",
  };
  // provenance 健全性（active とは別軸。active は「現在採用中」だけを意味する）
  const VALIDITY = {
    valid: ["OK", "VALID"],
    provenance_mismatch: ["ERROR", "PROVENANCE MISMATCH"],
    provenance_suspect: ["WARNING", "PROVENANCE SUSPECT"],
    unknown: ["UNKNOWN", "UNKNOWN"],
  };
  const FLAG_LABELS = { REGION_MISMATCH: "REGION MISMATCH", SHARED_SOURCE: "SHARED SOURCE" };
  function validityBadge(v) {
    const [st, label] = VALIDITY[v] || VALIDITY.unknown;
    return badge(st, label);
  }
  let _console = null;
  let _selected = null;

  // ── DOM helpers ──
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function badge(status, label) {
    const cls = status === "N/A" ? "NA" : status;
    return el("span", `badge ${cls}`, label || status);
  }
  function td(children, cls) {
    const c = el("td", cls);
    (Array.isArray(children) ? children : [children]).forEach(x => x && c.appendChild(typeof x === "string" ? document.createTextNode(x) : x));
    return c;
  }
  function withSub(main, sub) {
    const span = el("span");
    span.appendChild(main);
    if (sub) span.appendChild(el("span", "sub", sub));
    return span;
  }
  function fmtNum(n) { return n === null || n === undefined ? "—" : Number(n).toLocaleString("ja-JP"); }
  function fmtBytes(n) {
    if (n === null || n === undefined) return "—";
    if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
    if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
    if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${n} B`;
  }
  function fmtTime(s) {
    if (!s) return "UNKNOWN";
    const d = new Date(s);
    return isNaN(d) ? s : d.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) + " JST";
  }
  function showError(msg) {
    const bar = document.getElementById("error-bar");
    bar.textContent = msg || "";
    bar.classList.toggle("visible", !!msg);
  }
  async function getJSON(url) {
    const res = await fetch(url);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || body.error_code || `HTTP ${res.status}`);
    return body;
  }
  function kv(rows) {
    const grid = el("div", "kv");
    rows.forEach(([k, v]) => {
      grid.appendChild(el("div", "k", k));
      const cell = el("div", "v");
      if (v instanceof Node) cell.appendChild(v); else cell.textContent = (v === null || v === undefined || v === "") ? "—" : String(v);
      grid.appendChild(cell);
    });
    return grid;
  }
  function link(url) {
    if (typeof url !== "string" || !/^https?:\/\//i.test(url.trim())) return url ? el("span", "mono", url) : el("span", null, "UNKNOWN");
    const a = el("a", "mono", url);
    a.href = url.trim();
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  // ── 一覧 ──
  function acquisitionCell(acq) {
    const a = acq.active;
    const span = el("span");
    if (!a) {
      span.appendChild(badge("WARNING", "NO ACQUISITION HISTORY"));
      span.appendChild(document.createTextNode(" "));
      span.appendChild(validityBadge("unknown"));
      return span;
    }
    span.appendChild(badge("NA", "ACTIVE"));
    span.appendChild(document.createTextNode(" "));
    span.appendChild(validityBadge(acq.validity));
    (acq.validity_flags || []).forEach(f => {
      span.appendChild(document.createTextNode(" "));
      span.appendChild(badge("ERROR", FLAG_LABELS[f] || f));
    });
    const n = (a.source_files || []).length;
    span.appendChild(el("span", "sub", `${n} file${n === 1 ? "" : "s"} / ${METHOD_LABELS[a.acquisition_method] || a.acquisition_method}`
      + (acq.provenance_status !== "COMPLETE" ? " / PROVENANCE INCOMPLETE" : "")));
    return span;
  }
  function loadedCell(backend) {
    if (!backend) return badge("N/A");
    if (backend.loader_target === true) return withSub(badge("UNOBSERVED", "LOADER TARGET"), "読込は未観測");
    if (backend.loader_target === false) return withSub(badge(backend.status === "N/A" ? "N/A" : "WARNING", "NOT LOADER TARGET"), backend.loader_reason);
    return badge(backend.status);
  }
  function renderSummary(rows) {
    const counts = {};
    rows.forEach(r => { counts[r.integrity.overall] = (counts[r.integrity.overall] || 0) + 1; });
    const box = document.getElementById("summary");
    box.textContent = "";
    ["OK", "WARNING", "ERROR", "UNKNOWN"].forEach(k => {
      const card = el("div", "card");
      card.appendChild(badge(k));
      card.appendChild(el("div", "n", counts[k] || 0));
      box.appendChild(card);
    });
    const unreg = el("div", "card");
    unreg.appendChild(badge("WARNING", "UNREGISTERED"));
    unreg.appendChild(el("div", "n", (_console.unregistered_runtime_artifacts || []).length));
    box.appendChild(unreg);
  }
  function renderTable() {
    const tbody = document.getElementById("ops-tbody");
    tbody.textContent = "";
    const onlyProblems = document.getElementById("filter-problems").checked;
    const rows = (_console.datasets || []).filter(r => !onlyProblems || r.integrity.overall !== "OK");
    if (!rows.length) {
      const tr = el("tr");
      tr.appendChild(td("該当なし", "muted"));
      tr.firstChild.colSpan = 10;
      tbody.appendChild(tr);
      return;
    }
    rows.forEach(r => {
      const tr = el("tr", "clickable" + (r.dataset_id === _selected ? " selected" : ""));
      tr.tabIndex = 0;
      const idCell = el("span");
      idCell.appendChild(el("span", "ds-id", r.dataset_id));
      idCell.appendChild(el("span", "ds-name sub", r.display_name));
      const acq = r.acquisition;
      const rt = r.runtime;
      const integ = r.integrity;
      tr.appendChild(td(idCell));
      tr.appendChild(td(r.region));
      tr.appendChild(td(acq.source_provider ? el("span", null, acq.source_provider) : badge("UNKNOWN"), "wrap"));
      tr.appendChild(td(acquisitionCell(acq)));
      tr.appendChild(td(withSub(badge(r.transform.canonical.status), r.transform.canonical.feature_count != null ? `${fmtNum(r.transform.canonical.feature_count)} features` : null)));
      tr.appendChild(td(withSub(badge(r.transform.derived.status), r.transform.derived.feature_count != null ? `${fmtNum(r.transform.derived.feature_count)} features` : null)));
      tr.appendChild(td(withSub(badge(rt.status, RUNTIME_LABELS[rt.runtime_status] || rt.runtime_status), rt.reason)));
      tr.appendChild(td(loadedCell(rt.backend)));
      tr.appendChild(td(withSub(badge(r.tile.status), r.tile.tileset_id || null)));
      tr.appendChild(td(withSub(badge(integ.overall), integ.unobserved.length ? `未観測: ${integ.unobserved.join(", ")}` : null)));
      const open = () => openDetail(r.dataset_id);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", e => { if (e.key === "Enter") open(); });
      tbody.appendChild(tr);
    });
  }
  function renderUnregistered() {
    const tbody = document.getElementById("unreg-tbody");
    tbody.textContent = "";
    const items = _console.unregistered_runtime_artifacts || [];
    if (!items.length) {
      const tr = el("tr");
      const c = td("なし", "muted");
      c.colSpan = 5;
      tr.appendChild(c);
      tbody.appendChild(tr);
      return;
    }
    items.forEach(u => {
      const tr = el("tr");
      tr.appendChild(td(badge("WARNING", u.label || "UNREGISTERED RUNTIME SOURCE")));
      tr.appendChild(td(el("span", "mono", u.rel_path), "wrap"));
      tr.appendChild(td(fmtNum(u.feature_count)));
      tr.appendChild(td(u.loader_target === true ? withSub(badge("WARNING", "使用中（loader 対象）"), u.loader_reason)
        : withSub(badge("N/A", "loader 対象外"), u.loader_reason), "wrap"));
      tr.appendChild(td(badge("UNKNOWN", u.provenance || "UNKNOWN")));
      tbody.appendChild(tr);
    });
  }

  async function loadConsole() {
    showError("");
    try {
      _console = await getJSON(API);
    } catch (err) {
      showError(`一覧を取得できません: ${err.message}`);
      return;
    }
    document.getElementById("rt-version").textContent = _console.current_version || "UNKNOWN";
    document.getElementById("rt-published").textContent = fmtTime(_console.published_at);
    document.getElementById("rt-martin").textContent = _console.martin_catalog === "observed" ? "観測済み" : "UNOBSERVED（operator network から到達不可）";
    if (_console.runtime_error) showError(`実行環境を判定できません: ${_console.runtime_error}`);
    if ((_console.errors || []).length) showError(`一部 dataset の集計に失敗: ${_console.errors.map(e => e.dataset_id).join(", ")}`);
    renderSummary(_console.datasets || []);
    renderTable();
    renderUnregistered();
    const fromHash = decodeURIComponent((location.hash || "").replace(/^#/, ""));
    if (fromHash && !_selected && (_console.datasets || []).some(d => d.dataset_id === fromHash)) openDetail(fromHash);
  }

  // ── 詳細 ──
  function section(title, children) {
    const box = el("div", "layer");
    box.appendChild(el("h3", null, title));
    children.forEach(c => c && box.appendChild(c));
    return box;
  }
  function fileList(files) {
    if (!files || !files.length) return el("span", null, "UNKNOWN");
    const ul = el("ul", "file-list mono");
    files.forEach(f => {
      const li = el("li", null, `${f.name}${f.size != null ? `（${fmtBytes(f.size)}）` : ""}`);
      if (f.sha256) li.title = `sha256: ${f.sha256}`;
      ul.appendChild(li);
    });
    return ul;
  }
  function stageRows(label, s, extra) {
    if (!s || s.status === "N/A" && !s.path) return [[label, badge("N/A")]];
    const rows = [[label, withSub(badge(s.status || (s.exists ? "OK" : "UNKNOWN")), s.reason || null)],
      ["path", s.path ? el("span", "mono", s.path) : "—"],
      ["size / mtime", s.exists ? `${fmtBytes(s.size)} / ${fmtTime(s.mtime)}` : "存在しません"]];
    return rows.concat(extra || []);
  }

  async function openDetail(id) {
    _selected = id;
    renderTable();
    history.replaceState(null, "", `#${encodeURIComponent(id)}`);
    const box = document.getElementById("detail");
    box.hidden = false;
    box.textContent = "";
    box.appendChild(el("div", "muted", `${id} を読み込み中...（初回は反映元 sha256・tile 検査を計算します）`));
    let d, acqs;
    try {
      [d, acqs] = await Promise.all([getJSON(`${API}/${encodeURIComponent(id)}`),
        getJSON(`${API}/${encodeURIComponent(id)}/acquisitions`)]);
    } catch (err) {
      box.textContent = "";
      box.appendChild(el("div", "error-bar visible", `詳細を取得できません: ${err.message}`));
      return;
    }
    if (_selected !== id) return;
    box.textContent = "";
    const head = el("div", "detail-head");
    const h = el("h2", null, d.dataset_id);
    head.appendChild(h);
    const integ = el("div");
    integ.appendChild(el("span", "muted", "Integrity: "));
    integ.appendChild(badge(d.integrity.overall));
    head.appendChild(integ);
    box.appendChild(head);
    box.appendChild(el("div", "muted", `${d.display_name}（${d.category} / ${d.region}）`));

    const acq = d.acquisition;
    const notes = [...(acq.ingest_notes || []), ...(acq.operator_notes || [])];
    if (notes.length) {
      const n = el("div", "notes");
      n.appendChild(el("strong", null, "運用注意事項"));
      const ul = el("ul");
      notes.forEach(t => ul.appendChild(el("li", null, t)));
      n.appendChild(ul);
      box.appendChild(n);
    }

    // 整合性内訳
    const grid = el("div", "integrity-grid");
    Object.entries(d.integrity.components).forEach(([k, c]) => {
      const item = el("span", "item");
      item.appendChild(el("span", "muted", `${k}: `));
      item.appendChild(badge(c.status));
      if (c.reason && c.status !== "OK") item.title = c.reason;
      grid.appendChild(item);
    });
    box.appendChild(grid);
    if (d.integrity.unobserved.length) {
      box.appendChild(el("div", "muted small", `UNOBSERVED（overall 判定対象外・観測経路なし）: ${d.integrity.unobserved.join(", ")}`));
    }

    const layers = el("div", "layers");
    const a = acq.active;
    // 取得
    layers.appendChild(section("取得", [
      kv([
        ["Acquisition", a ? badge("NA", "ACTIVE") : badge("WARNING", "NO ACQUISITION HISTORY")],
        ["Provenance", (() => {
          const box = el("span");
          box.appendChild(validityBadge(acq.validity));
          (acq.validity_flags || []).forEach(f => { box.appendChild(document.createTextNode(" ")); box.appendChild(badge("ERROR", FLAG_LABELS[f] || f)); });
          return box;
        })()],
        ["Reason", acq.validity_reason || "—"],
        ["取得元組織", acq.source_provider || "UNKNOWN"],
        ["取得データ名", acq.source_dataset_name || "UNKNOWN"],
        ["公式URL", link(acq.official_source_url)],
        ["取得方法", a ? (METHOD_LABELS[a.acquisition_method] || a.acquisition_method) : "legacy_unknown"],
        ["実取得URL", a && a.source_url ? link(a.source_url) : "—"],
        ["DL 原本", a ? fileList(a.source_files) : el("span", null, "UNKNOWN")],
        ["bundle", a && a.bundle ? el("span", "mono", `${a.bundle.name}（${fmtBytes(a.bundle.size)}）`) : "—"],
        ["取得日時", a ? fmtTime(a.acquired_at) : "UNKNOWN"],
        ["年度 / 版", `${acq.source_year || "—"} / ${acq.source_version || "—"}`],
        ["原本構成", acq.source_group_mode ? `${acq.source_group_mode}${acq.ingest_mode ? " / " + acq.ingest_mode : ""}` : "未定義（制約なし）"],
        ["必要ファイル数", acq.required_source_count ?? "—"],
        ["一括処理必須", acq.single_batch_required ? "必須（個別投入禁止）" : "—"],
        ["canonical 置換", acq.ingest_replaces_canonical ? "取込で既存 canonical を置き換える" : "—"],
        ["provenance", withSub(badge(acq.provenance_status === "COMPLETE" ? "OK" : "WARNING", acq.provenance_status),
          (acq.provenance_missing || []).length ? `不足: ${acq.provenance_missing.join(", ")}` : null)],
      ]),
    ]));
    // 変換
    const tr = d.transform;
    const der = tr.derived || {};
    const rv = der.routing_validation;
    layers.appendChild(section("変換", [
      kv([].concat(
        stageRows("Raw", Object.assign({ status: tr.raw.exists ? "OK" : "UNKNOWN" }, tr.raw)),
        stageRows("Normalized", Object.assign({ status: tr.normalized.exists ? "OK" : "N/A" }, tr.normalized)),
        stageRows("Canonical", tr.canonical, [
          ["features", tr.canonical.feature_count != null ? `${fmtNum(tr.canonical.feature_count)}（${tr.canonical.feature_count_source}）` : "UNKNOWN"],
          ["validation", tr.canonical.validation_status],
          ["coverage", (() => {
            const cp = tr.coverage_policy;
            if (!cp) return "—";
            const box = el("span");
            box.appendChild(el("span", null, `required meshes: ${cp.required_meshes.join(", ")}`));
            (cp.exceptions || []).forEach(x => {
              box.appendChild(el("br"));
              box.appendChild(badge("WARNING", "COVERAGE EXCEPTION"));
              box.appendChild(document.createTextNode(` ${x}`));
            });
            (cp.notes || []).forEach(n => box.appendChild(el("span", "sub", n)));
            return box;
          })()],
          ["sha256", tr.canonical.sha256 ? el("span", "mono", tr.canonical.sha256) : "未計算"],
        ]),
        der.status === "N/A" ? [["Derived", badge("N/A")]] : stageRows("Derived (routing)", der, [
          ["features", fmtNum(der.feature_count)],
          ["routing 検証", rv ? `coverage FN=${rv.coverage_false_negatives}（${rv.source}）` : "記録なし"],
          ["builder", der.builder_version ? `v${der.builder_version} / ${der.generated_at || "—"}` : "—"],
        ]),
      )),
    ]));
    // 稼働
    const rt = d.runtime;
    const tile = d.tile;
    const be = rt.backend || {};
    const tileRows = tile.required ? [
      ["Display Tile", withSub(badge(tile.status), tile.reason)],
      ["tileset", el("span", "mono", tile.tileset_id)],
      ["current 内", tile.in_current ? "あり" : "なし"],
      ["Martin mirror", tile.mirror && tile.mirror.exists ? `${fmtBytes(tile.mirror.size)}` : "なし"],
      ["Martin source", tile.martin_registered],
      ["zoom / layer", tile.metadata ? `z${tile.metadata.minzoom ?? "?"}–${tile.metadata.maxzoom ?? "?"} / ${(tile.metadata.vector_layers || []).join(", ") || "—"}` : "—"],
      ["tile 数 / quick_check", tile.integrity ? `${fmtNum(tile.integrity.tile_count)} / ${tile.integrity.quick_check}` : "未計算"],
    ] : [["Display Tile", badge("N/A")]];
    layers.appendChild(section("稼働", [
      kv([
        ["current version", el("span", "mono", d.current_version || "UNKNOWN")],
        ["公開日時", fmtTime(d.published_at)],
        ["runtime_status", withSub(badge(rt.status, RUNTIME_LABELS[rt.runtime_status] || rt.runtime_status), rt.reason)],
        ["publish mode", rt.publish_mode],
        ["runtime artifact", rt.runtime_path ? el("span", "mono", rt.runtime_path) : (rt.runtime_rel ? `${rt.runtime_rel}（current に無し）` : "—")],
        ["features", fmtNum(rt.feature_count)],
        ["manifest sha256 一致", rt.manifest_match === true ? "一致" : rt.manifest_match === false ? "不一致" : "判定不能"],
        ["backend loader", be.loader_target === true ? "対象" : be.loader_target === false ? "対象外" : "—"],
        ["backend loaded", withSub(badge("UNOBSERVED"), be.loaded_reason || null)],
      ].concat(tileRows)),
    ]));
    box.appendChild(layers);

    // 取得履歴
    box.appendChild(el("h3", null, "取得履歴"));
    const records = acqs.acquisitions || [];
    if (!records.length) {
      box.appendChild(el("div", "muted", "取得履歴なし（provenance UNKNOWN）"));
    } else {
      const wrap = el("div", "table-wrap history");
      const t = el("table", "ops-table");
      const thead = el("thead");
      const hr = el("tr");
      ["取得日時", "方法", "原本", "版", "状態", "provenance", "記録", "job"].forEach(x => hr.appendChild(el("th", null, x)));
      thead.appendChild(hr);
      t.appendChild(thead);
      const tb = el("tbody");
      records.forEach(r => {
        const row = el("tr");
        row.appendChild(td(fmtTime(r.acquired_at)));
        row.appendChild(td(METHOD_LABELS[r.acquisition_method] || r.acquisition_method));
        row.appendChild(td(fileList(r.source_files), "wrap"));
        row.appendChild(td(r.source_version || r.source_year || "—"));
        row.appendChild(td(r.active ? badge("NA", "ACTIVE") : badge("N/A", r.status === "processed" ? "INACTIVE" : r.status.toUpperCase())));
        row.appendChild(td(withSub(validityBadge(r.validity || "unknown"), r.validity_reason || null), "wrap"));
        row.appendChild(td(r.record_origin === "migrated" ? "移行（既存記録から復元）" : "取込時に記録"));
        row.appendChild(td(el("span", "mono", r.ingest_job_id || "—")));
        tb.appendChild(row);
      });
      t.appendChild(tb);
      wrap.appendChild(t);
      box.appendChild(wrap);
    }

    const unreg = d.unregistered_runtime_artifacts || [];
    if (unreg.length) {
      box.appendChild(el("h3", null, "同じ hazard type の未登録 runtime artifact"));
      const ul = el("ul", "file-list");
      unreg.forEach(u => {
        const li = el("li");
        li.appendChild(badge("WARNING", "UNREGISTERED RUNTIME SOURCE"));
        li.appendChild(document.createTextNode(` ${u.rel_path}（${u.loader_target ? "backend loader 対象＝使用中" : "loader 対象外"}・${fmtNum(u.feature_count)} features）`));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.getElementById("reload-btn").addEventListener("click", loadConsole);
  document.getElementById("filter-problems").addEventListener("change", renderTable);
  loadConsole();
})();
