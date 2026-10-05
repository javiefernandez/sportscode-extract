"""Read-only checks against private packages, never copied into fixtures."""
import os
from pathlib import Path

import pytest

from sportscode_extract.inventory import inspect_package

ROOT=os.environ.get('SPORTSCODE_SAMPLES')
pytestmark=pytest.mark.skipif(not ROOT,reason='Set SPORTSCODE_SAMPLES to opt in to private sample inspection')
FIELDS='groups media_clips title_clips video_records video_folders unreferenced_video_records original_source_videos stream_files_probed stale_stream_dirs effects orphaned_effects tags clips_with_notes selected_streams_without_audio'.split()
SAMPLES=[
    ('Best goal for AP2025.SCPlaylist',[13,23,13,24,23,1,13,36,18,13,0,45,0,12]),
    ('Best CK against AP2025.SCPlaylist',[14,70,14,70,70,0,14,125,46,14,0,0,0,26]),
    # All 19 clips have note fields; 17 contain nonempty notes (§3).
    ('Leagues Cup/J1 Inter Miami vs Atlas.SCPlaylist',[6,19,6,102,102,83,1,38,0,13,7,3,17,0]),
]


@pytest.mark.parametrize('relative,values',SAMPLES)
def test_real_package_counts_invariants_and_timing(relative,values,ffprobe):
    result=inspect_package(Path(ROOT)/relative,ffprobe=ffprobe)
    report=result['report']
    assert {key:report['counts'][key] for key in FIELDS}==dict(zip(FIELDS,values))
    assert report['status']=='complete',report['issues']
    assert report['invariants']
    assert all(report['invariants'].values()),report['invariants']
    assert report['timing_confidence']=='media-consistent'
    ordered=[cid for group in result['playlist']['playlist']['groups'] for cid in group['clipIds']]
    assert [item['clip']['id'] for item in result['occurrences']]==ordered
    assert len(result['streams'])==values[7]
    for occurrence in result['occurrences']:
        clip=occurrence['clip']
        expected=clip['startTimeOffset']+clip['endTime']-clip['startTime']
        assert abs(float(occurrence['local_end'])-expected)<1e-8
        for stream in occurrence['streams']:
            assert abs(float(stream['probe']['format']['duration'])-expected)<=0.02
    import json
    metadata=json.loads((Path(ROOT)/relative/'package.meta').read_text())
    miami='Miami' in relative
    assert metadata['createdWithVersion']==('12.58.0' if miami else '12.64.0')
    colors={group['color'] for group in result['playlist']['playlist']['groups']}
    assert colors==({'#000000','#520001'} if miami else {'#520001'} if 'CK' in relative else {'#000000'})
    codecs={track['codec_name'] for stream in result['streams'] for track in stream['probe']['streams'] if track['codec_type']=='video'}
    assert codecs==({'h264'} if miami else {'h264','hevc'})
    if miami:
        assert sum('note' in item['clip']['moment'] for item in result['occurrences'])==19
        assert all(item['clip']['description']==item['clip']['moment']['note'] for item in result['occurrences'])
        assert sum(item['size_bytes'] for item in report['unreferenced_media'])>2.7e9
