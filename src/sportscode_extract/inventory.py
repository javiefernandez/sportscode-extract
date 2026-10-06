"""Discover and reconcile the actual package, not historical source paths."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from .media import probe, duration, has_audio
from .timing import check

MEDIA = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts'}


def files(root):
    root = Path(root).resolve()
    found = []
    for path in root.rglob('*'):
        if any(p.startswith('.') for p in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlinks are unsupported in packages: {path.relative_to(root)}')
        if path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError('Out-of-package file')
            found.append(path)
    return found


def read(path):
    with path.open(encoding='utf-8') as handle:
        return json.load(handle)


def inspect_package(path, ffprobe=None, tolerance=0.02, timing_config=None):
    root = Path(path).resolve()
    if not root.is_dir() or root.suffix.lower() != '.scplaylist':
        raise ValueError('Expected exactly one .SCPlaylist directory')
    paths = files(root)
    documents = [p for p in paths if p.name == 'Playlist.SCClips']
    if len(documents) != 1:
        raise ValueError('Expected exactly one Playlist.SCClips')
    document = read(documents[0])
    if document.get('version') != '1.11.0':
        raise ValueError(f"Unsupported playlist version: {document.get('version')}")
    playlist = document['playlist']
    groups, clips, videos = (playlist.get(k, []) for k in ('groups', 'clips', 'videos'))
    issues = []
    def issue(kind, message, clip_id=None):
        issues.append(dict(kind=kind, message=message, clip_id=clip_id))
    def index(items, key):
        result = defaultdict(list)
        for item in items:
            result[item.get(key)].append(item)
        return result
    clip_index, video_index = index(clips, 'id'), index(videos, 'localId')
    title_ids = {g.get('titleClipId') for g in groups}
    titles = [c for c in clips if not c.get('moment') and c.get('id') in title_ids]
    media_clips = [c for c in clips if c not in titles]
    referenced = {c.get('videoId') for c in media_clips}
    folders = defaultdict(list)
    for p in paths:
        if p.name == 'video.json':
            folders[p.parent.name].append(p.parent)
    stream_entries = []
    local_streams = defaultdict(lambda: defaultdict(list))
    unreferenced = []
    for local_id in set(folders) | set(video_index):
        if local_id not in referenced:
            directories = folders.get(local_id, [])
            unreferenced.append({'video_id': local_id, 'record_count': len(video_index.get(local_id, [])),
                                 'folders': [str(p.relative_to(root)) for p in directories],
                                 'size_bytes': sum(p.stat().st_size for p in paths if any(p.is_relative_to(d) for d in directories))})
            continue
        records, directories = video_index.get(local_id, []), folders.get(local_id, [])
        if len(records) != 1 or len(directories) != 1:
            issue('unresolved_reference', f'Expected one video record and folder for {local_id}')
            continue
        record, directory = records[0], directories[0]
        video_metadata = read(directory / 'video.json')
        if video_metadata.get('id') != record.get('id'):
            for clip in media_clips:
                if clip.get('videoId') == local_id:
                    issue('video_id_mismatch', f'video.json ID mismatch for {local_id}', clip['id'])
            continue
        metadata_files = [p for p in paths if p.name == 'stream.json' and p.is_relative_to(directory)]
        discovered_ids = {read(p).get('id') for p in metadata_files}
        declared_ids = {s.get('id') for item in (record, video_metadata) for s in item.get('streams', [])}
        if declared_ids - discovered_ids:
            for clip in media_clips:
                if clip.get('videoId') == local_id:
                    issue('unresolved_reference', 'Declared stream metadata is missing from its video folder', clip['id'])
        for metadata in metadata_files:
            stream = read(metadata)
            # Re-exported videos can leave video.json "streams" empty; treat that as undeclared.
            declarations = [item['streams'] for item in (record, video_metadata) if item.get('streams')]
            if any(sum(s.get('id') == stream.get('id') for s in declared) != 1 for declared in declarations):
                for clip in media_clips:
                    if clip.get('videoId') == local_id:
                        issue('stream_id_mismatch', 'Stream ID is absent or ambiguous in its video metadata', clip['id'])
                continue
            present = sorted(p for p in paths if p.parent == metadata.parent and p.suffix.lower() in MEDIA)
            listed = [s.get('fileName') for s in stream.get('segments', [])]
            exact = sorted(listed) == sorted(p.name for p in present) if all(isinstance(n, str) for n in listed) else False
            if exact:
                by_name = {p.name: p for p in present}
                present = [by_name[name] for name in listed]
            resolution = 'listed' if exact and present else 'discovered' if len(present) == 1 else 'ambiguous' if present else 'unresolved'
            entry = {'id': stream.get('id'), 'video_id': local_id, 'metadata': stream,
                     'metadata_path': str(metadata.relative_to(root)), 'segment_resolution': resolution,
                     'original_segments': stream.get('segments', []), 'source_spans': [], 'files': []}
            for p in present:
                info = probe(p, ffprobe)
                # ffprobe includes its absolute input filename; the package-relative path is sufficient.
                info.get('format', {}).pop('filename', None)
                entry['files'].append({'path': str(p.relative_to(root)), 'probe': info})
                entry['source_spans'].append({'path': str(p.relative_to(root)), 'local_start': None, 'local_end': None})
            if len(present) == 1:
                entry.update(entry['files'][0])
            local_streams[local_id][stream.get('id')].append(entry)
            stream_entries.append(entry)
    occurrences = []
    occurrence_ids = []
    for group in groups:
        for clip_id in group.get('clipIds', []):
            occurrence_ids.append(clip_id)
            matches = clip_index.get(clip_id, [])
            if len(matches) != 1:
                issue('unresolved_reference', f'Clip {clip_id} has {len(matches)} matches', clip_id)
                continue
            clip = matches[0]
            if clip in titles:
                continue
            occurrence = {'position': len(occurrences) + 1, 'group': group, 'clip': clip,
                          'streams': [], 'selected_stream': None, 'timing_status': 'timing_unresolved'}
            occurrences.append(occurrence)
            own = local_streams.get(clip.get('videoId'), {})
            streams = [s for matches in own.values() for s in matches]
            occurrence['streams'] = streams
            for stream in streams:
                if len(stream['files']) != 1 or stream['segment_resolution'] in ('ambiguous', 'unresolved'):
                    issue('unsupported_segments', f'Stream {stream["id"]}: {stream["segment_resolution"]}; multi-segment rendering unsupported', clip_id)
                    continue
                timing = check(clip, duration(stream['probe']), tolerance, (timing_config or {}).get(clip_id))
                stream['timing'] = timing
                stream['source_spans'][0].update(local_start=timing['local_start'], local_end=timing['local_end'])
                if timing['timing_status'] != 'resolved':
                    issue('timing_unresolved', f'Duration check failed for stream {stream["id"]}', clip_id)
            selected = clip.get('streamIds', [])
            if len(selected) != 1 or not selected[0] or clip.get('audioStreamIds') != selected:
                issue('unsupported_stream_selection', 'Exactly one matching visual/audio stream selection is required', clip_id)
                continue
            matches = own.get(selected[0], [])
            if len(matches) != 1:
                issue('unresolved_reference', 'Selected stream not uniquely resolved', clip_id)
                continue
            stream = matches[0]
            occurrence['selected_stream'] = stream
            occurrence.update(stream.get('timing', {}))
            records = video_index.get(clip.get('videoId'), [])
            if len(records) == 1 and clip.get('originalVideoId') != records[0].get('id'):
                issue('original_video_mismatch', 'Original video ID differs from record', clip_id)
                occurrence['timing_status'] = 'timing_unresolved'
    used_effects = {eid for c in clips for t in c.get('tracks', []) for eid in t.get('effectIds', [])}
    effects = playlist.get('effects', [])
    orphaned = [e.get('id') for e in effects if e.get('id') not in used_effects]
    counts_by_id = Counter(occurrence_ids)
    invariants = {
        'all_group_clip_ids_resolve': all(len(clip_index.get(i, [])) == 1 for i in occurrence_ids),
        'each_media_clip_in_one_group': all(counts_by_id[c['id']] == 1 for c in media_clips),
        'no_clip_repeats': all(n == 1 for n in counts_by_id.values()),
        'clip_id_equals_video_id': all(c.get('id') == c.get('videoId') for c in media_clips),
        'moment_times_match': all(c.get('startTime') == c.get('moment', {}).get('startTime') and c.get('endTime') == c.get('moment', {}).get('endTime') for c in media_clips),
        'single_matching_stream_selection': all(len(c.get('streamIds', [])) == 1 and c.get('audioStreamIds') == c.get('streamIds') for c in media_clips),
        'titles_disabled': playlist.get('titlesEnabled') is False,
        'upload_defaults': all(c.get('uploadedStartTime') == -1 and not c.get('uploadedStreamIds') for c in media_clips),
        'timing_rule_holds': all(s.get('timing', {}).get('timing_confidence') == 'media-consistent' for s in stream_entries),
    }
    for key, valid in invariants.items():
        if not valid:
            if key == 'timing_rule_holds' and stream_entries and all(s.get('timing', {}).get('timing_status') == 'resolved' for s in stream_entries):
                continue  # Explicit policies are valid, but are not evidence for the default rule.
            issue('invariant_violation', key)
    counts = dict(groups=len(groups), media_clips=len(media_clips), title_clips=len(titles), video_records=len(videos),
                  video_folders=sum(map(len, folders.values())), unreferenced_video_records=sum(1 for v in videos if v.get('localId') not in referenced),
                  original_source_videos=len({c.get('originalVideoId') for c in media_clips}),
                  stream_files_probed=sum(len(s['files']) for s in stream_entries),
                  stale_stream_dirs=sum(s['segment_resolution'] == 'discovered' for s in stream_entries),
                  effects=len(effects), orphaned_effects=len(orphaned),
                  tags=sum(len(c.get('moment', {}).get('tags', [])) for c in media_clips),
                  clips_with_notes=sum(bool(c.get('moment', {}).get('note') or c.get('description')) for c in media_clips),
                  selected_streams_without_audio=sum(bool(o['selected_stream'] and o['selected_stream'].get('probe') and not has_audio(o['selected_stream']['probe'])) for o in occurrences))
    report = {'status': 'partial' if issues else 'complete', 'counts': counts, 'issues': issues, 'invariants': invariants,
              'unreferenced_media': sorted(unreferenced, key=lambda x: str(x['video_id'])), 'orphaned_effects': orphaned,
              'metadata_completeness': 'partial' if issues else 'complete', 'media_availability': 'partial' if any(o['timing_status'] != 'resolved' for o in occurrences) else 'complete',
              'timing_confidence': 'media-consistent' if invariants['timing_rule_holds'] else 'explicit-policy' if stream_entries and all(s.get('timing', {}).get('timing_status') == 'resolved' for s in stream_entries) else 'unresolved',
              'xml_validation': 'not generated', 'application_compatibility': 'schema-matched, not application-tested',
              'rendering_fidelity': 'not rendered; editable effects are not reproduced in XML'}
    return {'schema_version': 1, 'playlist': document, 'occurrences': occurrences, 'streams': stream_entries, 'report': report}
