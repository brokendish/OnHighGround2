# OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN — Phase C Caddy提案（未適用）

Phase Bはlocal実装・検証のみで完了している。本ファイルはPhase C（VPS Caddy
変更）のOWNER承認を得るための提案であり、**このファイル自体はVPSへ何も
適用しない**。

## 前提（Phase Bで確定した契約）

- `operator-gateway`は引き続き`127.0.0.1:18100`のみにbindする（`0.0.0.0`化しない）。
- externalに公開が必要なoperator resourceはすべて`/admin/*`配下に統一済み
  （login/session/logout/shutdown、および既存dataset/hazards/simulation
  管理APIも`/admin/api/admin/*`・`/admin/api/simulation/*`へ移設済み）。
- session cookie（`ohg_admin_session`）は`Path=/admin`・`Secure`・`HttpOnly`・
  `SameSite=Strict`。Caddyが`/admin/*`のfull pathをそのまま
  `operator-gateway`へ転送する前提（path書き換えなし）。

## 変更対象

VPS `/etc/caddy/Caddyfile` の `ohg.brokendish.org` ブロックのみ。
`brokendish.org`・`api.brokendish.org`・`osrm.brokendish.org`ブロックは
変更しない。

### 現状（VPS実機で確認済み）

```caddyfile
ohg.brokendish.org {
	reverse_proxy 127.0.0.1:8080
	encode gzip
	log {
		output file /var/log/caddy/ohg_access.log {
			roll_size 100mb
			roll_keep 5
			roll_keep_for 720h
		}
		format json
	}
}
```

### 変更後（提案）

```caddyfile
ohg.brokendish.org {
	handle /admin/* {
		reverse_proxy 127.0.0.1:18100
	}
	handle {
		reverse_proxy 127.0.0.1:8080
	}
	encode gzip
	log {
		output file /var/log/caddy/ohg_access.log {
			roll_size 100mb
			roll_keep 5
			roll_keep_for 720h
		}
		format json
	}
}
```

差分は`handle /admin/* { reverse_proxy 127.0.0.1:18100 }`の追加と、既存の
`reverse_proxy 127.0.0.1:8080`を`handle {}`（catch-all）で包むことだけ。
`encode gzip`・`log`ブロックはブロック全体に効くため位置を変えない。

## 動作契約

- `https://ohg.brokendish.org/admin/*` → `operator-gateway`
  （`127.0.0.1:18100`。**operator profileが起動していない間はconnection
  refused → Caddyは502を返す**。これは意図した挙動——「管理画面を終了」直後や
  operator profile未起動時はこの502が正しい状態）。
- それ以外の全path（`/`, `/live`, `/live/stream`, `/api/*`等）→ 従来どおり
  `frontend:8080`。
- `operator-gateway`はrequestを受け取った時点でCaddyが付けた`/admin/...`の
  フルpathをそのまま見る（Caddyの`reverse_proxy`はpathを書き換えない）ため、
  operator/nginx.confの`location /admin/api/...`は現状のまま機能する
  （Phase Bで確認済みの契約と一致）。

## Caddy起動中との整合性

`caddy reload`は無停止で設定を反映する（Caddyの標準機能）。この変更は
`brokendish.org`（WordPress）・`api.brokendish.org`・`osrm.brokendish.org`の
いずれのブロックにも触れないため、それらのサービスに影響しない。

## 適用手順（Phase C、OWNER承認後）

1. VPS上で現在のCaddyfileをバックアップする。

   ```bash
   sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.pre-admin-route.bak
   ```

2. `ohg.brokendish.org`ブロックのみを上記「変更後」の内容へ編集する
   （他のブロックは一切変更しない）。

3. 構文検証（reloadする前に必ず実行、まだ何も反映されない）。

   ```bash
   sudo caddy validate --config /etc/caddy/Caddyfile
   ```

4. 検証OKの場合のみreload（無停止）。

   ```bash
   sudo systemctl reload caddy
   ```

5. 動作確認。

   ```bash
   # operator profile起動前: 502が正しい期待値
   curl -I https://ohg.brokendish.org/admin/

   # operator profile起動
   ssh <vps> 'cd ~/Development/GitHub/OnHighGround2 && docker compose --profile operator up -d'

   # 起動後: 200 (login.htmlへredirectまたは200)
   curl -I https://ohg.brokendish.org/admin/

   # 他routeが無影響であることの確認
   curl -I https://ohg.brokendish.org/
   curl -I https://ohg.brokendish.org/live
   curl -I https://brokendish.org/
   curl -I https://api.brokendish.org/health   # 既存route、変更なし
   ```

## Rollback

```bash
sudo cp /etc/caddy/Caddyfile.pre-admin-route.bak /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

`operator-gateway`・`backend-operator`自体のcompose定義は本Phase Cで一切
変更しないため、Caddy側のrollbackだけで完全に元の状態へ戻る。

## Phase Cで変更しないもの（再掲）

- `docker-compose.yml`
- `operator/nginx.conf`
- `backend/`配下の全ファイル
- `.env.operator`
- `brokendish.org`・`api.brokendish.org`・`osrm.brokendish.org`の各Caddyブロック
- Martin / backend-public / OSRM / runtime-init / data_runtime / data_lake
