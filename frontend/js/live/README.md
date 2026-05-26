このディレクトリは /live 専用です。

既存ナビ本体の state / UI / navigation.js に依存を追加しないこと。

共通化が必要な場合は frontend/js/shared/ に切り出す。

live 実装のために index.html を改変してはいけない。

shared は「live と nav の両方で使うことが確定したものだけ」。

live 専用 utility は live/ に置く。
nav 専用 utility は既存側に残す。

shared を巨大 state 管理置き場にしない。