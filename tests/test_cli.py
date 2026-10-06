import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import pytest

from conftest import ROOT, mutate


def cli(*args, ffmpeg, ffprobe):
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),SPORTSCODE_FFMPEG=ffmpeg,SPORTSCODE_FFPROBE=ffprobe)
    return subprocess.run([sys.executable,'-m','sportscode_extract',*map(str,args)],capture_output=True,text=True,env=env)


def test_render_xml_and_validate(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory(second=True)
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    mp4,=output.glob('*.mp4')
    xml,=output.glob('*.xml')
    root=ET.parse(xml).getroot()
    instances=root.findall('./ALL_INSTANCES/instance')
    assert len(instances)==2
    assert [i.findtext('ID') for i in instances]==['1','2']
    assert [i.findtext('code') for i in instances]==['Gól & <0>','Gól & <1>']
    assert float(instances[0].findtext('start'))==0
    for instance in instances:
        assert abs(float(instance.findtext('end'))-float(instance.findtext('start'))-0.8)<0.05
        labels=[(n.findtext('group'),n.findtext('text')) for n in instance.findall('label')]
        assert labels.count(('Note','A & B <note>'))==1
        assert ('Tag','Balón & <tag>') in labels
        assert ('Original row','Original <row>') in labels
        assert ('Match','Imaginary match') in labels
    colors=[tuple(row.findtext(k) for k in ('R','G','B')) for row in root.findall('./rows/row')]
    assert len(set(colors))==2
    probe=json.loads(subprocess.run([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(mp4)],capture_output=True,text=True,check=True).stdout)
    assert any(s['codec_type']=='audio' for s in probe['streams'])
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    assert abs(float(video['start_time']))<0.001
    assert abs(float(probe['format']['duration'])-float(instances[-1].findtext('end')))<0.1
    report=json.loads((output/'reports'/'extraction_report.json').read_text())
    assert report['status']=='complete'
    assert report['timing_confidence']=='media-consistent'
    assert report['application_compatibility']=='schema-matched, not application-tested'
    for key in ('metadata_completeness','media_availability','xml_validation','rendering_fidelity'):
        assert key in report
    original=output/'metadata'/'original_metadata'
    assert any(p.read_bytes()==(package/'Playlist.SCClips').read_bytes() for p in original.rglob('Playlist.SCClips'))
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    result=cli('extract',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1


def test_focus_target_free_text_rows_and_validate(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory(second=True)
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--target','focus',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    xml,=output.glob('*.xml')
    root=ET.parse(xml).getroot()
    for instance in root.findall('./ALL_INSTANCES/instance'):
        assert instance.findtext('free_text')=='A & B <note>'
        assert not any(n.findtext('group')=='Note' for n in instance.findall('label'))
    rows=root.findall('./rows/row')
    assert all(row.findtext('code') and row.find('Code') is None for row in rows)
    assert all(0<=int(row.findtext(k))<=65535 for row in rows for k in ('R','G','B'))
    assert json.loads((output/'manifest.json').read_text())['target']=='focus'
    assert 'Catapult Focus' in (output/'README.txt').read_text()
    assert cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe).returncode==0
    tree=ET.parse(xml)
    tree.find('./ALL_INSTANCES/instance/free_text').text='Wrong note'
    tree.write(xml,encoding='utf-8',xml_declaration=True)
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1 and 'Free text differs at instance 1' in result.stdout,result.stderr+result.stdout


def test_dry_run_and_no_render_copy(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory()
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--dry-run',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    assert not output.exists()
    result=cli('extract',package,'--output',output,'--no-render','--source-xml',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    assert not list(output.glob('*.mp4'))
    assert len(list((output/'clips').rglob('*.mov')))==1
    source,=(output/'source').glob('*.xml')
    instance=ET.parse(source).find('./ALL_INSTANCES/instance')
    assert float(instance.findtext('start'))==10
    assert float(instance.findtext('end'))==10.8


def test_output_cannot_destroy_source(package_factory,ffmpeg,ffprobe):
    package=package_factory()
    original=(package/'Playlist.SCClips').read_bytes()
    for output in (package,package/'export',package.parent):
        result=cli('extract',package,'--output',output,'--force','--no-render',ffmpeg=ffmpeg,ffprobe=ffprobe)
        assert result.returncode==1
        assert (package/'Playlist.SCClips').read_bytes()==original


def test_partial_requires_explicit_opt_in(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory(second=True)
    mutate(package,lambda p:p['clips'][-1].update(endTime=20.0))
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1
    assert not output.exists()
    result=cli('extract',package,'--output',output,'--allow-partial',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==2,result.stderr+result.stdout
    xml,=output.glob('*.xml')
    assert len(ET.parse(xml).findall('./ALL_INSTANCES/instance'))==1
    assert json.loads((output/'reports'/'extraction_report.json').read_text())['status']=='partial'


def test_hevc_render_titles_and_force(package_factory,tmp_path,ffmpeg,ffprobe):
    encoders=subprocess.run([ffmpeg,'-hide_banner','-encoders'],capture_output=True,text=True,check=True).stdout
    if 'libx265' not in encoders:
        pytest.skip('ffmpeg cannot generate HEVC fixture')
    package=package_factory(codec='libx265',audio=True)
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--render-titles',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    xml,=output.glob('*.xml')
    instances=ET.parse(xml).findall('./ALL_INSTANCES/instance')
    assert len(instances)==1
    assert abs(float(instances[0].findtext('start'))-2.0)<0.001
    assert abs(float(instances[0].findtext('end'))-2.8)<0.001
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    (output/'stale.txt').write_text('Previous export')
    result=cli('extract',package,'--output',output,'--no-render','--force',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    assert not (output/'stale.txt').exists()
    assert not list(output.glob('*.mp4'))


@pytest.mark.parametrize('tamper',['missing_mp4','xml_count','xml_order','xml_label','xml_end'])
def test_validate_rejects_tampered_render(package_factory,tmp_path,ffmpeg,ffprobe,tamper):
    package=package_factory(second=True)
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    xml,=output.glob('*.xml')
    tree=ET.parse(xml)
    instances=tree.find('ALL_INSTANCES')
    if tamper=='missing_mp4':
        mp4,=output.glob('*.mp4')
        mp4.unlink()
    elif tamper=='xml_count':
        instances.remove(instances[-1])
    elif tamper=='xml_order':
        instances[0].find('code').text='Wrong group'
    elif tamper=='xml_label':
        instances[0].find('label/text').text='Wrong label'
    else:
        instances[-1].find('end').text='9999.000'
    if tamper!='missing_mp4':
        tree.write(xml,encoding='utf-8',xml_declaration=True)
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1,result.stderr+result.stdout


def test_validate_missing_copied_media(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory()
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--no-render',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    next((output/'clips').rglob('*.mov')).unlink()
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1,result.stderr+result.stdout


def test_validate_rejects_manifest_path_escape(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory()
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--no-render',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    (tmp_path/'outside.txt').write_text('Not an export artifact')
    manifest=output/'manifest.json'
    data=json.loads(manifest.read_text())
    data['files'].append('../outside.txt')
    manifest.write_text(json.dumps(data))
    result=cli('validate',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==1,result.stderr+result.stdout


def test_partial_never_renders_mismatched_video_identity(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory(second=True)
    video=package/'Videos'/'clip0'/'video.json'
    data=json.loads(video.read_text())
    data['id']='another-match'
    video.write_text(json.dumps(data))
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--allow-partial',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==2,result.stderr+result.stdout
    xml,=output.glob('*.xml')
    assert [n.text for n in ET.parse(xml).findall('./ALL_INSTANCES/instance/code')]==['Gól & <1>']
    report=json.loads((output/'reports'/'extraction_report.json').read_text())
    assert report['omitted_clip_ids']==['clip0']


def test_nonzero_container_start_preserves_delayed_audio(package_factory,tmp_path,ffmpeg,ffprobe):
    import array
    package=package_factory(audio=True,offset=0)
    media=next(package.rglob('*.mov'))
    temporary=media.with_name('shifted.mov')
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-i',str(media),
                    '-filter_complex','[0:a]atrim=duration=0.4,asetpts=PTS-STARTPTS+0.3/TB[a]',
                    '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-output_ts_offset','5',str(temporary)],
                   check=True,capture_output=True)
    temporary.replace(media)
    probe=json.loads(subprocess.run([ffprobe,'-v','error','-show_format','-show_streams','-of','json',str(media)],
                                   capture_output=True,text=True,check=True).stdout)
    assert float(probe['format']['start_time'])>=5
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    mp4,=output.glob('*.mp4')
    raw=subprocess.run([ffmpeg,'-v','error','-i',str(mp4),'-map','0:a:0','-ac','1','-ar','48000','-f','f32le','-'],
                       capture_output=True,check=True).stdout
    samples=array.array('f'); samples.frombytes(raw)
    early=samples[:int(.15*48000)]
    later=samples[int(.4*48000):int(.55*48000)]
    assert max(abs(x) for x in early)<.001
    assert max(abs(x) for x in later)>.01


def test_resources_skip_hidden_symlinks_and_keep_empty_dirs(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory()
    resources=package/'Resources'
    (resources/'empty').mkdir()
    (resources/'visible.txt').write_text('Synthetic resource')
    (resources/'.private').symlink_to(tmp_path)
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--no-render',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    assert (output/'Resources'/'empty').is_dir()
    assert (output/'Resources'/'visible.txt').read_text()=='Synthetic resource'
    assert not (output/'Resources'/'.private').exists()


def test_inspect_normalizes_title_references(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory()
    output=tmp_path/'inspection'
    result=cli('inspect',package,'--output',output,ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==0,result.stderr+result.stdout
    data=json.loads((output/'metadata'/'playlist.json').read_text())
    title=next(c for c in data['playlist']['playlist']['clips'] if c['id']=='title0')
    assert title['videoId'] is None
    assert title['streamIds']==[None]


def test_partial_reports_ungrouped_media(package_factory,tmp_path,ffmpeg,ffprobe):
    package=package_factory(second=True)
    mutate(package,lambda p:p['groups'][0].update(clipIds=[]))
    output=tmp_path/'export'
    result=cli('extract',package,'--output',output,'--no-render','--allow-partial',ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert result.returncode==2,result.stderr+result.stdout
    report=json.loads((output/'reports'/'extraction_report.json').read_text())
    assert 'clip0' in report['omitted_clip_ids']
