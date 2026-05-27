'use strict';
// live-danger-summary.js — 危険地域サマリー集計
// navigation.js / state.js に依存しない純粋集計モジュール。

(function () {

    const _TSUNAMI_PRIORITY = ['major_warning', 'warning', 'advisory'];

    const _TSUNAMI_TO_LEVEL = {
        major_warning: 'danger',
        warning:       'danger',
        advisory:      'warning',
    };

    /**
     * buildSummary — 津波・地震データと API ステータスをまとめたサマリーオブジェクトを返す。
     * @param {object|null} tsunamiData  /api/tsunami/warnings/current のレスポンス
     * @param {Array}       eqData       /api/earthquakes のアイテム配列
     * @param {object}      statuses     各 API の ok/offline/unknown 状態
     */
    function buildSummary(tsunamiData, eqData, statuses) {
        const tsunamiAreas = (tsunamiData && Array.isArray(tsunamiData.areas))
            ? tsunamiData.areas : [];
        const eqItems = Array.isArray(eqData) ? eqData : [];

        return {
            updatedAt: new Date(),
            statuses: Object.assign(
                { rain: 'unknown', kikikuru: 'unknown', earthquake: 'unknown', tsunami: 'unknown' },
                statuses
            ),
            summary: {
                tsunamiActive:          tsunamiAreas.some(a => _TSUNAMI_PRIORITY.includes(a.level)),
                earthquakeCount24h:     eqItems.length,
                strongRainDetected:     false,
                kikikuruDangerDetected: false,
            },
            dangerousAreas: _buildDangerAreas(tsunamiAreas, eqItems),
        };
    }

    function _buildDangerAreas(tsunamiAreas, eqItems) {
        const result = [];

        // 津波エリア（priority 順）
        _TSUNAMI_PRIORITY.forEach(level => {
            tsunamiAreas
                .filter(a => a.level === level)
                .forEach((area, i) => {
                    result.push({
                        id:    `tsunami-${level}-${i}`,
                        label: area.name || '不明',
                        level: _TSUNAMI_TO_LEVEL[level] || 'warning',
                        types: ['tsunami'],
                        lat:   area.lat != null ? area.lat : null,
                        lng:   area.lng != null ? area.lng : null,
                    });
                });
        });

        // M5以上地震（最大3件）
        eqItems
            .filter(eq => (eq.magnitude || 0) >= 5.0)
            .slice(0, 3)
            .forEach((eq, i) => {
                result.push({
                    id:    `eq-${i}`,
                    label: eq.epicenter_name || '震源不明',
                    level: (eq.magnitude || 0) >= 6.0 ? 'danger' : 'warning',
                    types: ['earthquake'],
                    lat:   eq.lat != null ? eq.lat : null,
                    lng:   eq.lng != null ? eq.lng : null,
                });
            });

        // danger → warning 順にソート
        const _order = { danger: 0, warning: 1, normal: 2 };
        result.sort((a, b) => (_order[a.level] ?? 2) - (_order[b.level] ?? 2));
        return result;
    }

    window.liveDangerSummary = { buildSummary };

})();
