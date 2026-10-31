# PitLogger vehicle profiles

Open, human-readable descriptions of the diagnostic data that vehicles provide: which request to
send to which module, and how to turn the answer into a value with a unit. One JSON file per
vehicle model, usable by the [PitLogger](https://github.com/PitLogger) and by any other program.

| | |
|---|---|
| Profiles | 889 (1 generic OBD-II, makes, models) |
| Signals | ~249,000 |
| Recorded test answers | ~600,000, 99.9 % decode exactly as recorded |
| Format | [SPEC.md](SPEC.md) · [JSON Schema](schema/profile.schema.json) |

## Example

`profiles/vehicles/hyundai/i30.json`, one request to the ABS module:

```json
{
  "id": "7D1.7D9.220104",
  "bus": "can11",
  "tx": "7D1",
  "rx": "7D9",
  "request": "220104",
  "interval": 1,
  "answeredIn": [2017, 2019, 2020, 2021, 2022, 2023],
  "signals": [
    {"id": "I30_TIRE_FL_VSS", "name": "Front left wheel speed", "group": "Movement", "bit": 88, "bits": 8, "min": 0, "max": 255, "unit": "km/h"},
    {"id": "I30_STEER_ANGLE", "name": "Steering wheel angle", "group": "Control", "bit": 200, "bits": 16, "signed": true, "divide": 10, "min": -3276.8, "max": 3276.7, "unit": "°"},
    {"id": "I30_BRAKE_P", "name": "Brake pressure", "group": "Control", "bit": 256, "bits": 16, "signed": true, "divide": 86.7, "min": 0, "max": 100, "unit": "%"}
  ]
}
```

Send `22 01 04` to CAN ID `7D1`, wait for the answer from `7D9`, skip `62 01 04`, and read the
steering angle from bits 200–215 as a signed number divided by 10.

## Layout

```
profiles/index.json        all profiles with make, model, years and counts
profiles/generic/          standard OBD-II (SAE J1979)
profiles/makes/            requests shared by a make
profiles/vehicles/<make>/  one file per model, "@2015-2020" for year-specific variants
tests/                     recorded answers and the values they must decode to
schema/                    JSON Schema of the format
tools/                     converter, reference decoder, test runner
```

## Source and license

The profiles are generated from [OBDb](https://github.com/OBDb), the community database of vehicle
diagnostic parameters, and keep its license: **[CC BY-SA 4.0](LICENSE)** – free to use, share and
adapt, also commercially, with attribution and under the same license. Every profile names the
exact OBDb repository and revision it was generated from. Thanks to all OBDb contributors.

A [weekly job](.github/workflows/sync.yml) regenerates the profiles from the current OBDb data and
commits changes. Profiles whose source repository disappears are kept and marked
`"sourceMissing": true` in the index, so this archive stays complete on its own.

The tools in [tools/](tools/) are under the [MIT license](tools/LICENSE).

## Tools

```bash
pip install -r tools/requirements.txt
python tools/validate.py          # every profile against the schema
python tools/run_tests.py         # decode all recorded answers
python tools/convert_obdb.py DIR  # regenerate from OBDb clones in DIR
```

[`tools/pitprofile.py`](tools/pitprofile.py) is a small reference decoder without dependencies:

```python
import pitprofile
profile = pitprofile.load("profiles/vehicles/hyundai/i30.json")
decoder = pitprofile.Decoder([profile], year=2021)
answer = ["7D9 10 2C 62 01 04 FB C7 FF", "7D9 21 98 0F EC 04 00 04 E1", "7D9 22 FF 04 05 04 04 FC FF",
          "7D9 23 FF 00 F0 05 FC 00 00", "7D9 24 00 FF B7 F5 FF F3 00", "7D9 25 00 00 00 7F FF 7F FF",
          "7D9 26 FC 00 06 AA AA AA AA"]
for can_id, payload in pitprofile.reassemble(answer):
    print(decoder.decode(can_id, payload))
# {'I30_VSS_AVG': 4.0, 'I30_TIRE_FL_VSS': 4.0, 'I30_TIRE_FR_VSS': 5.0, ..., 'I30_STEER_ANGLE': -7.3, 'I30_BRAKE_P': 0}
```

Some OBDb test answers no longer match OBDb's own current definitions; they are listed in
[tests/known-failures.json](tests/known-failures.json) and do not fail the check.

## Contributing

Corrections to signals belong to OBDb, so that everyone benefits – open an issue or pull request
in the vehicle's OBDb repository; the change arrives here with the next weekly sync. Issues with
the format, the converter or the tools belong here.
