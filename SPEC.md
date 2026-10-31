# PitLogger vehicle profiles

**Version 1.0 – draft.** Until 1.0 is final, details may still change.

A vehicle profile tells a data logger which diagnostic requests a vehicle answers and how to turn
the answers into values: which bytes, which formula, which unit. Profiles are plain JSON so that
people can read, review and edit them, and so that any program can use them without a special
library. This document describes the format completely.

## 1. Design goals

1. **Readable.** Field names are words, not abbreviations. Addresses and requests are written in
   hexadecimal as they appear on the bus.
2. **Self-contained.** A profile states every value a decoder needs. Nothing depends on defaults
   hidden in an application.
3. **Transport-neutral.** The same profile works over a direct CAN connection and over an ELM327
   adapter.
4. **Traceable.** Every profile names its source, the exact revision it was generated from and its
   license.
5. **Extensible.** Readers ignore fields they do not know. A new minor version only adds fields.

## 2. Files and layering

```
profiles/
  index.json                 list of all profiles (section 9)
  generic/sae-j1979.json     standard OBD-II requests every vehicle may answer
  makes/hyundai.json         requests shared by a whole make
  vehicles/hyundai/i30.json  requests of one model
  vehicles/ford/f-150@2015-2020.json   a model with a separate profile for some years
```

A logger combines profiles for a vehicle in this order:

1. every **generic** profile,
2. every **make** profile with `"use": "always"` whose `vehicle.makes` contains the vehicle's make,
3. the **vehicle** profile – or, if there is none or it has no requests, the make profiles with
   `"use": "fallback"` for that make.

When an answer fits requests of several layers, the rules of section 5.5 decide.

File and directory names are lower case; spaces become `-`. A suffix `@FROM-TO` (or `@FROM-`,
`@-TO`) marks a profile that applies only to those model years. Among the profiles of one model,
a logger uses the one with the narrowest year range that contains the vehicle's model year and
otherwise the one without a suffix.

Profiles are encoded as UTF-8 without byte order mark.

## 3. Top level

