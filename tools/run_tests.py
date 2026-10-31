"""Decodes every recorded answer in tests/ with its profile and compares the values.

    python tools/run_tests.py [--verbose] [--update-known] [profile id ...]

Some OBDb test cases do not match OBDb's own current signal sets (a test for a command that was
changed or removed since). Those are listed in tests/known-failures.json; only failures not in
that list count. --update-known rewrites the list from the current run.

Exit code 1 if a case fails that is not a known failure.
"""
import hashlib
import json
import os
import sys

import pitprofile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = os.path.join(ROOT, "profiles")
TESTS = os.path.join(ROOT, "tests")
KNOWN = os.path.join(TESTS, "known-failures.json")


def case_key(profile_id, case):
    """Stable name of a test case, independent of its position in the file."""
    digest = hashlib.sha1("\n".join(case["frames"]).encode()).hexdigest()[:10]
    return f"{profile_id} {case['year']} {case['request']} {digest}"


def load_profile(pid):
    return pitprofile.load(os.path.join(PROFILES, pid + ".json"))


def layers(profile, index):
    """Profiles a logger combines for this one (SPEC.md section 2), generic first."""
    out = [load_profile(e["id"]) for e in index if e["kind"] == "generic"]
    if profile["kind"] != "vehicle":
        return out + [profile]
    make = profile["vehicle"]["make"]
    makes = [e for e in index if e["kind"] == "make" and make in e.get("makes", [])]
    out += [load_profile(e["id"]) for e in makes if e.get("use") == "always"]
    if profile["requests"]:
        return out + [profile]
    return out + [load_profile(e["id"]) for e in makes if e.get("use") == "fallback"]


def same(actual, expected):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(actual - expected) < 1e-5
    return actual == expected or (actual is not None and str(actual) == str(expected))


def main():
    verbose = "--verbose" in sys.argv
    update_known = "--update-known" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    with open(os.path.join(PROFILES, "index.json"), encoding="utf-8") as f:
        index = json.load(f)["profiles"]
    known = set()
    if os.path.exists(KNOWN) and not update_known:
        with open(KNOWN, encoding="utf-8") as f:
            known = set(json.load(f)["cases"])
    total = failed = known_failed = 0
    failed_profiles = {}
    failures = []
    for dirpath, _, files in os.walk(TESTS):
        for name in sorted(files):
            path = os.path.join(dirpath, name)
            if path == KNOWN:
                continue
            with open(path, encoding="utf-8") as f:
                suite = json.load(f)
            if only and suite["profile"] not in only:
                continue
            stack = layers(load_profile(suite["profile"]), index)
            decoders = {}
            for i, case in enumerate(suite["cases"]):
                year = case["year"]
                decoder = decoders.setdefault(year, pitprofile.Decoder(stack, year))
                values = {}
                for can_id, payload in pitprofile.reassemble(case["frames"], case.get("extendedAddressing", False)):
                    values.update(decoder.decode(can_id, payload))
                wrong = {k: (values.get(k, "missing"), v) for k, v in case["expect"].items()
                         if not same(values.get(k, "missing"), v)}
                total += 1
                if not wrong:
                    continue
                key = case_key(suite["profile"], case)
                failures.append(key)
                if key in known:
                    known_failed += 1
                    continue
                failed += 1
                failed_profiles[suite["profile"]] = failed_profiles.get(suite["profile"], 0) + 1
                if verbose:
                    print(f"FAIL {suite['profile']} case {i} ({case['request']}, {year}): "
                          + ", ".join(f"{k} got {a} expected {e}" for k, (a, e) in wrong.items()))
    if update_known:
        with open(KNOWN, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"note": "OBDb test cases that do not match OBDb's own current signal sets",
                       "cases": sorted(failures)}, f, indent=1)
            f.write("\n")
        print(f"{len(failures)} known failures written")
        return
    for pid, n in sorted(failed_profiles.items(), key=lambda x: -x[1]):
        print(f"{n:6d} failed  {pid}")
    print(f"{total - failed - known_failed} of {total} cases passed, {known_failed} known failures, "
          f"{failed} new failures")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
