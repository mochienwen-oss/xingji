"""Keep selected stops in compact daily areas without inventing travel times."""
import math
import re


DAY_CONSTRAINT = re.compile(r'第[一二两三四五1-5１-５]天|首日|次日|当天|上午|下午|中午|早上|傍晚|晚上|先.{1,30}(?:再|后)|然后|(?:周|星期)[一二三四五六日天].{0,8}(?:去|到|游|看)')


def distance_km(a: dict, b: dict) -> float | None:
    try:
        lon1, lat1 = (float(v) for v in a['location'].split(','))
        lon2, lat2 = (float(v) for v in b['location'].split(','))
        if not all(math.isfinite(x) for x in (lon1, lat1, lon2, lat2)):
            return None
        if not (73 <= lon1 <= 135 and 3 <= lat1 <= 54 and 73 <= lon2 <= 135 and 3 <= lat2 <= 54):
            return None
        lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
        h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        return 12742 * math.asin(min(1, math.sqrt(h)))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def day_span(day: dict) -> float | None:
    places = [stop['place'] for stop in day['stops']]
    distances = [distance_km(a, b) for i, a in enumerate(places) for b in places[i+1:]]
    return max(distances, default=0) if all(d is not None for d in distances) else None


def has_nearby_alternatives(days: list[dict], candidates: list[dict]) -> bool:
    selected = {stop['place']['id'] for day in days for stop in day['stops']}
    for day in days:
        span = day_span(day)
        if span is None or span <= 20:
            continue
        for stop in day['stops']:
            nearby = [p for p in candidates if (distance := distance_km(stop['place'], p)) is not None and distance <= 15]
            if len(nearby) >= len(day['stops']) and any(p['id'] not in selected for p in nearby):
                return True
    return False


def protected_ids(candidates: list[dict], selected: set[str], explicit: list[str], constraints: str, must_visit: str) -> set[str]:
    protected = set(explicit) | {p['id'] for p in candidates if p.get('name') and p['name'] in constraints}
    for keyword in (part.strip() for part in must_visit.replace('，', ',').split(',')):
        if not keyword:
            continue
        matches = {p['id'] for p in candidates if p['id'] in selected and p.get('name') and (keyword in p['name'] or p['name'] in keyword)}
        # An unresolved alias must not cause a requested stop to be silently removed.
        if not matches:
            return protected | selected
        protected.update(matches)
    if any(term in constraints for term in ('必去','一定要去','必须去')) and not (protected & selected):
        return protected | selected
    return protected


def group_days(days: list[dict], constraints: str) -> list[dict]:
    # Explicit day/order requirements take priority over geographic grouping.
    if len(days) < 2 or DAY_CONSTRAINT.search(constraints) or any(stop.get('fixed_time') for day in days for stop in day['stops']):
        return days
    stops = [stop for day in days for stop in day['stops']]
    distances = {}
    for i, first in enumerate(stops):
        for second in stops[i+1:]:
            value = distance_km(first['place'], second['place'])
            if value is None:
                return days
            distances[frozenset((first['place']['id'], second['place']['id']))] = value
    groups = [day['stops'][:] for day in days]

    def pair_stats(group):
        pairs = [distances[frozenset((a['place']['id'], b['place']['id']))]
                 for i, a in enumerate(group) for b in group[i+1:]]
        return max(pairs, default=0), sum(pairs)

    def insert_stats(group, excluded, added, base):
        extra = [distances[frozenset((stop['place']['id'], added['place']['id']))]
                 for i, stop in enumerate(group) if i != excluded]
        return max(base[0], max(extra, default=0)), base[1] + sum(extra)

    # Keep every selected POI and the number of stops per day; only accept improvements.
    for _ in range(len(stops) * 2):
        stats = [pair_stats(group) for group in groups]
        without = [[pair_stats(group[:i] + group[i+1:]) for i in range(len(group))] for group in groups]
        best = (round(max((value[0] for value in stats), default=0), 5), round(sum(value[1] for value in stats), 5))
        swap = None
        for a in range(len(groups)):
            for b in range(a+1, len(groups)):
                other_span = max((value[0] for i, value in enumerate(stats) if i not in (a,b)), default=0)
                other_total = sum(value[1] for i, value in enumerate(stats) if i not in (a,b))
                for i in range(len(groups[a])):
                    for j in range(len(groups[b])):
                        left = insert_stats(groups[a], i, groups[b][j], without[a][i])
                        right = insert_stats(groups[b], j, groups[a][i], without[b][j])
                        candidate = (round(max(other_span, left[0], right[0]), 5), round(other_total + left[1] + right[1], 5))
                        if candidate < best:
                            best, swap = candidate, (a, b, i, j)
        if swap is None:
            break
        a, b, i, j = swap
        first, second = groups[a][i], groups[b][j]
        groups[a][i], groups[b][j] = {**second, 'reason':''}, {**first, 'reason':''}
    return [{**day, 'stops':group} for day, group in zip(days, groups)]
