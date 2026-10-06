"""Sportscode XML shapes for Angles and Catapult Focus; application import remains untested."""
import re
import xml.etree.ElementTree as ET

PALETTE = ['#466EB4', '#DC783C', '#50965A', '#A564B4', '#D2AD3C', '#3CA5AA', '#C85A78']
# Angles reads 8-bit <Code> rows; Focus gets the Sportscode-native <code> and 16-bit channels.
ROWS = {'angles': ('Code', 1), 'focus': ('code', 257)}


def notes(clip):
    result = []
    for text in (clip.get('moment', {}).get('note'), clip.get('description')):
        if text and text not in result:
            result.append(text)
    return result


def labels(clip, code, position, provenance=False, note_labels=True):
    result = []
    if clip.get('originalGroupName') and clip['originalGroupName'] != code:
        result.append(('Original row', clip['originalGroupName']))
    if clip.get('timelineName'):
        result.append(('Match', clip['timelineName']))
    for tag in clip.get('moment', {}).get('tags', []):
        result.append((tag.get('key', '') if tag.get('value') else 'Tag', tag.get('value') or tag.get('key', '')))
    if note_labels:
        result.extend(('Note', text) for text in notes(clip))
    if provenance:
        result.extend([('Clip UUID', clip['id']), ('Playlist position', str(position)),
                       ('Original start', str(clip['startTime'])), ('Original end', str(clip['endTime']))])
    return result


def write_xml(path, occurrences, spans, code_from='group', provenance=False, target='angles'):
    # Focus keeps notes as free text so each distinct note does not become a filter label.
    focus = target == 'focus'
    root = ET.Element('file')
    instances = ET.SubElement(root, 'ALL_INSTANCES')
    colors = {o['group'].get('color') for o in occurrences}
    palette = len(colors) <= 1
    rows = {}
    for occurrence, span in zip(occurrences, spans):
        clip, group = occurrence['clip'], occurrence['group']
        code = group['name'] if code_from == 'group' else clip.get('originalGroupName', group['name'])
        node = ET.SubElement(instances, 'instance')
        for name, value in [('ID', len(instances)), ('start', f'{span[0]:.3f}'), ('end', f'{span[1]:.3f}'), ('code', code)]:
            ET.SubElement(node, name).text = str(value)
        if focus and notes(clip):
            ET.SubElement(node, 'free_text').text = '\n'.join(notes(clip))
        for name, value in labels(clip, code, occurrence['position'], provenance, not focus):
            label = ET.SubElement(node, 'label')
            ET.SubElement(label, 'text').text = str(value)
            ET.SubElement(label, 'group').text = name
        if code not in rows:
            color = PALETTE[len(rows) % len(PALETTE)] if palette else group.get('color', '#466EB4')
            rows[code] = color if re.fullmatch(r'#[0-9a-fA-F]{6}', color or '') else '#466EB4'
    key, scale = ROWS[target]
    row_node = ET.SubElement(root, 'rows')
    for code, color in rows.items():
        row = ET.SubElement(row_node, 'row')
        for name, value in [(key, code), ('R', int(color[1:3], 16) * scale), ('G', int(color[3:5], 16) * scale), ('B', int(color[5:7], 16) * scale)]:
            ET.SubElement(row, name).text = str(value)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return 'categorical palette' if palette else 'group colors'
