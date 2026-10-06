import json
import shutil

import pytest

from conftest import mutate
from sportscode_extract.inventory import inspect_package


def test_stale_title_optional_fields_order_and_metadata(package_factory, ffprobe):
    package=package_factory(second=True)
    result=inspect_package(package,ffprobe=ffprobe)
    counts=result['report']['counts']
    assert counts['media_clips']==2
    assert counts['title_clips']==2
    assert counts['stale_stream_dirs']==2
    assert counts['orphaned_effects']==1
    assert counts['selected_streams_without_audio']==2
    assert result['report']['status']=='complete'
    assert [item['clip']['id'] for item in result['occurrences']]==['clip0','clip1']
    assert all(item['segment_resolution']=='discovered' for item in result['streams'])
    assert all(abs(float(item['local_start'])-0.2)<1e-8 for item in result['occurrences'])
    assert all(abs(float(item['local_end'])-1.0)<1e-8 for item in result['occurrences'])
    assert result['playlist']['playlist']['unknown']=={'keep':'yes'}
    assert result['occurrences'][0]['clip']['mystery']=={'preserve':True}


def test_listed_without_tags(package_factory, ffprobe):
    result=inspect_package(package_factory(stale=False,tags=False,audio=True),ffprobe=ffprobe)
    assert result['report']['counts']['tags']==0
    assert result['report']['counts']['selected_streams_without_audio']==0
    assert result['streams'][0]['segment_resolution']=='listed'
    assert result['report']['status']=='complete'


def test_ambiguous_unlisted_media(package_factory, ffprobe):
    package=package_factory()
    media=next(package.rglob('*.mov'))
    shutil.copyfile(media,media.with_name('extra.mov'))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert 'ambiguous' in json.dumps(result['report']).lower()


def test_unreferenced_and_missing_records(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['videos'].extend([{'id':'other','localId':'unused','streams':[]},{'id':'other','localId':'unused_missing','streams':[]}]))
    unused=package/'Videos'/'unused'
    unused.mkdir()
    (unused/'video.json').write_text('{"id":"other"}')
    (unused/'opaque.mov').write_bytes(b'not probed because unreferenced')
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['counts']['unreferenced_video_records']==2
    assert result['report']['counts']['stream_files_probed']==1
    assert result['report']['status']=='complete'
    shutil.rmtree(package/'Videos'/'clip0')
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'


def test_bad_timing_is_unresolved(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['clips'][-1].update(endTime=20.0))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert 'timing' in json.dumps(result['report']).lower()


def test_unsupported_version(package_factory, ffprobe):
    package=package_factory()
    path=package/'Playlist.SCClips'
    data=json.loads(path.read_text()); data['version']='99.0'; path.write_text(json.dumps(data))
    try:
        result=inspect_package(package,ffprobe=ffprobe)
    except ValueError as exc:
        assert 'version' in str(exc).lower()
    else:
        assert result['report']['status']!='complete'


def test_symlink_escape_rejected(package_factory, ffprobe, tmp_path):
    package=package_factory()
    media=next(package.rglob('*.mov'))
    external=tmp_path/'outside.mov'
    media.rename(external)
    media.symlink_to(external)
    try:
        result=inspect_package(package,ffprobe=ffprobe)
    except ValueError:
        return
    assert result['report']['status']!='complete'


def test_hevc_probe(package_factory, ffmpeg, ffprobe):
    import subprocess
    encoders=subprocess.run([ffmpeg,'-hide_banner','-encoders'],capture_output=True,text=True,check=True).stdout
    if 'libx265' not in encoders:
        pytest.skip('ffmpeg cannot generate HEVC fixture')
    result=inspect_package(package_factory(codec='libx265'),ffprobe=ffprobe)
    assert result['report']['status']=='complete'
    assert 'hevc' in json.dumps(result['streams'])


def test_multiple_stream_selection_is_reported(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['clips'][-1].update(streamIds=['stream0','second'],audioStreamIds=['stream0','second']))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert any(issue['kind']=='unsupported_stream_selection' for issue in result['report']['issues'])


def test_duplicate_reference_is_ambiguous(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['videos'].append(dict(p['videos'][0])))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert any(issue['kind']=='unresolved_reference' for issue in result['report']['issues'])


def test_selected_stream_lookup_is_local(package_factory, ffprobe):
    package=package_factory(second=True)
    # Stream UUIDs may repeat between local videos; never join them globally.
    metadata=package/'Videos'/'clip1'/'Stream_0000'/'stream.json'
    data=json.loads(metadata.read_text()); data['id']='stream0'; metadata.write_text(json.dumps(data))
    video=package/'Videos'/'clip1'/'video.json'
    data=json.loads(video.read_text()); data['streams'][0]['id']='stream0'; video.write_text(json.dumps(data))
    def same_stream(p):
        for clip in p['clips']:
            if clip.get('moment'):
                clip.update(streamIds=['stream0'],audioStreamIds=['stream0'])
        p['videos'][1]['streams'][0]['id']='stream0'
    mutate(package,same_stream)
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']=='complete'
    assert result['occurrences'][1]['selected_stream']['video_id']=='clip1'


def test_stream_must_belong_to_its_video_record(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['videos'][0].update(streams=[{'id':'different-stream'}]))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert result['occurrences'][0].get('selected_stream') is None


def test_empty_video_json_streams_uses_record(package_factory, ffprobe):
    package=package_factory()
    video=package/'Videos'/'clip0'/'video.json'
    data=json.loads(video.read_text()); data['streams']=[]; video.write_text(json.dumps(data))
    result=inspect_package(package,ffprobe=ffprobe)
    assert not any(issue['kind']=='stream_id_mismatch' for issue in result['report']['issues'])
    assert result['occurrences'][0]['selected_stream']['id']=='stream0'


def test_missing_unselected_declared_stream_is_reported(package_factory, ffprobe):
    package=package_factory()
    mutate(package,lambda p:p['videos'][0]['streams'].append({'id':'missing-unselected'}))
    result=inspect_package(package,ffprobe=ffprobe)
    assert result['report']['status']!='complete'
    assert any(issue['kind']=='unresolved_reference' for issue in result['report']['issues'])
