# Sportscode Extract — Codex Implementation Plan

Implement a Python CLI named `sportscode-extract` that converts a Hudl Sportscode playlist package (`.SCPlaylist`) into media and timelines that import cleanly into **Angles**, with portable JSON/CSV as a lossless side output.

Build the tool, tests and installation documentation. Work from the real package files supplied with this brief. Preserve source files unchanged. This is an implementation specification, not an existing published package.

> **Revision note (2026-09-23).** This plan was re-checked against three real packages (§3). The original draft was written against a different, larger package and contained one rule that fails on real exports (trusting `stream.json` segment filenames). Corrections are marked **[Revised]**. The pre-revision text is kept alongside as `Sportscode_Extract_Implementation_Plan.original.md`.

## 1. Goal and scope **[Revised]**

The user's actual goal is: open a Sportscode playlist in Angles as **one video plus one XML timeline**, with the playlist's topics as codes and its tags/notes as labels.

Primary output (the first thing to build, not an optional extra):

- **Assembled playlist MP4** in playlist order, plus a **rebased Sportscode XML** timeline generated from the actual rendered output (§13).

Secondary output:

- Extracted original clip media (only media referenced by the playlist — §2, §11).
- Recovered playlist topics, clip order, tags and notes as lossless JSON and convenient CSV.
- A report identifying anything missing, unsupported or unresolved.

Optional output:

- **Source-match XML** (§12.3): when every clip in a playlist comes from one original match, an XML timeline in original match-video seconds, for use with the user's own full-match file in Angles.

Do not claim to recover full matches or the original complete coded timeline — the package contains only the selected footage.

## 2. Known package structure **[Revised]**

Discover recursively; do not require exact intermediate folder names:

```text
Example.SCPlaylist/
    package.meta
    Playlist.SCClips
    Resources/                  (empty in all three samples)
    Videos/
        [local-video-id]/       (= clip.videoId; one folder per media clip)
            video.json
            Stream_NNNN/
                stream.json
                Segment_00000.mov   (the trimmed clip footage)
```

### `stream.json` segment lists are not reliable

**Do not resolve media by the filenames listed in `stream.json`.** In real exports, `stream.json` is often copied unchanged from the *original match* `.SCVideo`, so it lists the original recording's segments (e.g. `Segment_00000.MP4` … `Segment_00006.MP4`, mixed `.MP4`/`.mp4`). The package folder actually contains a single trimmed `Segment_00000.mov`. Observed: 18 of 36 stream folders in "Best goal", 46 of 125 in "Best CK against", 0 of 38 in "Inter Miami".

Resolution rule:

1. List the media files actually present in the stream directory (ignore `stream.json`, `.DS_Store`).
2. If `stream.json`'s segment list matches the files on disk exactly → `segment_resolution = "listed"`.
3. Else if exactly one media file is present → bind it, set `segment_resolution = "discovered"`, and keep the stale `stream.json` segment list as provenance (`original_segments`).
4. Accept the binding only if the probed duration matches the clip span (§8) within tolerance (default 0.02 s); otherwise report it as `unresolved`.
5. More than one unlisted media file in a stream directory → `ambiguous`; never guess. (Not observed in any sample.)

Media must always be found inside the stream directory itself; never build a path from the historical `path`/`localPath`.

### Unreferenced video folders

Packages can contain video folders that no clip uses — apparently left behind when clips are deleted from a playlist in Sportscode. In "Inter Miami", 83 of 102 video records/folders are unused and hold **2.78 GB of real media (78% of the package)**. The reverse also happens: "Best goal" has a video record with no folder, which no clip uses.

- Only extract, probe and render **referenced** media by default.
- List unreferenced folders and records in the report as informational (`unreferenced_media`, with sizes). This does **not** lower the overall status.
- A missing folder is only an error when a clip references it.

### Package metadata

`package.meta` and `Playlist.SCClips` are ordinary JSON. Observed `createdWithVersion` values: 12.58.0, 12.64.0 (and 12.66.1 in the package the original draft used). All use playlist `version = "1.11.0"`.

```text
version = "1.11.0"
playlist
    uniqueId, groups[], clips[], videos[], effects[], labelTree,
    titlesEnabled, viewOptions, modifyCount, currentModifyCount,
    hudlSyncModifyCount, remoteHash
```

**Field sets vary between app builds within the same schema version:** Sportscode 12.58.0 clips have no `uploadedStreamIds` key; 12.64.0 clips do. Treat every non-core field as optional, preserve unknown fields, and report unsupported playlist versions instead of guessing their meaning.

