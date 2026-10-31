"""Converts OBDb signal sets (https://github.com/OBDb, CC BY-SA 4.0) into PitLogger vehicle profiles.

    python tools/convert_obdb.py OBDB_DIR [OUT_DIR]

OBDB_DIR contains one git clone per OBDb repository (SAEJ1979, Hyundai, Hyundai-i30, ...). Files
are read from each clone's HEAD with `git archive`, so this also works where the checkout itself
fails (OBDb test file names contain characters Windows does not allow). OUT_DIR (default: the
repository root) receives profiles/ and tests/.

Needs PyYAML for the OBDb test cases.
"""
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from datetime import date, timezone, datetime

import yaml

FORMAT = "pitlogger-profile/1.0"
SKIP_REPOS = re.compile(r"^\.|\.obdb\.community$|^obdb\.community$")
MAKES_WITH_HYPHEN = ["Mercedes-Benz", "Alfa-Romeo", "Aston-Martin", "Land-Rover", "Rolls-Royce"]
MAKE_SETS_ALWAYS = {"NissanInfiniti": ["Nissan", "Infiniti"]}

# OBDb unit -> (unit symbol, extra signal fields)
UNITS = {
    "ampereHours": "Ah", "amps": "A", "bars": "bar", "celsius": "°C", "centimeters": "cm",
    "coulombs": "C", "degrees": "°", "fahrenheit": "°F", "feet": "ft", "framesPerSecond": "fps",
    "gallons": "gal", "gallonsPerHour": "gal/h", "gigahertz": "GHz", "gramsPerLiter": "g/L",
    "gramsPerSecond": "g/s", "gravity": "g", "hertz": "Hz", "hours": "h", "inches": "in",
    "inchPound": "in·lb", "joules": "J", "kelvin": "K", "kiloampereHours": "kAh", "kiloamps": "kA",
    "kilogramsPerHour": "kg/h", "kilohertz": "kHz", "kilojoules": "kJ", "kilometers": "km",
    "kilometersPerHour": "km/h", "kiloohms": "kΩ", "kilopascal": "kPa", "kilovolts": "kV",
    "kilowattHours": "kWh", "kilowattHoursPer100Kilometers": "kWh/100km",
    "kilowattHoursPer100Miles": "kWh/100mi", "kilowatts": "kW", "liters": "L",
    "litersPerHour": "L/h", "megahertz": "MHz", "megaohms": "MΩ", "meters": "m",
    "metersPerSecond": "m/s", "metersPerSecondSquared": "m/s²", "microhertz": "µHz",
    "microohms": "µΩ", "miles": "mi", "milesPerKilowattHour": "mi/kWh", "milesPerHour": "mph",
    "milliampereHours": "mAh", "milliamps": "mA", "milligramsPerDeciliter": "mg/dL",
    "milligramsPerStroke": "mg/stroke", "millihertz": "mHz", "millimeters": "mm",
    "milliohms": "mΩ", "milliseconds": "ms", "millivolts": "mV", "milliwatts": "mW",
    "minutes": "min", "nanohertz": "nHz", "newtonMeters": "Nm", "ohms": "Ω", "percent": "%",
    "poundFoot": "lb·ft", "psi": "psi", "radians": "rad", "rpm": "rpm", "seconds": "s",
    "terahertz": "THz", "volts": "V", "watts": "W", "yards": "yd",
}
LABELS = {"noyes": ["No", "Yes"], "yesno": ["Yes", "No"], "offon": ["Off", "On"], "onoff": ["On", "Off"]}
DISPLAY = {"hex": "hex", "ascii": "text"}
NO_UNIT = {"scalar", "unknown", "normal", None}


# ---------------- reading the OBDb clones ----------------

