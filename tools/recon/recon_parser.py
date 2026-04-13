#!/usr/bin/env python3
"""
Парсер результатов сканирования: airodump-ng CSV + tshark pcap -> recon.json.

Двойной парсинг:
  1. CSV (airodump-ng) - быстрая табличная структура AP/STA
  2. pcap (tshark -T json) - IE/tagged params из beacon/probe response frames

Результат записывается атомарно (tmpfile + rename).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Band derivation
# ---------------------------------------------------------------------------

def channel_to_band(ch: int | None) -> str:
    if ch is None:
        return ""
    if 1 <= ch <= 14:
        return "2.4"
    if 32 <= ch <= 177:
        return "5"
    return ""


# ---------------------------------------------------------------------------
# Airodump CSV parser
# ---------------------------------------------------------------------------

def _strip_fields(row: list[str]) -> list[str]:
    return [f.strip() for f in row]


def _parse_int(val: str) -> int | None:
    val = val.strip()
    if not val or val == "-1":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_timestamp(val: str) -> str | None:
    val = val.strip()
    if not val:
        return None
    try:
        dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def parse_airodump_csv(csv_path: Path) -> tuple[list[dict], list[dict]]:
    """Parse airodump-ng CSV into AP and STA lists."""
    try:
        content = csv_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], []

    lines = content.strip().splitlines()
    if not lines:
        return [], []

    aps: list[dict] = []
    stas: list[dict] = []
    section = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            section = None
            continue

        if stripped.startswith("BSSID") and "First time seen" in stripped:
            section = "ap"
            continue
        if stripped.startswith("Station MAC") and "First time seen" in stripped:
            section = "sta"
            continue

        fields = _strip_fields(line.split(","))

        if section == "ap" and len(fields) >= 14:
            bssid = fields[0].strip().upper()
            if not bssid or len(bssid) != 17:
                continue

            essid_raw = ",".join(fields[13:]).strip() if len(fields) > 13 else ""
            essid_raw = essid_raw.strip().strip(",").strip()
            if essid_raw.startswith('"') and essid_raw.endswith('"'):
                essid_raw = essid_raw[1:-1].strip().strip(",").strip()

            # Любая отсутствующая/нулевая ESSID в выгрузке -> скрытая сеть (UI: "<Hidden>")
            nullish = (not essid_raw) or essid_raw.startswith("\\x00")
            if nullish:
                essid = None
                is_hidden = True
            else:
                essid = essid_raw
                is_hidden = False

            channel = _parse_int(fields[3])

            aps.append({
                "bssid": bssid,
                "essid": essid,
                "is_hidden": is_hidden,
                "channel": channel,
                "band": channel_to_band(channel),
                "power": _parse_int(fields[8]),
                "speed": _parse_int(fields[4]),
                "privacy": fields[5].strip() or None,
                "cipher": fields[6].strip() or None,
                "auth": fields[7].strip() or None,
                "beacons": _parse_int(fields[9]) or 0,
                "data_frames": _parse_int(fields[10]) or 0,
                "iv_count": _parse_int(fields[10]) or 0,
                "first_seen": _parse_timestamp(fields[1]),
                "last_seen": _parse_timestamp(fields[2]),
                "wps": None,
                "security_info": None,
                "tagged_params": None,
                "clients": [],
            })

        elif section == "sta" and len(fields) >= 6:
            mac = fields[0].strip().upper()
            if not mac or len(mac) != 17:
                continue

            associated_bssid_raw = fields[5].strip().upper()
            associated_bssid = (
                associated_bssid_raw
                if associated_bssid_raw and associated_bssid_raw != "(NOT ASSOCIATED)"
                and len(associated_bssid_raw) == 17
                else None
            )

            probed_raw = ",".join(fields[6:]).strip() if len(fields) > 6 else ""
            probed_essids = [
                p.strip()
                for p in probed_raw.split(",")
                if p.strip()
            ]

            stas.append({
                "mac": mac,
                "power": _parse_int(fields[3]),
                "packets": _parse_int(fields[4]) or 0,
                "probed_essids": probed_essids,
                "associated_bssid": associated_bssid,
                "first_seen": _parse_timestamp(fields[1]),
                "last_seen": _parse_timestamp(fields[2]),
            })

    return aps, stas


# ---------------------------------------------------------------------------
# tshark pcap parser (IE / tagged params from beacon & probe response)
# ---------------------------------------------------------------------------

TSHARK_FIELDS = [
    "wlan.bssid",
    "wlan.ssid",
    "wlan.ds.current_channel",
    "radiotap.dbm_antsignal",
    # RSN IE
    "wlan.rsn.gcs.type",
    "wlan.rsn.pcs.type",
    "wlan.rsn.akms.type",
    "wlan.rsn.capabilities.mfpc",
    "wlan.rsn.capabilities.mfpr",
    # WPS IE
    "wps.wifi_protected_setup_state",
    "wps.version",
    "wps.ap_setup_locked",
    "wps.device_name",
    "wps.manufacturer",
    "wps.model_name",
    "wps.model_number",
    "wps.serial_number",
    "wps.config_methods",
    # HT / VHT
    "wlan.ht.capabilities",
    "wlan.vht.capabilities",
    # Country
    "wlan.country_info.code",
    # Vendor
    "wlan.tag.vendor.oui.type",
]

AKM_SUITE_NAMES = {
    "1": "802.1X",
    "2": "PSK",
    "3": "FT-802.1X",
    "4": "FT-PSK",
    "6": "PSK-SHA256",
    "8": "SAE",
    "9": "FT-SAE",
    "12": "OWE",
    "18": "SAE-EXT",
}

CIPHER_SUITE_NAMES = {
    "1": "WEP-40",
    "2": "TKIP",
    "4": "CCMP",
    "5": "WEP-104",
    "6": "BIP-CMAC-128",
    "8": "GCMP-128",
    "9": "GCMP-256",
    "10": "CCMP-256",
    "11": "BIP-GMAC-128",
    "12": "BIP-GMAC-256",
}


def _norm_mac_colons(addr: str) -> str | None:
    addr = addr.strip().upper().replace("-", ":")
    if not addr:
        return None
    hexonly = addr.replace(":", "")
    if len(hexonly) == 12 and all(c in "0123456789ABCDEF" for c in hexonly):
        if ":" not in addr:
            return ":".join(hexonly[i : i + 2] for i in range(0, 12, 2))
        return addr if len(addr) == 17 else None
    return None


def _normalize_airodump_privacy(privacy: str | None) -> str:
    """Приводит поле Privacy из CSV к читаемому виду (OPN -> Open)."""
    if not privacy:
        return "Open"
    p = privacy.strip()
    pu = p.upper()
    if pu in ("OPN", "OPEN", "NONE"):
        return "Open"
    return p


def _privacy_suggests_wpa3(p_norm: str) -> bool:
    return "WPA3" in p_norm.upper() or "SAE" in p_norm.upper()


def _privacy_suggests_wep(p_norm: str) -> bool:
    return "WEP" in p_norm.upper()


def _akm_set_from_rsn(rsn: dict | None) -> frozenset[str]:
    if not rsn:
        return frozenset()
    suites = rsn.get("akm_suites") or []
    return frozenset(str(x) for x in suites)


def compute_display_security(csv_ap: dict, tagged_params: dict | None, wps: dict | None) -> str:
    """Краткая метка для таблицы: Open, WPA2, WPA3, WPA2/WPA3, OWE, WEP, ..."""
    rsn = (tagged_params or {}).get("rsn") if tagged_params else None
    akms = _akm_set_from_rsn(rsn)
    p_raw = csv_ap.get("privacy") or ""
    p_norm = _normalize_airodump_privacy(p_raw)

    has_sae = "SAE" in akms or "FT-SAE" in akms or "SAE-EXT" in akms
    has_psk = "PSK" in akms or "FT-PSK" in akms
    has_8021x = "802.1X" in akms or "FT-802.1X" in akms
    has_owe = "OWE" in akms

    if has_owe:
        return "OWE"
    if has_sae and has_psk:
        return "WPA2/WPA3"
    if has_sae:
        return "WPA3"
    if has_psk or has_8021x:
        pcs = frozenset((rsn or {}).get("pairwise_ciphers") or [])
        if has_psk and "TKIP" in pcs and "CCMP" not in pcs:
            return "WPA"
        return "WPA2" if has_psk and not has_8021x else "WPA2-Enterprise"

    if p_norm == "Open":
        return "Open"
    if _privacy_suggests_wep(p_norm):
        return "WEP"
    if _privacy_suggests_wpa3(p_norm) and "WPA2" in p_norm.upper():
        return "WPA2/WPA3"
    if _privacy_suggests_wpa3(p_norm):
        return "WPA3"
    if "WPA2" in p_norm.upper() and "WPA" in p_norm.upper() and "WPA3" not in p_norm.upper():
        return "WPA/WPA2"
    if "WPA2" in p_norm.upper():
        return "WPA2"
    if "WPA" in p_norm.upper():
        return "WPA"
    return p_norm


def run_wash_on_pcap(pcap_path: Path) -> dict[str, dict[str, Any]]:
    """wash -f pcap - офлайн WPS (не конфликтует с airodump по интерфейсу)."""
    out: dict[str, dict[str, Any]] = {}
    if not pcap_path.exists() or pcap_path.stat().st_size < 64:
        return out
    cmd = [
        "wash",
        "-f",
        str(pcap_path),
        "-j",
        "-a",
        "-F",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return out

    rows_to_process: list[dict] = []
    raw_out = (r.stdout or "").strip()
    if raw_out.startswith("["):
        try:
            bulk = json.loads(raw_out)
            if isinstance(bulk, list):
                rows_to_process.extend(x for x in bulk if isinstance(x, dict))
        except json.JSONDecodeError:
            pass
    if not rows_to_process:
        text = raw_out + "\n" + (r.stderr or "")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("Wash ") or line.startswith("BSSID"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, list):
                rows_to_process.extend(x for x in row if isinstance(x, dict))
            elif isinstance(row, dict):
                rows_to_process.append(row)

    for row in rows_to_process:
        lk = {str(k).lower(): v for k, v in row.items()}
        bssid = lk.get("bssid") or lk.get("mac")
        if not bssid:
            continue
        nb = _norm_mac_colons(str(bssid))
        if not nb:
            continue
        wps_ver = lk.get("wps_version")
        if wps_ver is not None:
            wps_ver = str(wps_ver)
        locked_raw = lk.get("wps_locked")
        if isinstance(locked_raw, str):
            wps_locked = locked_raw.strip().lower() in ("1", "true", "yes", "locked")
        else:
            wps_locked = bool(locked_raw)
        wps_state = lk.get("wps_state")
        enabled = str(wps_state or "") in ("1", "2")
        if wps_ver is not None and str(wps_ver).strip() != "":
            enabled = True
        out[nb] = {
            "wash_seen": True,
            "wps_version": str(wps_ver) if wps_ver is not None else None,
            "wps_locked": wps_locked,
            "wps_state": wps_state,
            "wash_essid": lk.get("essid") or lk.get("ssid"),
            "wash_channel": lk.get("channel"),
            "wash_rssi": lk.get("rssi") or lk.get("dbm"),
            "enabled": enabled,
        }
    return out


def merge_wash_into_aps(aps: list[dict], wash_by_bssid: dict[str, dict[str, Any]]) -> list[dict]:
    for ap in aps:
        w = wash_by_bssid.get(ap["bssid"])
        if not w:
            continue
        base = dict(ap.get("wps") or {})
        src = list(base.get("enrichment_sources") or [])
        if "wash" not in src:
            src.append("wash")
        base["enrichment_sources"] = src
        if w.get("wps_version") is not None:
            base["version"] = base.get("version") or w["wps_version"]
        base["locked"] = bool(base.get("locked")) or bool(w.get("wps_locked"))
        if w.get("enabled"):
            base["enabled"] = True
        if str(w.get("wps_state") or "") == "2":
            base["configured"] = True
        ap["wps"] = base
    return aps


def parse_hcx_rcascan_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Разбор stdout hcxdumptool --rcascan (таблица с '|')."""
    found: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return found
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line or line.startswith("CHA|") or line.startswith("TIME") or line.startswith("---"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        ch_s = parts[0].strip()
        if ":" in ch_s:
            continue
        ch = _parse_int(ch_s)
        if ch is None:
            continue
        ap_mac_raw = parts[4] if len(parts) > 4 else ""
        essid = parts[5].strip() if len(parts) > 5 else ""
        nb = _norm_mac_colons(ap_mac_raw)
        if not nb:
            continue
        found[nb] = {
            "channel": ch,
            "essid_hint": essid or None,
            "source": "hcxdumptool_rcascan",
        }
    return found


def merge_hcx_into_aps(aps: list[dict], hcx_by_bssid: dict[str, dict[str, Any]]) -> list[dict]:
    for ap in aps:
        h = hcx_by_bssid.get(ap["bssid"])
        if not h:
            continue
        tp = dict(ap.get("tagged_params") or {})
        tp["hcx_rcascan"] = {"channel": h.get("channel"), "essid_hint": h.get("essid_hint")}
        ap["tagged_params"] = tp
        if ap.get("channel") is None and h.get("channel") is not None:
            ap["channel"] = h["channel"]
            ap["band"] = channel_to_band(h["channel"])
        w = dict(ap.get("wps") or {})
        src = list(w.get("enrichment_sources") or [])
        if "hcxdumptool" not in src:
            src.append("hcxdumptool")
        w["enrichment_sources"] = src
        ap["wps"] = w
    return aps


def _first(vals: list[str] | str | None) -> str | None:
    if isinstance(vals, list):
        return vals[0] if vals else None
    return vals


def _all(vals: list[str] | str | None) -> list[str]:
    if isinstance(vals, list):
        return vals
    if vals:
        return [vals]
    return []


def _bool_field(val: str | list | None) -> bool | None:
    v = _first(val) if isinstance(val, list) else val
    if v is None:
        return None
    return v in ("1", "true", "True")


def run_tshark(pcap_path: Path) -> list[dict]:
    """Run tshark on pcap, extract beacon/probe response fields as JSON."""
    if not pcap_path.exists() or pcap_path.stat().st_size == 0:
        return []

    cmd = [
        "tshark", "-r", str(pcap_path),
        "-Y", "wlan.fc.type_subtype == 0x08 || wlan.fc.type_subtype == 0x05",
        "-T", "ek",
    ]
    for field in TSHARK_FIELDS:
        cmd.extend(["-e", field])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(f"[parser] tshark error: {r.stderr[:500]}", file=sys.stderr)
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f"[parser] tshark failed: {e}", file=sys.stderr)
        return []

    packets: list[dict] = []
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "layers" in obj:
                packets.append(obj["layers"])
        except json.JSONDecodeError:
            continue

    return packets


