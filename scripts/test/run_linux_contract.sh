#!/usr/bin/env bash
# run_linux_contract.sh — Linux 専用の runtime 契約（atomic publish / rollback / mirror 整合 / required tile guard）を
# Linux container 内で正式に検証する（ROLLBACK-PORTABILITY-LINUX-CONTRACT、2026-10-12）。
#
# 本番の atomic publish は Linux の renameat2(RENAME_NOREPLACE) に依存する（backend/app/services/runtime_atomic.py）。
# macOS には renameat2 が無く、macOS 用の代替実装は作らない。Mac からは、この runner が Linux container
# （Docker Desktop の Linux VM kernel）でテストを実行する。
#
#   - image: backend-public image（backend/Dockerfile = python:3.11-slim + requirements.txt）に、
#     requirements-dev と同じ版の pytest だけを足したテスト用 image（無ければ 1 回だけ build、以後は cache）
#   - fixture: 専用の Docker named volume（Linux の filesystem）。atomic 性は bind mount 上で判定しない。
#     repo は read only の bind mount で、コードを読むためだけに使う
#   - identity: operator と同じ uid 10002 / gid 10002、supplemental gid 20001
#   - network: none。container・volume は終了時に必ず削除する（Local stack には触れない）
#   - container 内では OHG2_LINUX_CONTRACT_INNER=1 を立てる。テストはこの flag があると container への
#     再委譲をしない（再帰しない）
#
# 使い方:
#   scripts/test/run_linux_contract.sh [--qualify-only] [--evidence <file>] [pytest node id ...]
#   --qualify-only は image・kernel・filesystem・renameat2 の実動作だけを確かめて終わる（テストは実行しない）。
#   node id を省略すると Linux 契約一式（下の DEFAULT_TESTS）を実行する。
# 環境変数:
#   OHG2_LINUX_CONTRACT_BASE_IMAGE（既定 onhighground2-backend-public:latest）
#   OHG2_LINUX_CONTRACT_TIMEOUT（秒、既定 1200）
# 終了コード: 0 = 全 PASS / 1 = テスト失敗 / 2 = 実行環境の不備（image・Docker・qualification）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_IMAGE="${OHG2_LINUX_CONTRACT_BASE_IMAGE:-onhighground2-backend-public:latest}"
TIMEOUT_SEC="${OHG2_LINUX_CONTRACT_TIMEOUT:-1200}"
# requirements-dev.txt（pytest>=8.0）に対し、開発機の venv と同じ版に固定する
PYTEST_PKGS="pytest==9.0.3 pluggy==1.6.0 iniconfig==2.3.0 packaging==26.0 Pygments==2.20.0"
DEFAULT_TESTS=(
    backend/tests/test_phase2b6_rollback.py
    tests/test_atomic_publish_validation_reuse.py
    tests/test_rollback_preflight.py
    tests/test_tile_mirror_reconcile.py
    tests/test_tile_retirement.py
    tests/test_tile_path_migration.py
)

die() { echo "ERROR: $*" >&2; exit 2; }

EVIDENCE=""
QUALIFY_ONLY=0
TESTS=()
while (( $# )); do
    case "$1" in
        --evidence) EVIDENCE="${2:?--evidence <file>}"; shift 2 ;;
        --qualify-only) QUALIFY_ONLY=1; shift ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        *) TESTS+=("$1"); shift ;;
    esac