class Repo:
    """Files of one OBDb clone at HEAD, read without a checkout."""

    def __init__(self, path):
        self.name = os.path.basename(path)
        # protectNTFS off: the files are only read into memory, never written to disk
        git = ["git", "-c", "core.protectNTFS=false", "-C", path]
        self.revision = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True,
                                       check=True).stdout.strip()
        archive = subprocess.run(git + ["archive", "HEAD", "README.md", "generations.yaml",
                                        "signalsets", "tests/test_cases"],
                                 capture_output=True)
        if archive.returncode != 0:     # not every repo has every path
            archive = subprocess.run(git + ["archive", "HEAD"], capture_output=True, check=True)
        self.files = {}
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            for m in tar.getmembers():
                if m.isfile() and (m.name in ("README.md", "generations.yaml")
                                   or m.name.startswith(("signalsets/v3/", "tests/test_cases/"))):
                    self.files[m.name] = tar.extractfile(m).read().decode("utf-8")

    def json(self, name):
        return json.loads(self.files[name])

    def yaml(self, name):
        return yaml.safe_load(self.files[name])


def split_repo_name(name):
    for make in MAKES_WITH_HYPHEN:
        if name.startswith(make + "-"):
            return make, name[len(make) + 1:]
    if "-" in name:
        make, model = name.split("-", 1)
        return make, model
    return name, None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def display_names(repo, make, model):
    """Make and model as the README writes them ("# Hyundai IONIQ 5"), else from the repo name."""
    readme = repo.files.get("README.md", "")
    m = re.match(r"#\s*(.+)", readme.strip())
    title = m.group(1).strip() if m else ""
    make_name = make.replace("-", " ")
    if model is None:
        return make_name, None
    if title.lower().startswith(make_name.lower() + " "):
        return make_name, title[len(make_name) + 1:].strip()
    return make_name, model.replace("-", " ")


# ---------------- commands -> requests ----------------

def command_id(cmd):
    """The id OBDb gives a command; test files are named after it (schemas/python/can/signals.py)."""
    svc, param = next(iter(cmd["cmd"].items()))
    cid = cmd["hdr"] + ("." + cmd["rax"] if cmd.get("rax") else "") + "." + svc + param.upper()
    parts = []
    if cmd.get("tmo") and int(cmd["tmo"], 16):
        parts.append(f"t={int(cmd['tmo'], 16):02X}")
    if cmd.get("eax") and int(cmd["eax"], 16):
        parts.append(f"e={int(cmd['eax'], 16):02X}")
    if cmd.get("tst") and int(cmd["tst"], 16):
        parts.append(f"ta={int(cmd['tst'], 16):02X}")
    if cmd.get("fcm1"):
        parts.append("fc=1")
    if cmd.get("pri") and int(cmd["pri"], 16):
        parts.append(f"c={int(cmd['pri'], 16):02X}")
    if cmd.get("filter"):
        parts.append("f=" + filter_id(cmd["filter"]))
    if "din" in cmd:
        parts.append(f"din={int(cmd['din'], 16):02X}")
    if "dout" in cmd:
        parts.append(f"dout={int(cmd['dout'], 16):02X}")
    if "baud" in cmd:
        parts.append(f"b={cmd['baud']}")
    if "init" in cmd:
        parts.append(f"fi={cmd['init']['lo']}-{cmd['init']['hi']}")
    return cid + ("|" + ",".join(parts) if parts else "")


def filter_id(f):
    parts = []
    lo, hi = f.get("from"), f.get("to")
    if lo is not None and hi is not None and lo < hi:
        parts.append(f"{lo}-{hi}")
    else:
        if lo is not None:
            parts.append(f"{lo}-")
        if hi is not None:
            parts.append(f"-{hi}")
    parts += [str(y) for y in sorted(f.get("years") or [])]
    return ";".join(parts)


def year_range(f):
    if not f:
        return None
    out = {}
    for k in ("from", "to"):
        if f.get(k) is not None:
            out[k] = f[k]
    if f.get("years"):
        out["years"] = sorted(f["years"])
    return out


def bus_of(cmd):
    proto = cmd.get("proto")
    if proto == "9141-2":
        return "kline-9141"
    if proto == "14230":
        return "kline-14230"
    return "can29" if len(cmd["hdr"]) == 4 else "can11"


