# sportscode-extract

Export **exactly one** `.SCPlaylist` package as an assembled H.264/AAC MP4 and a Sportscode XML timeline, ordered by playlist group and clip order. Python 3.10+; standard library runtime. Install from this repository, which is not published on PyPI.

## Quick start (new laptop)

```bash
git clone https://github.com/javiefernandez/sportscode-extract.git && cd sportscode-extract
./setup.sh   # installs Homebrew, Python 3.12, FFmpeg (homebrew-ffmpeg tap); creates .venv; runs tests
./run.sh     # drag a .SCPlaylist into the window; exports to local_exports/<name>
```

`setup.sh` supports macOS (Homebrew) and Debian/Ubuntu (apt), is safe to re-run, and accepts `--skip-tests`. `./run.sh <inspect|extract|validate> ...` passes arguments straight to the CLI.

## Manual setup

```bash
/Users/javierfernandez/miniconda3/envs/football-pipeline/bin/python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export SPORTSCODE_FFMPEG=/Users/javierfernandez/miniconda3/envs/football-pipeline/bin/ffmpeg
export SPORTSCODE_FFPROBE=/Users/javierfernandez/miniconda3/envs/football-pipeline/bin/ffprobe
sportscode-extract inspect '/path/One.SCPlaylist'
sportscode-extract extract '/path/One.SCPlaylist' --output './local_exports/One'
sportscode-extract validate './local_exports/One'
```

Install an FFmpeg build with `libx264`, AAC encoding, and HEVC decoding. Both executable environment variables above can be replaced by `--ffmpeg` and `--ffprobe` options; otherwise the tools are found on PATH. `python -m sportscode_extract` is equivalent to the installed command.

An explicit `--output DIR` is required for extraction. Choose a separate directory for each playlist. Existing destinations fail unless `--force` is supplied; force only replaces a recognized prior export. Output cannot overlap the input package. Exports are staged beside the destination and published only after validation. Sources are read-only. Inspection optionally writes reports and metadata to `--output DIR`, without copying footage.

The export contains `<playlist>.mp4`, `<playlist>.xml`, `manifest.json`, `README.txt`, canonical metadata/CSV, original JSON copies, and reports including every rendered source span. The canonical JSON retains unknown fields but redacts historical absolute `path`/`localPath` values and normalizes empty title references to null. Byte-for-byte original metadata retains all values, including private paths: treat the full export as private. Unreferenced footage is reported but never copied or probed.

Open the MP4 in Angles, then import the adjacent Sportscode XML timeline. The group name becomes the code; source match, tags, distinct original row and notes become grouped labels. Identical note/description text appears once. Uniform source colors use a fixed categorical palette.

For **Catapult Focus**, extract with `--target focus`. In Focus, create an Archive Session from the MP4 (Generic session type), then choose Tags ▸ Import Tags and select the XML. The assembled timeline starts at zero, so no sync is needed. The Focus profile writes notes and descriptions as one `<free_text>` per instance, not as `Note` labels, so the Focus label filter isn't flooded with one-off notes. Rows use the Sportscode-native `<code>` with 16-bit (0–65535) colour channels. The default `--target angles` output is unchanged. To use `--source-xml` against your own full-match recording in Focus, line it up with Tags ▸ Sync Tags (kick-off timing tag) or the Tag Properties Time Offset.

**Compatibility: schema-matched, not application-tested.** Manual Angles and Focus import/playback has not been performed. Check clip boundaries, grouped labels, notes and row colors in the target application before relying on application compatibility. Timing confidence is **media-consistent**, not playback-verified.

Useful extraction options:

- `--no-render`: metadata and referenced original media only.
- `--copy-clips`: also retain referenced original media with the rendered pair.
- `--source-xml`: original-clock XML, available only for a single source video. These times use the original `.SCVideo` clock; they may differ from a re-encoded full-match file, and angle/segment offsets may apply.
- `--target focus`: Catapult Focus XML profile (free-text notes, Sportscode-native rows); default `angles`.
- `--code-from original`: use the original coding row instead of playlist group.
- `--provenance-labels`: include UUID/order/original-time XML labels.
- `--render-titles`: insert two-second plain group title cards. Editable source effects remain metadata only.
- `--fps 30000/1001`, `--width 1920`, `--height 1080`: output profile (default 30 fps, 1920×1080, letterboxed).
- `--dry-run`: inspect and report without writing an export.
- `--allow-partial`: explicitly permit omissions; all omitted IDs appear in the report and export README.

The default local interval is `startTimeOffset` through `startTimeOffset + endTime - startTime`. Actual media duration must match its end within 0.02 seconds, with valid bounds. Segment offsets are provenance, not added to this interval. Multiple selected streams and unsupported multi-segment footage are reported. `--timing-config FILE` accepts a JSON object keyed by clip UUID, each value containing numeric `local_start` and `local_end`; this is explicitly reported as an override. `--timing-tolerance` controls input checks and `--drift-tolerance` controls total rendered drift (default 0.1 seconds). XML times come from probed rendered spans, not requested durations. Missing/muted audio gets silence; all rendered clips use a shared frame clock.

Exit codes: **0 complete**, **2 partial**, **1 failed**. Unreferenced media and orphaned effects are informational. By default extraction rejects unresolved items; partial output requires explicit opt-in. Rendering-disabled exports may be complete within that requested mode, with rendering clearly reported as not performed.

```bash
pytest --basetemp=.tmp/pytest
SPORTSCODE_SAMPLES='/Users/javierfernandez/Documents/GitHub/football-tactical-pipeline/SPORTSCODE_EXPORT_GP' pytest --basetemp=.tmp/integration tests/test_integration.py
```

Tests use hand-written JSON and tiny generated lavfi clips. Private samples are opt-in and are never fixtures. Real exports belong in ignored `local_exports/`.

The suggested `models.py`, `parsers/playlist_v1_11.py` and `reporting.py` split is consolidated into `inventory.py` and plain dictionaries to avoid empty abstractions. Parsing validates the supported 1.11.0 version; reporting lives beside reconciliation. Validation has its own module. No batch processing, binary parsers or speculative stream policies are included.

For an offline environment with setuptools and pytest already installed, the verified setup is `python -m venv --system-site-packages .venv`, followed by `.venv/bin/python -m pip install --no-build-isolation --no-deps -e .`. Use the Python executable shown above to create the environment. Set `TMPDIR="$PWD/.tmp"` after creating `.tmp/` to keep temporary build files inside the project.