## 3. Verified sample characteristics **[Revised]**

These are fixture-specific reconciliation checks. Tests must take expected counts from the fixture actually used; never hardcode one package's numbers into the parser.

| | Best goal for AP2025 | Best CK against AP2025 | J1 Inter Miami vs Atlas |
|---|---:|---:|---:|
| Sportscode version | 12.64.0 | 12.64.0 | 12.58.0 |
| Groups | 13 | 14 | 6 |
| Media clips | 23 | 70 | 19 |
| Title clips | 13 | 14 | 6 |
| Video records / folders | 24 / 23 | 70 / 70 | 102 / 102 |
| Unreferenced video records | 1 (no folder) | 0 | 83 (2.78 GB) |
| Original source videos (matches) | 13 | 14 | 1 |
| Stream files probed | 36 | 125 | 38 |
| Stale `stream.json` dirs | 18 | 46 | 0 |
| Effects (all text annotations) | 13 | 14 | 13 (7 orphaned) |
| Tags (all key-only, empty value) | 45 | 0 | 3 |
| Clips with non-empty notes | 0 | 0 | 17 (of 19; 2 empty) |
| Group colours | all `#000000` | all `#520001` | `#000000`, `#520001` |
| Video codecs | H.264 + HEVC | H.264 + HEVC | H.264 |
| Selected streams with no audio track | 12 | 26 | 0 |