def _extract_tagged_params(layers: dict) -> dict:
    """Build tagged_params dict from tshark layers."""
    rsn_gcs_vals = _all(layers.get("wlan_rsn_gcs_type"))
    rsn_pcs_vals = _all(layers.get("wlan_rsn_pcs_type"))
    rsn_akm_vals = _all(layers.get("wlan_rsn_akms_type"))
    mfpc = _bool_field(layers.get("wlan_rsn_capabilities_mfpc"))
    mfpr = _bool_field(layers.get("wlan_rsn_capabilities_mfpr"))

    rsn = None
    if rsn_akm_vals or rsn_pcs_vals or rsn_gcs_vals:
        rsn = {
            "group_cipher": CIPHER_SUITE_NAMES.get(rsn_gcs_vals[0], rsn_gcs_vals[0]) if rsn_gcs_vals else None,
            "pairwise_ciphers": [CIPHER_SUITE_NAMES.get(v, v) for v in rsn_pcs_vals],
            "akm_suites": [AKM_SUITE_NAMES.get(v, v) for v in rsn_akm_vals],
            "mfp_capable": mfpc,
            "mfp_required": mfpr,
        }

    ht_cap = _first(layers.get("wlan_ht_capabilities"))
    vht_cap = _first(layers.get("wlan_vht_capabilities"))
    country = _first(layers.get("wlan_country_info_code"))

    return {
        "rsn": rsn,
        "ht_capabilities": ht_cap,
        "vht_capabilities": vht_cap,
        "country": country,
    }