def addresses(cmd, bus):
    """tx, rx and rxMask as full CAN IDs (SPEC.md 5.2; OBDb rules in signals.py Command.from_json)."""
    hdr, rax = cmd["hdr"].upper(), cmd.get("rax", "").upper()
    if bus != "can29":
        return hdr, rax or None, None
    pri = int(cmd["pri"], 16) if "pri" in cmd else None
    tester = cmd.get("tst", "F1").upper()
    tx = f"{pri if pri is not None else 0x18:02X}{hdr}{tester}"
    if not rax:
        return tx, None, None
    value = int(rax, 16)
    if value > 0xFFFFFF:
        return tx, f"{value & 0x1FFFFFFF:08X}", None
    if value <= 0xFF:
        return tx, f"{(((pri or 0x18) & 0x1F) << 24) | 0xDAF100 | value:08X}", None
    if pri is not None:
        return tx, f"{(pri << 24) | value:08X}", None
    return tx, f"{value:08X}", "00FFFFFF"


def convert_signal(s):
    fmt = s["fmt"]
    out = {"id": s["id"], "name": s["name"]}
    if s.get("description"):
        out["description"] = s["description"]
    if s.get("path"):
        out["group"] = s["path"]
    if s.get("hidden"):
        out["hidden"] = True
    if s.get("suggestedMetric"):
        out["metric"] = s["suggestedMetric"]
    out["bit"] = fmt.get("bix", 0)
    out["bits"] = fmt["len"]
    if fmt.get("blsb"):
        out["byteOrder"] = "little"
    if fmt.get("sign"):
        out["signed"] = True
    if "map" in fmt:
        out["values"] = {}
        descriptions = {}
        for raw, v in fmt["map"].items():
            if isinstance(v, dict):
                out["values"][str(raw)] = v["value"]
                if v.get("description"):
                    descriptions[str(raw)] = v["description"]
            else:
                out["values"][str(raw)] = str(v)
        if descriptions:
            out["valueDescriptions"] = descriptions
        return out
    for src, dst in (("mul", "multiply"), ("div", "divide"), ("add", "add")):
        if src in fmt:
            out[dst] = fmt[src]
    out["min"] = fmt.get("min", 0)
    out["max"] = fmt["max"]
    unit = fmt.get("unit")
    if unit in UNITS:
        out["unit"] = UNITS[unit]
    elif unit in LABELS:
        out["labels"] = LABELS[unit]
    elif unit in DISPLAY:
        out["display"] = DISPLAY[unit]
    elif unit not in NO_UNIT:
        raise ValueError(f"unknown OBDb unit {unit!r} in {s['id']}")
    if "nullmin" in fmt:
        out["invalidAtOrBelow"] = fmt["nullmin"]
    if "nullmax" in fmt:
        out["invalidAtOrAbove"] = fmt["nullmax"]
    optimal = {k: fmt[o] for o, k in (("omin", "min"), ("omax", "max"), ("oval", "value")) if o in fmt}
    if optimal:
        out["optimal"] = optimal
    return out


def convert_command(cmd, generic=False):
    svc, param = next(iter(cmd["cmd"].items()))
    bus = "obd" if generic else bus_of(cmd)
    req = {"id": command_id(cmd), "bus": bus}
    if not generic:
        tx, rx, mask = addresses(cmd, bus)
        req["tx"] = tx
        if rx:
            req["rx"] = rx
        if mask:
            req["rxMask"] = mask
    if cmd.get("eax"):
        req["extendedAddress"] = cmd["eax"].upper()
    req["request"] = (svc + param).upper()
    req["interval"] = cmd["freq"]
    if "tmo" in cmd:
        req["timeout"] = round(int(cmd["tmo"], 16) * 0.004, 3)   # ELM327 AT ST units of 4 ms
    if cmd.get("fcm1"):
        req["flowControl"] = True
    if "tst" in cmd:
        req["tester"] = cmd["tst"].upper()
    if "din" in cmd or "dout" in cmd:
        req["session"] = {k: cmd[o].upper() for o, k in (("din", "enter"), ("dout", "exit")) if o in cmd}
    if "baud" in cmd or "init" in cmd:
        req["kline"] = {}
        if "baud" in cmd:
            req["kline"]["baud"] = cmd["baud"]
        if "init" in cmd:
            req["kline"]["fastInit"] = {"low": cmd["init"]["lo"], "high": cmd["init"]["hi"]}
    if cmd.get("filter"):
        req["years"] = year_range(cmd["filter"])
    req["signals"] = [convert_signal(s) for s in cmd["signals"]]
    return req


