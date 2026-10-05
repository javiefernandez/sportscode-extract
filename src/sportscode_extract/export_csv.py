import csv
from .export_xml import labels


def write_csv(directory, occurrences):
    with (directory / 'clips.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['position', 'clip_id', 'group', 'original_row', 'match', 'original_start', 'original_end', 'local_start', 'local_end', 'notes'])
        for o in occurrences:
            c = o['clip']
            writer.writerow([o['position'], c['id'], o['group']['name'], c.get('originalGroupName'), c.get('timelineName'), c.get('startTime'), c.get('endTime'), o.get('local_start'), o.get('local_end'), '\n'.join(v for k, v in labels(c, o['group']['name'], o['position']) if k == 'Note')])
    with (directory / 'labels.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['position', 'clip_id', 'group', 'text'])
        for o in occurrences:
            for name, value in labels(o['clip'], o['group']['name'], o['position']):
                writer.writerow([o['position'], o['clip']['id'], name, value])