def _extract_wps(layers: dict) -> dict | None:
    wps_state = _first(layers.get("wps_wifi_protected_setup_state"))
    if not wps_state:
        return None

    return {
        "enabled": wps_state in ("1", "2"),
        "configured": wps_state == "2",
        "version": _first(layers.get("wps_version")),
        "locked": _bool_field(layers.get("wps_ap_setup_locked")) or False,
        "device_name": _first(layers.get("wps_device_name")),
        "manufacturer": _first(layers.get("wps_manufacturer")),
        "model_name": _first(layers.get("wps_model_name")),
        "model_number": _first(layers.get("wps_model_number")),
        "serial_number": _first(layers.get("wps_serial_number")),
        "enrichment_sources": ["tshark"],
    }


def _derive_security_info(tagged_params: dict, wps: dict | None, csv_ap: dict) -> dict:
    """Derive simplified security analysis from tagged params and CSV data."""
    rsn = (tagged_params or {}).get("rsn")

    enc_raw = (csv_ap.get("privacy") or "").strip()
    display_sec = compute_display_security(csv_ap, tagged_params or {}, wps)

    cipher = csv_ap.get("cipher") or ""
    akm = csv_ap.get("auth") or ""
    pmf = "none"

    if rsn:
        akm_suites = rsn.get("akm_suites", [])
        pairwise = rsn.get("pairwise_ciphers", [])
        if akm_suites:
            akm = ", ".join(akm_suites)
        if pairwise:
            cipher = ", ".join(pairwise)
        if rsn.get("mfp_required"):
            pmf = "required"
        elif rsn.get("mfp_capable"):
            pmf = "capable"

    wps_enabled = bool(wps and wps.get("enabled"))
    wps_locked = bool(wps and wps.get("locked"))

    vulnerabilities: list[str] = []

    if rsn:
        akm_suites = rsn.get("akm_suites", [])
        if any(a in ("PSK", "SAE", "FT-PSK", "FT-SAE") for a in akm_suites):
            vulnerabilities.append("pmkid_possible")
        if pmf != "required":
            vulnerabilities.append("deauth_possible")
        pairwise = rsn.get("pairwise_ciphers", [])
        if "TKIP" in pairwise and "CCMP" in pairwise:
            vulnerabilities.append("downgrade_possible")
    else:
        if display_sec != "Open":
            vulnerabilities.append("deauth_possible")

    eru = enc_raw.upper()
    if not rsn and "WPA" in eru and "WPA2" not in eru and "WPA3" not in eru:
        vulnerabilities.append("legacy_wpa")

    if "WEP" in display_sec or "WEP" in eru:
        vulnerabilities.append("wep_crackable")

    if wps_enabled and not wps_locked:
        vulnerabilities.append("wps_brute_force")

    return {
        "encryption": display_sec,
        "display_security": display_sec,
        "cipher": cipher,
        "akm": akm,
        "pmf": pmf,
        "wps_enabled": wps_enabled,
        "wps_locked": wps_locked,
        "vulnerabilities": vulnerabilities,
    }


