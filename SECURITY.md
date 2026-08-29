# セキュリティ方針

## サポート対象リリースの状況

本リポジトリは初回の公開リリースを準備中です。サポート対象リリースの
保守方針はまだ確立していません。

## 脆弱性の報告

セキュリティに関わる報告には GitHub Private Vulnerability Reporting を
利用してください。認証情報・API キー・`.env` ファイル・operator の secret
などの機微な情報を public issue に含めないでください。セキュリティ窓口として
個人のメールアドレスは公開していません。

Private Vulnerability Reporting が利用できない場合は、リポジトリ所有者へ
非公開で連絡し、詳細を public issue で開示しないでください。

## デプロイ境界

公開アプリケーションは `/admin` 管理 route を意図的に提供していません。
privileged な operator サービスは別の任意ワークフローです。
[docs/operator-setup.md](docs/operator-setup.md) を参照してください。public と
operator の設定ファイルは分離し、それぞれの secret を決してコミットしないで
ください。
