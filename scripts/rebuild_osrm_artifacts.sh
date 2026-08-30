#!/usr/bin/env bash
# Canonical Compose imageでOSRM MLD成果物を安全に再生成するowner-local用手順。
set -euo pipefail

backup_root=""
if [[ ${1:-} == "--backup-root" ]]; then
  [[ -n ${2:-} ]] || { echo "--backup-root requires a directory" >&2; exit 64; }
  backup_root=$2
  shift 2
fi
[[ $# -eq 0 ]] || { echo "usage: $0 [--backup-root DIR]" >&2; exit 64; }

if [[ -z $backup_root ]]; then
  backup_root="${TMPDIR:-/tmp}/onhighground2-osrm-backup-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$backup_root"

rebuild() {
  local service=$1 backup_name=$2 prefix=$3 profile=$4 input_name=$5 build_command=$6
  local output_dir base_name backup_dir manifest container_prefix
  output_dir=$(dirname "$prefix")
  base_name=$(basename "$prefix")
  container_prefix="/data_lake/${prefix#data_lake/}"
  backup_dir="$backup_root/$backup_name"
  manifest="$backup_dir/inventory.tsv"

  [[ -f "${prefix}.osm.pbf" ]] || { echo "FATAL: missing input PBF: ${prefix}.osm.pbf" >&2; exit 65; }
  mkdir -p "$backup_dir"
  shopt -s nullglob
  local artifacts=("${prefix}.osrm"*)
  shopt -u nullglob
  if (( ${#artifacts[@]} > 0 )) && [[ -s $manifest && -s "${prefix}.osrm.provenance.json" ]]; then
    local required suffix
    required=1
    for suffix in '' .cells .partition .mldgr .fileIndex .ramIndex; do
      [[ -s "${prefix}.osrm${suffix}" ]] || required=0
    done
    if (( required == 1 )); then
      # retain は「artifact 一式が揃っている」だけでは不十分。current guard
      # schema / canonical digest-pinned image で `osrm-provenance verify` が
      # PASS する場合のみ retain を許可する。verify が FAIL（旧 schema・
      # image/digest mismatch・input PBF hash mismatch・required field 欠落等）
      # なら retain せず、下の backup + controlled rebuild 経路へ fail-closed で
      # 進む（stale provenance の温存を防ぐ）。
      if docker compose --profile driving run --rm --no-deps --entrypoint sh "$service" -c "
        /usr/local/bin/osrm-provenance verify '${container_prefix}.osrm' '${profile}' '${input_name}' '${container_prefix}.osm.pbf'
      "; then
        echo "Existing regenerated artifacts retained (provenance verified): $service"
        return
      fi
      echo "Existing provenance failed verification — backing up and rebuilding: $service" >&2
    fi
  fi
  if (( ${#artifacts[@]} == 0 )); then
    [[ -s $manifest ]] || { echo "FATAL: no artifacts and no retained backup inventory: $prefix" >&2; exit 66; }
    echo "Resuming regeneration from retained backup: $backup_dir"
  else
    : > "$manifest"
    for artifact in "${artifacts[@]}"; do
      [[ -f $artifact ]] || continue
      printf '%s\t%s\t%s\n' "$(basename "$artifact")" "$(stat -f '%z' "$artifact")" "$(shasum -a 256 "$artifact" | awk '{print $1}')" >> "$manifest"
    done
    [[ -s $manifest ]] || { echo "FATAL: artifact inventory is empty: $prefix" >&2; exit 67; }
    echo "Backing up ${#artifacts[@]} artifact(s): $service -> $backup_dir"
    for artifact in "${artifacts[@]}"; do
      [[ -f $artifact ]] && mv "$artifact" "$backup_dir/"
    done
  fi

  # docker compose run inherits the exact, digest-pinned image and mounts from docker-compose.yml.
  # osrm-provenance の usage は <write|verify> <artifact-prefix> <profile> <input-pbf-name> <input-pbf-path>
  # の 5 引数（scripts/osrm_provenance.sh を正本とする）。第 5 引数の input PBF path は
  # input_pbf_sha256 の実測に必須。
  docker compose --profile driving run --rm --no-deps --entrypoint sh "$service" -c "
    set -eu
    ${build_command}
    /usr/local/bin/osrm-provenance write '${container_prefix}.osrm' '${profile}' '${input_name}' '${container_prefix}.osm.pbf'
  "

  for suffix in '' .cells .partition .mldgr .fileIndex .ramIndex .provenance.json; do
    [[ -s "${prefix}.osrm${suffix}" ]] || { echo "FATAL: regenerated artifact missing or empty: ${prefix}.osrm${suffix}" >&2; exit 68; }
  done
}

rebuild osrm-walking walking \
  data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214 \
  foot tokyo-kanagawa-260214.osm.pbf \
  "osrm-extract --threads 2 -p /opt/foot.lua /data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf && osrm-partition --threads 2 /data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osrm && osrm-customize --threads 2 /data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osrm"
rebuild osrm-driving driving \
  data_lake/validated/tokyo/osm/driving/kanto-260214 \
  car kanto-260214.osm.pbf \
  "osrm-extract -p /opt/car.lua /data_lake/validated/tokyo/osm/driving/kanto-260214.osm.pbf && osrm-partition /data_lake/validated/tokyo/osm/driving/kanto-260214.osrm && osrm-customize /data_lake/validated/tokyo/osm/driving/kanto-260214.osrm"

echo "OSRM regeneration completed. Backup retained at: $backup_root"
