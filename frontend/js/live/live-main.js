'use strict';
// live-main.js — /live エントリポイント
// 読み込み順: live-map.js → live-layers.js → live-tide-layer.js → live-danger-summary.js → live-alert-panel.js → live-ui.js → live-main.js

(async function () {

    // ── 初期化 ──────────────────────────────────────────────────────────────

    liveUI.initToggles();
    liveUI.setUpdating();

    // 雨雲・地震・津波を並列取得。各 API の成否を個別に追跡する。
    // liveAlertPanel.update() は内部で allSettled を使い { tsunamiOk, eqOk } を返す。
    const [alertResult, rainResult] = await Promise.allSettled([
        liveAlertPanel.update(),
        liveLayers.rain.refresh(),
    ]);

    const rainOk      = rainResult.status === 'fulfilled';
    const alertStatus = alertResult.status === 'fulfilled'
        ? alertResult.value
        : { eqOk: false, tsunamiOk: false };

    if (rainResult.status === 'rejected')
        console.warn('[live] 雨雲更新失敗:', rainResult.reason?.message);
    if (alertResult.status === 'rejected')
        console.warn('[live] 警戒カード更新失敗:', alertResult.reason?.message);

    // 雨雲状態をアラートパネルに反映（update() と並列だったため完了後に更新）
    liveAlertPanel.setStatus({ rain: rainOk ? 'ok' : 'offline' });

    liveUI.setStatus({
        rainOk,
        eqOk:      alertStatus.eqOk,
        tsunamiOk: alertStatus.tsunamiOk,
    });
    liveUI.hideLoading();

    // ── 定期更新 ────────────────────────────────────────────────────────────

    // 雨雲: 5分ごと。失敗時は status を offline に更新。
    setInterval(async () => {
        const [result] = await Promise.allSettled([liveLayers.rain.refresh()]);
        if (result.status === 'rejected')
            console.warn('[live] 雨雲更新失敗:', result.reason?.message);
        const ok = result.status === 'fulfilled';
        liveUI.updateRainStatus(ok);
        liveAlertPanel.setStatus({ rain: ok ? 'ok' : 'offline' });
    }, 5 * 60 * 1000);

    // 地震 + 津波 + カード: 2分ごと。
    setInterval(async () => {
        const status = await liveAlertPanel.update();
        liveUI.updateAlertStatus(status);
    }, 2 * 60 * 1000);

    // キキクル: 10分ごと（ON 時のみ再取得）
    setInterval(() => {
        const el = document.getElementById('toggle-kikikuru');
        if (el && el.checked) liveLayers.kikikuru.setVisible(true);
    }, 10 * 60 * 1000);

})();
