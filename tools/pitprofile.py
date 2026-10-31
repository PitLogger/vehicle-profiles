"""Reference decoder for PitLogger vehicle profiles (SPEC.md).

Pure Python 3.9+, no dependencies. Used by the test runner and as an executable description of
the rules in SPEC.md sections 4.1, 5 and 6.
"""
import json
import sys

FORMAT = "pitlogger-profile/1.0"


def load(path):
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    major = profile.get("format", "").split("/")[-1].split(".")[0]
    if major != FORMAT.split("/")[-1].split(".")[0]:
        raise ValueError(f"{path}: unsupported format {profile.get('format')!r}")
    return profile


# ---------------- 4.1 Year range ----------------

def year_matches(rng, year):
    """True if the model year lies in the range. None (no range) matches every year."""
    if rng is None or year is None:
        return True
    lo, hi = rng.get("from"), rng.get("to")
    if lo is not None and hi is not None:
        if lo < hi and lo <= year <= hi:
            return True
        if lo >= hi and (year >= lo or year <= hi):
            return True
    elif hi is not None and year <= hi:
        return True
    elif lo is not None and year >= lo:
        return True
    return year in rng.get("years", [])


# ---------------- 6.1 / 6.2 Signals ----------------

def extract_raw(data, bit, bits, little=False):
    if bit + bits > len(data) * 8:
        return None
    if little and bits > 8:
        first = bit // 8
        count = (bits + 7) // 8
        data = bytearray(data)
        data[first:first + count] = reversed(data[first:first + count])
    raw = 0
    for i in range(bit, bit + bits):
        raw = (raw << 1) | ((data[i // 8] >> (7 - i % 8)) & 1)
    return raw


def decode_signal(sig, data):
    """Value of a signal in the data bytes of an answer: number, text or None (no value)."""
    raw = extract_raw(data, sig["bit"], sig["bits"], sig.get("byteOrder") == "little")
    if raw is None:
        return None
    if sig.get("signed") and raw & (1 << (sig["bits"] - 1)):
        raw -= 1 << sig["bits"]
    if "values" in sig:
        return sig["values"].get(str(raw))
    value = raw * sig.get("multiply", 1) / sig.get("divide", 1) + sig.get("add", 0)
    lo, hi = sig.get("min", 0), sig["max"]
    if hi > lo:
        value = max(lo, min(value, hi))
    eps = sys.float_info.epsilon
    if "invalidAtOrBelow" in sig and value <= sig["invalidAtOrBelow"] + eps:
        return None
    if "invalidAtOrAbove" in sig and value >= sig["invalidAtOrAbove"] - eps:
        return None
    return value


# ---------------- 5.1 Answers ----------------

def reassemble(frames, extended=False):
    """ISO-TP messages from CAN frames written as "7E8 10 14 49 02 ...".

    Returns a list of (can_id, payload). Frames of several modules may be interleaved.
    """
    partial = {}
    messages = []
    for line in frames:
        parts = line.split()
        try:
            can_id, data = parts[0].upper(), bytes(int(b, 16) for b in parts[1:])
        except (ValueError, IndexError):                # adapter text such as "NO DATA"
            continue
        if extended:
            data = data[1:]
        if not data:
            continue
        kind = data[0] >> 4
        if kind == 0:                                   # single frame
            messages.append((can_id, data[1:1 + (data[0] & 0x0F)]))
        elif kind == 1 and len(data) >= 2:              # first frame
            size = ((data[0] & 0x0F) << 8) | data[1]
            partial[can_id] = (bytearray(data[2:]), size)
        elif kind == 2 and can_id in partial:           # consecutive frame
            buf, size = partial[can_id]
            buf += data[1:]
            if len(buf) >= size:
                messages.append((can_id, bytes(buf[:size])))
                del partial[can_id]
    return messages


def rx_matches(req, can_id):
    if "rx" not in req:
        return False
    if "rxMask" in req:
        mask = int(req["rxMask"], 16)
        return int(can_id, 16) & mask == int(req["rx"], 16) & mask
    return req["rx"] == can_id


class Decoder:
    """Finds the request an answer belongs to and decodes its signals.

    Requests are taken in layer order (generic first, then vehicle); among requests with the same
    service and identifier, one whose rx matches the answer wins, the most recently listed first;
    otherwise every request without rx decodes the answer.
    """

    def __init__(self, profiles, year=None):
        self.by_key = {}
        for profile in profiles:
            for req in profile["requests"]:
                if not year_matches(req.get("years"), year):
                    continue
                key = req["request"][:2], req["request"][2:]
                self.by_key.setdefault(key, []).append(req)

    def decode(self, can_id, payload):
        if not payload or payload[0] < 0x40:
            return {}
        service = f"{payload[0] - 0x40:02X}"
        width = 2 if service == "22" else 1             # identifier bytes echoed in the answer
        ident = payload[1:1 + width].hex().upper()
        data = payload[1 + width:]
        candidates = list(reversed(self.by_key.get((service, ident), [])))
        matching = [r for r in candidates if rx_matches(r, can_id)]
        chosen = matching[:1] or [r for r in candidates if "rx" not in r]
        if service == "01":
            chosen = chosen[:1]
        values = {}
        for req in chosen:
            for sig in req["signals"]:
                values[sig["id"]] = decode_signal(sig, data)
        return values
