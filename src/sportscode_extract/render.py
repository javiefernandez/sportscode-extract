"""Normalize independently, then join uniform streams on a cumulative frame clock."""
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
import shutil
from .media import executable, run, probe, has_audio, duration


def render(root, output, occurrences, ffmpeg=None, ffprobe=None, fps='30', width=1920, height=1080,
           drift_tolerance=0.1, render_titles=False, preset='veryfast'):
    binary = executable('ffmpeg', ffmpeg)
    decoders = run([binary, '-hide_banner', '-decoders'])
    if any(s.get('codec_name') == 'hevc' for o in occurrences for s in o['selected_stream']['probe']['streams']) and 'hevc' not in decoders:
        raise ValueError('FFmpeg lacks HEVC decoding support')
    rate = Fraction(fps)
    if rate <= 0 or width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('FPS must be positive and dimensions positive even integers')
    work = output.parent / '_render'
    work.mkdir()
    schedule, last_group = [], None
    for o in occurrences:
        if render_titles and o['group']['id'] != last_group:
            schedule.append((None, 2.0, o['group']['name']))
        schedule.append((o, Decimal(str(o['local_end'])) - Decimal(str(o['local_start'])), None))
        last_group = o['group']['id']
    requested_total, frames_total = Decimal(0), 0
    mapping, paths = [], []
    actual_cursor = 0.0
    for index, (o, requested, title) in enumerate(schedule):
        requested_total += Decimal(str(requested))
        target_frames = int((requested_total * Decimal(rate.numerator) / Decimal(rate.denominator)).to_integral_value(rounding=ROUND_HALF_UP))
        frames = target_frames - frames_total
        frames_total = target_frames
        if frames <= 0:
            raise ValueError('Clip is shorter than the output frame resolution')
        target_duration = float(Fraction(frames, 1) / rate)
        destination = work / f'{index:06d}.mp4'
        command = [binary, '-hide_banner', '-loglevel', 'error', '-y', '-copyts', '-threads', '2']
        if o:
            stream = o['selected_stream']
            command += ['-i', root / stream['path']]
            origin = float(stream['probe'].get('format', {}).get('start_time', 0))
            audio = has_audio(stream['probe']) and not stream['metadata'].get('isAudioMuted', False)
            video_filter = f"[0:v:0]setpts=PTS-({origin})/TB,trim=start={o['local_start']}:end={o['local_end']},setpts=PTS-({o['local_start']})/TB,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=fps={fps}:start_time=0,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={frames}[v]"
            if audio:
                audio_filter = f"[0:a:0]asetpts=PTS-({origin})/TB,atrim=start={o['local_start']}:end={o['local_end']},asetpts=PTS-({o['local_start']})/TB,aresample=48000:async=1:first_pts=0,aformat=channel_layouts=stereo,apad,atrim=duration={target_duration}[a]"
            else:
                command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                audio_filter = f'[1:a]atrim=duration={target_duration},asetpts=PTS-STARTPTS[a]'
        else:
            # A text file avoids treating group names as filter syntax.
            title_file = work / f'title{index}.txt'
            title_file.write_text(title, encoding='utf-8')
            command += ['-f', 'lavfi', '-i', f'color=c=black:s={width}x{height}:r={fps}', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
            video_filter = f"[0:v]drawtext=textfile=title{index}.txt:expansion=none:fontcolor=white:fontsize=52:x=(w-tw)/2:y=(h-th)/2,trim=end_frame={frames}[v]"
            # FFmpeg receives a cwd below for the generated-only text filename.
            audio_filter = f'[1:a]atrim=duration={target_duration},asetpts=PTS-STARTPTS[a]'
        command += ['-filter_complex_threads', '1', '-filter_complex', video_filter + ';' + audio_filter,
                    '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', preset, '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-r', fps, '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-video_track_timescale', str(rate.numerator), '-movflags', '+faststart', destination]
        if title:
            import subprocess
            result = subprocess.run([str(x) for x in command], cwd=work, capture_output=True, text=True)
            if result.returncode:
                raise ValueError(result.stderr[-4000:])
        else:
            run(command)
        info = probe(destination, ffprobe)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        actual = float(video['duration'])
        if abs(actual - target_duration) > 0.001:
            raise ValueError('Rendered video does not match the allocated frame duration')
        item = {'clip_id': o['clip']['id'] if o else None, 'kind': 'clip' if o else 'title',
                'source_file': o['selected_stream']['path'] if o else None,
                'local_start': o['local_start'] if o else None, 'local_end': o['local_end'] if o else None,
                'requested_duration': float(requested), 'actual_duration': actual,
                'output_start': actual_cursor, 'output_end': actual_cursor + actual, 'frames': frames}
        mapping.append(item)
        actual_cursor += actual
        paths.append(destination)
    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{p.name}'\nduration {m['actual_duration']:.9f}\n" for p, m in zip(paths, mapping)), encoding='utf-8')
    # Re-encode audio across joins to remove intermediate AAC priming/padding.
    run([binary, '-hide_banner', '-loglevel', 'error', '-y', '-copyts', '-f', 'concat', '-safe', '1', '-i', concat,
         '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-af', 'aresample=async=1:first_pts=0', '-c:a', 'aac',
         '-t', str(actual_cursor), '-movflags', '+faststart', output])
    info = probe(output, ffprobe)
    final_duration = duration(info)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    if abs(float(video.get('start_time', 0))) > 0.001 or abs(float(video['duration']) - actual_cursor) > 0.001:
        raise ValueError('Final video timestamps differ from the rendered clip mapping')
    drift = final_duration - float(requested_total)
    if abs(drift) > drift_tolerance:
        raise ValueError(f'Total duration drift {drift:.6f}s exceeds {drift_tolerance}s')
    shutil.rmtree(work)
    return mapping, {'mp4_duration': final_duration, 'requested_duration': float(requested_total), 'drift': drift,
                     'instance_count': len(occurrences), 'fps': str(rate), 'width': width, 'height': height}