done
(( ${#TESTS[@]} )) || TESTS=("${DEFAULT_TESTS[@]}")
[[ "${OHG2_LINUX_CONTRACT_INNER:-}" != "1" ]] || die "container 内（OHG2_LINUX_CONTRACT_INNER=1）から runner を呼ばない"

command -v docker >/dev/null || die "docker が無い"
docker image inspect "${BASE_IMAGE}" >/dev/null 2>&1 || die "base image が無い: ${BASE_IMAGE}（docker compose build backend で作る）"

# ── 1. テスト用 image（base image id と pytest の版で tag を決め、無ければ build）──────────
base_id="$(docker image inspect -f '{{.Id}}' "${BASE_IMAGE}")"
pkg_tag="$(printf '%s' "${PYTEST_PKGS}" | shasum -a 256 2>/dev/null | cut -c1-8 || printf '%s' "${PYTEST_PKGS}" | sha256sum | cut -c1-8)"
TEST_IMAGE="ohg2-linux-contract:${base_id#sha256:}"
TEST_IMAGE="${TEST_IMAGE:0:32}-${pkg_tag}"
if ! docker image inspect "${TEST_IMAGE}" >/dev/null 2>&1; then
    echo "build test image ${TEST_IMAGE}（${BASE_IMAGE} + ${PYTEST_PKGS}）" >&2
    printf 'FROM %s\nUSER 0:0\nLABEL ohg2.linux-contract.base-image-id=%s\nRUN pip install --no-cache-dir %s\n' \
        "${BASE_IMAGE}" "${base_id}" "${PYTEST_PKGS}" \
        | docker build -q -t "${TEST_IMAGE}" - >/dev/null || die "test image の build に失敗"
fi
# 別の base から作った image を使わない（build 中に base の tag が変わった場合など）
[[ "$(docker image inspect -f '{{index .Config.Labels "ohg2.linux-contract.base-image-id"}}' "${TEST_IMAGE}")" == "${base_id}" ]] \
    || die "test image の base が ${BASE_IMAGE}（${base_id}）と一致しない: ${TEST_IMAGE}"
test_image_id="$(docker image inspect -f '{{.Id}}' "${TEST_IMAGE}")"

# ── 2. 専用 volume / container 名と後始末 ───────────────────────────────────────────
RUN_ID="$(date +%s)-$$"
VOL="ohg2-linux-contract-${RUN_ID}"
CNAME="ohg2-linux-contract-${RUN_ID}"
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/ohg2-linux-contract.XXXXXX")"
cleanup() {
    local rc=$?
    docker rm -f "${CNAME}" "${CNAME}-q" >/dev/null 2>&1 || true
    if ! docker volume rm -f "${VOL}" >/dev/null 2>&1; then
        echo "WARN: volume を削除できない: ${VOL}" >&2
    fi
    if (( rc == 0 )); then rm -rf "${LOGDIR}"; else echo "log を残す: ${LOGDIR}" >&2; fi
    exit "${rc}"
}
trap cleanup EXIT
docker volume create --label ohg2.purpose=linux-contract "${VOL}" >/dev/null

# ── 3. qualification（Linux kernel・filesystem・renameat2 の実動作・fixture 準備）──────────
docker run -i --rm --name "${CNAME}-q" --network none --user 0:0 -v "${VOL}:/contract" \
    -v "${ROOT}/backend:/repo/backend:ro" --entrypoint python3 "${TEST_IMAGE}" - > "${LOGDIR}/qualification.json" <<'PY' \
    || die "qualification に失敗（${LOGDIR}/qualification.json）"
import json, os, platform, subprocess, sys
sys.path.insert(0, "/repo/backend")
from app.services.runtime_atomic import renameat2_noreplace, open_dir_fd
q = {"uname_s": platform.system(), "uname_r": platform.release(), "machine": platform.machine()}
q["fs_type"] = subprocess.run(["stat", "-f", "-c", "%T", "/contract"], capture_output=True, text=True).stdout.strip()
q["mount"] = next((l.strip() for l in open("/proc/mounts") if l.split()[1] == "/contract"), None)
d = "/contract/.qualify"
os.makedirs(d)
for n in ("a", "b"):
    open(os.path.join(d, n), "w").write(n)
with open_dir_fd(d) as fd:
    renameat2_noreplace(fd, "a", fd, "c")                # 置き換え先が無ければ rename される
    try:
        renameat2_noreplace(fd, "b", fd, "c")            # 置き換え先があれば EEXIST で拒否（上書きしない）
        q["noreplace_rejects_existing"] = False
    except FileExistsError:
        q["noreplace_rejects_existing"] = True
q["renameat2"] = sorted(os.listdir(d)) == ["b", "c"] and open(os.path.join(d, "c")).read() == "a"
for n in os.listdir(d):
    os.unlink(os.path.join(d, n))
os.rmdir(d)
os.makedirs("/contract/tmp")
os.chown("/contract", 10002, 10002); os.chown("/contract/tmp", 10002, 10002)
q["qualified"] = q["uname_s"] == "Linux" and q["renameat2"] and q["noreplace_rejects_existing"] \
    and q["fs_type"] not in ("fuseblk", "fuse", "virtiofs", "9p", "nfs", "smb2", "cifs")
print(json.dumps(q))
sys.exit(0 if q["qualified"] else 3)
PY

# 空の結果や不合格を通さない（container へ script が渡らなかった場合も含む）
python3 -c 'import json,sys; q=json.load(open(sys.argv[1])); sys.exit(0 if q.get("qualified") is True else 1)' \
    "${LOGDIR}/qualification.json" 2>/dev/null || die "qualification の結果が不正（${LOGDIR}/qualification.json）"

if (( QUALIFY_ONLY )); then
    echo "LINUX_CONTRACT_QUALIFICATION $(cat "${LOGDIR}/qualification.json") test_image_id=${test_image_id}"
    exit 0
fi

# ── 4. formal test（1 回）─────────────────────────────────────────────────────────────
start=$(date +%s)
set +e
docker run --rm --name "${CNAME}" --network none \
    --user 10002:10002 --group-add 20001 \
    -e OHG2_LINUX_CONTRACT_INNER=1 -e HOME=/contract/tmp -e TMPDIR=/contract/tmp \
    -e PYTHONDONTWRITEBYTECODE=1 -e OHG2_LEASES_GID=20001 \
    -v "${VOL}:/contract" -v "${ROOT}:/repo:ro" -w /repo \
    --entrypoint timeout "${TEST_IMAGE}" "${TIMEOUT_SEC}" \
    python3 -m pytest -q --no-header -p no:cacheprovider --basetemp=/contract/pytest -rfEs "${TESTS[@]}" \
    > "${LOGDIR}/pytest.log" 2>&1
rc=$?
set -e
elapsed=$(( $(date +%s) - start ))
cat "${LOGDIR}/pytest.log"

# ── 5. evidence ───────────────────────────────────────────────────────────────────────
head="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
dirty="$(git -C "${ROOT}" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
summary="$(grep -E '^[=]* ?[0-9]+ (passed|failed)|^[0-9]+ (passed|failed)|no tests ran' "${LOGDIR}/pytest.log" | tail -1 || true)"
python3 - "${LOGDIR}/qualification.json" "${rc}" "${elapsed}" "${head}" "${dirty}" "${test_image_id}" "${BASE_IMAGE}" \
    "${summary}" "${TESTS[@]}" > "${LOGDIR}/evidence.json" <<'PY'
import json, sys
q = json.load(open(sys.argv[1]))
rc, elapsed, head, dirty, image_id, base, summary = sys.argv[2:9]
print(json.dumps({"git_head": head, "git_dirty_paths": int(dirty), "test_image_id": image_id, "base_image": base,
                  "uname": f"{q['uname_s']} {q['uname_r']} {q['machine']}", "fs_type": q["fs_type"], "mount": q["mount"],
                  "renameat2_noreplace": q["renameat2"] and q["noreplace_rejects_existing"],
                  "identity": "10002:10002 + 20001", "tests": sys.argv[9:], "pytest_exit": int(rc),
                  "summary": summary, "result": "PASS" if rc == "0" else "FAIL", "elapsed_sec": int(elapsed)},
                 ensure_ascii=False))
PY
echo "LINUX_CONTRACT_EVIDENCE $(cat "${LOGDIR}/evidence.json")"
[[ -z "${EVIDENCE}" ]] || cp "${LOGDIR}/evidence.json" "${EVIDENCE}"
(( rc == 0 )) || exit 1
exit 0