def convert_ecu(e):
    out = {"tx": e["hdr"].upper()}
    if "rax" in e:
        out["rx"] = e["rax"].upper()
    if "eax" in e:
        out["extendedAddress"] = e["eax"].upper()
    if "filter" in e:
        out["years"] = year_range(e["filter"])
    out["type"] = e["type"]
    return out


def convert_group(g):
    out = {"id": g["id"]}
    for src, dst in (("name", "name"), ("path", "group"), ("matchingRegex", "match"),
                     ("suggestedMetricGroup", "metric")):
        if src in g:
            out[dst] = g[src]
    return out


def convert_synthetic(s):
    out = {"id": s["id"], "name": s["name"], "group": s["path"], "min": s.get("min", 0), "max": s["max"]}
    if s["unit"] in UNITS:
        out["unit"] = UNITS[s["unit"]]
    if s.get("suggestedMetric"):
        out["metric"] = s["suggestedMetric"]
    f = dict(s["formula"])
    if f["op"] == "unit":
        f["units"] = {k: UNITS.get(v, v) for k, v in f["units"].items()}
    out["formula"] = f
    return out


# ---------------- signal set files and test cases ----------------

def file_years(filename):
    """Year range of a signal set file name: default.json -> None, 2005-2018.json, 0000-2004.json."""
    m = re.match(r"(\d{4})-(\d{4})\.json$", filename)
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    rng = {}
    if lo > 0:
        rng["from"] = lo
    if hi < 9999:
        rng["to"] = hi
    return rng


def suffix(rng):
    if not rng:
        return ""
    return f"@{rng.get('from', '')}-{rng.get('to', '')}"


def signalset_for_year(sets, year):
    """OBDb's choice (signalsets/loader.py): narrowest range containing the year, else default."""
    ranged = [(name, r) for name, r in sets.items() if r]
    hits = [(name, r) for name, r in ranged
            if r.get("from", 0) <= year <= r.get("to", 9999)]
    if hits:
        hits.sort(key=lambda h: h[1].get("to", 9999) - h[1].get("from", 0))
        return hits[0][0]
    return "default.json" if "default.json" in sets else None


def support_lists(repo):
    """{command id: ([years answered], [years not answered])} from command_support.yaml files."""
    out = {}
    for name, text in repo.files.items():
        m = re.match(r"tests/test_cases/(\d{4})/command_support\.yaml$", name)
        if not m:
            continue
        year = int(m.group(1))
        data = yaml.safe_load(text) or {}
        for key, slot in (("supported_commands_by_ecu", 0), ("unsupported_commands_by_ecu", 1)):
            for ids in (data.get(key) or {}).values():
                for entry in ids or []:
                    cid = str(entry).split(":", 1)[0]
                    out.setdefault(cid, ([], []))[slot].append(year)
    return out


def frame_text(line, id_digits):
    line = re.sub(r"\s+", "", line)
    data = line[id_digits:]
    return line[:id_digits] + " " + " ".join(data[i:i + 2] for i in range(0, len(data), 2))


def test_cases(repo, commands_by_id):
    """[(year, case)] from tests/test_cases/<year>/commands/<command id>.yaml."""
    cases = []
    for name, text in sorted(repo.files.items()):
        m = re.match(r"tests/test_cases/(\d{4})/commands/[^/]+\.yaml$", name)
        if not m:
            continue
        data = yaml.safe_load(text) or {}
        cid = data.get("command_id")
        cmd = commands_by_id.get(cid)
        # 29-bit when the header has 4 digits; standard requests are named e.g. "DB33.0101"
        header = cmd["hdr"] if cmd else str(cid).split(".")[0]
        id_digits = 8 if len(header) == 4 else 3
        extended = bool(cmd and cmd.get("eax"))
        for tc in data.get("test_cases") or []:
            lines = [l for l in (re.sub(r"\s+", "", l) for l in str(tc["response"]).split("\n"))
                     if re.fullmatch(r"[0-9A-Fa-f]+", l) and len(l) > id_digits
                     and (len(l) - id_digits) % 2 == 0]       # drops adapter text like "NO DATA"
            case = {"year": int(m.group(1)), "request": cid,
                    "frames": [frame_text(l, id_digits) for l in lines],
                    "expect": tc["expected_values"]}
            if extended:
                case["extendedAddressing"] = True
            cases.append((int(m.group(1)), case))
    return cases


