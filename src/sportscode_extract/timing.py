"""Keep source, package and rendered clocks separate."""
from decimal import Decimal


def interval(clip):
    start = Decimal(str(clip.get('startTimeOffset', 0)))
    span = Decimal(str(clip['endTime'])) - Decimal(str(clip['startTime']))
    return start, start + span


def check(clip, duration, tolerance=0.02, override=None, lenient=False):
    start, end = interval(clip)
    policy = 'startTimeOffset + (endTime - startTime)'
    if override is not None:
        start, end = Decimal(str(override['local_start'])), Decimal(str(override['local_end']))
        policy = 'explicit timing-config'
    length = Decimal(str(duration))
    tail = length - end
    valid = start.is_finite() and end.is_finite() and 0 <= start < end <= length + Decimal(str(tolerance))
    valid = valid and (override is not None or abs(tail) <= Decimal(str(tolerance)))
    confidence = 'media-consistent' if valid and override is None else 'explicit-policy' if valid else 'unresolved'
    if not valid and lenient and override is None and start.is_finite() and end.is_finite() and 0 <= start < min(end, length):
        # Keep the clip despite the mismatch: use the interval as-is, ending early if the file is short.
        end = min(end, length)
        valid, confidence = True, 'lenient'
        policy += ' (lenient: file duration mismatch' + (', end clamped to file)' if tail < 0 else ')')
    return {'local_start': float(start), 'local_end': float(end), 'timing_status': 'resolved' if valid else 'timing_unresolved',
            'timing_rule': policy, 'tail_error': float(tail), 'timing_confidence': confidence}
