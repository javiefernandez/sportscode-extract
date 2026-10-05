"""Keep source, package and rendered clocks separate."""
from decimal import Decimal


def interval(clip):
    start = Decimal(str(clip.get('startTimeOffset', 0)))
    span = Decimal(str(clip['endTime'])) - Decimal(str(clip['startTime']))
    return start, start + span


def check(clip, duration, tolerance=0.02, override=None):
    start, end = interval(clip)
    policy = 'startTimeOffset + (endTime - startTime)'
    if override is not None:
        start, end = Decimal(str(override['local_start'])), Decimal(str(override['local_end']))
        policy = 'explicit timing-config'
    tail = Decimal(str(duration)) - end
    valid = start.is_finite() and end.is_finite() and 0 <= start < end <= Decimal(str(duration)) + Decimal(str(tolerance))
    valid = valid and (override is not None or abs(tail) <= Decimal(str(tolerance)))
    return {'local_start': float(start), 'local_end': float(end), 'timing_status': 'resolved' if valid else 'timing_unresolved',
            'timing_rule': policy, 'tail_error': float(tail), 'timing_confidence': 'media-consistent' if valid and override is None else 'explicit-policy' if valid else 'unresolved'}
