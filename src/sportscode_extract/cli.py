"""One package per invocation, with atomic publication of exports."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from .inventory import inspect_package, files
from .export_json import write_json, redact, safe_name
from .export_csv import write_csv
from .export_xml import write_xml
from .render import render
from .validation import validate_export

README = {
    'angles': 'Open the assembled MP4 in Angles and import its matching Sportscode XML timeline.\n'
              'XML compatibility: schema-matched, not application-tested. Manual Angles playback remains unverified.\n',
    'focus': 'In Catapult Focus, create an Archive Session (Generic session type) from the assembled MP4,\n'
             'then use Tags > Import Tags with its matching Sportscode XML. Notes are written as free text.\n'
             'XML compatibility: schema-matched, not application-tested. Manual Focus import remains unverified.\n',
}
SOURCE_SYNC = {
    'angles': '',
    'focus': 'In Focus, align source XML to the full match with Tags > Sync Tags (kick-off timing tag) or Time Offset.\n',
}


def parser():
    p = argparse.ArgumentParser(prog='sportscode-extract')
    commands = p.add_subparsers(dest='command', required=True)
    for command in ('inspect', 'extract', 'validate'):
        c = commands.add_parser(command)
        c.add_argument('path', type=Path)
        c.add_argument('--ffprobe')
        if command == 'validate':
            continue
        c.add_argument('--output', type=Path, required=command == 'extract')
        c.add_argument('--force', action='store_true')
        c.add_argument('--timing-config', type=Path)
        c.add_argument('--timing-tolerance', type=float, default=.02)
        c.add_argument('--lenient-timing', action='store_true',
                       help='keep clips whose file duration does not match the metadata (end clamped to the file)')
        c.add_argument('--dry-run', action='store_true')
        if command == 'extract':
            c.add_argument('--ffmpeg')
            for option in ('no-render', 'copy-clips', 'provenance-labels', 'source-xml', 'render-titles', 'allow-partial'):
                c.add_argument('--' + option, action='store_true')
            c.add_argument('--code-from', choices=('group', 'original'), default='group')
            c.add_argument('--target', choices=('angles', 'focus'), default='angles')
            c.add_argument('--fps', default='30')
            c.add_argument('--width', type=int, default=1920)
            c.add_argument('--height', type=int, default=1080)
            c.add_argument('--drift-tolerance', type=float, default=.1)
    return p


def check_output(source, output, force):
    if output.is_symlink():
        raise ValueError('Output cannot be a symlink')
    output = output.resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Output must not overlap the source package')
    if output.exists() and not force:
        raise ValueError('Output already exists; choose another directory or pass --force')
    if output.exists() and force and not ((output / 'manifest.json').is_file() or (output / 'reports/extraction_report.json').is_file()):
        raise ValueError('--force only replaces a recognized sportscode-extract export')
    if output.exists() and not output.is_dir():
        raise ValueError('Output must be a directory')
    return output


def publish(stage, output):
    backup = None
    if output.exists():
        backup = Path(tempfile.mkdtemp(prefix='.sportscode-backup-', dir=output.parent))
        backup.rmdir()
        output.rename(backup)
    try:
        stage.rename(output)
    except BaseException:
        if backup:
            backup.rename(output)
        raise
    if backup:
        shutil.rmtree(backup)


def canonical_metadata(data):
    canonical = redact(data)
    titles = {g.get('titleClipId') for g in canonical['playlist']['playlist'].get('groups', [])}
    for clip in canonical['playlist']['playlist'].get('clips', []):
        if clip.get('id') in titles and not clip.get('moment'):
            for key in ('videoId', 'originalVideoId', 'timelineName'):
                if clip.get(key) == '':
                    clip[key] = None
            for key in ('streamIds', 'audioStreamIds'):
                clip[key] = [None if value == '' else value for value in clip.get(key, [])]
    return canonical


def extract(args, source, stage, data):
    report = data['report']
    occurrences = data['occurrences']
    bad_ids = {issue.get('clip_id') for issue in report['issues'] if issue.get('clip_id')}
    ready = [o for o in occurrences if o['timing_status'] == 'resolved' and o.get('selected_stream') and o['clip']['id'] not in bad_ids]
    playlist = data['playlist']['playlist']
    title_ids = {g.get('titleClipId') for g in playlist.get('groups', [])}
    media_ids = [c['id'] for c in playlist.get('clips', []) if c.get('moment') or c.get('id') not in title_ids]
    grouped_ids = [cid for g in playlist.get('groups', []) for cid in g.get('clipIds', []) if cid not in title_ids]
    ready_ids = {o['clip']['id'] for o in ready}
    report['omitted_clip_ids'] = list(dict.fromkeys(cid for cid in grouped_ids + media_ids if cid not in ready_ids))
    if report['status'] != 'complete' and not args.allow_partial:
        raise ValueError('Package has unresolved/unsupported items; inspect it or use --allow-partial')
    name = safe_name(source.stem)
    metadata = stage / 'metadata'
    metadata.mkdir()
    canonical = canonical_metadata(data)
    write_csv(metadata, occurrences)
    original = metadata / 'original_metadata'
    source_files = files(source)
    for path in source_files:
        if path.name in ('package.meta', 'Playlist.SCClips', 'video.json', 'stream.json'):
            destination = original / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for path in source_files:
        relative = path.relative_to(source)
        if 'Resources' in relative.parts[:-1]:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    # Preserve visible empty resource directories without copying hidden contents.
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if any(part.startswith('.') for part in relative.parts):
            continue
        if 'Resources' in relative.parts and path.is_dir():
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError('Unsafe resource directory')
            (stage / relative).mkdir(parents=True, exist_ok=True)
    if args.copy_clips or args.no_render:
        for o in occurrences:
            folder = f"{o['position']:03d}_{safe_name(o['group']['name'])}_{safe_name(o['clip']['id'])}"
            for stream in o['streams']:
                for item in stream['files']:
                    relative = Path(item['path'])
                    destination = stage / 'clips' / folder / relative.parent.name / relative.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / relative, destination)
    mapping = []
    manifest = {'schema_version': 1, 'video': None, 'xml': None,
                'code_from': args.code_from, 'provenance_labels': args.provenance_labels, 'target': args.target}
    if not args.no_render:
        if not ready:
            raise ValueError('No resolved clips available to render')
        mapping, stats = render(source, stage / f'{name}.mp4', ready, args.ffmpeg, args.ffprobe,
                                args.fps, args.width, args.height, args.drift_tolerance, args.render_titles)
        spans = [(m['output_start'], m['output_end']) for m in mapping if m['kind'] == 'clip']
        report['row_color_policy'] = write_xml(stage / f'{name}.xml', ready, spans, args.code_from, args.provenance_labels, args.target)
        report['render'] = stats
        report['xml_validation'] = 'passed'
        report['rendering_fidelity'] = 'normalized H.264/AAC; missing or muted audio filled with silence; editable effects not reproduced'
        manifest.update(video=f'{name}.mp4', xml=f'{name}.xml')
    if args.source_xml:
        ids = {o['clip'].get('originalVideoId') for o in occurrences}
        if len(ids) != 1 or not all(ids):
            raise ValueError('--source-xml requires exactly one original source video')
        destination = stage / 'source' / (safe_name(occurrences[0]['clip'].get('timelineName') or name) + '.xml')
        destination.parent.mkdir()
        write_xml(destination, ready, [(o['clip']['startTime'], o['clip']['endTime']) for o in ready], args.code_from, args.provenance_labels, args.target)
    canonical['report'] = redact(report)
    write_json(metadata / 'playlist.json', canonical)
    write_json(stage / 'reports/source_mapping.json', mapping)
    write_json(stage / 'reports/extraction_report.json', report)
    (stage / 'README.txt').write_text(
        README[args.target] + 'Timing confidence: ' + report['timing_confidence'] + '.\n'
        'Editable visual effects are preserved as metadata but not reproduced in XML/video.\n'
        'metadata/original_metadata contains private, byte-for-byte source JSON and historical paths.\n'
        'Canonical JSON redacts historical absolute path/localPath values; raw copies retain all unknown fields.\n'
        'Source XML uses the original .SCVideo clock, which may not map to a re-encoded full match; angle/segment offsets may apply.\n'
        + SOURCE_SYNC[args.target] +
        'Omitted clip IDs: ' + json.dumps(report['omitted_clip_ids']) + '\n', encoding='utf-8')
    manifest['files'] = sorted(str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file())
    write_json(stage / 'manifest.json', manifest)
    checked = validate_export(stage, args.ffprobe)
    if checked['errors']:
        raise ValueError('; '.join(checked['errors']))
    return report


def main(argv=None):
    args = parser().parse_args(argv)
    stage = None
    try:
        if args.command == 'validate':
            report = validate_export(args.path, args.ffprobe)
        else:
            source = args.path.resolve()
            output = check_output(source, args.output, args.force) if args.output else None
            config = json.loads(args.timing_config.read_text()) if args.timing_config else None
            data = inspect_package(source, args.ffprobe, args.timing_tolerance, config, args.lenient_timing)
            report = data['report']
            if not args.dry_run and output:
                output.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='.sportscode-stage-', dir=output.parent))
                if args.command == 'extract':
                    report = extract(args, source, stage, data)
                else:
                    write_json(stage / 'reports/extraction_report.json', report)
                    write_json(stage / 'metadata/playlist.json', canonical_metadata(data))
                publish(stage, output)
                stage = None
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return {'complete': 0, 'partial': 2, 'failed': 1}[report['status']]
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError, ArithmeticError) as exc:
        print(f'sportscode-extract: {exc}', file=sys.stderr)
        return 1
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)
