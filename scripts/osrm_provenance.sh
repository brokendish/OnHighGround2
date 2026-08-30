#!/bin/sh
# OSRM MLD成果物のversion互換性を明示する最小provenance契約。
# コンテナ内で実行し、実行中imageのosrm-routedからversionを取得する。
set -eu

usage() {
  echo "usage: osrm-provenance <write|verify> <artifact-prefix> <profile> <input-pbf-name> <input-pbf-path>" >&2
  exit 64
}

[ "$#" -eq 5 ] || usage
action=$1
prefix=$2
profile=$3
input_pbf=$4
input_path=$5
metadata="${prefix}.provenance.json"
image_ref=${OSRM_IMAGE_REF:?FATAL: OSRM_IMAGE_REF is required}
image=${image_ref%@*}
image_digest=${image_ref##*@}

runtime_version=$(osrm-routed --version | sed -n 's/.*v\([0-9][0-9.]*\).*/\1/p' | head -n 1)
if [ -z "$runtime_version" ]; then
  echo "FATAL: OSRM runtime version could not be determined" >&2
  exit 65
fi

require_artifacts() {
  for suffix in '' .partition .mldgr .cells .fileIndex .ramIndex; do
    if [ ! -s "${prefix}${suffix}" ]; then
      echo "FATAL: required OSRM artifact is missing or empty: ${prefix}${suffix}" >&2
      exit 66
    fi
  done
}

# provenance metadata を「構文的・構造的に正しい JSON object」として検証し、
# top-level の 7 required field を型付きで期待値と比較する。
# OSRM runtime image (Debian 9 / perl 5.24) には python3 / jq / JSON::PP が
# 無いため、perl core だけで動く最小 JSON パーサ（tokenizer + 再帰下降）を
# インラインで用いる。追加依存は導入しない。
# 引数: <metadata-path> <exp-version> <exp-image> <exp-digest> <exp-profile> <exp-input-name> <exp-input-sha256>
verify_metadata_json() {
  perl - "$@" <<'PROV_JSON_VERIFY'
use strict; use warnings;

my ($file, $exp_version, $exp_image, $exp_digest, $exp_profile, $exp_input, $exp_sha) = @ARGV;
sub fail { my $m = shift; print STDERR "provenance-json: $m\n"; exit 1; }

local $/;
open(my $fh, '<:raw', $file) or fail("cannot read $file");
my $src = <$fh>;
close $fh;

# ---- tokenizer ----
my @tok;
{
  my $s = $src;
  while (length $s) {
    if ($s =~ s/^[ \t\r\n]+//) { next; }
    if ($s =~ s/^([{}\[\]:,])//) { push @tok, ['p', $1]; next; }
    if ($s =~ s/^"((?:[^"\\\x00-\x1f]|\\(?:["\\\/bfnrt]|u[0-9a-fA-F]{4}))*)"//) {
      my $raw = $1;
      $raw =~ s/\\u([0-9a-fA-F]{4})/chr(hex($1))/ge;
      $raw =~ s/\\([bfnrt])/{b=>"\b",f=>"\f",n=>"\n",r=>"\r",t=>"\t"}->{$1}/ge;
      $raw =~ s/\\(["\\\/])/$1/g;
      push @tok, ['s', $raw]; next;
    }
    if ($s =~ s/^(-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)//) { push @tok, ['n', $1]; next; }
    if ($s =~ s/^(true|false|null)//) { push @tok, ['k', $1]; next; }
    fail("invalid token near: " . substr($s, 0, 20));
  }
}

# ---- recursive-descent parser ----
my $i = 0;
sub peek { $tok[$i] }
sub next_tok { $tok[$i++] }
sub expect_p { my $c = shift; my $t = next_tok(); fail("expected '$c'") unless $t && $t->[0] eq 'p' && $t->[1] eq $c; }

sub parse_value {
  my $t = peek() or fail("unexpected end of input");
  if ($t->[0] eq 'p' && $t->[1] eq '{') { return parse_object(); }
  if ($t->[0] eq 'p' && $t->[1] eq '[') { return parse_array(); }
  if ($t->[0] eq 's') { next_tok(); return { t => 'string', v => $t->[1] }; }
  if ($t->[0] eq 'n') { next_tok(); return { t => 'number', v => $t->[1] }; }
  if ($t->[0] eq 'k') { next_tok(); return { t => $t->[1], v => $t->[1] }; }
  fail("unexpected token '$t->[1]'");
}
sub parse_array {
  expect_p('['); my @a;
  if (peek() && peek()->[0] eq 'p' && peek()->[1] eq ']') { next_tok(); return { t => 'array', v => \@a }; }
  while (1) {
    push @a, parse_value();
    my $t = next_tok() or fail("unterminated array");
    last if $t->[0] eq 'p' && $t->[1] eq ']';
    fail("expected ',' or ']' in array") unless $t->[0] eq 'p' && $t->[1] eq ',';
  }
  return { t => 'array', v => \@a };
}
sub parse_object {
  expect_p('{'); my %h; my %seen;
  if (peek() && peek()->[0] eq 'p' && peek()->[1] eq '}') { next_tok(); return { t => 'object', v => \%h }; }
  while (1) {
    my $k = next_tok() or fail("unterminated object");
    fail("object key must be a string") unless $k->[0] eq 's';
    fail("duplicate key '$k->[1]'") if $seen{$k->[1]}++;
    expect_p(':');
    $h{$k->[1]} = parse_value();
    my $t = next_tok() or fail("unterminated object");
    last if $t->[0] eq 'p' && $t->[1] eq '}';
    fail("expected ',' or '}' in object") unless $t->[0] eq 'p' && $t->[1] eq ',';
  }
  return { t => 'object', v => \%h };
}

fail("empty document") unless @tok;
my $root = parse_value();
fail("trailing content after JSON value") if $i != @tok;
fail("top-level JSON value must be an object") unless $root->{t} eq 'object';
my $o = $root->{v};

# ---- structural + type validation ----
my @required = qw(schema_version osrm_version image image_digest profile input_pbf input_pbf_sha256);
for my $k (@required) { fail("missing required field: $k") unless exists $o->{$k}; }

my $sv = $o->{schema_version};
fail("schema_version must be an integer") unless $sv->{t} eq 'number' && $sv->{v} =~ /^-?[0-9]+$/;
fail("schema_version must be 1") unless $sv->{v} + 0 == 1;

for my $k (qw(osrm_version image image_digest profile input_pbf input_pbf_sha256)) {
  my $f = $o->{$k};
  fail("$k must be a string") unless $f->{t} eq 'string';
  fail("$k must be non-empty") unless length $f->{v};
}

# ---- value compatibility (既存 fail-closed contract) ----
fail("osrm_version mismatch")     if $o->{osrm_version}{v}     ne $exp_version;
fail("image mismatch")            if $o->{image}{v}            ne $exp_image;
fail("image_digest mismatch")     if $o->{image_digest}{v}     ne $exp_digest;
fail("profile mismatch")          if $o->{profile}{v}          ne $exp_profile;
fail("input_pbf name mismatch")   if $o->{input_pbf}{v}        ne $exp_input;
fail("input_pbf_sha256 mismatch") if $o->{input_pbf_sha256}{v} ne $exp_sha;

exit 0;
PROV_JSON_VERIFY
}

case "$action" in
  write)
    require_artifacts
    input_sha256=$(sha256sum "$input_path" | awk '{print $1}')
    temporary="${metadata}.tmp.$$"
    trap 'rm -f "$temporary"' EXIT HUP INT TERM
    umask 022
    printf '{\n  "schema_version": 1,\n  "osrm_version": "%s",\n  "image": "%s",\n  "image_digest": "%s",\n  "profile": "%s",\n  "input_pbf": "%s",\n  "input_pbf_sha256": "%s"\n}\n' \
      "$runtime_version" "$image" "$image_digest" "$profile" "$input_pbf" "$input_sha256" > "$temporary"
    mv -f "$temporary" "$metadata"
    trap - EXIT HUP INT TERM
    echo "OSRM provenance written: ${metadata} (version ${runtime_version})"
    ;;
  verify)
    require_artifacts
    if [ ! -f "$metadata" ]; then
      echo "FATAL: OSRM provenance is missing: ${metadata}; regeneration is required" >&2
      exit 67
    fi
    input_sha256=$(sha256sum "$input_path" | awk '{print $1}')
    if ! verify_metadata_json "$metadata" "$runtime_version" "$image" "$image_digest" "$profile" "$input_pbf" "$input_sha256"; then
      echo "FATAL: OSRM provenance is malformed or incompatible: ${metadata}; runtime=${runtime_version}, regeneration is required" >&2
      exit 68
    fi
    echo "OSRM provenance verified: ${metadata} (version ${runtime_version})"
    ;;
  *) usage ;;
esac
