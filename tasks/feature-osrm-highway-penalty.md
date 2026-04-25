# タスク: OSRM foot.lua 幹線道路コスト調整 + Config画面連携

## 概要

OSRMの徒歩ルーティングで幹線道路（primary/trunk）のコストを上げ、
迂回ルートを優先させる。
コスト値はConfig画面から変更・再ビルドできるようにする。

---

## 背景・制約

- OSMデータに crossing タグがほぼ存在しないため、highway タグでコスト制御する
- foot.lua はビルド時（osrm-extract）にのみ参照される静的ファイル
- → **コスト変更 = foot.lua 更新 + osrm-extract 再実行** が必要
- Config画面の値はリアルタイムには反映されない（再ビルドが必要）

---

## 実装前のCHECKLIST

```
[ ] 1. ./osrm/foot.lua を確認した（docker cp 済みか確認）
       未取得なら: docker cp evacuation-navi-osrm-walking:/opt/foot.lua ./osrm/foot.lua
[ ] 2. foot.lua 内の speed_profile テーブルを特定した
[ ] 3. foot.lua 内の surface_speeds / avoid テーブルを確認した
[ ] 4. 既存Configのキー命名規則を確認した（例: navigation.arrival_distance_m）
[ ] 5. Config値の保存・読み込みAPIのエンドポイントを確認した
[ ] 6. docker-compose.yml の osrm-walking サービスを確認した
[ ] 7. 修正方針を出力してから実装に入った
```

---

## 実装内容（4ステップ）

---

### Step 1: foot.lua のコスト定数を先頭にまとめる

foot.lua の先頭付近（`local parameters`ブロックの近く）に
コスト定数をまとめて配置する。

```lua
-- ===== OnHighGround: 幹線道路コスト設定 =====
-- この値は scripts/rebuild_osrm.py によって自動更新されます
-- 手動編集しないでください
local OHG_TRUNK_PENALTY    = 0.15  -- trunk の速度係数（低いほど遅い=迂回優先）
local OHG_PRIMARY_PENALTY  = 0.25  -- primary の速度係数
local OHG_SECONDARY_FACTOR = 0.80  -- secondary の速度係数（基本維持）
-- ==========================================
```

speed_profile テーブルの trunk / primary 部分をこの定数で置き換える：

```lua
local speed_profile = {
  trunk          = OHG_TRUNK_PENALTY * 100,  -- 既存値をペナルティ係数で調整
  primary        = OHG_PRIMARY_PENALTY * 100,
  secondary      = OHG_SECONDARY_FACTOR * 100,
  -- 他はそのまま
}
```

※ 既存値を確認してから適切な係数に調整すること。
  最初は保守的な値（primary を現状の50%程度）から始める。

---

### Step 2: Configキーを追加

既存Configシステムに以下のキーを追加する。
（他のnavigation.*キーと同じ方法で追加する）

| 設定名 | キー | デフォルト値 | 説明 | 範囲 |
|--------|------|-------------|------|------|
| 幹線道路ペナルティ（trunk） | `osrm.trunk_penalty` | 0.15 | trunk道路の速度係数。低いほど迂回優先 | 0.05〜1.0 |
| 幹線道路ペナルティ（primary） | `osrm.primary_penalty` | 0.25 | primary道路の速度係数 | 0.05〜1.0 |
| 補助幹線係数（secondary） | `osrm.secondary_factor` | 0.80 | secondary道路の速度係数 | 0.3〜1.0 |

---

### Step 3: 再ビルドスクリプトを作成

`scripts/rebuild_osrm_walking.py` を新規作成する。

