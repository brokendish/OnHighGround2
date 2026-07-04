'use strict';
// /live/stream — 注目 event 選定ポリシー (Stream Phase 4-A)
// LiveStreamEventStore.getEvents() が返す正規化イベント (severity > rank > updatedAt > type
// 優先度で既にソート済み) から、自動巡回の対象にする候補を絞り込む。
// 副作用・DOM操作・タイマーは持たない純粋関数のみ。

const LiveStreamFocusPolicy = (function () {

  const MAX_CANDIDATES = 5;
  // カテゴリ偏り抑制の目安。critical/high はこの上限を超えても採用してよい。
  const MAX_PER_CATEGORY_SOFT = 2;

  /**
   * 巡回候補を選ぶ。
   * @param {Array} events  LiveStreamEventStore.getEvents() の出力
   * @returns {Array} 巡回候補 (最大 MAX_CANDIDATES 件)
   */
  function selectCandidates(events) {
    if (!Array.isArray(events) || events.length === 0) return [];
    const perCategory = {};
    const picked = [];
    for (const e of events) {
      if (picked.length >= MAX_CANDIDATES) break;
      // 地図フォーカスできない (緯度経度なし) event は対象外。
      if (e.lat == null || e.lng == null || !isFinite(e.lat) || !isFinite(e.lng)) continue;
      // low/info は原則フォーカス対象外。ただし地震は子画面が「対象 n/m」として
      // 履歴内の地震を巡回表示するため、低震度でも候補に残す。これにより
      // 高震度地震の詳細 hold 完了後も、地図/パネル/テロップの注目ID同期を保ったまま
      // 次の地震へ進める。
      if ((e.severity === 'low' || e.severity === 'info') && e.type !== 'earthquake') continue;
      const n = perCategory[e.type] || 0;
      const isImportant = e.severity === 'critical' || e.severity === 'high';
      if (!isImportant && n >= MAX_PER_CATEGORY_SOFT) continue;
      perCategory[e.type] = n + 1;
      picked.push(e);
    }
    return picked;
  }

  return { selectCandidates };
})();
