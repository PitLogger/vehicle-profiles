"""Checks every profile against schema/profile.schema.json and the rules a schema cannot express.

    python tools/validate.py

Needs the jsonschema package.
"""
import json
import os
import sys

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(ROOT, "schema", "profile.schema.json"), encoding="utf-8") as f:
        validator = jsonschema.Draft202012Validator(json.load(f))
    errors = count = 0
    for dirpath, _, files in os.walk(os.path.join(ROOT, "profiles")):
        for name in files:
            if name == "index.json":
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as f:
                profile = json.load(f)
            count += 1
            problems = [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(profile)]
            rel = os.path.relpath(path, os.path.join(ROOT, "profiles")).replace(os.sep, "/")
            if profile.get("id") + ".json" != rel:
                problems.append(f"id {profile.get('id')!r} does not match the file name")
            seen = set()
            for req in profile.get("requests", []):
                if req["id"] in seen:
                    problems.append(f"request id {req['id']} twice")
                seen.add(req["id"])
            for p in problems[:5]:
                print(f"{rel}: {p}")
            errors += bool(problems)
    print(f"{count - errors} of {count} profiles valid")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
