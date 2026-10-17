#!/bin/bash
# Build pooler's cpuminer (minerd) from the official git repository.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/third_party/cpuminer"
M4="$ROOT/third_party/m4"
JOBS="$(sysctl -n hw.ncpu)"

mkdir -p "$ROOT/bin" "$M4"

if [[ ! -d "$SRC/.git" ]]; then
  git clone --depth 1 https://github.com/pooler/cpuminer.git "$SRC"
fi

if [[ ! -f "$M4/libcurl.m4" ]]; then
  curl -fsSL -o "$M4/libcurl.m4" \
    https://raw.githubusercontent.com/curl/curl/curl-8_7_1/docs/libcurl/libcurl.m4
fi

cd "$SRC"
export ACLOCAL_PATH="$M4${ACLOCAL_PATH:+:$ACLOCAL_PATH}"

# Upstream waits 60s between hashrate lines on stratum (LP_SCANTIME).
# Five seconds matches the miner's own non-stratum default and feeds the chart.
perl -0pi -e 's/#define\s+LP_SCANTIME\s+60/#define LP_SCANTIME\t\t5/' cpu-miner.c

if [[ ! -f Makefile ]]; then
  ./autogen.sh
  # Apple's assembler does not expand the upstream gas macros.
  # nomacro.pl is the step documented in pooler's README.
  if [[ ! -f sha2-x64.S.orig ]]; then
    perl ./nomacro.pl
  fi
  # Homebrew jansson 2.15 aborts inside json_loads on this miner's stratum
  # messages (heap error in lex_scan). The bundled jansson is the one this
  # source was written against.
  ./configure CFLAGS="-O3 -march=native" ac_cv_lib_jansson_json_loads=no
fi

make -j"$JOBS"
cp -f minerd "$ROOT/bin/minerd"
chmod 755 "$ROOT/bin/minerd"
shasum -a 256 "$ROOT/bin/minerd" | awk '{print $1}' > "$ROOT/bin/minerd.sha256"
echo "Built $ROOT/bin/minerd"
"$ROOT/bin/minerd" --version || true
