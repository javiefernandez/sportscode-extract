"""Fixtures are generated from invented metadata; private sample data stays external."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
BIN = Path('/Users/javierfernandez/miniconda3/envs/football-pipeline/bin')


def binary(name):
    return os.environ.get('SPORTSCODE_' + name.upper()) or (str(BIN / name) if (BIN / name).exists() else shutil.which(name))


@pytest.fixture(scope='session')
def ffmpeg():
    value = binary('ffmpeg')
    if not value:
        pytest.skip('ffmpeg required for synthetic media')
    return value


@pytest.fixture(scope='session')
def ffprobe():
    value = binary('ffprobe')
    if not value:
        pytest.skip('ffprobe required for media tests')
    return value


@pytest.fixture
def package_factory(tmp_path, ffmpeg):
    def make(*, stale=True, audio=False, offset=0.2, tags=True, codec='libx264', second=False):
        package = tmp_path / 'Balón & <test>.SCPlaylist'
        package.mkdir()
        groups, clips, videos = [], [], []
        for index in range(2 if second else 1):
            cid, sid, gid = f'clip{index}', f'stream{index}', f'group{index}'
            title = f'title{index}'
            groups.append(dict(id=gid, name=f'Gól & <{index}>', color='#000000', titleClipId=title, clipIds=[cid]))
            clips.append(dict(id=cid, videoId=cid, originalVideoId='match', streamIds=[sid], audioStreamIds=[sid],
                startTime=10.0 + index, endTime=10.8 + index, startTimeOffset=offset,
                originalGroupName='Original <row>', timelineName='Imaginary match', description='A & B <note>',
                originalIndex=99-index, uploadedStartTime=-1, tracks=[], mystery={'preserve': True},
                moment=dict(id=f'moment{index}', startTime=10.0+index,endTime=10.8+index,note='A & B <note>',
                            tags=[{'key':'Balón & <tag>', 'value':''}] if tags else [], source={'type':'timeline','id':'match','contextId':'context'})))
            clips.append(dict(id=title, videoId='', streamIds=[''], audioStreamIds=[''], tracks=[{'id':f'track{index}', 'effectIds':[f'effect{index}']}]))
            videos.append(dict(id='match', localId=cid, path='/private/analyst/match.SCVideo', localPath='/historical/package', streams=[{'id':sid,'name':'Angle 1'}]))
            folder = package / 'Videos' / cid
            stream = folder / 'Stream_0000'
            stream.mkdir(parents=True)
            (folder/'video.json').write_text(json.dumps({'id':'match','streams':[{'id':sid,'name':'Angle 1'}]}))
            (stream/'stream.json').write_text(json.dumps({'id':sid,'name':'Angle 1','isAudioMuted':False,'segments':[{'fileName':'old.MP4' if stale else 'Segment_00000.mov','offset':7.5,'id':'segment'}]}))
            args = [ffmpeg,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i',f'color=c=red:s={"160x90" if index==0 else "128x96"}:r={"25" if index==0 else "30"}']
            if audio:
                args += ['-f','lavfi','-i','sine=frequency=440:sample_rate=48000']
            args += ['-t',str(0.8+offset),'-c:v',codec,'-pix_fmt','yuv420p']
            if codec == 'libx265':
                args += ['-x265-params','pools=1:frame-threads=1:log-level=error']
            if audio:
                args += ['-c:a','aac']
            args += [str(stream/'Segment_00000.mov')]
            subprocess.run(args,check=True,capture_output=True)
        # Deliberately reverse the storage order; playback order remains the group order.
        effects = [dict(id=f'effect{i}',type='annotation',trackId=f'track{i}',streamId='',text=group['name'],startFlicks=0,endFlicks=0) for i,group in enumerate(groups)]
        effects.append(dict(id='orphan',type='annotation',trackId='deleted',text='Deleted group'))
        data={'version':'1.11.0','playlist':dict(groups=groups,clips=list(reversed(clips)),videos=videos,effects=effects,titlesEnabled=False,labelTree={},unknown={'keep':'yes'})}
        (package/'Playlist.SCClips').write_text(json.dumps(data,ensure_ascii=False))
        (package/'package.meta').write_text(json.dumps({'createdWithVersion':'12.64.0'}))
        (package/'Resources').mkdir()
        return package
    return make


def mutate(package, callback):
    path=package/'Playlist.SCClips'
    data=json.loads(path.read_text())
    callback(data['playlist'])
    path.write_text(json.dumps(data))