```json
{
  "format": "pitlogger-profile/1.0",
  "id": "vehicles/hyundai/i30",
  "kind": "vehicle",
  "vehicle": { "make": "Hyundai", "model": "i30", "years": null },
  "source": { ... },
  "ecus": [ ... ],
  "requests": [ ... ],
  "groups": [ ... ],
  "computed": [ ... ]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `format` | string | yes | `pitlogger-profile/MAJOR.MINOR`. Readers reject an unknown major version. |
| `id` | string | yes | Path of the file below `profiles/` without `.json`. |
| `kind` | string | yes | `generic`, `make` or `vehicle`. |
| `use` | string | for `make` | `always` or `fallback` (section 2). |
| `vehicle` | object | for `make`, `vehicle` | Vehicle profiles: `make`, `model`; make profiles: `makes` (list of make names). Both: `years` (a [year range](#41-year-range) or `null` for all years) and optionally `generations` (`name`, `from`, `to`). |
| `diagnosticSession` | hex string | no | Diagnostic session the vehicle's modules must be in, e.g. `"03"` (section 5.4). |
| `source` | object | yes | Where the data comes from (section 8). |
| `ecus` | array | no | Names the modules behind addresses (section 7). |
| `requests` | array | yes | Requests and the signals in their answers (section 5). |
| `groups` | array | no | Signals presented together (section 7). |
| `computed` | array | no | Values calculated from other signals (section 7). |

## 4. Conventions

| Item | Rule |
|---|---|
| Hex strings | Upper case, no `0x` prefix, no spaces: `"7E0"`, `"22BC03"` |
| Bit positions | Bit 0 is the most significant bit of the first data byte (section 6.1) |
| Times | Seconds as JSON numbers, may have a fraction |
| Missing optional fields | Mean "not set", never a hidden default unless this document gives one |

### 4.1 Year range

```json
{ "from": 2017, "to": 2020, "years": [2014] }
```

All fields are optional. A model year matches when it lies in `from`…`to` (both inclusive; an
open side has no limit) **or** is listed in `years`. If `from` is greater than `to`, the range
wraps: years `>= from` or `<= to` match. An object without `from` and `to` matches only the
listed `years`.

## 5. Requests

```json
{
  "id": "770.778.22BC03",
  "bus": "can11",
  "tx": "770",
  "rx": "778",
  "request": "22BC03",
  "interval": 1,
  "years": { "from": 2012 },
  "answeredIn": [2017, 2019, 2020, 2021],
  "notAnsweredIn": [2009, 2011],
  "signals": [ ... ]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique within the profile. Generated profiles use the source's command id. |
| `bus` | string | yes | `can11` (11-bit CAN, ISO 15765-4), `can29` (29-bit CAN), `kline-9141` (ISO 9141-2), `kline-14230` (ISO 14230 / KWP2000) or `obd` (section 5.6). |
| `tx` | hex string | not for `obd` | CAN ID the request is sent to (3 digits on `can11`, 8 on `can29`). On K-line the header as the source writes it. |
| `rx` | hex string | no | CAN ID of the answer. Missing: accept the answer from any module (functional request). |
| `rxMask` | hex string | no | Only these bits of the answer's ID are compared with `rx` (`can29` only). |
| `extendedAddress` | hex string | no | ISO 15765-2 extended addressing: this byte is put in front of every request frame; answers carry their own address byte in front, which is removed before decoding. |
| `request` | hex string | yes | Request bytes, service first: `22BC03` = ReadDataByIdentifier `BC03`. |
| `interval` | number | yes | Suggested seconds between two requests. A logger may ask less often if the bus is busy, and more often if its user asks for it (e.g. for track sessions). |
| `timeout` | number | no | Seconds to wait for the answer. Missing: the logger's default. (OBDb states it in ELM327 `AT ST` units of 4 ms; the converter writes seconds.) |
| `flowControl` | boolean | no | `true`: send ISO-TP flow control frames explicitly to `tx` (some modules need it for multi-frame answers; ELM327 `ATFCSM1`). |
| `tester` | hex string | no | Tester (source) address: on `can29` the low byte of `tx`, on K-line the source byte, with `extendedAddress` on CAN the address byte the answers carry. Default `F1`. |
| `session` | object | no | `enter` / `exit`: diagnostic session to enter before and leave after this request (section 5.4). |
| `kline` | object | no | K-line only: `baud` (bits/s) and `fastInit` `{ "low": ms, "high": ms }`. |
| `years` | [year range](#41-year-range) | no | The request exists only for these model years. Missing: all years of the profile. |
| `answeredIn` | array of years | no | Model years in which a real vehicle answered this request. |
| `notAnsweredIn` | array of years | no | Model years in which a real vehicle was asked and did not answer. |
| `signals` | array | yes | Values in the answer (section 6). |

A logger should prefer requests whose `answeredIn` contains the vehicle's model year and may skip
those whose `notAnsweredIn` contains it. Without either list nothing is known.

### 5.1 Answer

A positive answer starts with the request's service byte plus `0x40` followed by the request's
remaining bytes (the identifier) – for `22BC03` that is `62 BC 03`. These bytes are checked and
removed; **bit positions count from the first byte after them**. Any other first byte (`7F` is a
negative response) means there is no value this time.

For `01` requests with several identifiers in one request (`0100 0C 0D`), the answer contains
each identifier followed by its data; this is the only service where a logger needs to split the
answer.

### 5.2 Addresses on 29-bit CAN

`tx` and `rx` are the full 29-bit IDs, e.g. `18DA17F1` and `18DAF117`. Profiles generated from a
source that uses short forms state the expanded IDs; `rxMask` keeps a partial match where the
source has one.

### 5.3 Several answers

If more than one module answers a functional request (no `rx`), every answer is decoded with the
same signals. A logger should keep the first one and may record the others raw.

### 5.4 Diagnostic sessions

Some values are only available in a non-default diagnostic session. `diagnosticSession` at the
top level means: enter it once (`10 03`) and keep it alive (`3E 00`). `session.enter` /
`session.exit` on a request mean: switch before and switch back after. Loggers must never send
anything else than reading services and session control based on a profile.

### 5.5 Which request an answer belongs to

An answer is assigned by its service, its identifier and the CAN ID it came from. Among the
requests of all layers (in layer order) with the same service and identifier that apply to the
model year:

1. If one or more have an `rx` matching the answer's CAN ID, the one listed **last** decodes it.
2. Otherwise every request without `rx` decodes it; where they define the same signal, the one
   listed first wins.
3. For service `01` only one request decodes an answer.

### 5.6 Standard OBD-II requests

Requests with `"bus": "obd"` (used by the generic profile) have no `tx` and `rx`. They are sent as
functional OBD-II requests on whatever protocol the vehicle uses – `7DF` on 11-bit CAN, `18DB33F1`
on 29-bit CAN, the standard header on K-line – and accepted from every module.

### 5.7 Single and multi-frame answers on CAN

Answers longer than 7 bytes arrive in several CAN frames (ISO 15765-2): a first frame with the
total length, then consecutive frames. A logger joins them per CAN ID and cuts the result to the
announced length; bytes beyond the length (padding) are not part of the answer. The same applies
to the length in a single frame.

## 6. Signals

```json
{
  "id": "I30_TRUNK",
  "name": "Trunk open?",
  "group": "Doors",
  "bit": 32,
  "bits": 1,
  "min": 0,
  "max": 1,
  "labels": ["No", "Yes"]
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Unique within the profile. Stays stable across revisions. |
| `name` | string | yes | Short English name. |
| `description` | string | no | Longer explanation. |
| `group` | string | no | Category with optional sub levels separated by `.`: `Engine`, `Battery.Modules`. |
| `hidden` | boolean | no | `true`: needed for computations, not shown by default. |
| `metric` | string | no | Standard meaning (section 6.4), e.g. `speed`, `engineSpeed`. |
| `bit` | integer | yes | First bit of the raw value (section 6.1). |
| `bits` | integer | yes | Length of the raw value in bits. |
| `byteOrder` | string | no | `big` (default) or `little` (section 6.1). |
| `signed` | boolean | no | Raw value is two's complement. Default `false`. |
| `multiply` | number | no | Default `1`. |
| `divide` | number | no | Default `1`. |
| `add` | number | no | Default `0`. |
| `min` | number | for numbers | Lowest valid value (after scaling). |
| `max` | number | for numbers | Highest valid value (after scaling). |
| `unit` | string | no | Unit symbol (section 6.3). Missing: no unit. |
| `invalidAtOrBelow` | number | no | A value `<=` this means "not available". |
| `invalidAtOrAbove` | number | no | A value `>=` this means "not available". |
| `optimal` | object | no | `min`, `max` and/or `value`: the range or value considered good, for display. |
| `labels` | array of 2 strings | no | Display text for raw `0` and `1` of a two-state value. The value itself stays a number. |
| `values` | object | no | Enumeration: raw number (as decimal string) → text. The value **is** the text (section 6.2). |
| `valueDescriptions` | object | no | Longer explanation of some enumeration texts, same keys as `values`. |
| `display` | string | no | `hex`: show the raw value in hexadecimal. `text`: the bytes are ASCII text. |

### 6.1 Extracting the raw value

The data bytes (section 5.1) are read as one bit string, most significant bit of each byte first.
Bit `bit` is the first and most significant bit of the raw value, `bits` bits long:

```
raw = 0
for i in bit .. bit + bits - 1:
    raw = raw * 2 + ((data[i / 8] >> (7 - i % 8)) & 1)
```

If the answer is too short, there is no value. With `byteOrder: "little"` and `bits > 8`, the
`ceil(bits / 8)` bytes starting at byte `bit / 8` are reversed before extraction.

### 6.2 From raw value to value

1. `signed`: if the top bit of the raw value is set, subtract `2^bits`.
2. **Enumeration** (`values` present): the value is `values[raw]`; a raw number not in the table
   gives no value. Steps 3–5 are skipped.
3. `value = raw × multiply ÷ divide + add`
4. If `max > min`: limit the value to `min`…`max`.
5. If `invalidAtOrBelow` is set and `value <= invalidAtOrBelow`, or `invalidAtOrAbove` is set and
   `value >= invalidAtOrAbove`: no value.

Order and rounding match the OBDb reference decoder, so generated profiles give the same values
as the source's test cases (section 10).

### 6.3 Units

Units are written as symbols. A reader that converts units should know at least this list:

| Quantity | Symbols |
|---|---|
| Temperature | `°C` `°F` `K` |
| Length / distance | `mm` `cm` `m` `km` `in` `ft` `yd` `mi` |
| Speed | `km/h` `mph` `m/s` |
| Acceleration | `m/s²` `g` |
| Rotation / frequency | `rpm` `nHz` `µHz` `mHz` `Hz` `kHz` `MHz` `GHz` `THz` `fps` |
| Time | `ms` `s` `min` `h` |
| Electrical | `mV` `V` `kV` `mA` `A` `kA` `mΩ` `µΩ` `Ω` `kΩ` `MΩ` `mW` `W` `kW` `C` |
| Charge / energy | `mAh` `Ah` `kAh` `J` `kJ` `kWh` |
| Consumption | `kWh/100km` `kWh/100mi` `mi/kWh` `L/h` `gal/h` `kg/h` `g/s` `mg/stroke` |
| Pressure | `kPa` `bar` `psi` |
| Torque | `Nm` `lb·ft` `in·lb` |
| Angle | `°` `rad` |
| Volume / concentration | `L` `gal` `g/L` `mg/dL` |
| Ratio | `%` |

### 6.4 Standard meanings

`metric` links a signal to a well-known quantity so that a logger can show it in a fixed place
(speedometer, rev counter) whatever the vehicle calls it. Values are taken over from the source,
e.g. `speed`, `engineSpeed`, `engineCoolantTemperature`, `odometer`, `stateOfCharge`,
`tractionBatteryVoltage`, `frontLeftTirePressure`. Group-wide meanings in `groups[].metric`:
`batteryModulesStateOfCharge`, `batteryModulesVoltage`.

## 7. Modules, groups and computed values

**`ecus`** – `{ "tx": "7E0", "rx": "7E8", "extendedAddress": "12", "years": {...}, "type": "engine" }`.
A request belongs to the entry with the same `tx` whose `rx`, `extendedAddress` and `years` match
where the entry sets them; if several match, the one setting the most of them wins. `type` is one
of `abs`, `airbag`, `allWheelDrive`, `battery`, `bodyControl`, `charger`, `cluster`,
`dcdcConverter`, `door`, `driverAssistance`, `engine`, `gateway`, `hvac`, `hybridControl`,
`infotainment`, `keyless`, `lighting`, `motor`, `parkingAssist`, `seat`, `steering`,
`suspension`, `telematics`, `tpms`, `transmission`, `vehicleControl`.

**`groups`** – `{ "id": "...", "name": "...", "group": "Battery.Modules", "match": "^BZ4X_CELL_V_\\d+$", "metric": "batteryModulesVoltage" }`.
All signals whose `id` matches the regular expression `match` belong together.

**`computed`** – a value derived from other signals, with `id`, `name`, `group`, `min`, `max`,
`unit`, `metric` like a signal and a `formula`:

| `formula.op` | Fields | Value |
|---|---|---|
| `ratio` | `a`, `b` | `a ÷ b` |
| `select` | `match`, `cases` | `cases` maps enumeration signals to value signals; the value of the one value signal whose enumeration currently shows `match`. No value if none or several do. |
| `unit` | `value`, `key`, `units` | The number of `value`, shown in the unit that `units` assigns to the current text of `key`. Not converted, only labelled. |

## 8. Source

```json
"source": {
  "name": "OBDb",
  "url": "https://github.com/OBDb/Hyundai-i30",
  "file": "signalsets/v3/default.json",
  "revision": "4f1c2d9…",
  "license": "CC-BY-SA-4.0",
  "attribution": "OBDb contributors, https://obdb.community"
}
```

`revision` is the exact source revision (git commit) the profile was generated from. Profiles
written by hand use `"name": "PitLogger"` and may omit `url`, `file` and `revision`. The license
of a profile is the license of its source; a derived profile must keep it.

## 9. Index

`profiles/index.json` lists every profile so that a logger or app can pick one without opening
all files:

```json
{
  "format": "pitlogger-profile-index/1.0",
  "generated": "2026-11-01",
  "profiles": [
    { "id": "makes/hyundai", "kind": "make", "use": "fallback", "makes": ["Hyundai"],
      "years": null, "requests": 148, "signals": 1552, "tests": 0 },
    { "id": "vehicles/hyundai/i30", "kind": "vehicle", "make": "Hyundai", "model": "i30",
      "years": null, "requests": 98, "signals": 456, "tests": 1863 }
  ]
}
```

`"sourceMissing": true` marks a profile whose source no longer exists (or could not be fetched at
the last update). The profile is kept unchanged.

## 10. Test cases

Recorded answers with the values they must decode to are kept next to the profiles in
`tests/<profile id>.json`:

```json
{
  "format": "pitlogger-profile-tests/1.0",
  "profile": "vehicles/hyundai/i30",
  "cases": [
    {
      "year": 2017,
      "request": "770.778.22BC03",
      "frames": ["778 10 0B 62 BC 03 FF EE 7C", "778 21 73 00 00 00 00 AA AA"],
      "expect": { "I30_TRUNK": 0, "I30_DOOR_FL": 0 }
    }
  ]
}
```

`frames` are the CAN frames of the answer as received (ID, then data bytes; with
`"extendedAddressing": true` the first data byte is the address byte). `year` is the model year
of the recording, `request` the id of the request that was sent. A decoder passes when every
signal in `expect` decodes to the given number (within `1e-5`) or text. These cases also let an
emulator answer like the real vehicle.

Some source test cases do not match the source's own current definitions (a request was changed
after the recording). They are listed in `tests/known-failures.json`.

## 11. Versioning

This document is version 1.0 of the format. Minor versions only add optional fields; readers of the
same major version keep working. A change that existing readers would misread raises the major
version.
