"""Subprocess boundaries: always argument arrays, never a shell."""
import json
import os
import subprocess


def executable(kind, override=None):
    return override or os.environ.get('SPORTSCODE_' + kind.upper()) or kind


def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f'{args[0]} failed: {result.stderr[-4000:]}')
    return result.stdout


def probe(path, ffprobe=None):
    return json.loads(run([executable('ffprobe', ffprobe), '-v', 'error', '-show_format',
                           '-show_streams', '-of', 'json', path]))


def duration(data):
    return float(data['format']['duration'])


def has_audio(data):
    return any(s.get('codec_type') == 'audio' for s in data.get('streams', []))