```python
#!/usr/bin/env python3
"""
OSRMウォーキングプロファイル再ビルドスクリプト
Config値を読み込み、foot.lua を更新して osrm-extract を再実行する。
"""

import subprocess
import re
import sys

# Config APIからペナルティ値を取得
# （既存のConfig取得方法に合わせること）
def get_config_values():
    # 既存のConfig読み込み処理を流用
    return {
        "trunk_penalty":    get_config("osrm.trunk_penalty",    0.15),
        "primary_penalty":  get_config("osrm.primary_penalty",  0.25),
        "secondary_factor": get_config("osrm.secondary_factor", 0.80),
    }

def update_foot_lua(values):
    lua_path = "./osrm/foot.lua"
    with open(lua_path, "r") as f:
        content = f.read()

    # 定数ブロックを置換
    content = re.sub(
        r'local OHG_TRUNK_PENALTY\s*=\s*[\d.]+',
        f'local OHG_TRUNK_PENALTY    = {values["trunk_penalty"]}',
        content
    )
    content = re.sub(
        r'local OHG_PRIMARY_PENALTY\s*=\s*[\d.]+',
        f'local OHG_PRIMARY_PENALTY  = {values["primary_penalty"]}',
        content
    )
    content = re.sub(
        r'local OHG_SECONDARY_FACTOR\s*=\s*[\d.]+',
        f'local OHG_SECONDARY_FACTOR = {values["secondary_factor"]}',
        content
    )

    with open(lua_path, "w") as f:
        f.write(content)
    print(f"[OK] foot.lua 更新完了: {values}")

def run_osrm_rebuild():
    pbf_path = "/data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf"
    osrm_path = pbf_path.replace(".osm.pbf", ".osrm")

    cmds = [
        ["docker", "exec", "evacuation-navi-osrm-walking",
         "osrm-extract", "-p", "/opt/foot.lua", pbf_path],
        ["docker", "exec", "evacuation-navi-osrm-walking",
         "osrm-partition", osrm_path],
        ["docker", "exec", "evacuation-navi-osrm-walking",
         "osrm-customize", osrm_path],
    ]

    for cmd in cmds:
        print(f"[RUN] {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[ERROR] {result.stderr}")
            sys.exit(1)
        print(f"[OK] 完了")

    # コンテナ再起動
    subprocess.run(["docker", "restart", "evacuation-navi-osrm-walking"])
    print("[OK] OSRMコンテナ再起動完了")

if __name__ == "__main__":
    values = get_config_values()
    update_foot_lua(values)
    run_osrm_rebuild()
```

---

### Step 4: Config画面に再ビルドボタンを追加

既存のConfigタブに `osrm.*` セクションを追加し、
「OSRMに適用（再ビルド）」ボタンを設置する。

```
[ osrm セクション ]
────────────────────────────────────────────────
⚠️ 変更後は「OSRMに適用」ボタンで再ビルドが必要です（数分かかります）

幹線道路ペナルティ(trunk)    0.15  [保存]
幹線道路ペナルティ(primary)  0.25  [保存]
補助幹線係数(secondary)      0.80  [保存]

[🔄 OSRMに適用（再ビルド実行）]  ← このボタンでスクリプト実行
────────────────────────────────────────────────
```

ボタン押下時:
1. FastAPI に POST `/admin/osrm/rebuild` を送る
2. バックエンドで `rebuild_osrm_walking.py` を実行
3. 進行中はボタンを無効化し「再ビルド中...」表示
4. 完了後に「✅ 再ビルド完了」を表示

FastAPI エンドポイント:

```python
@router.post("/admin/osrm/rebuild")
async def rebuild_osrm():
    """foot.luaを更新してOSRMを再ビルドする"""
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "python3", "scripts/rebuild_osrm_walking.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=stderr.decode())
    return {"status": "ok", "message": "再ビルド完了"}
```

---

### Step 5: docker-compose.yml にマウント追加

```yaml
osrm-walking:
  volumes:
    - ./data_lake:/data_lake
    - ./osrm/foot.lua:/opt/foot.lua  # ← 追加（永続化）
```

---

## DO NOT

- ❌ foot.lua の速度テーブル全体を書き換えない（trunk/primary のみ調整）
- ❌ driving コンテナ（car.lua）を変更しない
- ❌ 既存のConfig保存・読み込みロジックを変更しない
- ❌ 再ビルドを自動実行しない（必ずボタン押下をトリガーにする）
- ❌ バックエンドの他のAPIを変更しない

---

## 完了条件

```
[ ] foot.lua の先頭に OHG_* 定数ブロックがある
[ ] speed_profile の trunk/primary が定数を参照している
[ ] docker-compose.yml に foot.lua のマウントが追加されている
[ ] osrm.* の Config キーが3つ追加されている
[ ] Config画面の osrm セクションに3つの設定値が表示される
[ ] 「OSRMに適用」ボタンで再ビルドスクリプトが実行される
[ ] rebuild_osrm_walking.py が scripts/ に存在する
[ ] 再ビルド中のUI表示（無効化・進行中・完了）が実装されている
```

---

## 完了時の報告フォーマット

```
## 実装完了レポート

### foot.lua の変更内容
- trunk の速度: 変更前 → 変更後
- primary の速度: 変更前 → 変更後

### 変更したファイル
- ファイル名: 変更内容

### 初回再ビルドの実行結果
- 成功 / 失敗（失敗の場合はエラー内容）

### 懸念点
（あれば記載）
```
