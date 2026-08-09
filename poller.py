#!/usr/bin/env python3
"""
Sabarimala Risk Poller + WhatsApp + Route Monitoring
Comprehensive monitoring for Chennai → Sabarimala pilgrimage route.
Sources: Sachet/NDMA, IMD, GSI Bhusanket, Kerala SDMA, INCOIS, CWC, Open-Meteo.
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from pathlib import Path

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("riskpoller")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class DistrictState:
    level: str
    since: Optional[str]
    sources: List[str]
    rainfall_24h: float
    rainfall_3d: float
    rainfall_7d: float
    river_level: Optional[float]
    river_trend: str
    alert_text: str = ""
    landslide_risk: str = "low"

@dataclass
class Alert:
    source: str
    district: str
    severity: str
    title: str
    body: str
    timestamp: str
    url: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None

@dataclass
class RoutePoint:
    name: str
    lat: float
    lon: float
    district: str
    state: str
    type: str  # city | town | base | temple | pass | river
    river_station: Optional[str] = None

# ---------------------------------------------------------------------------
# State Manager
# ---------------------------------------------------------------------------
class StateManager:
    def __init__(self, path: str = "state.json"):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {
            "version": 2,
            "districts": {},
            "alerts": [],
            "source_hashes": {},
            "notifications_sent": [],
            "route_points": {}
        }

    def save(self):
        self.data["last_run"] = datetime.now(timezone.utc).isoformat()
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    def get_hash(self, source: str) -> Optional[str]:
        return self.data.get("source_hashes", {}).get(source)

    def set_hash(self, source: str, h: str):
        self.data.setdefault("source_hashes", {})[source] = h

    def get_district(self, name: str) -> dict:
        return self.data.setdefault("districts", {}).setdefault(name, {
            "level": "green", "since": None, "sources": [],
            "rainfall_24h": 0.0, "rainfall_3d": 0.0, "rainfall_7d": 0.0,
            "river_level": None, "river_trend": "steady", "landslide_risk": "low"
        })

    def set_district(self, name: str, state: dict):
        self.data["districts"][name] = state

    def add_alert(self, alert: Alert):
        self.data.setdefault("alerts", []).insert(0, asdict(alert))
        self.data["alerts"] = self.data["alerts"][:300]

    def was_notified(self, key: str, within_minutes: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        sent = self.data.setdefault("notifications_sent", [])
        for item in list(sent):
            ts = datetime.fromisoformat(item["at"])
            if now - ts > timedelta(minutes=within_minutes * 2):
                sent.remove(item)
        for item in sent:
            if item["key"] == key:
                ts = datetime.fromisoformat(item["at"])
                if now - ts < timedelta(minutes=within_minutes):
                    return True
        return False

    def mark_notified(self, key: str):
        self.data.setdefault("notifications_sent", []).append({
            "key": key, "at": datetime.now(timezone.utc).isoformat()
        })

# ---------------------------------------------------------------------------
# Notifiers
# ---------------------------------------------------------------------------
class TelegramNotifier:
    def __init__(self, cfg: dict):
        self.token = cfg.get("bot_token", "")
        self.chat_id = cfg.get("chat_id", "")

    def send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=30)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

class NtfyNotifier:
    def __init__(self, topic: str):
        self.topic = topic

    def send(self, title: str, body: str, priority: int = 3) -> bool:
        if not self.topic:
            return False
        url = f"https://ntfy.sh/{self.topic}"
        headers = {"Title": title, "Priority": str(priority)}
        try:
            r = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=30)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"ntfy send failed: {e}")
            return False

class WhatsAppNotifier:
    def __init__(self, cfg: dict):
        self.enabled = cfg.get("enabled", False)
        self.mode = cfg.get("mode", "click_to_chat")
        self.access_token = cfg.get("access_token", "")
        self.phone_number_id = cfg.get("phone_number_id", "")
        self.recipient_phone = cfg.get("recipient_phone", "")
        self.webhook_url = cfg.get("webhook_url", "")
        self.webhook_secret = cfg.get("webhook_secret", "")
        self.click_to_chat_number = cfg.get("click_to_chat_number", "")

    def _cloud_api(self, message: str) -> bool:
        if not all([self.access_token, self.phone_number_id, self.recipient_phone]):
            logger.warning("WhatsApp Cloud API not fully configured")
            return False
        url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.recipient_phone,
            "type": "text",
            "text": {"body": message}
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                logger.info("WhatsApp Cloud API message sent")
                return True
            else:
                logger.error(f"WhatsApp Cloud API error: {r.status_code} {r.text}")
                return False
        except Exception as e:
            logger.error(f"WhatsApp Cloud API failed: {e}")
            return False

    def _webhook_relay(self, message: str, title: str = "") -> bool:
        if not self.webhook_url:
            return False
        payload = {
            "phone": self.recipient_phone or self.click_to_chat_number,
            "message": message,
            "title": title,
            "secret": self.webhook_secret
        }
        try:
            r = requests.post(self.webhook_url, json=payload, timeout=30)
            return r.status_code in (200, 202)
        except Exception as e:
            logger.error(f"WhatsApp webhook relay failed: {e}")
            return False

    def _click_to_chat_url(self, message: str) -> str:
        import urllib.parse
        number = self.click_to_chat_number or self.recipient_phone
        if not number:
            return ""
        encoded = urllib.parse.quote(message)
        return f"https://wa.me/{number}?text={encoded}"

    def send(self, alert: Alert) -> bool:
        if not self.enabled:
            return False
        emoji = {"green": "🟢", "orange": "🟠", "red": "🔴"}
        em = emoji.get(alert.severity, "⚪")
        message = f"{em} *{alert.district}* — {alert.severity.upper()}\n"
        message += f"*{alert.title}*\n"
        message += f"{alert.body}"

        if self.mode == "cloud_api":
            return self._cloud_api(message)
        elif self.mode == "webhook_relay":
            return self._webhook_relay(message, alert.title)
        elif self.mode == "click_to_chat":
            url = self._click_to_chat_url(message)
            if url:
                logger.info(f"WhatsApp click-to-chat URL: {url}")
                print(f"::notice::WhatsApp share URL: {url}")
            return False
        return False

    def send_digest(self, states: Dict[str, DistrictState]) -> bool:
        if not self.enabled or self.mode != "cloud_api":
            return False
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"📋 Daily Digest — {now}"]
        for dname, st in states.items():
            em = {"green": "🟢", "orange": "🟠", "red": "🔴"}.get(st.level, "⚪")
            lines.append(f"{em} {dname}: {st.level.upper()} | 24h: {st.rainfall_24h:.1f}mm | 3d: {st.rainfall_3d:.1f}mm")
        return self._cloud_api("\n".join(lines))

class Notifier:
    def __init__(self, cfg: dict):
        self.telegram = TelegramNotifier(cfg.get("telegram", {}))
        self.ntfy = NtfyNotifier(cfg.get("ntfy", {}).get("topic", ""))
        self.whatsapp = WhatsAppNotifier(cfg.get("whatsapp", {}))

    def notify(self, alert: Alert, state_mgr: StateManager):
        key = f"{alert.source}:{alert.district}:{alert.severity}:{alert.title[:40]}"
        if state_mgr.was_notified(key, within_minutes=30):
            logger.info(f"De-duped: {key}")
            return

        emoji = {"green": "🟢", "orange": "🟠", "red": "🔴"}
        em = emoji.get(alert.severity, "⚪")
        text = f"{em} *{alert.district}* — {alert.severity.upper()}\n"
        text += f"*{alert.title}*\n"
        text += f"{alert.body}\n"
        if alert.url:
            text += f"[Source]({alert.url})"

        sent = False
        if self.telegram.send(text):
            sent = True
        if self.whatsapp.send(alert):
            sent = True
        if not sent:
            pri = {"green": 1, "orange": 3, "red": 5}.get(alert.severity, 3)
            self.ntfy.send(f"{alert.district}: {alert.severity.upper()}", f"{alert.title}\n{alert.body}", pri)

        state_mgr.mark_notified(key)

    def daily_digest(self, states: Dict[str, DistrictState], state_mgr: StateManager):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"📋 *Daily Digest* — {now}\n"]
        for dname, st in states.items():
            em = {"green": "🟢", "orange": "🟠", "red": "🔴"}.get(st.level, "⚪")
            lines.append(f"{em} *{dname}*: {st.level.upper()} | 24h: {st.rainfall_24h:.1f}mm | 3d: {st.rainfall_3d:.1f}mm | Landslide: {st.landslide_risk}")
        text = "\n".join(lines)
        self.telegram.send(text)
        self.whatsapp.send_digest(states)
        state_mgr.data["last_digest"] = datetime.now(timezone.utc).isoformat()

# ---------------------------------------------------------------------------
# Source Pollers
# ---------------------------------------------------------------------------
class SachetPoller:
    """NDMA Sachet CAP/XML feed — national disaster alerts."""
    URL = "https://sachet.ndma.gov.in/cap_public_website/Feeds/atom"

    def poll(self) -> List[Alert]:
        alerts = []
        try:
            r = requests.get(self.URL, timeout=30)
            r.raise_for_status()
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.content)
            ns = {"atom": "http://www.w3.org/2005/Atom", "cap": "urn:oasis:names:tc:emergency:cap:1.2"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "", ns)
                summary = entry.findtext("atom:summary", "", ns)
                updated = entry.findtext("atom:updated", "", ns)
                relevant = any(x in title + summary for x in [
                    "Kerala", "Tamil Nadu", "Idukki", "Pathanamthitta", "Theni",
                    "Kottayam", "Ernakulam", "Chennai", "landslide", "heavy rain",
                    "flood", "thunderstorm", "cyclone", "flash flood"
                ])
                if not relevant:
                    continue
                severity = "orange"
                if any(x in title.lower() for x in ["red", "extreme", "severe"]):
                    severity = "red"
                elif any(x in title.lower() for x in ["green", "low", "minor"]):
                    severity = "green"
                district = None
                for d in ["Idukki", "Pathanamthitta", "Theni", "Kottayam", "Ernakulam", "Chennai"]:
                    if d.lower() in (title + summary).lower():
                        district = d
                        break
                if not district:
                    district = "Kerala"
                alerts.append(Alert(
                    source="sachet", district=district, severity=severity,
                    title=title[:120], body=summary[:400], timestamp=updated,
                    url="https://sachet.ndma.gov.in"
                ))
        except Exception as e:
            logger.error(f"Sachet poll failed: {e}")
        return alerts

    def content_hash(self) -> str:
        try:
            r = requests.get(self.URL, timeout=30)
            return hashlib.sha256(r.content).hexdigest()[:16]
        except Exception:
            return ""

class IMDPoller:
    """
    IMD district warnings — uses both district warning page and nowcast page.
    Also checks subdivision rainfall forecast for Kerala/Tamil Nadu.
    """
    WARNING_URL = "https://mausam.imd.gov.in/imd_latest/contents/districtwise-warning.php"
    NOWCAST_URL = "https://mausam.imd.gov.in/imd_latest/contents/districtwise-nowcast.php"
    SUBDIV_URL = "https://mausam.imd.gov.in/imd_latest/contents/subdivisionwise-warning.php"

    DISTRICTS = ["Idukki", "Pathanamthitta", "Theni", "Kottayam", "Ernakulam", "Chennai"]

    def _scrape_page(self, url: str) -> str:
        try:
            r = requests.get(url, timeout=30)
            return r.text
        except Exception as e:
            logger.error(f"IMD scrape failed for {url}: {e}")
            return ""

    def _parse_warnings(self, text: str, page_name: str) -> List[Alert]:
        alerts = []
        for district in self.DISTRICTS:
            idx = text.lower().find(district.lower())
            if idx == -1:
                continue
            snippet = text[max(0, idx-300):idx+300]
            severity = "green"
            if "red" in snippet.lower():
                severity = "red"
            elif "orange" in snippet.lower():
                severity = "orange"
            elif "yellow" in snippet.lower():
                severity = "orange"
            if severity != "green":
                # Try to extract warning text
                warning_text = ""
                if "heavy rain" in snippet.lower():
                    warning_text = "Heavy rainfall expected"
                elif "thunderstorm" in snippet.lower():
                    warning_text = "Thunderstorm warning"
                elif "landslide" in snippet.lower():
                    warning_text = "Landslide risk"
                alerts.append(Alert(
                    source=f"imd_{page_name}", district=district, severity=severity,
                    title=f"IMD {page_name}: {district}",
                    body=warning_text or f"District warning level: {severity}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    url=self.WARNING_URL
                ))
        return alerts

    def poll(self) -> List[Alert]:
        alerts = []
        for url, name in [(self.WARNING_URL, "warning"), (self.NOWCAST_URL, "nowcast"), (self.SUBDIV_URL, "subdivision")]:
            text = self._scrape_page(url)
            alerts.extend(self._parse_warnings(text, name))
        return alerts

    def content_hash(self) -> str:
        try:
            texts = []
            for url in [self.WARNING_URL, self.NOWCAST_URL, self.SUBDIV_URL]:
                r = requests.get(url, timeout=30)
                texts.append(r.text)
            combined = "".join(texts)
            return hashlib.sha256(combined.encode()).hexdigest()[:16]
        except Exception:
            return ""

class GSIPoller:
    """GSI landslide bulletins — Bhusanket portal + Bhooskhalan app data."""
    PORTAL_URL = "https://www.gsi.gov.in/webcenter/portal/GeologicalSurveyofIndia/pages_bhukamp"
    BHOOSKHALAN_URL = "https://bhukamp.gsi.gov.in/"

    def poll(self) -> List[Alert]:
        alerts = []
        keywords = ["Idukki", "Pathanamthitta", "Kerala", "Tamil Nadu", "landslide", "Landslide", "Western Ghats"]
        landslide_keywords = ["landslide", "Landslide", "rockfall", "mudslide", "debris flow", "slope failure"]

        for url in [self.PORTAL_URL, self.BHOOSKHALAN_URL]:
            try:
                r = requests.get(url, timeout=30)
                text = r.text
                if any(k in text for k in keywords):
                    severity = "orange"
                    if any(lk in text for lk in landslide_keywords):
                        # Check for high-risk language
                        if any(x in text.lower() for x in ["high risk", "very high", "critical", "red zone"]):
                            severity = "red"
                        alerts.append(Alert(
                            source="gsi", district="Idukki", severity=severity,
                            title="GSI Landslide Bulletin Updated",
                            body="GSI portal has new landslide-related content for Western Ghats region. Review bulletin for district-specific details.",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            url=url
                        ))
                        # Also check for Pathanamthitta specifically
                        if "pathanamthitta" in text.lower() or "sabarimala" in text.lower():
                            alerts.append(Alert(
                                source="gsi", district="Pathanamthitta", severity=severity,
                                title="GSI: Sabarimala Route Landslide Alert",
                                body="Landslide bulletin mentions Sabarimala pilgrimage route or Pathanamthitta district.",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                url=url
                            ))
            except Exception as e:
                logger.error(f"GSI poll failed for {url}: {e}")
        return alerts

    def content_hash(self) -> str:
        try:
            texts = []
            for url in [self.PORTAL_URL, self.BHOOSKHALAN_URL]:
                r = requests.get(url, timeout=30)
                texts.append(r.text)
            combined = "".join(texts)
            return hashlib.sha256(combined.encode()).hexdigest()[:16]
        except Exception:
            return ""

class KeralaSDMAPoller:
    """Kerala SDMA daily bulletins + specific landslide alerts."""
    URL = "https://sdma.kerala.gov.in/"
    LANDSLIDE_URL = "https://sdma.kerala.gov.in/landslide/"

    def poll(self) -> List[Alert]:
        alerts = []
        districts = ["Idukki", "Pathanamthitta", "Kottayam", "Ernakulam"]
        for url in [self.URL, self.LANDSLIDE_URL]:
            try:
                r = requests.get(url, timeout=30)
                text = r.text
                for district in districts:
                    if district.lower() not in text.lower():
                        continue
                    snippet = text.lower()
                    severity = "green"
                    if any(w in snippet for w in ["red alert", "extreme", "severe"]):
                        severity = "red"
                    elif any(w in snippet for w in ["orange", "warning", "caution", "heavy rain", "landslide"]):
                        severity = "orange"
                    if severity != "green":
                        body = "SDMA bulletin contains warnings for district."
                        if "landslide" in snippet:
                            body = "Landslide warning issued for district."
                        alerts.append(Alert(
                            source="kerala_sdma", district=district, severity=severity,
                            title=f"Kerala SDMA: {district} Alert",
                            body=body,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            url=url
                        ))
            except Exception as e:
                logger.error(f"Kerala SDMA poll failed: {e}")
        return alerts

    def content_hash(self) -> str:
        try:
            texts = []
            for url in [self.URL, self.LANDSLIDE_URL]:
                r = requests.get(url, timeout=30)
                texts.append(r.text)
            combined = "".join(texts)
            return hashlib.sha256(combined.encode()).hexdigest()[:16]
        except Exception:
            return ""

class INCOISPoller:
    """INCOIS — Indian National Centre for Ocean Information Services.
    Monitors coastal swell (Kallakkadal) and high wave alerts for Kerala coast."""
    URL = "https://incois.gov.in/portal/osf/osf.jsp"
    ALERT_URL = "https://incois.gov.in/portal/osf/kallakkadal.jsp"

    def poll(self) -> List[Alert]:
        alerts = []
        try:
            r = requests.get(self.URL, timeout=30)
            text = r.text
            # Check for Kerala coastal alerts
            kerala_keywords = ["Kerala", "Kollam", "Alappuzha", "Thiruvananthapuram", "Kochi", "Kozhikode"]
            if any(k in text for k in kerala_keywords):
                # Check for Kallakkadal or high wave warnings
                if any(w in text.lower() for w in ["kallakkadal", "high wave", "rough sea", "swell", "coastal"]):
                    severity = "orange"
                    if any(w in text.lower() for w in ["red", "extreme", "severe", "dangerous"]):
                        severity = "red"
                    alerts.append(Alert(
                        source="incois", district="Pathanamthitta", severity=severity,
                        title="INCOIS: Kerala Coastal Alert",
                        body="Coastal swell or high wave warning for Kerala. Pilgrims traveling via coastal routes should exercise caution.",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        url=self.URL
                    ))
        except Exception as e:
            logger.error(f"INCOIS poll failed: {e}")
        return alerts

    def content_hash(self) -> str:
        try:
            r = requests.get(self.URL, timeout=30)
            return hashlib.sha256(r.content).hexdigest()[:16]
        except Exception:
            return ""

class CWCPoller:
    """Central Water Commission — river level monitoring.
    Checks CWC flood forecasting portal for key rivers."""
    FLOOD_URL = "https://ffs.india-water.gov.in/"
    # Key stations along the route
    STATIONS = {
        "Periyar": {"district": "Idukki", "station_code": None},
        "Pamba": {"district": "Pathanamthitta", "station_code": None},
        "Vaigai": {"district": "Theni", "station_code": None},
    }

    def poll(self) -> List[Alert]:
        alerts = []
        try:
            r = requests.get(self.FLOOD_URL, timeout=30)
            text = r.text.lower()
            # Look for flood warnings related to our rivers/districts
            river_keywords = ["periyar", "pamba", "vaigai", "idukki", "pathanamthitta", "theni"]
            if any(k in text for k in river_keywords):
                if any(w in text for w in ["flood", "above danger", "warning", "alert", "high level"]):
                    alerts.append(Alert(
                        source="cwc", district="Idukki", severity="orange",
                        title="CWC: River Level Alert",
                        body="Central Water Commission reports elevated river levels in the Western Ghats region. Check specific station data.",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        url=self.FLOOD_URL
                    ))
        except Exception as e:
            logger.error(f"CWC poll failed: {e}")
        return alerts

    def content_hash(self) -> str:
        try:
            r = requests.get(self.FLOOD_URL, timeout=30)
            return hashlib.sha256(r.content).hexdigest()[:16]
        except Exception:
            return ""

class OpenMeteoPoller:
    """Open-Meteo forecast + accumulated rainfall for route points."""
    API = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, districts_cfg: List[dict], route_points: List[RoutePoint]):
        self.districts_cfg = districts_cfg
        self.route_points = route_points

    def poll(self) -> Tuple[Dict[str, dict], Dict[str, dict]]:
        """Returns (district_rainfall, point_rainfall)"""
        district_results = {}
        point_results = {}

        # District-level aggregation
        for dist_cfg in self.districts_cfg:
            dname = dist_cfg["name"]
            total_24h = 0.0
            total_3d = 0.0
            total_7d = 0.0
            for loc in dist_cfg.get("locations", []):
                try:
                    params = {
                        "latitude": loc["lat"],
                        "longitude": loc["lon"],
                        "daily": "precipitation_sum",
                        "forecast_days": 7,
                        "timezone": "Asia/Kolkata"
                    }
                    r = requests.get(self.API, params=params, timeout=30)
                    data = r.json()
                    daily = data.get("daily", {}).get("precipitation_sum", [])
                    if len(daily) >= 4:
                        total_24h += daily[1]
                        total_3d += sum(daily[1:4])
                    if len(daily) >= 8:
                        total_7d += sum(daily[1:8])
                except Exception as e:
                    logger.error(f"Open-Meteo failed for {loc['name']}: {e}")
            district_results[dname] = {
                "rainfall_24h": total_24h,
                "rainfall_3d": total_3d,
                "rainfall_7d": total_7d
            }

        # Route point-level
        for pt in self.route_points:
            try:
                params = {
                    "latitude": pt.lat,
                    "longitude": pt.lon,
                    "daily": "precipitation_sum",
                    "forecast_days": 7,
                    "timezone": "Asia/Kolkata"
                }
                r = requests.get(self.API, params=params, timeout=30)
                data = r.json()
                daily = data.get("daily", {}).get("precipitation_sum", [])
                point_results[pt.name] = {
                    "lat": pt.lat,
                    "lon": pt.lon,
                    "district": pt.district,
                    "type": pt.type,
                    "rainfall_24h": daily[1] if len(daily) >= 2 else 0,
                    "rainfall_3d": sum(daily[1:4]) if len(daily) >= 4 else 0,
                    "rainfall_7d": sum(daily[1:8]) if len(daily) >= 8 else 0,
                }
            except Exception as e:
                logger.error(f"Open-Meteo failed for route point {pt.name}: {e}")

        return district_results, point_results

    def content_hash(self, results: dict) -> str:
        return hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Risk Aggregator
# ---------------------------------------------------------------------------
class RiskAggregator:
    def __init__(self, cfg: dict):
        self.thresholds = cfg.get("thresholds", {})
        self.districts_cfg = cfg.get("districts", [])

    def compute(self, rainfall: Dict[str, dict], alerts: List[Alert], point_rainfall: Dict[str, dict]) -> Dict[str, DistrictState]:
        states = {}

        # Initialize from rainfall
        for dist_cfg in self.districts_cfg:
            dname = dist_cfg["name"]
            rain = rainfall.get(dname, {"rainfall_24h": 0, "rainfall_3d": 0, "rainfall_7d": 0})
            level = "green"
            landslide = "low"

            # Core thresholds
            if rain["rainfall_24h"] >= self.thresholds.get("daily_max", 115):
                level = "red"
                landslide = "high"
            elif rain["rainfall_3d"] >= self.thresholds.get("three_day_max", 200):
                level = "red"
                landslide = "high"
            elif rain["rainfall_7d"] >= self.thresholds.get("seven_day_max", 350):
                level = "red"
                landslide = "high"
            elif rain["rainfall_24h"] >= self.thresholds.get("daily_max", 115) * 0.7:
                level = "orange"
                landslide = "moderate"
            elif rain["rainfall_3d"] >= self.thresholds.get("three_day_max", 200) * 0.7:
                level = "orange"
                landslide = "moderate"

            states[dname] = DistrictState(
                level=level, since=datetime.now(timezone.utc).isoformat(),
                sources=["open_meteo"], rainfall_24h=rain["rainfall_24h"],
                rainfall_3d=rain["rainfall_3d"], rainfall_7d=rain.get("rainfall_7d", 0),
                river_level=None, river_trend="steady", alert_text="",
                landslide_risk=landslide
            )

        # Elevate based on external alerts
        for alert in alerts:
            dname = alert.district
            if dname not in states:
                continue
            current = states[dname]
            if alert.severity == "red" and current.level != "red":
                current.level = "red"
                current.sources.append(alert.source)
                current.alert_text = alert.title
                current.landslide_risk = "high"
            elif alert.severity == "orange" and current.level == "green":
                current.level = "orange"
                current.sources.append(alert.source)
                current.alert_text = alert.title
                if current.landslide_risk == "low":
                    current.landslide_risk = "moderate"

        # Check route point rainfall for granular alerts
        for pt_name, pt_data in point_rainfall.items():
            dname = pt_data.get("district", "")
            if dname not in states:
                continue
            st = states[dname]
            # If any point in district exceeds thresholds, elevate
            if pt_data.get("rainfall_24h", 0) >= self.thresholds.get("daily_max", 115):
                if st.level != "red":
                    st.level = "red"
                    st.sources.append("open_meteo_point")
                    st.alert_text = f"High rainfall at {pt_name}: {pt_data['rainfall_24h']:.1f}mm/24h"
                    st.landslide_risk = "high"

        return states

# ---------------------------------------------------------------------------
# Main Controller
# ---------------------------------------------------------------------------
class PollerApp:
    def __init__(self, config_path: str = "config.yaml", state_path: str = "state.json"):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        self.state = StateManager(state_path)
        self.notifier = Notifier(self.cfg)
        self.aggregator = RiskAggregator(self.cfg)

        # Build route points from config
        self.route_points = []
        for rp in self.cfg.get("route_points", []):
            self.route_points.append(RoutePoint(
                name=rp["name"],
                lat=rp["lat"],
                lon=rp["lon"],
                district=rp["district"],
                state=rp.get("state", ""),
                type=rp.get("type", "town"),
                river_station=rp.get("river_station")
            ))

        self.pollers = {
            "sachet": SachetPoller(),
            "imd": IMDPoller(),
            "gsi": GSIPoller(),
            "kerala_sdma": KeralaSDMAPoller(),
            "incois": INCOISPoller(),
            "cwc": CWCPoller(),
            "open_meteo": OpenMeteoPoller(
                self.cfg.get("districts", []),
                self.route_points
            ),
        }

    def run_risk_poller(self):
        logger.info("=== Risk Poller Run ===")
        all_alerts = []

        for name, poller in self.pollers.items():
            if not self.cfg.get("sources", {}).get(name, {}).get("enabled", True):
                continue
            new_hash = ""
            if name == "open_meteo":
                district_rain, point_rain = poller.poll()
                combined = {"districts": district_rain, "points": point_rain}
                new_hash = poller.content_hash(combined)
            else:
                new_hash = poller.content_hash()

            old_hash = self.state.get_hash(name)
            if old_hash and old_hash == new_hash:
                logger.info(f"{name}: no change")
                continue

            logger.info(f"{name}: content changed")
            self.state.set_hash(name, new_hash)

            if name == "open_meteo":
                self._rainfall_cache = district_rain
                self._point_rainfall_cache = point_rain
            else:
                alerts = poller.poll()
                for a in alerts:
                    all_alerts.append(a)
                    self.state.add_alert(a)

        rainfall = getattr(self, "_rainfall_cache", {})
        point_rainfall = getattr(self, "_point_rainfall_cache", {})
        if not rainfall and "open_meteo" in self.pollers:
            rainfall, point_rainfall = self.pollers["open_meteo"].poll()

        states = self.aggregator.compute(rainfall, all_alerts, point_rainfall)

        for dname, st in states.items():
            old = self.state.get_district(dname)
            old_level = old.get("level", "green")
            if st.level != old_level:
                logger.info(f"{dname}: {old_level} -> {st.level}")
                alert = Alert(
                    source="aggregator",
                    district=dname,
                    severity=st.level,
                    title=f"Risk Level Changed: {old_level} → {st.level}",
                    body=f"24h: {st.rainfall_24h:.1f}mm | 3d: {st.rainfall_3d:.1f}mm | 7d: {st.rainfall_7d:.1f}mm | Landslide: {st.landslide_risk} | Sources: {', '.join(set(st.sources))}",
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                self.state.add_alert(alert)
                if st.level == "red":
                    alert.title += " 🚨 DECIDE BY TONIGHT"
                self.notifier.notify(alert, self.state)
            self.state.set_district(dname, {
                "level": st.level,
                "since": st.since,
                "sources": list(set(st.sources)),
                "rainfall_24h": st.rainfall_24h,
                "rainfall_3d": st.rainfall_3d,
                "rainfall_7d": st.rainfall_7d,
                "river_level": st.river_level,
                "river_trend": st.river_trend,
                "alert_text": st.alert_text,
                "landslide_risk": st.landslide_risk
            })

        digest_hour = self.cfg.get("intervals", {}).get("digest_hour", 8)
        now = datetime.now(timezone.utc)
        last_digest = self.state.data.get("last_digest")
        if now.hour == digest_hour:
            if not last_digest or (datetime.fromisoformat(last_digest).day != now.day):
                self.notifier.daily_digest(states, self.state)

        self._write_pwa_data(states, all_alerts, point_rainfall)
        self.state.save()
        logger.info("=== Risk Poller Done ===")

    def _write_pwa_data(self, states: Dict[str, DistrictState], alerts: List[Alert], point_rainfall: Dict[str, dict]):
        pwa_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "districts": {k: {
                "level": v.level,
                "since": v.since,
                "sources": v.sources,
                "rainfall_24h": v.rainfall_24h,
                "rainfall_3d": v.rainfall_3d,
                "rainfall_7d": v.rainfall_7d,
                "river_level": v.river_level,
                "river_trend": v.river_trend,
                "alert_text": v.alert_text,
                "landslide_risk": v.landslide_risk
            } for k, v in states.items()},
            "route_points": point_rainfall,
            "latest_alerts": [asdict(a) for a in alerts[:30]],
            "all_alerts": [asdict(a) for a in alerts]
        }
        
        pwa_path = Path("data.json")

        with open(pwa_path, "w") as f:
            json.dump(pwa_data, f, indent=2)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = PollerApp()
    app.run_risk_poller()