Invariants that held in **all three** packages (validate them, and report when they don't hold rather than assuming):

- All group `clipIds` resolve; every media clip is in exactly one group; no clip repeats.
- `clip.id == clip.videoId` for every media clip (one local video per clip; no sharing).
- Clip `startTime`/`endTime` equal `moment.startTime`/`endTime` (no padding).
- Every media clip selects exactly one visual stream, and `audioStreamIds == streamIds`.
- `titlesEnabled` is false.
- `uploadedStartTime == -1` and `uploadedStreamIds` is empty or absent.
- Timing rule §8 holds for every stream file (199/199).

## 4. Identifier relationships

A playlist video record contains:

```text
id          Original video ID (the source match .SCVideo)
localId     Package-local video ID (= Videos/ folder name)
path        Historical original source path, e.g. "~/Desktop/Juegos AP2025/Leagues Cup/J1 Miami vs Atlas.SCVideo"
localPath   Historical absolute package path (contains the exporting analyst's username)
streams[]   Stream IDs and names ("Angle 1", "Angle 2", ...)
```

A media clip contains `id, videoId, originalVideoId, startTime, endTime, startTimeOffset, streamIds[], audioStreamIds[], timelineName, originalGroupName, originalIndex, description, moment, tracks[], modifyCount, uploadedStartTime` and optionally `uploadedStreamIds`.

Resolve:

```text
clip.videoId          → playlist.videos[].localId → Videos/<localId>/
clip.originalVideoId  → playlist.videos[].id
Videos/<localId>/video.json.id == playlist.videos[].id   (validate)
```

- **[Revised] Title clips carry empty-string references, not missing fields:** `videoId: ""`, `streamIds: [""]`, `audioStreamIds: [""]`, `timelineName: ""`, no `moment`. Normalise `""` to null. Identify title clips by the lack of `moment` and by being some group's `titleClipId`. Never report them as unresolved joins.
- Never deduplicate local video objects by original video ID. (In "Inter Miami" all 102 records share one original ID.)
- Look up stream IDs within their own local video object only.
- Treat historical absolute paths as provenance only. They contain the exporting analyst's macOS username, so redact or omit them in outputs meant to be shared.
- Report ambiguous joins rather than choosing the first match.

## 5. Playlist order and metadata

Rebuild playback order from `playlist.groups` array order, then each group's `clipIds` array order. Do not use `clips[]` order, `originalIndex` or chronology. (Observed: groups contain clips in non-chronological order, e.g. "Chance against" = 389 s, 2571 s, 1268 s, 2902 s, 5748 s.)

Each group has `id`, `name`, `color`, `titleClipId`, `clipIds[]`, `modifyCount`.

Keep these concepts separate:

- Current playlist group/topic (`group.name`).
- Original coding row (`originalGroupName`). **These differ in practice:** in "Inter Miami", a clip in group "Goal against" has `originalGroupName = "Pressing GK"`.
- Original source/match name (`timelineName`, e.g. "Atlas vs Querétaro 2do Tiempo").
- `description` and `moment.note`. **[Revised]** These were identical on all 19 clips in "Inter Miami" (17 non-empty, 2 empty). Count only non-empty notes. Store both in JSON, but in XML/CSV write the text once unless they differ.
- `moment.tags`: key/value records. In every observed tag the value is empty (`{"key": "WFK", "value": ""}`). Keep key-only tags as standalone tags; do not drop them.
- `labelTree`: lists tag keys as groups with empty `labels` arrays. Preserve it; it adds no information beyond the tags.
- Original moment ID and `moment.source` (`type: "timeline"`, `id`, `contextId`).

Keep exact spelling, capitalisation and accents ("Balón controlado", "GOL EN CONTRA", "GOL."). Any taxonomy cleanup must be an optional, separate mapping.

A playlist may contain **no tags at all** ("Best CK against"): the XML then carries only codes and provenance labels, and that is a valid outcome, not a failure.

## 6. Stream and segment metadata **[Revised]**

Observed `stream.json`:

```json
{
  "id": "8204C41D-8F3B-475B-B170-B501AB4F93DE",
  "name": "Angle 1",
  "source": "unknown",
  "isAudioMuted": false,
  "segments": [
    { "offset": 0.23997596371882057, "fileName": "Segment_00000.mov", "id": "45B56BB0-..." }
  ]
}
```

- Keep segment offsets and mute settings. A mute setting does not tell you whether an audio track exists.
- Segment `offset` values seen: 0 to 15.08 s. They are **the same within each source match** (e.g. Angle 1 = 1.2599 s on every clip from "Atlas vs Cruz Azul", 1.3046 s on every clip from "Monterrey vs Atlas"), which suggests they are the original recording's multi-angle sync values. They are **not** needed to explain the trimmed clip files (§8). Their meaning is unverified.
- Resolve media files per §2, not from `segments[].fileName`.
- The individually uploaded loose MOVs used in the original draft are superseded by intact packages; the flattened-upload association manifest is not needed (§10).

## 7. Media probing

Use `ffprobe` (argument arrays, never shell strings) to record container duration/start time, video/audio tracks and codecs, dimensions, pixel format, nominal/average frame rates, time bases, and rotation/timecode metadata where available.

Observed across the three packages:

- Video: H.264 and **HEVC** (HEVC on 26 of 199 stream files, all 1920×1080). Resolutions: 1920×1080 and 1280×720.
- Average frame rates are irregular (e.g. 29.8, 29.86, 29.97, 30) — treat all sources as possibly variable-frame-rate and work from timestamps, never frame count ÷ 30.
- **Audio is frequently absent**: 38 selected streams (12 + 26) have no audio track at all.
- Container start times are 0 in every sample. Still, handle nonzero start times.

Do not transcode during inspection or source-preserving extraction.

## 8. Timing model **[Revised: hypothesis confirmed on all samples]**

Keep separate clocks:

1. Original source-video time (`startTime`/`endTime` — seconds in the original match `.SCVideo`).
2. Package-local media time (time within the trimmed `Segment_00000.mov`).
3. Rendered playlist time.
4. Football match clock — only if independently established. Never assume it equals source-video time.

Mapping:

```text
local_start = startTimeOffset
local_end   = startTimeOffset + (endTime − startTime)
```

**Evidence:** for all 199 stream files across three packages, probed file duration equals `startTimeOffset + (endTime − startTime)` within 0.0013 s (tail error). The only nonzero offset (clip `EA024AD6`, "Best goal": offset 39.644 s, span 31.851 s, file 71.495 s) matches too, which is the case that could have disproved the rule. This is strong metadata-vs-media evidence. It remains **not playback-verified** in Sportscode or Angles — record it as `timing_confidence = "media-consistent"`, not `"playback-verified"`.

Rules:

- Apply this mapping by default when the §2 duration check passes. Record the rule and its evidence per clip.
- Do not add or subtract segment `offset` (§6).
- If the check fails for a clip, mark that clip `timing_unresolved`, still export its metadata, and leave it out of rendering/XML unless the user passes an explicit timing policy (`--timing-config`).
- Do not clamp invalid intervals automatically. Validate bounds (`0 ≤ local_start < local_end ≤ file_duration + tolerance`).
- Keep original float values unchanged in JSON. Use `Decimal`/`Fraction` for the arithmetic.
- Clips spanning several segments, gaps and overlaps: not observed. Support them in the data model (ordered source spans), but report them as unsupported for rendering rather than guessing.

## 9. Effects and resources **[Revised]**

Every effect in all three packages is a `type: "annotation"` text box with `startFlicks == endFlicks == 0`, belonging to a **title clip**, whose text is the group name (e.g. "LC 2 Goal for"). There are no drawings over footage in these samples. (The original draft's larger package had ellipses and lines, so keep support for other types generic.)

- Keep all effects as JSON with their links (`clip.tracks[].effectIds`, `effect.trackId`, `effect.streamId`).
- **Orphaned effects:** "Inter Miami" has 7 effects not referenced by any clip track, with `trackId`s that match no track. They are title cards from deleted groups ("High press", "Low block", "Goal for", …). Report them as `orphaned`; do not render them.
- Copy `Resources/` unchanged (empty in all samples).
- Titles: `titlesEnabled` is false everywhere. By default, do not render title cards; the group name is already the XML code. `--render-titles` may render a plain title card from the group name (`effect.text`) for users who want section breaks in the MP4.
- Report that editable visual effects are not reproduced in XML.

## 10. CLI **[Revised: reduced first-version scope]**

```bash
sportscode-extract inspect  "/path/Example.SCPlaylist" [--output DIR]     # read-only report, no media copy
sportscode-extract extract  "/path/Example.SCPlaylist" --output DIR       # render MP4+XML, plus JSON/CSV
sportscode-extract validate DIR
```

Options for the first version:

```text
--no-render                     Metadata + referenced-media extraction only
--copy-clips                    Also copy referenced original clip files (default: off; the MP4 is the deliverable)
--code-from group|original      XML code = playlist group (default) or originalGroupName
--provenance-labels             Add UUID/order/original-time labels to the XML (default: off; always in JSON)
--source-xml                    Also emit source-match XML (§12.3) when the playlist has a single original video
--render-titles                 Insert title cards between groups
--timing-config FILE            Override timing for clips that fail §8
--dry-run
```

Deferred until a real need appears (and reasons):

- `--media-mode reference`, `--association-manifest`: intact packages make these unnecessary.
- `--stream-policy FILE`: every clip in every sample selects exactly one stream. Use `clip.streamIds[0]` when there is exactly one. **Fail** with a clear message when there are several, and add a policy then.
- HTML report and checksums file: JSON report is enough for the first version.

Default behaviour: preserve inputs, never overwrite an existing export (fail unless `--force`), extract only referenced media, report unresolved/unsupported items, never report `complete` when anything was left out.

Requires `ffprobe`; `ffmpeg` only when rendering. Look for them on `PATH`; allow `--ffmpeg`/`--ffprobe` overrides (a broken Homebrew ffmpeg has shadowed working ones on this machine before).

## 11. Output structure **[Revised]**

```text
export/
    [Playlist name].mp4              Assembled playlist (Angles video)
    [Playlist name].xml              Rebased Sportscode XML (Angles timeline)
    manifest.json
    README.txt                       How to open the pair in Angles; limitations
    metadata/
        playlist.json                Lossless canonical JSON (versioned; unknown fields kept; null for unknown)
        clips.csv                    One row per playlist occurrence, in playback order
        labels.csv
        original_metadata/           Byte-for-byte copies of package.meta, Playlist.SCClips, all stream.json/video.json
    reports/
        extraction_report.json
        source_mapping.json          Each output span → clip ID, source file, local in/out, requested vs actual duration
    source/                          Only with --source-xml
        [timelineName].xml
    clips/                           Only with --copy-clips
        [NNN]_[group]_[clip-id]/Stream_NNNN/Segment_00000.mov
```

Use relative paths throughout. Sanitise file names derived from playlist/group names (accents and spaces allowed; path separators and control characters removed).

## 12. XML export policy **[Revised]**

### 12.1 Format

Generate with an XML library (`xml.etree.ElementTree`), UTF-8, with the same shape as the XML this project already sends to Angles (`buildAnglesXml` in `performance-studio-web/src/PreMatchReportView.tsx`):

```xml
<?xml version='1.0' encoding='utf-8'?>
<file>
  <ALL_INSTANCES>
    <instance>
      <ID>1</ID>
      <start>0.000</start>
      <end>14.633</end>
      <code>PT 1 Goal for</code>
      <label><text>Filadelfia vs Atlas</text><group>Match</group></label>
      <label><text>CPA</text><group>Tag</group></label>
      <label><text>(+) Zona intermedia. (-) Tipo de pase.</text><group>Note</group></label>
    </instance>
  </ALL_INSTANCES>
  <rows>
    <row><Code>PT 1 Goal for</Code><R>…</R><G>…</G><B>…</B></row>
  </rows>
</file>
```

`<R>/<G>/<B>` are 8-bit (0–255) integers, as `buildAnglesXml` writes them (e.g. `70/110/180`).

### 12.1b Catapult Focus profile (`--target focus`)

Focus imports Sportscode-style `.xml` (as well as `.json` and `.sctimeline`) through Tags ▸ Import Tags, after an Archive Session has been created from the MP4. `--target focus` changes three things and leaves everything else as in §12.1:

- `moment.note` / `description` go into one `<free_text>` per instance, after `<code>` and joined with a newline. They are not written as `Note` labels. Focus labels are reusable filter values, so a label per unique note would flood the filter list.
- Rows use the Sportscode-native `<code>` element and 16-bit colour channels (8-bit value × 257).
- `manifest.json` records `"target": "focus"`, and validation checks free text and rows against that target. Older manifests without the key validate as `angles`.

Source-match XML is lined up in Focus with Sync Tags (kick-off timing tag) or Time Offset. Compatibility stays `schema-matched, not application-tested` until one Focus import is checked. Open questions: does `<free_text>` show as Tag Notes, are row colours applied, and is the `ID` order kept?

### 12.2 Field mapping (rebased playlist XML)

| Recovered field | XML | Default |
|---|---|---|
| Playlist group | `<code>` | on (`--code-from original` swaps in `originalGroupName`) |
| `originalGroupName` | label group `Original row` | on only when it differs from the code |
| `timelineName` (match) | label group `Match` | on |
| Tag key (empty value) | label group `Tag`, text = key | on |
| Tag with non-empty value | label group = key, text = value | on (not observed yet) |
| `moment.note` / `description` | label group `Note` (once if identical) | on when non-empty |
| Clip UUID, playlist position, original start/end | provenance labels | **off**; `--provenance-labels` (always kept in JSON/CSV) |

Rationale for keeping provenance labels off by default: they add a unique, filter-useless label to every instance in Angles' label list.

Row colours: use `group.color` when groups have distinct colours. When all groups share one colour (all `#000000` in "Best goal", all `#520001` in "Best CK against"), fall back to a fixed categorical palette so rows are distinguishable. Record which applied.

Instance IDs: sequential integers in playback order. Times come from the **actual rendered output** (§13), with 3 decimals.

### 12.3 Source-match XML (optional, `--source-xml`)

Available only when every media clip shares one `originalVideoId` ("Inter Miami": all 19 from "J1 Miami vs Atlas.SCVideo"). Emit instances at the original `startTime`/`endTime` for use against the user's own full-match recording. Mark it `not application-tested`, and in the README note that:

- times are relative to the original `.SCVideo`'s own clock. If that recording was made of several segment files (as the stale `stream.json` lists suggest), times may not map onto a single re-encoded full-match file;
- segment/angle offsets (§6) may apply to non-primary angles.

### 12.4 Compatibility status

Report XML compatibility as `schema-matched, not application-tested` until a generated file has been opened in Angles and checked. Open questions for that check: whether Angles shows grouped labels as expected, and whether `<rows>` colours apply.

## 13. Assembled playlist rendering **[Revised: primary output]**

1. Resolve group and clip order (§5). Skip title clips unless `--render-titles`.
2. For each clip, take the single selected visual stream (`streamIds[0]`) and the selected audio stream (`audioStreamIds[0]`). If they differ, fail and report it (never observed).
3. Trim to `[local_start, local_end]` (§8) using timestamp-accurate trimming (decode-side `-ss`/`-to` or `trim`/`atrim` filters; not keyframe copy).
4. Normalise every clip to a common output profile, because sources mix codecs, sizes and frame rates: default 1920×1080 (letterbox/pad 1280×720, never stretch), constant 29.97 or 30 fps (configurable), H.264 yuv420p, AAC 48 kHz stereo, `+faststart`.
5. **Generate silent audio (`anullsrc`) for clips with no audio track**, so audio and video stay aligned across the join. 38 selected streams in the samples have no audio.
6. Apply any rotation metadata. Handle HEVC input (the full ffmpeg build decodes it; verify at startup).
7. Join the normalised clips (concat filter, or concat demuxer on uniform intermediates).
8. Probe the result and build XML times from **actual** output durations and cumulative timestamps, not requested durations. Record each clip's requested vs actual length in `source_mapping.json`.
9. Stop with an error if the total drift between summed requested and actual durations exceeds a tolerance (default 0.1 s over the playlist).

Do not silently skip clips. Leave out unresolved clips only when the user passes `--allow-partial`, and list every omission in the report and README.

## 14. Safety and robustness

- Parse JSON as data; never execute package content.
- Reject path traversal and out-of-package references; do not follow symlinks out of the package.
- Use argument arrays for subprocess calls.
- Handle filenames and names with spaces, accents, dots and parentheses (observed: "J1 Puebla vs Atlas..SCVideo", "Atlas vs Querétaro 2do Tiempo").
- Write to a temporary directory, then rename on completion.
- Ignore `.DS_Store` and other hidden files throughout.
- Report unsupported formats without unsafe deserialisation. Do not build binary parsers speculatively.

## 15. Tests and acceptance criteria **[Revised]**

Real packages are private (they contain club footage and the exporting analyst's local paths), multi-GB, and must **not** be committed. Tests use:

- **Synthetic fixtures** (small JSON + tiny generated `ffmpeg -f lavfi` clips) for:
  - stale `stream.json` with a discovered `.mov`;
  - several unlisted media files (ambiguous);
  - unreferenced folders and records, and a referenced missing folder;
  - title clips with `""` references;
  - clips lacking `uploadedStreamIds`;
  - orphaned effects;
  - a nonzero `startTimeOffset`;
  - group order that differs from `clips[]` order;
  - `originalGroupName` that differs from the group;
  - key-only tags and a playlist with no tags;
  - identical note/description;
  - uniform group colours;
  - a clip with no audio track;
  - mixed resolutions and frame rates;
  - HEVC input (if the ffmpeg build can encode it);
  - Unicode and XML escaping.
- **Opt-in integration tests** pointed at real packages by environment variable (e.g. `SPORTSCODE_SAMPLES=/path/to/SPORTSCODE_EXPORT_GP`), skipped when it's unset. For each package, check the §3 table values and all §3 invariants, check that §8 holds for every stream file, and check that `inspect` flags exactly the expected stale/unreferenced/orphaned items.

Acceptance, per sample package:

- `inspect` reports the §3 counts exactly and no false unresolved references.
- `extract` produces one MP4 + XML whose instance count equals media clip count, in group order, with each instance's length within 0.05 s of its clip span. The XML parses back and all instances are inside the MP4 duration.
- The report separately states metadata completeness, media availability, timing confidence (`media-consistent`), XML validation, application compatibility (`not application-tested`) and rendering fidelity.

Overall status: `complete`, `partial` or `failed`, with documented exit codes (0 / 2 / 1). Unreferenced media and orphaned effects are informational and do not make a result partial.

**Manual check before calling it done:** open at least one rendered MP4 + XML pair in Angles and confirm clip boundaries, codes, labels and row colours. Record the result in the README.

## 16. Suggested project layout and installation

Create this as its **own repository**, outside the football-tactical-pipeline platform repo.

```text
sportscode-extract/
    pyproject.toml
    README.md
    src/sportscode_extract/
        __main__.py
        cli.py
        models.py
        parsers/playlist_v1_11.py
        inventory.py          package discovery, stale-stream resolution, unreferenced media
        media.py              ffprobe/ffmpeg wrappers
        timing.py
        render.py
        export_xml.py
        export_json.py
        export_csv.py
        reporting.py
        validation.py
    tests/
        fixtures/             synthetic only
```

Expose both `sportscode-extract` and `python -m sportscode_extract`. Python ≥ 3.10; standard library only apart from test tooling.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Document installing FFmpeg/ffprobe (with HEVC decode support), example commands, the timing policy and the Angles import steps. Do not present the project as a PyPI package unless it is actually published.

## 17. Implementation order and final deliverables **[Revised]**

1. Parser + reference indexes, with title-clip and missing-optional-field handling (§2, §4, §5).
2. Inventory: stale-stream resolution, unreferenced media, orphaned effects; `inspect` command and JSON report (§2, §9).
3. Probing + §8 timing validation per clip.
4. Rendering of the assembled MP4, with normalisation and silent-audio fill (§13).
5. Rebased XML from actual output timings (§12.1–12.2).
6. JSON/CSV exports, then `validate`.
7. Optional `--source-xml`, `--copy-clips`, `--render-titles`.
8. Tests (synthetic + opt-in real), README, example report from the three sample packages.
9. Manual Angles import check (§15).

Deliver working source, tests, installation instructions and example extraction reports for the three sample packages. Keep three kinds of claim clearly separate: verified from metadata, verified against media, and still needing playback comparison in Sportscode or Angles.
