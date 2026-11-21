"""Explicit sample coverage and linearly interpolated percentile summaries."""
import math


def distribution(values):
    values = sorted(float(v) for v in values if type(v) in (int, float) and math.isfinite(v))
    def percentile(p):
        if not values:
            return None
        index = (len(values)-1)*p
        low = int(index)
        high = min(low+1, len(values)-1)
        return values[low] + (values[high]-values[low])*(index-low)
    return {'count': len(values), 'mean': sum(values)/len(values) if values else None,
            'p50': percentile(.5), 'p95': percentile(.95), 'p99': percentile(.99),
            'known_sum': sum(values) if values else None,
            'min': values[0] if values else None, 'max': values[-1] if values else None}
