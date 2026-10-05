"""Check exported files and compare XML against the measured rendering."""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from .media import probe, duration
from .export_xml import labels


def validate_export(directory, ffprobe=None):
    root = Path(directory).resolve()
    def load(name):
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError(f'Unsafe export file: {name}')
        return json.loads(path.read_text(encoding='utf-8'))
    manifest = load('manifest.json')
    report = load('reports/extraction_report.json')
    canonical = load('metadata/playlist.json')
    mapping = load('reports/source_mapping.json')
    errors = []
    def artifact(name):
        path = root / name
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or unsafe export file: {name}')
        return path
    for name in ('README.txt', 'metadata/playlist.json', 'metadata/clips.csv', 'metadata/labels.csv', 'reports/extraction_report.json', 'reports/source_mapping.json'):
        artifact(name)
        if name not in manifest['files']:
            errors.append(f'Required file absent from manifest: {name}')
    for name in manifest['files']:
        artifact(name)
    if report.get('render') and (not manifest.get('video') or not manifest.get('xml')):
        errors.append('Rendered export must declare its video and XML')
    if bool(manifest.get('video')) != bool(manifest.get('xml')):
        errors.append('Video and XML must be declared together')
    for key in ('video', 'xml'):
        if manifest.get(key) and manifest[key] not in manifest['files']:
            errors.append(f'{key} absent from file manifest')
    video_duration = None
    if manifest.get('video') and manifest.get('xml'):
        info = probe(artifact(manifest['video']), ffprobe)
        video_duration = duration(info)
        video_track = next(s for s in info['streams'] if s['codec_type'] == 'video')
        if abs(float(video_track.get('start_time', 0))) > .001:
            errors.append('Video does not start at zero')
        cursor = 0.0
        for span in mapping:
            if abs(span['output_start'] - cursor) > .001 or span['output_end'] <= span['output_start']:
                errors.append('Source mapping has a gap, overlap or invalid span')
            cursor = span['output_end']
        spans = [m for m in mapping if m['kind'] == 'clip']
        omitted = set(report.get('omitted_clip_ids', []))
        occurrences = [o for o in canonical['occurrences'] if o['clip']['id'] not in omitted]
        instances = ET.parse(artifact(manifest['xml'])).findall('./ALL_INSTANCES/instance')
        if len(instances) != len(occurrences) or len(spans) != len(occurrences):
            errors.append('Instance, mapping and occurrence counts differ')
        previous = 0.0
        for index, (node, occurrence, span) in enumerate(zip(instances, occurrences, spans), 1):
            start, end = float(node.findtext('start')), float(node.findtext('end'))
            if not all(math.isfinite(n) for n in (start, end)) or not 0 <= start < end <= video_duration + .001 or start < previous - .001:
                errors.append(f'Invalid interval at instance {index}')
            previous = end
            if node.findtext('ID') != str(index) or span['clip_id'] != occurrence['clip']['id']:
                errors.append(f'Invalid order at instance {index}')
            if abs(start - span['output_start']) > .001 or abs(end - span['output_end']) > .001:
                errors.append(f'Mapping differs at instance {index}')
            code = occurrence['group']['name'] if manifest['code_from'] == 'group' else occurrence['clip'].get('originalGroupName', occurrence['group']['name'])
            expected = labels(occurrence['clip'], code, occurrence['position'], manifest['provenance_labels'])
            actual = [(n.findtext('group') or '', n.findtext('text') or '') for n in node.findall('label')]
            if node.findtext('code') != code or actual != expected:
                errors.append(f'Code or labels differ at instance {index}')
            if abs(span['actual_duration'] - span['requested_duration']) > .05:
                errors.append(f'Clip duration drift at instance {index}')
        if mapping and abs(mapping[-1]['output_end'] - video_duration) > .1:
            errors.append('Video and mapping final durations differ')
    for name in manifest['files']:
        if name.endswith('.xml'):
            tree = ET.parse(artifact(name))
            for row in tree.findall('./rows/row'):
                if not row.findtext('Code') or any(not 0 <= int(row.findtext(k)) <= 255 for k in ('R', 'G', 'B')):
                    errors.append(f'Invalid XML row: {name}')
            if tree.getroot().tag != 'file' or tree.find('ALL_INSTANCES') is None or tree.find('rows') is None:
                errors.append(f'Invalid XML structure: {name}')
    return {'status': 'failed' if errors else report['status'], 'errors': errors,
            'mp4_duration': video_duration, 'xml_validation': 'failed' if errors else 'passed',
            'application_compatibility': 'schema-matched, not application-tested'}
