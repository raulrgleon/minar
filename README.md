# Minar

Local Bitcoin solo-mining panel for an Intel Mac. It runs pooler's `minerd` against `solo.ckpool.org` and shows the hashrate, the pool connection, and the real odds of finding a block.

This is a lottery. A 2020 iMac cannot compete with the Bitcoin network. The panel is here so that fact stays visible.

The program only needs a public Bitcoin address. It will not accept a private key or a seed phrase.

## What was verified on this iMac

Machine: iMac 2020, Intel Core i7-10700K (8 cores / 16 threads), 32 GB RAM, macOS 26.7.1.

Homebrew has no `cpuminer` formula (`brew search cpuminer` returns nothing). JayDDee/cpuminer-opt was not used. The macOS fork `bellflower2015/cpuminer-opt` was not needed: pooler's original miner built and hashed SHA-256d.

Build notes from the real compile:

- `./autogen.sh` needs Curl's `libcurl.m4` (the system `curl-config` is present, the m4 macro is not).
- The first `make` failed in `scrypt-x64.S` because Apple's assembler does not expand those GNU macros (`vpshufd` immediates were stripped).
- `perl ./nomacro.pl` is the workaround documented in pooler's README. After that, `make` produced a Mach-O `minerd`.
- Upstream prints a hashrate about every 60 seconds while on stratum (`LP_SCANTIME`). The build script changes that constant to 5 so the chart is not stuck on the first short sample. Hashing itself is unchanged.

Benchmark, 4 threads, algorithm `sha256d`, machine otherwise idle (`bin/minerd --benchmark -a sha256d -t 4`):

```text
[2026-10-17 13:55:59] Total: 60546 khash/s
[2026-10-17 13:56:04] Total: 59333 khash/s
```

Sustained rate on this Mac with 4 threads: about 59 MH/s. The first sample of each run is a short burst and is not the number to trust. An earlier run while Homebrew was compiling fell to about 11 MH/s, so the rate moves when the CPU is busy.

Pool check, 2 threads, about 28 seconds:

```text
[2026-10-17 13:49:39] Starting Stratum on stratum+tcp://solo.ckpool.org:3333
[2026-10-17 13:49:39] 2 miner threads started, using 'sha256d' algorithm.
[2026-10-17 13:49:40] Stratum requested work restart
[2026-10-17 13:49:41] thread 0: 2097152 hashes, 15452 khash/s
[2026-10-17 13:49:41] thread 1: 2097152 hashes, 15441 khash/s
```

`Stratum requested work restart` means the pool sent a job and the address was accepted. Solo mining only reports a share if the machine finds a block, so accepted shares stay at 0 during a normal run. A later run from the panel, 2 threads, stayed connected and held about 31–32 MH/s. With that rate and difficulty `140577680051919.62`, the panel's own odds were about 1 block every 600 million years, or about 1 in 220 billion in the next day.

One subscribe timed out once and the miner retried 30 seconds later. After the jansson fix, the next sessions connected on the first try.

`ps` showed the miner at nice value 19. The launcher asks for `nice -n 15`; macOS reported 19. Either way it is below normal priority. `caffeinate -ims` stayed up for the same session.

During one 2-thread run, `pmset` reported a CPU speed limit under 100 on two checks in a row. The panel stopped the miner for that. A following run stayed at speed limit 100. Temperature in degrees was never available without sudo.

Network difficulty read from `mempool.space` while building this: `140577680051919.62` at block `971898`.

## Install the miner

Dependencies that this build actually used:

```bash
brew install automake libtool pkg-config
```

Do not point this build at Homebrew's jansson. The first binary linked jansson 2.15.1 and, on a real pool session, aborted after about 90 seconds inside `json_loads` (`malloc` error in `lex_scan`, signal SIGABRT). The build script forces the jansson bundled with pooler's source (`ac_cv_lib_jansson_json_loads=no`). The resulting `minerd` links only the system libcurl.

From the project directory:

```bash
chmod +x scripts/build-minerd.sh start.command
./scripts/build-minerd.sh
```

The script clones `https://github.com/pooler/cpuminer.git`, downloads `libcurl.m4` from the official curl repository, runs `nomacro.pl`, configures with `-O3 -march=native`, and copies the binary to `bin/minerd`. That binary is gitignored. Do not replace it with a downloaded executable.

Short benchmark:

```bash
bin/minerd --benchmark -a sha256d -t 4
```

Stop it with Control-C.

## Run the panel

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
```

Edit `config.json` and set `btc_address` to your public address. `threads` defaults to 4.

```bash
./start.command
```

Or double-click `start.command` in Finder. It opens `http://127.0.0.1:8765/` and keeps the Terminal window open. Closing that window stops the panel and the miner.

The server is started as:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Manual miner command, if you want it without the panel:

```bash
caffeinate -ims nice -n 15 bin/minerd \
  -a sha256d \
  -o stratum+tcp://solo.ckpool.org:3333 \
  -u YOUR_PUBLIC_ADDRESS \
  -p x \
  -t 4
```

## What the panel does

- Start and stop one `minerd` process.
- Thread count from 1 to the number of logical CPUs. Default 4 of 16 on this iMac.
- Priority `nice -n 15`.
- `caffeinate -ims` while the miner is running, so idle sleep stays off.
- Live chart, current hashrate, and an average that ignores the first 8 seconds.
- Accepted and rejected shares, uptime, pool status, and the latest log lines. Stats are parsed from `minerd` stderr. A line that cannot be parsed is kept in the log and does not stop the panel.
- CPU use from `psutil`, and CPU speed limit from `pmset -g therm`, both without sudo.
- Temperature in degrees is not shown. macOS only exposes it through `powermetrics`, which asks for an administrator password. This program never calls sudo. If `CPU_Speed_Limit` stays under 100 for two checks in a row, the miner is stopped.
- Odds from your hashrate and the current difficulty at `https://mempool.space/api/`. Expected hashes per block are `difficulty × 2^32`. The panel states the expected years and the chance of a block in the next day as `1 in N`.

## Configuration

`config.json` (mode `0600`, gitignored):

```json
{
  "btc_address": "bc1qyourpublicaddress",
  "threads": 4
}
```

There is no `.env` secret. `.env.example` only says so. The pool URL and the password `x` are fixed in code. The address is checked as mainnet base58 (P2PKH, P2SH) or bech32/bech32m (`bc1`) before the process starts.

External calls are only the pool and `mempool.space`. Redirects off `mempool.space` are refused. Nothing else is contacted, and the address is not sent to the difficulty API.

## Tests

```bash
.venv/bin/python -m unittest tests.test_core -v
```

## Layout

```text
app/                FastAPI panel, parser, address checks, miner control
app/static/         HTML, CSS, and the chart
bin/minerd          built locally, not committed
scripts/build-minerd.sh
start.command
config.json         your public address, not committed
```

## Security

- Listens on `127.0.0.1` only, and rejects other `Host` and `Origin` values.
- The miner is started with an argument list. The address is validated first. The binary must be the local Mach-O file `bin/minerd`, not a symlink.
- No private key, seed, wallet file, or API key is read or stored.
- The page is served with a content security policy and is not embeddable in a frame.
- Do not point this at a pool other than the one compiled in, and do not paste a private key into the address field. A key is rejected, but it should never be copied into a browser in the first place.