# ---------------- main ----------------

def generations(repo):
    if "generations.yaml" not in repo.files:
        return None
    gens = []
    for g in (repo.yaml("generations.yaml") or {}).get("generations") or []:
        entry = {"name": g["name"]}
        for k, dst in (("start_year", "from"), ("end_year", "to")):
            v = g.get(k)
            m = re.search(r"\d{4}", str(v)) if v is not None else None
            if m:
                entry[dst] = int(m.group(0))
        gens.append(entry)
    return gens or None


def dumps(value, depth, inline_depth, indent="  "):
    """JSON with nesting down to inline_depth spread over lines and everything deeper on one line,
    so that a signal or a test case reads as one line. Short objects stay on one line as well."""
    compact = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    if depth >= inline_depth or not isinstance(value, (dict, list)) or len(compact) <= 72:
        return compact
    pad, inner = indent * depth, indent * (depth + 1)
    if isinstance(value, dict):
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {dumps(v, depth + 1, inline_depth)}"
                 for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    items = [inner + dumps(v, depth + 1, inline_depth) for v in value]
    return "[\n" + ",\n".join(items) + "\n" + pad + "]"


def write_json(path, data, inline_depth):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(data, 0, inline_depth) + "\n")


def convert_repo(repo, out_dir, index):
    make, model = split_repo_name(repo.name)
    generic = repo.name == "SAEJ1979"
    make_name, model_name = display_names(repo, make, model)
    sets = {n.split("/")[-1]: file_years(n.split("/")[-1])
            for n in repo.files if re.match(r"signalsets/v3/[^/]+\.json$", n)}
    if not sets:
        return
    support = support_lists(repo)
    all_commands = {}
    profiles = {}
    for filename, rng in sorted(sets.items()):
        data = repo.json("signalsets/v3/" + filename)
        if generic:
            kind, pid = "generic", "generic/sae-j1979"
        elif model is None:
            kind, pid = "make", f"makes/{slug(make)}"
        else:
            kind, pid = "vehicle", f"vehicles/{slug(make)}/{slug(model)}"
        pid += suffix(rng)
        profile = {"format": FORMAT, "id": pid, "kind": kind}
        if kind == "make":
            # OBDb adds the Nissan/Infiniti set to every vehicle of both makes; other make sets
            # only stand in for models without their own commands
            shared = MAKE_SETS_ALWAYS.get(repo.name)
            profile["use"] = "always" if shared else "fallback"
            vehicle = {"makes": shared or [make_name]}
        elif kind == "vehicle":
            vehicle = {"make": make_name, "model": model_name}
        if kind != "generic":
            vehicle["years"] = rng
            gens = generations(repo)
            if gens:
                vehicle["generations"] = gens
            profile["vehicle"] = vehicle
        if "diagnosticLevel" in data:
            profile["diagnosticSession"] = data["diagnosticLevel"].upper()
        profile["source"] = {
            "name": "OBDb", "url": f"https://github.com/OBDb/{repo.name}",
            "file": "signalsets/v3/" + filename, "revision": repo.revision,
            "license": "CC-BY-SA-4.0", "attribution": "OBDb contributors, https://obdb.community",
        }
        if data.get("ecu"):
            profile["ecus"] = [convert_ecu(e) for e in data["ecu"]]
        requests = []
        for cmd in data["commands"]:
            req = convert_command(cmd, generic)
            signals = req.pop("signals")
            if req["id"] in support:
                answered, missing = support[req["id"]]
                if answered:
                    req["answeredIn"] = sorted(set(answered))
                if missing:
                    req["notAnsweredIn"] = sorted(set(missing))
            req["signals"] = signals
            requests.append(req)
            all_commands[req["id"]] = cmd
        profile["requests"] = requests
        if data.get("signalGroups"):
            profile["groups"] = [convert_group(g) for g in data["signalGroups"]]
        if data.get("synthetics"):
            profile["computed"] = [convert_synthetic(s) for s in data["synthetics"]]
        profiles[filename] = profile

    tests = {}
    for year, case in test_cases(repo, all_commands):
        filename = signalset_for_year(sets, year)
        if filename:
            tests.setdefault(filename, []).append(case)

    for filename, profile in profiles.items():
        write_json(os.path.join(out_dir, "profiles", profile["id"] + ".json"), profile, 4)
        cases = tests.get(filename, [])
        if cases:
            write_json(os.path.join(out_dir, "tests", profile["id"] + ".json"),
                       {"format": "pitlogger-profile-tests/1.0", "profile": profile["id"], "cases": cases}, 2)
        index.append(index_entry(profile, len(cases)))