def enrich_aps_with_tshark(aps: list[dict], pcap_path: Path) -> list[dict]:
    """Enrich AP list with tagged params and WPS data from pcap via tshark (без финального security_info)."""
    packets = run_tshark(pcap_path)
    ie_by_bssid: dict[str, dict] = {}
    for layers in packets:
        bssid_raw = _first(layers.get("wlan_bssid"))
        if not bssid_raw:
            continue
        bssid = bssid_raw.upper().replace("-", ":")
        ie_by_bssid[bssid] = layers

    for ap in aps:
        layers = ie_by_bssid.get(ap["bssid"])
        if layers:
            ap["tagged_params"] = _extract_tagged_params(layers)
            ap["wps"] = _extract_wps(layers)
        else:
            ap["tagged_params"] = None
    return aps


def finalize_aps_security(aps: list[dict]) -> list[dict]:
    """После merge wash/hcx - единый security_info."""
    for ap in aps:
        tp = ap.get("tagged_params") or {}
        ap["security_info"] = _derive_security_info(tp, ap.get("wps"), ap)
    return aps


# ---------------------------------------------------------------------------
# Merge & output
# ---------------------------------------------------------------------------

def build_recon_json(
    aps: list[dict],
    stas: list[dict],
    scan_id: str,
    started_at: str,
    scan_mode: str,
    interface: str,
    bands: str,
) -> dict:
    """Build the final recon.json structure."""
    bssid_to_clients: dict[str, list[str]] = {}
    unassociated: list[dict] = []

    for sta in stas:
        assoc = sta.get("associated_bssid")
        if assoc:
            bssid_to_clients.setdefault(assoc, []).append(sta["mac"])
        else:
            unassociated.append(sta)

    for ap in aps:
        clients_from_stas = bssid_to_clients.get(ap["bssid"], [])
        ap["clients"] = clients_from_stas
        ap["client_count"] = len(clients_from_stas)

    associated_count = sum(1 for s in stas if s.get("associated_bssid"))

    return {
        "scan_id": scan_id,
        "started_at": started_at,
        "stopped_at": None,
        "is_running": True,
        "scan_mode": scan_mode,
        "interface": interface,
        "bands": bands,
        "stats": {
            "ap_count": len(aps),
            "sta_count": len(stas),
            "associated_count": associated_count,
            "unassociated_count": len(stas) - associated_count,
            "last_parsed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "aps": aps,
        "stas": stas,
        "unassociated_stas": unassociated,
    }


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: tmpfile + rename."""
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.rename(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_mac_filter(filter_path: str) -> set[str]:
    """Load MAC addresses from a file (one per line), return uppercase set."""
    macs: set[str] = set()
    try:
        for line in Path(filter_path).read_text(encoding="utf-8").splitlines():
            mac = line.strip().upper()
            if mac and len(mac) == 17:
                macs.add(mac)
    except OSError:
        pass
    return macs


def apply_mac_filter(
    aps: list[dict],
    stas: list[dict],
    filter_type: str,
    filter_macs: set[str],
) -> tuple[list[dict], list[dict]]:
    """Filter APs by BSSID and remove STAs associated with excluded APs."""
    if not filter_macs:
        return aps, stas

    if filter_type == "whitelist":
        filtered_aps = [ap for ap in aps if ap["bssid"] in filter_macs]
    else:
        filtered_aps = [ap for ap in aps if ap["bssid"] not in filter_macs]

    kept_bssids = {ap["bssid"] for ap in filtered_aps}
    filtered_stas = [
        sta for sta in stas
        if not sta.get("associated_bssid") or sta["associated_bssid"] in kept_bssids
    ]

    return filtered_aps, filtered_stas


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse airodump CSV + tshark pcap -> recon.json")
    parser.add_argument("--scan-dir", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--pcap", required=True)
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--scan-mode", default="continuous")
    parser.add_argument("--interface", default="")
    parser.add_argument("--bands", default="abg")
    parser.add_argument("--mac-filter", default=None, help="Path to mac_filter.txt")
    parser.add_argument("--mac-filter-type", default=None, choices=["whitelist", "blacklist"])
    args = parser.parse_args()

    scan_dir = Path(args.scan_dir)
    csv_path = Path(args.csv)
    pcap_path = Path(args.pcap)

    aps, stas = parse_airodump_csv(csv_path)
    aps = enrich_aps_with_tshark(aps, pcap_path)
    wash_map = run_wash_on_pcap(pcap_path)
    aps = merge_wash_into_aps(aps, wash_map)
    aps = finalize_aps_security(aps)

    if args.mac_filter and args.mac_filter_type:
        filter_macs = load_mac_filter(args.mac_filter)
        if filter_macs:
            aps, stas = apply_mac_filter(aps, stas, args.mac_filter_type, filter_macs)

    recon = build_recon_json(
        aps=aps,
        stas=stas,
        scan_id=args.scan_id,
        started_at=args.started_at,
        scan_mode=args.scan_mode,
        interface=args.interface,
        bands=args.bands,
    )

    recon_path = scan_dir / "recon.json"
    atomic_write_json(recon_path, recon)

    ap_count = len(aps)
    sta_count = len(stas)
    print(f"[parser] recon.json: {ap_count} APs, {sta_count} STAs", file=sys.stderr)


if __name__ == "__main__":
    main()
