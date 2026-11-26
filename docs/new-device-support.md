# Requesting support for a new Renogy device

This guide explains how to collect the information needed to add or extend device
support in `renogy-ble` and the Home Assistant integration, `renogy-ha`. You do not
need to write code or decode the Bluetooth protocol. Your job is to show what the
device exposes and record a working conversation with the Renogy app.

Discovery or a successful Bluetooth connection does not establish protocol
compatibility. Devices with similar names can use different commands, addresses,
registers, or value scaling. A service list describes the Bluetooth interface; a
traffic capture shows how the app uses it. Both can be necessary.

## Choose where to start

| Your situation | What to collect |
| --- | --- |
| Opening a device support request | Complete [device details](#1-record-device-and-software-details) and attach available logs/screenshots. Advanced captures are optional at this stage. |
| Device is missing, misidentified, or fails to connect/read | Also collect [advertisements and services](#3-collect-bluetooth-advertisements-and-services). |
| Device connects but its protocol is unknown | Collect a [working app session](#4-capture-a-working-renogy-app-session-on-android) and [matching readings](#5-record-readings-and-operating-states). |
| Some values are missing or wrong | Capture the affected operating states and matching app readings. |
| Requesting a switch or setting | First establish telemetry, then capture [one control at a time](#6-capture-controls-and-settings-when-requested). |
| You cannot capture app traffic | Use the [alternatives](#8-alternatives-and-common-problems) and submit what you have. |

For Home Assistant requests, use the
[feature request form](https://github.com/IAmTheMitchell/renogy-ha/issues/new?template=feature_request.yml).
For standalone library use, open a
[renogy-ble issue](https://github.com/IAmTheMitchell/renogy-ble/issues).
Search existing issues for your exact model first; add evidence to an existing
request instead of opening a duplicate. Use one issue as the discussion location
and link any related issue in the other repository.

## Before collecting data

- Keep the device in a normal, safe operating setup. Only use loads, charging
  sources, and settings you already know are appropriate. Do not create faults,
  discharge a battery to its protection cutoff, or change protection thresholds
  just to obtain a capture. Mark unavailable states as untested.
- Keep the phone near the device. Use one Bluetooth client at a time: Home
  Assistant, the Renogy app, nRF Connect, and other gateways can compete for the
  same connection. Disconnect the current client before switching tools.
- For app/nRF captures, temporarily disable the device's Renogy integration entry
  in Home Assistant, if configured, and disconnect any Renogy gateway that uses
  its Bluetooth connection. Record what you paused and restore it afterward.
  For integration logs, instead close the phone apps and allow Home Assistant to
  connect. Do not delete the integration entry or reset the device.
- Save each session in a separate local folder, such as `device-01-baseline`.
  Keep original files unchanged locally. Work on copies when preparing uploads.
- Reports and attachments on GitHub are public. Phone bug reports can contain
  unrelated app logs, account details, network names, and identifiers; Bluetooth
  captures can include other devices and credentials. Collect short sessions
  without unrelated Bluetooth accessories when practical. Follow the
  [sharing instructions](#7-check-and-share-the-evidence) before uploading.

## 1. Record device and software details

Copy this checklist into your issue or a local `device-details.md` file. Write
`unknown` or `not applicable` rather than guessing.

```text
Product name:
Exact model/SKU, including regional suffix:
Hardware revision (from label or app):
Device firmware versions (include all components the app lists):
Bluetooth module: built-in / BT-1 / BT-2 / other:
Bluetooth module firmware, if shown:
Bluetooth advertised name (preserve the prefix; mask a unique suffix if needed):
Renogy app name and version (for example, DC Home):
Phone model and Android/iOS version:
Does the Renogy app show live readings over local Bluetooth?:
Home Assistant Core version, if used:
renogy-ha version, if used:
renogy-ble version, if known:
HA Bluetooth adapter/proxy and connection mode, if used:
Selected device type and inverter profile, if configured:
Requested readings or controls:
What currently works and what fails:
Can you test a development version? Any limits on testing?:
```

Include a photograph of the model label with serial numbers and QR codes covered,
an app device-information screenshot, and any available manufacturer manual or
protocol-document link. A marketing name alone may cover several revisions.
Do not upgrade firmware during a set of captures; if you do upgrade, label the
before/after captures separately.

Confirm that the app readings are live, rather than cached or from a cloud gateway.
If practical, after signing in normally, temporarily turn off phone Wi-Fi and
mobile data while leaving Bluetooth enabled, reconnect in the app, and observe
readings updating. Record whether this works. If the app requires network access,
say so; do not sign out, unbind the device, or factory-reset it for this test.

## 2. Collect existing integration logs, if you use Home Assistant

Skip this section if you only use the library or have not configured the device.

1. Close/disconnect the Renogy app and nRF Connect.
2. Open **Settings > Devices & services > Renogy**, use the integration's menu to
   **Enable debug logging**, and note the start time and timezone.
3. Let the device attempt at least two polls. Record your polling interval. If the
   device is in a failure cooldown, reload its entry once while logging to capture
   a fresh connection attempt, then wait for it to finish.
4. Use **Disable debug logging** to download the log. Keep the connection and
   request/response sequence, not just the final timeout line.
5. In the entry menu, also select **Download diagnostics** if available. If it is
   absent or empty, say so. Diagnostics are cached integration data and may be
   model-specific; they do not replace an app traffic capture.

If the downloaded log contains integration messages but no library details, merge
these entries into your existing `logger` configuration in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.renogy: debug
    renogy_ble: debug
```

Do not add a second `logger:` key if one already exists. Check the configuration
and restart Home Assistant, reproduce the problem, then collect the raw Core log
from **Settings > System > Logs**. Remove the temporary logging entries and
restart after collecting. See Home Assistant's
[debug log and diagnostics instructions](https://www.home-assistant.io/docs/configuration/troubleshooting/#debug-logs-and-diagnostics)
for UI variations and the [Logger reference](https://www.home-assistant.io/integrations/logger/)
for YAML logging. Review logs for identifiers before sharing.

For a standalone library report, include your library version, a minimal script
without credentials, the selected device type/model hint, and the complete debug
request/response sequence if available. Do not send arbitrary commands to an
unknown device to produce logs.

## 3. Collect Bluetooth advertisements and services

Use [nRF Connect for Mobile](https://www.nordicsemi.com/Products/Development-tools/nRF-Connect-for-mobile)
by Nordic Semiconductor on Android or iOS. You need the mobile scanner, not the
desktop application or a firmware-update utility. Its Android documentation is
[here](https://github.com/nordicsemi/Android-nRF-Connect).

### Advertisement: what the device broadcasts

1. Disconnect competing clients as described above. Open nRF Connect, enable
   Bluetooth, and grant Bluetooth/Nearby devices permissions. Older Android
   versions may also need location permission and location services for scanning.
2. Start a scan. Find the device by the name shown in the Renogy app or its
   Bluetooth address on Android. A `BT-TH-*` prefix alone does not identify the
   attached product. If uncertain, compare with the app and the label rather than
   power-cycling equipment that is supplying loads.
3. Expand its scan result. Save screenshots of the full advertisement details,
   including scan response data if displayed: local name, advertised service UUIDs,
   manufacturer/company ID **and raw data bytes**, service data bytes, and whether
   it is connectable. Keep the hexadecimal data as text too when copy/export is
   available. If fields are absent, record that.
4. Record the RSSI (signal strength), phone OS, and capture time. iOS typically
   shows an app-specific identifier instead of a MAC address; submit that fact
   rather than trying to derive a MAC from the identifier.

### GATT services: what the device exposes after connection

1. Tap **Connect** and wait for service discovery to finish.
2. Expand **every service**, then its characteristics and descriptors. Proprietary
   entries may be named **Unknown Service** or **Unknown Characteristic**; their
   UUIDs and properties are the useful information.
3. Save overlapping screenshots covering the complete list. Use a service export
   if your app version offers one, but verify it includes the UUIDs and properties.
   A screenshot of only the collapsed service headings is incomplete.
4. For each characteristic, include the parent service UUID, full characteristic
   UUID, handle if shown, and properties: **Read**, **Write**, **Write Without
   Response**, **Notify**, or **Indicate**. Include descriptor UUIDs/handles,
   particularly `0x2902` (Client Characteristic Configuration Descriptor), if shown.
5. If the standard **Device Information** service (`0x180A`) is present, you may
   read model/hardware/firmware characteristics marked readable and record the
   results. Mask serial numbers. Do not write values, invoke DFU, or enable
   unknown controls. Record permission/pairing errors exactly; do not reset bonds
   or bypass security to continue.
6. Save the app's connection/service-discovery log if its log/share function is
   available, then **Disconnect** before opening the Renogy app.

For a text inventory, repeat a row like this for each characteristic:

```text
Service UUID | Characteristic UUID | Handle | Properties | Descriptor UUIDs/handles
```

nRF Connect records its own interactions. It does **not** capture the Renogy app's
conversation just because it is installed on the same phone. Empty values on a
custom characteristic do not prove that telemetry is unavailable; the device may
require a request or initialization first.

## 4. Capture a working Renogy app session on Android

This is the advanced step for unknown protocols. The goal is a recording from
**before the app connects** through several successful telemetry updates, with
requests and replies intact. An Android HCI snoop log records the phone's Bluetooth
traffic; no external radio sniffer is needed for this method.

You need an Android phone on which the Renogy app works, and preferably a computer
to extract and check the recording. Stock phones vary in what they include in
bug reports. Rooting, bootloader unlocking, and paid hardware are not prerequisites.

### A. Enable recording

1. Close the Renogy app, disconnect nRF Connect, and pause other device clients.
2. Enable Android **Developer options**: find **Build number** in **Settings >
   About phone** (sometimes under **Software information**) and tap it seven times.
   Enter the phone PIN if requested. See Android's
   [device setup instructions](https://developer.android.com/studio/run/device).
3. In Developer options, set **Bluetooth HCI snoop log** to **Enabled**. If offered
   a choice, use the full/unfiltered mode rather than filtered logging.
4. Turn phone Bluetooth off and back on so the setting takes effect. Reconnect
   only the Renogy device during the test where practical. Android documents the
   logging requirement and Bluetooth restart in its
   [Bluetooth debugging guide](https://source.android.com/docs/core/connect/bluetooth/verifying_debugging).

### B. Record a baseline session

1. Note the date, timezone, and start time to the second. Start a screen recording
   or take timestamped screenshots. Keep the app's device page visible.
2. Open the Renogy app, connect to the device, and wait for readings to settle.
   Leave it connected for about 60–120 seconds, long enough for several updates.
3. Open the device-information and relevant telemetry pages. Record the readings
   using the [session table](#5-record-readings-and-operating-states). For the first
   session, leave settings unchanged so initialization and normal polling are clear.
4. Note the end time and collect the bug report immediately using C. Avoid another
   Bluetooth restart first, which may rotate the capture. Do not leave the log
   running for hours while doing other things on the phone.

### C. Retrieve the recording

Choose either method from Android's
[bug report instructions](https://developer.android.com/studio/debug/bug-report):

- **Phone UI:** In Developer options, select **Take bug report** (or **Bug report**).
  Choose a full report if offered, wait for the ready notification, and save the
  ZIP locally or transfer it to your computer. Do not upload the whole report.
- **Computer via USB:** Download and extract Google's
  [SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools).
  Enable **USB debugging** in Developer options, connect a data-capable USB cable,
  unlock the phone, and accept its debugging prompt for your own computer. In a
  terminal opened in the extracted `platform-tools` directory, run:

  ```sh
  ./adb devices
  ./adb bugreport renogy-bugreport.zip
  ```

  On Windows PowerShell, use `.\adb.exe` instead of `./adb`. `devices` should list
  one phone with status `device`. For `unauthorized`, unlock it and approve the
  prompt; for no device, check the cable, USB debugging, and any required vendor
  USB driver. Disconnect extra phones/emulators before collecting.

Extract the ZIP on your computer into a private folder. Search its contents for
`btsnoop`, including rotated siblings such as `.last`. A common location is
`FS/data/misc/bluetooth/logs/btsnoop_hci.log`; vendor layouts may differ. Copy the
log(s) covering your test into your session folder. Note the original path and
which file covers which session. Do not rename an entire bug report ZIP to `.log`.
Normal production phones may deny direct access to `/data/misc/...` with a file
manager or `adb pull`; use the bug report rather than attempting to gain root.

If the ZIP has no raw snoop log, its main `bugreport-....txt` may contain an
embedded Bluetooth trace. Android provides
[`btsnooz.py`](https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/system/tools/scripts/btsnooz.py)
to extract it. Install [Python 3](https://www.python.org/downloads/) if needed.
In a terminal in your session folder, download the script from Android's source
repository with this command. The source server returns base64 text, so the
command decodes it before saving; saving the HTML viewer page will not work.

```sh
python3 -c "import base64, pathlib, urllib.request; url = 'https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/system/tools/scripts/btsnooz.py?format=TEXT'; pathlib.Path('btsnooz.py').write_bytes(base64.b64decode(urllib.request.urlopen(url).read()))"
```

Copy the extracted report text into that folder and run the following command,
substituting the actual text filename. Keep the terminal open while it runs;
do not pipe another command's output into it.

```sh
python3 btsnooz.py "bugreport-actual-name.txt" > device-btsnoop.log
```

On Windows use **Command Prompt**, with `py -3` instead of `python3`. Older
PowerShell versions can corrupt binary output when using `>` with a native
command. This fallback may lack application payloads or the beginning of your
session; validate it using D. An output file existing is not proof of a useful
capture. If extraction fails or values are missing, record the limitation and
use [the alternatives](#8-alternatives-and-common-problems).

### D. Check that the recording contains useful device data

Install [Wireshark](https://www.wireshark.org/download.html) on your computer.
Opening an existing capture does not require starting a network capture or
installing a Bluetooth sniffer.

1. Open the extracted `.log` in Wireshark. Set **View > Time Display Format** to
   a date/time format and check that packets overlap your recorded session. Note
   any timezone difference between the computer and phone.
2. Enter `btatt` in the display-filter bar and press Enter. This shows Bluetooth
   Attribute Protocol traffic. Check for app writes/reads and incoming replies,
   notifications, or indications with nonempty **Value** bytes during updates.
   Wireshark documents these fields in its
   [Bluetooth ATT filter reference](https://www.wireshark.org/docs/dfref/b/btatt.html).
3. Check that the traffic belongs to the Renogy connection. Select an ATT packet
   and expand **Bluetooth HCI ACL Packet** in the packet details. If the source or
   destination address matches your device, right-click that field and use
   **Apply as Filter > Selected**. If only a connection handle is available,
   match it to the Renogy address in the preceding connection-complete event.
   You can then use a filter such as `btatt && bthci_acl.chandle == 0x000b`,
   replacing `0x000b` with the observed handle. Handles can be reused after a
   disconnect; limit the check to your session times. See Wireshark's
   [HCI ACL fields](https://www.wireshark.org/docs/dfref/b/bthci_acl.html).
4. Include the connection start, initialization writes, notification subscription,
   and later requests/replies. Service discovery may be cached, so also include
   the separate GATT inventory from section 3. Leave protocol interpretation to
   the maintainers; do not remove packets simply because their purpose is unclear.

A capture with only discovery/events, an empty `btatt` result, missing Value
bytes, or timestamps outside the test is not enough to implement a parser.
Confirm full HCI logging, restart phone Bluetooth, and repeat once. If the
Renogy app uses a non-GATT transport, retain that observation and its connection
traffic; do not conclude from an empty `btatt` result alone that logging failed.
Report the result if you cannot obtain payloads.

After saving the report, turn HCI snoop logging off. Turn USB debugging off if you
enabled it for this task. Restore paused clients after finishing all captures.

## 5. Record readings and operating states

A stream of bytes alone does not tell us which field represents volts, watts, or
state of charge. Supply app screenshots or a screen recording and a short event
table alongside the Bluetooth capture. Record units, signs, decimal places, and
all relevant pages, including any totals and status indicators.

Use one row per event or screenshot. The example values below are illustrative;
replace them with your observations. Use a timezone offset, such as `+01:00`,
rather than a timezone abbreviation alone.

```text
Session: device-01-baseline
Capture file: device-01-baseline.log
Date: YYYY-MM-DD; phone timezone: UTC+01:00
Time       | Event/state         | App readings                     | Evidence
14:02:10   | App connects        | Device info/firmware page        | info.png
14:02:45   | Idle                | SOC 63%; battery 13.2 V; load 0 W| idle.png
14:03:20   | Normal load enabled | SOC 63%; output 80 W             | load.png
14:04:00   | Load off            | SOC 63%; output 0 W              | off.png
```

Collect only states your equipment normally supports and you can safely arrange:

| Device family | Useful comparisons |
| --- | --- |
| Battery or shunt | Idle, normal charging, normal discharging; pack voltage/current, SOC, cell readings, temperature and sign conventions. |
| Controller | No PV input versus normal solar charging; PV voltage/current/power, battery data, charging stage, load data and daily totals. |
| DCC charger | Solar only, alternator only, both inputs, neither input; identify which sources are present and record each input's voltage/current/power. |
| Inverter or power station | Idle, a normal AC/DC load, normal charging; battery data, input/output power, AC voltage/frequency, output-enabled indicators. |

Hold each state long enough for multiple app updates, typically 30–60 seconds
after it settles. Note transitions and which inputs/outputs were actually
connected. Include independent meter readings if already available, with their
units and times; they help distinguish combined input power from one source.
Do not rewire live circuits or connect a meter in an unfamiliar way for this task.

Mark app-derived estimates (such as remaining runtime) separately from measured
values. A field that never changes may remain ambiguous; state what you could
and could not vary instead of guessing a formula. Additional sessions at different
normal SOC or load levels help confirm scaling. Report unknown, unavailable, or
error values too, but do not induce a fault to obtain them.

## 6. Capture controls and settings when requested

Do this only for a requested control you already understand and can operate
safely through the official app. Telemetry-only requests can skip it. Do not use
nRF Connect to replay writes or probe unknown registers.

1. Make a separate, clearly named capture with HCI logging enabled before app
   connection. Record the current setting, units, available choices or permitted
   range, and connected loads/charging sources.
2. Change **one** setting in the Renogy app. Record the exact time and old/new
   values. Wait for several normal updates and record any visible effect.
3. Reopen the setting page or reconnect in the app to show the value read back
   from the device. An app success message or Bluetooth write acknowledgement
   alone does not establish that a setting was applied or persisted.
4. Restore the original setting through the app if appropriate and capture its
   readback too. Note whether the app requires a mode such as Custom before
   allowing edits. Do not power-cycle essential equipment to test persistence;
   mark restart persistence as untested unless a normal safe restart was possible.
5. Save the capture and a table of actions/results. Repeat separately for other
   controls so each transaction has an identifiable purpose.

## 7. Check and share the evidence

Before submitting, check that your evidence package contains:

- [ ] Exact model/revision, firmware, module, app/OS versions, and requested features.
- [ ] What already works, selected integration type/profile, and relevant logs if used.
- [ ] Advertisement details, including manufacturer/service data bytes when present.
- [ ] Complete GATT inventory with UUIDs and properties, or the error obtaining it.
- [ ] App traffic capture including initialization and live updates, if obtainable.
- [ ] Matching readings/screenshots and an event table with timezone and filenames.
- [ ] For controls, before/after values, action times, and readback results.
- [ ] A list of missing items, failed capture methods, and states not tested.
- [ ] Whether you can test development builds and compare their readings with the app.

### Prepare files for a public issue

1. Review label/app screenshots and text logs. Cover account details, QR codes,
   serial numbers, and unique address/name suffixes as needed. Keep model numbers,
   name prefixes, service/characteristic UUIDs, timestamps, and measurement bytes.
   Use consistent aliases such as `device-A` so the same device can be followed
   across files. Manufacturer data can contain identifiers too; explain any
   redactions without presenting altered bytes as original protocol evidence.
2. Extract only the Bluetooth log from the phone bug report. **Do not attach the
   complete Android bug report ZIP or its main text file.** Removing a screenshot
   or renaming a file does not sanitize the rest of a bug report.
3. Inspect the Bluetooth capture for unrelated connections and sensitive payloads.
   If trimming is necessary, work on a copy and use Wireshark's
   [File > Export Specified Packets](https://www.wireshark.org/docs/wsug_html_chunked/ChIOExportSection.html)
   to retain the target session, including its setup and both directions of
   traffic. Export a packet range covering that connection if unsure which setup
   packets are needed. A display filter alone does not remove packets from the
   saved original. Reopen the exported capture and repeat the checks in section 4D.
4. Exporting selected packets is **not** anonymization of the retained packets.
   Addresses, keys, or identifiers can remain. Do not hex-edit a binary capture to
   redact it; that may break framing and checksums. If unsure it is safe to publish,
   submit the non-sensitive details first and ask in the issue how to arrange a
   suitable sharing method. Do not assume private uploads or private support are
   available, and do not post credentials.
5. Attach reviewed `.log`/`.pcapng`, text, and images to the issue. Use a ZIP
   containing **only the reviewed evidence files** if a file type is rejected.
   Give each file a descriptive session name; list what each contains. Include
   copied text logs in fenced code blocks rather than screenshots alone.

You can submit the basic report before the advanced evidence is ready. Explain
what is missing and add files in follow-up comments. Keep local originals until
the investigation is complete; a trimmed capture may omit something needed later.

## 8. Alternatives and common problems

| Problem | Next step |
| --- | --- |
| Only an iPhone/iPad is available | Collect app screenshots and nRF Connect advertisements/GATT inventory on iOS. This guide's HCI method is Android-specific; an nRF log on iOS does not capture another app. If possible, borrow an Android phone compatible with the official app; otherwise report the limitation. |
| No computer is available | Collect basic details and nRF screenshots; save a phone-generated bug report privately if available. Do not upload the entire report because you cannot extract it yet. |
| Device does not appear in a scan | Close other clients, confirm Bluetooth permissions, move nearer, and confirm the app can find it. Record missing fields and screenshots of the scan result; do not reset the device. |
| nRF Connect connects but returns a security error | Save the error and service list that is visible. Capture how the official app connects instead of guessing pairing codes. |
| Services exist, but custom values are empty | Obtain the working app capture. Unknown devices may need initialization or commands before returning data. |
| Missing/filtered HCI file, or no payload after one repeat | Record phone model, OS, logging mode, extraction method, and result. Try another compatible Android phone if available. A `btsnooz` fallback is useful only if its payloads survive. |
| App works only with internet access | Record whether the device is reached through a gateway or directly over Bluetooth. Capture the Bluetooth attempt; cloud API traffic alone does not specify the local BLE protocol. |
| Considering `btmon` on a Linux HA host | It records that host's Bluetooth controller traffic, not a separate phone's app conversation. It helps with existing integration requests, but cannot replace a working app capture on the phone. |
| No way to obtain a working app capture | Supply manufacturer protocol/register documentation if available, the GATT inventory, and existing logs. Ask Renogy for documentation covering the exact model/revision and local BLE initialization, framing, registers, scaling, and controls. |

External radio sniffers and platform-specific developer tools are possible
advanced alternatives, but may require extra hardware, connection-following, or
encryption handling. You do not need to buy hardware or root a phone to submit a
request. State what you can provide so maintainers can assess the remaining gaps.

## What happens after submission

Maintainers use the inventory and successful transactions to identify the
transport, commands, field meanings, and scaling, then add regression tests from
real responses. Protocol and parsing support belongs in `renogy-ble`; Home
Assistant discovery, configuration, and entities belong in `renogy-ha`.

A follow-up development build may need you to compare readings against the app
in the same operating states, report unavailable fields and reconnect behavior,
and verify control readback. Good evidence reduces back-and-forth, but does not
guarantee support for every field or firmware revision. Never describe an untested
state as verified.