def index_entry(profile, tests):
    entry = {"id": profile["id"], "kind": profile["kind"]}
    if "use" in profile:
        entry["use"] = profile["use"]
    if "vehicle" in profile:
        entry.update({k: profile["vehicle"][k] for k in ("make", "makes", "model") if k in profile["vehicle"]})
        entry["years"] = profile["vehicle"]["years"]
    entry["requests"] = len(profile["requests"])
    entry["signals"] = sum(len(r["signals"]) for r in profile["requests"])
    entry["tests"] = tests
    return entry


def existing_profiles(out_dir):
    """{profile id: profile} of the profiles already on disk."""
    found = {}
    root = os.path.join(out_dir, "profiles")
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name == "index.json" or not name.endswith(".json"):
                continue
            with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                profile = json.load(f)
            found[profile["id"]] = profile
    return found


def keep_or_remove_old(out_dir, old, index, converted_repos):
    """Profiles from a previous run that were not written this time.

    If their OBDb repository was converted, the source dropped them: remove. If the repository is
    gone (deleted upstream, or the clone failed), keep them – this archive must outlive its source –
    and mark them in the index."""
    written = {e["id"] for e in index}
    kept = 0
    for pid, profile in old.items():
        if pid in written:
            continue
        repo = profile.get("source", {}).get("url", "").rsplit("/", 1)[-1]
        test_path = os.path.join(out_dir, "tests", pid + ".json")
        if repo in converted_repos:
            os.remove(os.path.join(out_dir, "profiles", pid + ".json"))
            if os.path.exists(test_path):
                os.remove(test_path)
            continue
        tests = 0
        if os.path.exists(test_path):
            with open(test_path, encoding="utf-8") as f:
                tests = len(json.load(f)["cases"])
        entry = index_entry(profile, tests)
        entry["sourceMissing"] = True
        index.append(entry)
        kept += 1
    return kept


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    obdb_dir = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    old = existing_profiles(out_dir)
    index, failed, converted = [], [], set()
    for name in sorted(os.listdir(obdb_dir)):
        path = os.path.join(obdb_dir, name)
        if SKIP_REPOS.search(name) or not os.path.isdir(os.path.join(path, ".git")):
            continue
        try:
            convert_repo(Repo(path), out_dir, index)
            converted.add(name)
        except Exception as e:                      # one broken repo must not stop the others
            failed.append(f"{name}: {e}")
    kept = keep_or_remove_old(out_dir, old, index, converted)
    index.sort(key=lambda e: e["id"])
    write_json(os.path.join(out_dir, "profiles", "index.json"), {
        "format": "pitlogger-profile-index/1.0",
        "generated": datetime.now(timezone.utc).date().isoformat(),
        "profiles": index,
    }, 2)
    print(f"{len(index)} profiles, {sum(e['signals'] for e in index)} signals, "
          f"{sum(e['tests'] for e in index)} test cases, {kept} kept without source")
    for f in failed:
        print("FAILED", f)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
