// /live/stream — テロップ初期化
// render() でも毎回上書きするが、初期値もここでセット
// 依存: TICKER_TEXT (live-stream-scene.js)

function initTicker() {
  const a = document.getElementById('ticker-a');
  const b = document.getElementById('ticker-b');
  if (a) a.textContent = TICKER_TEXT;
  if (b) b.textContent = TICKER_TEXT;
}
