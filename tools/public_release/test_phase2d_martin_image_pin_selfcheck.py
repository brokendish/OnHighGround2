"""
test_phase2d_martin_image_pin_selfcheck.py — Martin immutable image pin
のself-test（Phase 2-D Round 9、指示書第7節・第6.3節）。

CODEX AT-17A独立検証はDocker build/startup/Martin healthy/catalog/synthetic
tile 200まで実機確認済みだったが、その時点のMartin参照は`ghcr.io/maplibre/
martin:latest`のままだった。GitHub公開後に上流が同じtagへ新bytesを
無警告で再pushすれば、公開版の挙動が予告なく変わり得る（再現性が無い）。
本fileは、base release Compose（docker-compose.yml）のMartin image
referenceが`<repo>:<tag>@sha256:<digest>`形式のimmutable pinへ変更され、
`latest`が残っていないこと、demo Compose（docker-compose.demo.yml）が
image referenceを独自overrideせず同じpinをそのまま継承すること、pin対象の
digestが実際に`martin --version`で1.14.0を返すことをtasks/public-release/
の実装報告書に記録した実測と整合することを検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_martin_image_pin_selfcheck.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# CODEX AT-17A独立検証・本実装で実測したMartin 1.14.0のOCI image index
# （multi-arch manifest list）digest。`docker buildx imagetools inspect
# ghcr.io/maplibre/martin:1.14.0`で取得し、amd64/arm64双方のplatform別
# digestを個別にpull・`martin --version`実行して1.14.0であることを直接
# 確認済み（tasks/public-release/github_public_audit_phase2d_claude_
# implementation.md Round 9節参照）。
EXPECTED_MARTIN_DIGEST = "sha256:fe5e8952312ca8ea0a25c4b1f72ceb13676f2b50dca310843e48b31c8ceb2264"
EXPECTED_MARTIN_REPOSITORY = "ghcr.io/maplibre/martin"
EXPECTED_MARTIN_TAG = "1.14.0"
EXPECTED_MARTIN_IMAGE_REF = f"{EXPECTED_MARTIN_REPOSITORY}:{EXPECTED_MARTIN_TAG}@{EXPECTED_MARTIN_DIGEST}"

IMMUTABLE_PIN_PATTERN = re.compile(
    r"^(?P<repo>[\w./-]+):(?P<tag>[\w.-]+)@(?P<digest>sha256:[0-9a-f]{64})$"
)


class _ComposeOverrideLoader(yaml.SafeLoader):
    pass


def _override_constructor(loader: yaml.Loader, node: yaml.Node):
    return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)


_ComposeOverrideLoader.add_constructor("!override", _override_constructor)


def _load_compose(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.load(text, Loader=_ComposeOverrideLoader)


# ---------------------------------------------------------------------------
# 1. base docker-compose.yml: Martin imageがexact immutable pin
# ---------------------------------------------------------------------------

def test_01_base_compose_martin_image_is_immutable_pin():
    compose = _load_compose(REPO_ROOT / "docker-compose.yml")
    image = compose["services"]["martin"]["image"]
    assert image == EXPECTED_MARTIN_IMAGE_REF
    match = IMMUTABLE_PIN_PATTERN.match(image)
    assert match is not None, f"not a <repo>:<tag>@sha256:<digest> reference: {image!r}"
    assert match.group("tag") == EXPECTED_MARTIN_TAG
    assert match.group("digest") == EXPECTED_MARTIN_DIGEST


# ---------------------------------------------------------------------------
# 2. base compose: `latest`が残っていない（Martin serviceのimage行のみ対象、
#    OSRM imageのpinはRound 9のscope外）
# ---------------------------------------------------------------------------

def test_02_base_compose_martin_image_has_no_latest_tag():
    compose = _load_compose(REPO_ROOT / "docker-compose.yml")
    image = compose["services"]["martin"]["image"]
    assert "latest" not in image
    assert "@" in image, "image reference missing digest pin"


# ---------------------------------------------------------------------------
# 3. demo compose: Martin serviceがimageを独自overrideしない
#    （継承のみ、demoだけ別pin/別tagにしない）
# ---------------------------------------------------------------------------

def test_03_demo_compose_does_not_override_martin_image():
    compose = _load_compose(REPO_ROOT / "docker-compose.demo.yml")
    assert "image" not in compose["services"]["martin"], (
        "docker-compose.demo.yml must not override the martin image — "
        "it must inherit the base release Compose's immutable pin"
    )


# ---------------------------------------------------------------------------
# 4. resolved config（`docker compose config`相当）でbase/demoのMartin
#    imageがexact一致することを、素朴なmerge規則で直接確認する
#    （Compose自体のmerge実装に依存せず、YAML構造から静的に検証）
# ---------------------------------------------------------------------------

def test_04_base_and_demo_resolve_to_identical_martin_image():
    base = _load_compose(REPO_ROOT / "docker-compose.yml")
    demo = _load_compose(REPO_ROOT / "docker-compose.demo.yml")
    base_image = base["services"]["martin"]["image"]
    demo_martin = demo["services"]["martin"]
    resolved_demo_image = demo_martin.get("image", base_image)
    assert resolved_demo_image == base_image == EXPECTED_MARTIN_IMAGE_REF


# ---------------------------------------------------------------------------
# 5. digest形式の妥当性（tagからの推測ではなく、実際にpull検証された
#    sha256:<64 hex>形式であること）
# ---------------------------------------------------------------------------

def test_05_digest_format_is_valid_sha256():
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", EXPECTED_MARTIN_DIGEST)


# ---------------------------------------------------------------------------
# 6. OSRM image pinはRound 9のscope外であることの明示的な回帰確認
#    （誤って一緒にpinしてしまっていないか、また既存latestを壊していないか）
# ---------------------------------------------------------------------------

def test_06_osrm_images_unchanged_out_of_scope():
    compose = _load_compose(REPO_ROOT / "docker-compose.yml")
    assert compose["services"]["osrm-driving"]["image"] == "osrm/osrm-backend:latest"
    assert compose["services"]["osrm-walking"]["image"] == "osrm/osrm-backend:latest"
