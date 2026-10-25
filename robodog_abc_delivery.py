import csv
import json
import math
import os
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from aigo_on_patrol import PatrolService, validate_route
from kocoafab_robodog import *

try:
    import serial as pyserial
except ImportError:
    pyserial = None

"""A/B/C 안부 카드 배송 데모.

클래스 매핑: CLASS1=장애물(멧돼지 등), CLASS2=A, CLASS3=B, CLASS4=C.
관제 보고는 로컬 파이썬 웹 서버를 통해 HTML 화면에 전송합니다.
QR은 RoboDog 공개 API로 읽습니다.
공개 API에 MP3 파일 재생 기능이 없어 현재는 내장 인사 소리로 대체합니다.
재난 라디오 게이트웨이의 EMERGENCY:E1/F1/G1/H1 신호는 배송 여부와 관계없이 수신하며, 로보독을 정지시키고 관제 명령을 기다립니다. 대피 안내 명령은 현재 배송 계획에 포함된 영향 지점을 방문해 빨간 LED와 짖기 소리로 알린 뒤 배송 경로를 이어갑니다.
"""

ROBOT_PORT = os.environ.get("ROBODOG_PORT", "None").strip() or "None"
SPEED = 50
CM_PER_SEC = 23.0
NORMAL_SCALE = 1.25
# Feedback: measured travel was short, so increase commanded travel time 2.5×.
# Adjust between 2.0 and 3.0 after checking the real course.
DRIVE_DISTANCE_MULTIPLIER = 2.5
GYRO_TOLERANCE = 1.5
MAX_ROTATE_ATTEMPTS = 4
GYRO_SAMPLE_COUNT = 5
GYRO_SAMPLE_DELAY = 0.015
STABILIZE_DELAY = 0.4
TURN_CHUNK_DEG = 15
TURN_SPEED = 40
POLL_INTERVAL = 0.1
PERSON_TIMEOUT = 60
QR_TIMEOUT = 60
QR_RETRIES = 3
EVACUATION_BARK_COUNT = 3
REDIRECT_REQUESTED = "REDIRECT"
RETURN_HOME_REQUESTED = "RETURN_HOME"
EMERGENCY_INTERRUPTED = "EMERGENCY_INTERRUPTED"
DELIVERY_SOUND_TRACK = 안녕
LOG_FILE = Path("pawcare_delivery_log.csv")
TILT_LOG_FILE = Path("pawcare_tilt_log.csv")
MICROBIT_SENSOR_LOG_FILE = Path("pawcare_microbit_sensor_log.csv")
TILT_UPDATE_INTERVAL = 0.5
# 정사각형 시험 코스: 변 길이와 회전각은 여기만 바꾸면 됩니다.
COURSE_SIDE_CM = 50
# 지도 원점은 왼쪽 위, +X는 처음 향한 방향, +Y는 지도 아래쪽입니다.
SQUARE_MAP_POINTS = [
    (COURSE_SIDE_CM, 0),
    (COURSE_SIDE_CM, COURSE_SIDE_CM),
    (0, COURSE_SIDE_CM),
    (0, 0),
]
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8765
try:
    # 일반 .py 실행에서는 스크립트 폴더를 기준으로 관제 HTML을 찾습니다.
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    # Thonny의 Run -c $EDITOR_CONTENT 실행에는 __file__이 없을 수 있습니다.
    working_dir = Path.cwd()
    dashboard_dirs = (
        working_dir,
        working_dir / "outputs",
        working_dir / "PawCare_Thonny_관제_패키지",
        working_dir / "pawcare_control_bundle",
    )
    SCRIPT_DIR = next(
        (folder for folder in dashboard_dirs if (folder / "pawcare_control.html").is_file()),
        working_dir,
    )
DASHBOARD_FILE = SCRIPT_DIR / "pawcare_control.html"
LOG_FILE = SCRIPT_DIR / "pawcare_delivery_log.csv"
# Read newline-delimited emergency or observation packets from PC-attached
# micro:bit receivers. Set MICROBIT_PORTS=COM10,COM7 to listen to multiple
# groups with separate receiver micro:bits; MICROBIT_PORT remains supported.
_microbit_ports_setting = os.environ.get("MICROBIT_PORTS")
if _microbit_ports_setting is None:
    _microbit_ports_setting = os.environ.get("MICROBIT_PORT", "")
MICROBIT_PORTS = tuple(dict.fromkeys(
    port.strip() for port in _microbit_ports_setting.split(",") if port.strip()
))
MICROBIT_PORT = ", ".join(MICROBIT_PORTS)
MICROBIT_BAUDRATE = int(os.environ.get("MICROBIT_BAUDRATE", "115200"))
MICROBIT_RECONNECT_SECONDS = 2.0
OBSERVATION_TIMEOUT = 3.0
OBSERVATION_STATIONS = {"1": ("A", "B"), "2": ("B", "C")}
FIRE_ACTIVE = int(os.environ.get("ROBODOG_FLAME_ACTIVE_LEVEL", "1"))
GAS_ACTIVE = int(os.environ.get("ROBODOG_GAS_ACTIVE_LEVEL", "1"))
DISASTER_LABELS = {
    "EARTHQUAKE": "지진",
    "FIRE": "화재",
    "HEAT": "무더위",
    "GAS": "가스 유출",
}
DISASTER_ALIASES = {
    "E": "EARTHQUAKE", "EARTHQUAKE": "EARTHQUAKE", "QUAKE": "EARTHQUAKE", "지진": "EARTHQUAKE",
    "F": "FIRE", "FIRE": "FIRE", "화재": "FIRE",
    "H": "HEAT", "HEAT": "HEAT", "HOT": "HEAT", "무더위": "HEAT", "폭염": "HEAT",
    "G": "GAS", "GAS": "GAS", "GASLEAK": "GAS", "가스": "GAS", "가스유출": "GAS", "가스누출": "GAS",
}
EMERGENCY_AREAS = {
    "1": ("A", "B"),
    "2": ("B", "C"),
}
MAP_LOCATION_ALIASES = {
    "START": "start", "HOME": "start", "출발": "start", "출발점": "start",
    "A": "A", "A지역": "A", "A구역": "A",
    "B": "B", "B지역": "B", "B구역": "B",
    "C": "C", "C지역": "C", "C구역": "C",
}

TARGET_CLASS = {"A": 2, "B": 3, "C": 4}
AREA_NAME = {"A": "A 지역", "B": "B 지역", "C": "C 지역"}

# 사용자 코드에서 확인된 로보독 API 상수/호출을 사용합니다.
dog = RoboDog()
gyro_zero_offset = 0.0
current_heading = 0.0
map_x_cm = 0.0
map_y_cm = 0.0
tilt_roll_zero = 0.0
tilt_pitch_zero = 0.0
visit_id = ""
_last_tilt_log = 0.0
stop_requested = threading.Event()
hazard_resume = threading.Event()
hazard_resume.set()
emergency_hold = threading.Event()
emergency_decision_ready = threading.Event()
emergency_command_lock = threading.Lock()
pending_emergency_command = None
status_lock = threading.Lock()
status = {
    "robot_port": ROBOT_PORT, "bridge": "jeongseon-aigo-v1", "connected": False, "busy": False, "state": "대기", "current_area": "출발점",
    "ai_class": None, "roll": 0.0, "pitch": 0.0, "x_cm": 0.0, "y_cm": 0.0,
    "heading_deg": 0.0, "trail": [{"x": 0.0, "y": 0.0}],
    "course_width_cm": COURSE_SIDE_CM, "course_height_cm": COURSE_SIDE_CM,
    "course_points": {"start": [4, 4], "A": [46, 4], "B": [46, 46], "C": [4, 46]},
    "delivery_areas": [],
    "hazard_wait": False, "hazard_clear_confirmed": False,
    "can_redirect": False, "redirect_area": None,
    "microbit_connected": False, "microbit_port": MICROBIT_PORT or "미설정",
    "microbit_baudrate": MICROBIT_BAUDRATE,
    "microbit_status": "수신기 포트 미설정 · ON에서 수신기 연결", "microbit_last_rx": "",
    "microbit_sensor": None,
    "observation_stations": {"1": None, "2": None},
    "active_emergency": None, "active_emergencies": {}, "emergency_history": [],
    "emergency_waiting": False, "emergency_command": None,
    "last_evacuation_alert": None,
    "head_led_on": False, "head_led_mode": "꺼짐",
    "last_event_id": 0, "events": [],
}
job_thread = None
job_lock = threading.Lock()
log_lock = threading.Lock()
microbit_shutdown = threading.Event()
microbit_port_states = {}


def record(event, detail=""):
    with log_lock:
        new_file = not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0
        with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "visit_id", "event", "detail"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), visit_id, event, detail])


def load_run_history(limit=30):
    """Read and summarize recent delivery runs from the persistent CSV log."""
    with log_lock:
        if not LOG_FILE.is_file():
            return []
        with LOG_FILE.open("r", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

    runs = {}
    for row in rows:
        run_id = (row.get("visit_id") or "").strip()
        event = (row.get("event") or "").strip()
        detail = (row.get("detail") or "").strip()
        timestamp = (row.get("time") or "").strip()
        if not run_id or not event:
            continue

        run = runs.setdefault(run_id, {
            "visit_id": run_id, "started_at": timestamp, "last_at": timestamp,
            "mode": "배송", "areas": [], "events": [], "_seen": set(),
        })
        duplicate_key = (timestamp, event, detail)
        if duplicate_key in run["_seen"]:
            continue
        run["_seen"].add(duplicate_key)
        run["last_at"] = timestamp or run["last_at"]
        run["events"].append({"time": timestamp, "event": event, "detail": detail})

        if event == "SEQUENTIAL_ROUTE_START":
            run["mode"] = "A→B→C 순차 배송"
        elif event in ("VISIT_START", "ROUTE_START") and run["mode"] == "배송":
            run["mode"] = "지역 선택 배송"
        if event == "RUN_START":
            if "순차" in detail:
                run["mode"] = "A→B→C 순차 배송"
            elif "선택" in detail:
                run["mode"] = "지역 선택 배송"
        if event == "ARRIVED":
            area = detail.upper()
            if area in TARGET_CLASS and area not in run["areas"]:
                run["areas"].append(area)

    with status_lock:
        active_visit = visit_id
        currently_busy = bool(status.get("busy"))

    summaries = []
    for run in runs.values():
        events = run["events"]
        event_names = {item["event"] for item in events}
        run_end = next((item["detail"] for item in reversed(events) if item["event"] == "RUN_END"), "")
        if run["visit_id"] == active_visit and currently_busy:
            outcome = "진행 중"
        elif "ERROR" in event_names:
            outcome = "오류"
        elif "USER_ABORT" in event_names or "ROUTE_ABORTED" in event_names:
            outcome = "중단"
        elif run_end in ("SEQUENTIAL_ROUTE_DONE", "RETURNED") or "SEQUENTIAL_ROUTE_DONE" in event_names or "RETURNED" in event_names:
            outcome = "완료 · 복귀"
        elif "RETURN_START" in event_names:
            outcome = "복귀 기록 확인 필요"
        else:
            outcome = "완료 기록 없음"
        summaries.append({
            "visit_id": run["visit_id"], "started_at": run["started_at"],
            "last_at": run["last_at"], "mode": run["mode"],
            "areas": run["areas"], "outcome": outcome, "events": events,
        })

    summaries.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    return summaries[:max(1, int(limit))]


def report_control_center(event, detail=""):
    """콘솔/CSV에 기록하고 로컬 HTML 관제 화면의 이벤트 피드에 반영."""
    print(f"\n[관제센터 보고] {event}: {detail}")
    record(event, detail)
    with status_lock:
        status["last_event_id"] += 1
        status["events"].append({
            "id": status["last_event_id"], "event": event, "detail": detail,
            "area": status.get("current_area"),
            "time": datetime.now().isoformat(timespec="seconds"),
        })
        status["events"] = status["events"][-40:]
        status["state"] = event


def update_status(**values):
    with status_lock:
        status.update(values)


def connect_robot(port=None):
    """Open the existing SDK session without starting movement."""
    global ROBOT_PORT
    with job_lock:
        if job_thread is not None and job_thread.is_alive():
            return False, "운행 중에는 연결 설정을 바꿀 수 없습니다."
        selected = str(port or ROBOT_PORT).upper().strip()
        if not re.fullmatch(r"COM[1-9][0-9]{0,3}", selected):
            return False, "COM8과 같은 포트 번호를 선택하세요."
        with status_lock:
            connected = bool(status.get("connected"))
        if connected:
            return (True, "이미 연결되어 있습니다.") if selected == ROBOT_PORT else (False, "연결을 해제한 뒤 포트를 변경하세요.")
        try:
            if not dog.Open(selected):
                try:
                    dog.Close()
                except Exception:
                    pass
                return False, f"{selected} 연결 실패. USB와 포트 사용 여부를 확인하세요."
            ROBOT_PORT = selected
            update_status(connected=True, robot_port=selected, state="연결 완료 · 배송 대기")
            return True, f"로보독 {selected} 연결 완료"
        except Exception as exc:
            try:
                dog.Close()
            except Exception:
                pass
            update_status(connected=False)
            return False, f"연결 오류: {exc}"


def disconnect_robot():
    with job_lock:
        if job_thread is not None and job_thread.is_alive():
            return False, "운행을 정지하고 종료된 뒤 연결을 해제하세요."
        try:
            with status_lock:
                connected = bool(status.get("connected"))
            if connected:
                dog.Close()
            update_status(connected=False, head_led_on=False, state="연결 해제")
            return True, "로보독 연결을 해제했습니다."
        except Exception as exc:
            return False, f"연결 해제 오류: {exc}"


on_service = PatrolService(lambda snapshot: update_status(on_patrol=snapshot))

def start_on_patrol(config):
    global job_thread
    config = validate_route(config)
    with job_lock:
        if job_thread is not None and job_thread.is_alive():
            return False, "OUT 또는 ON이 운행 중입니다. 먼저 정지하세요."
        with status_lock:
            connected = bool(status.get("connected"))
        if not connected:
            return False, "먼저 로보독 연결 버튼으로 연결하세요."
        dog.Close()
        update_status(connected=False, busy=True, state="ON 순찰로 제어권 전환 중")
        on_service.prepare()
        def worker():
            try:
                on_service.run(ROBOT_PORT, config)
            finally:
                update_status(connected=False, busy=False, state="ON 순찰 종료 · 로보독 재연결 가능")
        job_thread = threading.Thread(target=worker, daemon=True)
        job_thread.start()
        return True, "ON 순찰을 시작합니다."


def start_delivery_job(mode, area, side_x, side_y, course_points):
    """Start a job through one lock shared by dashboard and micro:bit commands."""
    global job_thread
    with job_lock:
        if job_thread is not None and job_thread.is_alive():
            return False
        with status_lock:
            if not status.get("connected"):
                return False
        stop_requested.clear()
        hazard_resume.set()
        update_status(
            busy=True, state="연결 중", hazard_wait=False,
            hazard_clear_confirmed=False, ai_class=None,
            can_redirect=False, redirect_area=None,
            course_width_cm=side_x, course_height_cm=side_y,
            course_points=course_points,
            delivery_areas=(list(("A", "B", "C")) if mode == "sequential" else [area]),
        )
        job_thread = threading.Thread(
            target=run_job,
            args=(mode, area, side_x, side_y, course_points),
            daemon=True,
        )
        job_thread.start()
        return True


def request_area_redirect(area, source="관제 화면"):
    """Queue an A/B/C reroute while moving or a home request at any safe phase."""
    area = str(area).upper()
    if area not in TARGET_CLASS and area != "HOME":
        return False
    with status_lock:
        can_redirect = (
            status.get("busy")
            and (not status.get("hazard_wait") or (area == "HOME" and source == "재난 관제 명령"))
            and not stop_requested.is_set()
            and (area == "HOME" or status.get("can_redirect"))
        )
        if can_redirect:
            status["redirect_area"] = area
    if can_redirect:
        if area == "HOME":
            report_control_center("RETURN_HOME_REQUESTED", f"{source} 출발점 귀환 요청")
        else:
            report_control_center("ROUTE_REDIRECT_REQUESTED", f"{source} 목적지 변경 요청: {area}")
    return bool(can_redirect)


def normalize_disaster_type(token):
    token = str(token).strip()
    if "=" in token:
        key, value = token.split("=", 1)
        if key.strip().upper() in ("TYPE", "DISASTER", "ALERT"):
            token = value.strip()
    compact = token.upper().replace(" ", "").replace("_", "").replace("-", "")
    return DISASTER_ALIASES.get(compact) or DISASTER_ALIASES.get(token)


def parse_emergency_location(parts):
    """Parse a map point label or map coordinates from the sender's radio payload."""
    raw_location = "|".join(str(part).strip() for part in parts if str(part).strip())
    if not raw_location:
        return "위치 정보 없음", None, None, None, None

    x_match = re.search(r"(?:^|[|;,])\s*X\s*[:=]\s*(-?\d+(?:\.\d+)?)", raw_location, re.I)
    y_match = re.search(r"(?:^|[|;,])\s*Y\s*[:=]\s*(-?\d+(?:\.\d+)?)", raw_location, re.I)
    coordinate_match = re.search(r"(-?\d+(?:\.\d+)?)\s*[,/]\s*(-?\d+(?:\.\d+)?)", raw_location)
    try:
        if x_match and y_match:
            x_cm, y_cm = float(x_match.group(1)), float(y_match.group(1))
        elif coordinate_match:
            x_cm, y_cm = float(coordinate_match.group(1)), float(coordinate_match.group(2))
        else:
            x_cm = y_cm = None
        if x_cm is not None and y_cm is not None and math.isfinite(x_cm) and math.isfinite(y_cm):
            # Dashboard 코스 크기는 브라우저에서 바뀔 수 있으므로 지도 최대 설정값만 확인합니다.
            if 0 <= x_cm <= 300 and 0 <= y_cm <= 300:
                x_cm, y_cm = round(x_cm, 1), round(y_cm, 1)
                return f"지도 좌표 ({x_cm:g}, {y_cm:g})cm", None, None, x_cm, y_cm
            return f"지도 범위 밖 좌표 ({x_cm:g}, {y_cm:g})cm", None, None, None, None
    except (TypeError, ValueError):
        pass

    location = raw_location
    if "=" in location:
        key, value = location.split("=", 1)
        if key.strip().upper() in ("LOC", "LOCATION", "ZONE", "위치", "구역"):
            location = value.strip()
    compact = location.upper().replace(" ", "").replace("_", "").replace("-", "")
    if compact in ("1", "2"):
        return f"위치 {compact}", None, compact, None, None
    map_point = MAP_LOCATION_ALIASES.get(compact) or MAP_LOCATION_ALIASES.get(location)
    if map_point:
        label = {"start": "출발점", "A": "A 지역", "B": "B 지역", "C": "C 지역"}[map_point]
        return label, map_point, None, None, None
    location = "".join(ch for ch in location if ch.isprintable())[:80]
    return location or "위치 정보 없음", None, None, None, None


def refresh_active_emergency_locked():
    """Keep the newest active alert in the legacy single-alert field."""
    active = list(status.get("active_emergencies", {}).values())
    status["active_emergency"] = max(active, key=lambda event: event.get("time", "")) if active else None


def register_emergency_signal(payload, source="microbit_gateway"):
    """Record an alert, keep it active by zone, and publish affected delivery areas."""
    global pending_emergency_command
    raw = "".join(ch for ch in str(payload) if ch.isprintable()).strip()[:160]
    compact_signal = re.fullmatch(r"([EFGH])([12])", raw.upper())
    if compact_signal:
        parts = [compact_signal.group(1), compact_signal.group(2)]
    else:
        parts = [part.strip() for part in re.split(r"[|;]+", raw) if part.strip()]
    if parts and parts[0].upper() in ("DISASTER", "EMERGENCY", "ALERT"):
        parts = parts[1:]
    if not parts:
        return False

    disaster_code = None
    type_index = None
    for index, part in enumerate(parts):
        disaster_code = normalize_disaster_type(part)
        if disaster_code:
            type_index = index
            break
    if not disaster_code:
        return False

    location, map_point, location_code, x_cm, y_cm = parse_emergency_location(parts[type_index + 1:])
    if location_code not in EMERGENCY_AREAS:
        print(f"재난 신호에 위치 번호 1 또는 2가 없습니다: {raw}")
        return False
    label = DISASTER_LABELS[disaster_code]
    received_at = datetime.now().isoformat(timespec="seconds")
    affected_areas = list(EMERGENCY_AREAS.get(location_code, ()))
    affected_text = ", ".join(affected_areas) if affected_areas else "대상 배송지 미지정"
    detail = f"{label} 신호 · 위치: {location} · 영향 배송지: {affected_text}"
    # Stop before publishing the emergency into the dashboard status snapshot.
    stop_dog()
    emergency_hold.set()
    emergency_decision_ready.clear()
    with emergency_command_lock:
        pending_emergency_command = None
    record("EMERGENCY_SIGNAL", f"{disaster_code} | {location} | 영향 배송지: {affected_text} | {raw}")
    with status_lock:
        status["last_event_id"] += 1
        event = {
            "id": status["last_event_id"], "event": "EMERGENCY_SIGNAL",
            "detail": detail, "label": label, "emergency_type": disaster_code,
            "location": location, "map_point": map_point, "location_code": location_code,
            "affected_areas": affected_areas, "acknowledged": False,
            "x_cm": x_cm, "y_cm": y_cm, "raw": raw, "time": received_at,
            "source": source,
        }
        status["events"].append(event)
        status["events"] = status["events"][-40:]
        status.setdefault("active_emergencies", {})[str(location_code)] = dict(event)
        refresh_active_emergency_locked()
        status["emergency_history"].insert(0, dict(event))
        status["emergency_history"] = status["emergency_history"][:8]
        status["emergency_waiting"] = True
        status["emergency_command"] = None
        status["state"] = "재난 신호 수신 · 관제 명령 대기"
    print(f"\n[재난 신호 수신] {detail}")
    show_emergency_eye_pattern(disaster_code)
    report_control_center("EMERGENCY_STOPPED", f"{detail} · 로보독 정지, 관제 명령 대기")
    update_status(
        emergency_waiting=True, emergency_command=None,
        state="재난 신호 수신 · 관제 명령 대기", can_redirect=False,
    )
    return True


def handle_microbit_sensor_packet(packet):
    """Parse the compact 14-character sound/light packet from the dog-mounted micro:bit."""
    packet = str(packet).strip().upper()
    if len(packet) != 14 or packet[0] != "S":
        return False
    if packet[7] not in ("T", "S", "D"):
        return False
    try:
        if not (packet[1:7] + packet[8:14]).isdigit():
            return False
        sample = {
            "elapsed_ms": int(packet[1:5]) * 100,
            "segment": int(packet[5:7]),
            "phase": {"T": "TURN", "S": "STRAIGHT", "D": "DONE"}[packet[7]],
            "sound": int(packet[8:11]),
            "light": int(packet[11:14]),
            "received_at": datetime.now().isoformat(timespec="seconds"),
        }
    except (ValueError, IndexError):
        return False

    update_status(microbit_sensor=sample)
    try:
        new_file = not MICROBIT_SENSOR_LOG_FILE.exists()
        with MICROBIT_SENSOR_LOG_FILE.open("a", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            if new_file:
                writer.writerow(["received_at", "time_ms", "segment", "phase", "sound", "light"])
            writer.writerow([
                sample["received_at"], sample["elapsed_ms"], sample["segment"],
                sample["phase"], sample["sound"], sample["light"],
            ])
    except OSError as exc:
        print(f"micro:bit 센서 CSV 기록 오류: {exc}")
    return True


def parse_observation_packet(message):
    """Parse OBS,station,flame,gas_AO,gas_DO from the micro:bit serial input."""
    parts = str(message).strip().split(",")
    if len(parts) != 5 or parts[0].strip().upper() != "OBS":
        return None
    station = parts[1].strip()
    if station not in OBSERVATION_STATIONS:
        return None
    try:
        flame, gas_analog, gas_digital = map(int, parts[2:])
    except ValueError:
        return None
    if flame not in (0, 1) or gas_digital not in (0, 1):
        return None
    if not 0 <= gas_analog <= 1023:
        return None
    return station, flame, gas_analog, gas_digital


def add_microbit_event(event, detail):
    """Add an observation event without replacing the robot's current state."""
    record(event, detail)
    with status_lock:
        status["last_event_id"] += 1
        status["events"].append({
            "id": status["last_event_id"], "event": event, "detail": detail,
            "area": status.get("current_area"),
            "time": datetime.now().isoformat(timespec="seconds"),
        })
        status["events"] = status["events"][-40:]


def handle_observation_packet(message):
    """Update station readings and stop/report when flame or gas is detected."""
    parsed = parse_observation_packet(message)
    if parsed is None:
        return False
    station, flame, gas_analog, gas_digital = parsed
    received_at = datetime.now().isoformat(timespec="seconds")
    sample = {
        "station": station, "flame": flame,
        "gas_analog": gas_analog, "gas_digital": gas_digital,
        "received_at": received_at, "_received_monotonic": time.monotonic(),
    }
    with status_lock:
        stations = status.setdefault("observation_stations", {"1": None, "2": None})
        previous = stations.get(station)
        previous_flame = previous.get("flame") if previous else None
        previous_gas = previous.get("gas_digital") if previous else None
        stations[station] = sample

    affected = "·".join(OBSERVATION_STATIONS[station])
    fire_detected = flame == FIRE_ACTIVE
    gas_detected = gas_digital == GAS_ACTIVE
    previous_fire_detected = previous_flame == FIRE_ACTIVE
    previous_gas_detected = previous_gas == GAS_ACTIVE

    if fire_detected and not previous_fire_detected:
        add_microbit_event(
            "OBS_FIRE_SIGNAL",
            f"관측소 {station} 화재 감지 · 영향 배송지 {affected}",
        )
    elif not fire_detected and previous_fire_detected:
        add_microbit_event(
            "OBS_FIRE_CLEARED",
            f"관측소 {station} 화재 신호 해제 · 영향 배송지 {affected}",
        )
    if gas_detected and not previous_gas_detected:
        add_microbit_event(
            "OBS_GAS_SIGNAL",
            f"관측소 {station} 가스 감지 · 영향 배송지 {affected}",
        )
    elif not gas_detected and previous_gas_detected:
        add_microbit_event(
            "OBS_GAS_CLEARED",
            f"관측소 {station} 가스 신호 해제 · 영향 배송지 {affected}",
        )

    # A sensor alarm becomes a normal active emergency: stop the dog, show the
    # disaster eye pattern, and publish the alert for the dashboard controls.
    # When both inputs are active, report fire first; the next packet can
    # replace it with gas if the flame input clears while gas remains active.
    detected_type = "FIRE" if fire_detected else "GAS" if gas_detected else None
    if detected_type and not on_service.active:
        on_service.signal(("F" if detected_type == "FIRE" else "G") + station)
    if on_service.active:
        if detected_type:
            on_service.signal(("F" if detected_type == "FIRE" else "G") + station)
        update_status(microbit_status=f"연결됨 · ON 관측소 {station} OBS 수신")
        return True
    if detected_type:
        with status_lock:
            active = status.get("active_emergencies", {}).get(station)
            already_reported = (
                active is not None
                and active.get("source") == "obs_packet"
                and active.get("emergency_type") == detected_type
            )
        if not already_reported:
            code = "F" if detected_type == "FIRE" else "G"
            register_emergency_signal(f"{code}{station}", source="obs_packet")
    elif previous_fire_detected or previous_gas_detected:
        with status_lock:
            active = status.get("active_emergencies", {}).get(station)
            sensor_alert_active = active is not None and active.get("source") == "obs_packet"
        if sensor_alert_active:
            clear_active_emergency(station)

    update_status(
        microbit_status=f"연결됨 · 관측소 {station} OBS 수신",
        microbit_last_rx=str(message).strip()[:160],
    )
    return True


def handle_microbit_command(raw_command):
    """Handle station OBS data, sensor telemetry, and serial emergency alerts."""
    raw_text = str(raw_command).strip()
    if not raw_text:
        return False
    with status_lock:
        status["microbit_rx_seq"] = status.get("microbit_rx_seq", 0) + 1
        status["microbit_last_rx"] = raw_text[:160]
    if raw_text.upper().startswith("OBS,"):
        if handle_observation_packet(raw_text):
            return True
        update_status(microbit_status="연결됨 · OBS 데이터 형식 오류")
        print(f"지원하지 않는 관측소 패킷: {raw_text[:160]}")
        return False
    if raw_text.upper().startswith("SENSOR:"):
        packet = raw_text.split(":", 1)[1].strip()
        if handle_microbit_sensor_packet(packet):
            update_status(microbit_status="연결됨 · 소리/빛 센서 수신")
            return True
        update_status(microbit_status="연결됨 · 센서 데이터 형식 오류")
        print(f"지원하지 않는 micro:bit 센서 패킷: {packet[:160]}")
        return False
    if raw_text.upper().startswith("EMERGENCY:"):
        raw_text = raw_text.split(":", 1)[1].strip()
    elif raw_text.upper().startswith("REPORT:EMERGENCY:"):
        raw_text = raw_text[len("REPORT:EMERGENCY:"):].strip()
    elif raw_text.upper().startswith("RX:"):
        # Older PC-gateway MakeCode project used RX:<signal>.
        raw_text = raw_text.split(":", 1)[1].strip()
    if on_service.active:
        if on_service.signal(raw_text):
            update_status(microbit_status="연결됨 · ON 재난 안내 신호 수신")
            return True
        return False
    on_service.signal(raw_text)
    if register_emergency_signal(raw_text):
        update_status(microbit_status="연결됨 · 재난 신호 수신")
        return True
    update_status(microbit_status="연결됨 · 지원하지 않는 재난 신호")
    print(f"지원하지 않는 micro:bit 재난 신호: {raw_text[:160]}")
    return False


def acknowledge_active_emergency(location_code=None):
    with status_lock:
        active_events = status.get("active_emergencies", {})
        if location_code is None:
            active = status.get("active_emergency")
            location_code = active.get("location_code") if active else None
        active = active_events.get(str(location_code)) if location_code is not None else None
        if active is None and location_code is None:
            active = status.get("active_emergency")
        if active is None:
            return False
        active["acknowledged"] = True
        status["last_event_id"] += 1
        event = {
            "id": status["last_event_id"], "event": "EMERGENCY_ACKNOWLEDGED",
            "detail": f"{active.get('label', '재난')} 관제 확인 · 위치: {active.get('location', '위치 정보 없음')} · 영향 배송지: {', '.join(active.get('affected_areas', [])) or '미지정'}",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        status["events"].append(event)
        status["events"] = status["events"][-40:]
        refresh_active_emergency_locked()
    record("EMERGENCY_ACKNOWLEDGED", event["detail"])
    return True


def clear_active_emergency(location_code):
    with status_lock:
        active_events = status.get("active_emergencies", {})
        active = active_events.pop(str(location_code), None)
        if active is None:
            return False
        status["last_event_id"] += 1
        event = {
            "id": status["last_event_id"], "event": "EMERGENCY_CLEARED",
            "detail": f"{active.get('label', '재난')} 해제 · 위치 {location_code} · 영향 배송지: {', '.join(active.get('affected_areas', [])) or '미지정'}",
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        status["events"].append(event)
        status["events"] = status["events"][-40:]
        refresh_active_emergency_locked()
        no_active_radio_alerts = not active_events
    record("EMERGENCY_CLEARED", event["detail"])
    if no_active_radio_alerts:
        emergency_hold.clear()
        emergency_decision_ready.set()
        update_status(emergency_waiting=False, emergency_command=None)
        try:
            clear_head_led()
            update_status(head_led_on=False, head_led_mode="꺼짐")
        except Exception as exc:
            print("재난 해제 후 눈 LED 끄기 오류:", exc)
    return True


def active_emergency_for_area(area):
    """Return the newest active alert or station fire reading for this area."""
    with status_lock:
        matches = [
            dict(event) for event in status.get("active_emergencies", {}).values()
            if area in event.get("affected_areas", [])
        ]
        for station, sample in status.get("observation_stations", {}).items():
            if (
                sample
                and sample.get("flame") == FIRE_ACTIVE
                and area in OBSERVATION_STATIONS.get(station, ())
            ):
                matches.append({
                    "label": "화재", "emergency_type": "FIRE",
                    "location": f"관측소 {station}", "location_code": station,
                    "affected_areas": list(OBSERVATION_STATIONS[station]),
                    "time": sample.get("received_at", ""),
                })
    return max(matches, key=lambda event: event.get("time", "")) if matches else None


def queue_emergency_command(action, location_code):
    """Queue a dashboard response for an active radio alert while a job is running."""
    global pending_emergency_command
    location_code = str(location_code)
    if action not in ("evacuate", "emergency_return"):
        return False, "지원하지 않는 재난 대응 명령입니다."
    with status_lock:
        emergency = status.get("active_emergencies", {}).get(location_code)
        busy = bool(status.get("busy"))
    if emergency is None:
        return False, f"위치 {location_code}에 활성 라디오 재난 신호가 없습니다."
    if not busy:
        return False, "재난 대응은 로보독이 배송 운행 중일 때 실행할 수 있습니다. 먼저 배송을 시작해 주세요."
    with emergency_command_lock:
        pending_emergency_command = {
            "action": action, "location_code": location_code,
        }
        emergency_decision_ready.set()
    emergency_hold.set()
    stop_dog()
    label = "대피 안내" if action == "evacuate" else "출발점 복귀"
    update_status(
        emergency_waiting=True, emergency_command=label,
        state=f"재난 대응 · {label} 준비", can_redirect=False,
    )
    report_control_center("EMERGENCY_COMMAND_QUEUED", f"위치 {location_code} 재난 대응: {label}")
    update_status(
        emergency_waiting=True, emergency_command=label,
        state=f"재난 대응 · {label} 준비", can_redirect=False,
    )
    return True, f"{label} 명령을 로보독에 전달했습니다."


def update_microbit_port_state(port, connected, detail):
    """Keep the dashboard connection indicator accurate for multiple receivers."""
    with status_lock:
        microbit_port_states[port] = (connected, detail)
        connected_ports = [name for name, (is_connected, _) in microbit_port_states.items() if is_connected]
        all_details = [f"{name}: {message}" for name, (_, message) in microbit_port_states.items()]
        status["microbit_connected"] = bool(connected_ports)
        status["microbit_port"] = ", ".join(MICROBIT_PORTS) or "미설정"
        status["microbit_baudrate"] = MICROBIT_BAUDRATE
        if connected_ports:
            status["microbit_status"] = f"연결됨 · {', '.join(connected_ports)}"
        elif all_details:
            status["microbit_status"] = " · ".join(all_details)


def microbit_serial_receiver(port):
    """Read one PC-side micro:bit serial bridge and reconnect if unplugged."""
    if not port:
        update_status(
            microbit_connected=False,
            microbit_status="PC micro:bit 시리얼 포트 미설정",
            microbit_port="미설정",
            microbit_baudrate=MICROBIT_BAUDRATE,
        )
        return

    if pyserial is None:
        update_microbit_port_state(port, False, "pyserial 미설치")
        print("micro:bit 수신을 사용하려면 Python 환경에 pyserial을 설치하세요: python -m pip install pyserial")
        return

    update_microbit_port_state(port, False, "연결 중")
    while not microbit_shutdown.is_set():
        try:
            with pyserial.Serial(port, MICROBIT_BAUDRATE, timeout=0.25) as connection:
                update_microbit_port_state(port, True, "연결됨")
                while not microbit_shutdown.is_set():
                    raw = connection.readline()
                    if not raw:
                        continue
                    message = raw.decode("utf-8", errors="replace").strip()
                    if not message:
                        continue
                    try:
                        handle_microbit_command(message)
                    except Exception as exc:
                        print(f"micro:bit 재난 신호 처리 오류: {exc}")
        except Exception as exc:
            update_microbit_port_state(port, False, f"연결 안 됨 · {exc}")
            microbit_shutdown.wait(MICROBIT_RECONNECT_SECONDS)
    update_microbit_port_state(port, False, "종료됨")


def peek_redirect_area():
    with status_lock:
        return status.get("redirect_area")


def take_redirect_area():
    with status_lock:
        area = status.get("redirect_area")
        status["redirect_area"] = None
        return area


def close_redirect_window():
    """Atomically stop accepting redirections at the end of a path segment."""
    with status_lock:
        has_pending = bool(status.get("redirect_area"))
        status["can_redirect"] = False
        return has_pending


def normalize_course_points(raw_points, width_cm, height_cm):
    """Validate dashboard points in cm from the map's upper-left origin."""
    if raw_points is None:
        raw_points = {
            "start": [0, 0], "A": [width_cm, 0],
            "B": [width_cm, height_cm], "C": [0, height_cm],
        }
    if not isinstance(raw_points, dict):
        raise ValueError("출발점과 A/B/C 위치를 지도에서 다시 설정해 주세요.")

    points = {}
    for key in ("start", "A", "B", "C"):
        value = raw_points.get(key)
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("출발점과 A/B/C 위치가 모두 필요합니다.")
        try:
            x_cm, y_cm = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            raise ValueError("지도 좌표는 숫자로 입력해 주세요.") from None
        if not (math.isfinite(x_cm) and math.isfinite(y_cm)):
            raise ValueError("지도 좌표는 유한한 숫자여야 합니다.")
        if not (0 <= x_cm <= width_cm and 0 <= y_cm <= height_cm):
            raise ValueError("모든 점은 지도 경계 안에 놓아 주세요.")
        points[key] = [round(x_cm, 1), round(y_cm, 1)]

    keys = ("start", "A", "B", "C")
    for index, key in enumerate(keys):
        for other in keys[index + 1:]:
            if math.dist(points[key], points[other]) < 1:
                raise ValueError("출발점과 배송지 점은 1cm 이상 떨어뜨려 주세요.")
    return points


def points_relative_to_start(course_points):
    """Return A/B/C map coordinates relative to the selected start point."""
    start_x, start_y = course_points["start"]
    return {
        area: (course_points[area][0] - start_x, course_points[area][1] - start_y)
        for area in ("A", "B", "C")
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, code, body):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.path = urlsplit(self.path).path
        if self.path == "/api/bridge-handshake":
            payload = b'{"bridge":"jeongseon-aigo-v1"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/ports":
            from serial.tools import list_ports
            self._send_json(200, {"ports": [{"port": p.device, "description": p.description} for p in list_ports.comports()]})
            return
        if self.path == "/api/runs":
            try:
                self._send_json(200, {"runs": load_run_history(30)})
            except OSError as exc:
                self._send_json(500, {"error": f"운행 기록을 읽을 수 없습니다: {exc}"})
            return
        if self.path == "/api/runs.csv":
            try:
                with log_lock:
                    payload = LOG_FILE.read_bytes() if LOG_FILE.is_file() else b"time,visit_id,event,detail\r\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="pawcare_delivery_log.csv"')
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError as exc:
                self._send_json(500, {"error": f"CSV 운행 기록을 읽을 수 없습니다: {exc}"})
            return
        if self.path == "/api/status":
            with status_lock:
                snapshot = dict(status)
                snapshot["events"] = list(status["events"])
                snapshot["trail"] = [dict(point) for point in status.get("trail", [])]
                snapshot["active_emergency"] = (
                    dict(status["active_emergency"])
                    if status.get("active_emergency") else None
                )
                snapshot["active_emergencies"] = {
                    key: dict(event)
                    for key, event in status.get("active_emergencies", {}).items()
                }
                snapshot["emergency_history"] = [
                    dict(event) for event in status.get("emergency_history", [])
                ]
                snapshot["observation_stations"] = {}
                for station, sample in status.get("observation_stations", {}).items():
                    if sample is None:
                        snapshot["observation_stations"][station] = None
                        continue
                    item = dict(sample)
                    age = max(0.0, time.monotonic() - item.pop("_received_monotonic", time.monotonic()))
                    item["age_s"] = round(age, 1)
                    item["fresh"] = age <= OBSERVATION_TIMEOUT
                    snapshot["observation_stations"][station] = item
            snapshot["visit_id"] = visit_id
            self._send_json(200, snapshot)
            return
        if self.path in ("/", "/index.html"):
            try:
                payload = DASHBOARD_FILE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except OSError as exc:
                self._send_json(500, {"error": f"관제 HTML을 읽을 수 없습니다: {exc}"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}":
            self._send_json(403, {"error": "로컬 관제 화면에서 요청하세요."})
            return
        if self.path != "/api/command":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            command = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "잘못된 JSON 요청"})
            return

        if not isinstance(command, dict):
            self._send_json(400, {"error": "명령은 JSON 객체여야 합니다."})
            return
        action = command.get("action")
        if action == "on_start":
            try:
                ok, message = start_on_patrol(command.get("route"))
            except (ValueError, TypeError, AttributeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(202 if ok else 409, {"ok": ok, "message": message})
            return
        if action == "on_signal":
            signal = str(command.get("signal", "")).strip().upper()
            if not re.fullmatch(r"[EFGH][12]", signal):
                self._send_json(400, {"error": "재난 신호 형식이 올바르지 않습니다."})
                return
            on_service.signal(signal)
            self._send_json(200, {"ok": True, "message": "재난 신호를 접수했습니다."})
            return
        if action == "on_decision":
            try:
                decision = command.get("decision")
                areas = command.get("areas", [])
                alert_id = command.get("alert_id")
                # Validate before taking control of the physical port.
                if decision not in ("evacuate", "return", "hold"):
                    raise ValueError("관제 명령을 확인하세요.")
                if not isinstance(areas, list) or any(a not in ("A", "B", "C") for a in areas):
                    raise ValueError("지역 선택을 확인하세요.")
                if decision == "evacuate" and not areas:
                    raise ValueError("안내할 지역을 선택하세요.")
                if not on_service.latest_alert or alert_id != on_service.latest_alert['id']:
                    raise ValueError("최신 재난 알림에서 다시 선택하세요.")
                if not on_service.active:
                    if decision == "hold":
                        self._send_json(200, {"ok": True, "message": "현 위치 대기를 유지합니다."})
                        return
                    ok, message = start_on_patrol(command.get("route"))
                    if not ok:
                        self._send_json(409, {"error": message})
                        return
                on_service.decide(decision, areas, alert_id)
            except (ValueError, TypeError, AttributeError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(202, {"ok": True, "message": "관제 선택을 전달했습니다."})
            return
        if action == "on_resume_hazard":
            try:
                on_service.resume_after_hazard()
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, {"ok": True, "message": "CLASS1 해제 확인 후 재개를 요청했습니다."})
            return
        if action == "on_stop":
            on_service.stop_event.set()
            self._send_json(200, {"ok": True, "message": "ON 순찰 정지를 요청했습니다."})
            return
        if on_service.active:
            self._send_json(409, {"error": "ON 순찰 중에는 OUT 제어를 사용할 수 없습니다. ON에서 먼저 정지하세요."})
            return
        if action in ("connect_robot", "disconnect_robot"):
            ok, message = connect_robot(command.get("port")) if action == "connect_robot" else disconnect_robot()
            self._send_json(200 if ok else 409, {"ok": ok, "message": message})
            return
        if action in ("head_led_on", "head_led_off"):
            ok, message = set_head_led(action == "head_led_on")
            self._send_json(200 if ok else 409, {"ok": ok, "message": message})
            return
        if action == "ack_emergency":
            location_code = command.get("location_code")
            acknowledged = acknowledge_active_emergency(location_code)
            message = (
                f"위치 {location_code} 재난 신호를 확인했습니다. 대피 알림 조건은 해제 전까지 유지됩니다."
                if acknowledged else "확인할 재난 신호가 없습니다."
            )
            self._send_json(200, {"ok": True, "message": message})
            return
        if action == "clear_emergency":
            location_code = str(command.get("location_code", ""))
            if location_code not in EMERGENCY_AREAS:
                self._send_json(400, {"error": "해제할 재난 위치 1 또는 2를 선택해 주세요."})
                return
            cleared = clear_active_emergency(location_code)
            message = f"위치 {location_code} 재난 신호를 해제했습니다." if cleared else f"위치 {location_code}에 활성 재난 신호가 없습니다."
            self._send_json(200, {"ok": True, "message": message})
            return
        if action in ("evacuate", "emergency_return"):
            location_code = str(command.get("location_code", ""))
            if location_code not in EMERGENCY_AREAS:
                self._send_json(400, {"error": "재난 위치 번호 1 또는 2가 필요합니다."})
                return
            queued, message = queue_emergency_command(action, location_code)
            self._send_json(202 if queued else 409, {"ok": queued, "message": message})
            return
        if action == "start":
            with status_lock:
                connected = bool(status.get("connected"))
            if not connected:
                self._send_json(409, {"error": "먼저 로보독 연결 버튼으로 연결하세요."})
                return
            mode = command.get("mode", "sequential")
            area = str(command.get("area", "A")).upper()
            if mode not in ("sequential", "single") or (mode == "single" and area not in TARGET_CLASS):
                self._send_json(400, {"error": "운행 모드 또는 지역 값이 올바르지 않습니다."})
                return
            try:
                side_x = int(command.get("side_x", COURSE_SIDE_CM))
                side_y = int(command.get("side_y", COURSE_SIDE_CM))
            except (TypeError, ValueError):
                self._send_json(400, {"error": "코스 길이는 숫자(cm)로 입력해 주세요."})
                return
            if not (10 <= side_x <= 300 and 10 <= side_y <= 300):
                self._send_json(400, {"error": "코스 길이는 10~300cm 범위로 설정해 주세요."})
                return
            try:
                course_points = normalize_course_points(
                    command.get("course_points"), side_x, side_y
                )
            except (TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            if not start_delivery_job(mode, area, side_x, side_y, course_points):
                self._send_json(409, {"error": "이미 운행 중입니다."})
                return
            self._send_json(202, {"ok": True, "message": "운행을 시작합니다."})
            return
        if action == "return_home":
            if not request_area_redirect("HOME"):
                self._send_json(
                    409,
                    {"error": "출발점 귀환은 운행 중이고 위험 정지 상태가 아닐 때 요청할 수 있습니다."},
                )
                return
            self._send_json(202, {"ok": True, "message": "현재 단계에서 출발점으로 귀환합니다."})
            return
        if action == "redirect":
            area = str(command.get("area", "")).upper()
            if area not in TARGET_CLASS:
                self._send_json(400, {"error": "A, B, C 중 목적지를 선택해 주세요."})
                return
            if not request_area_redirect(area):
                self._send_json(
                    409,
                    {"error": "이동 중에만 목적지를 바꿀 수 있습니다. 인식 대기나 위험 정지 중에는 변경할 수 없습니다."},
                )
                return
            self._send_json(202, {"ok": True, "message": f"{area} 지역으로 경로를 변경합니다."})
            return
        if action == "stop":
            stop_requested.set()
            hazard_resume.set()
            emergency_hold.clear()
            emergency_decision_ready.set()
            stop_dog()
            update_status(
                state="정지 요청", hazard_wait=False,
                hazard_clear_confirmed=False, can_redirect=False,
                redirect_area=None, emergency_waiting=False,
                emergency_command=None,
            )
            self._send_json(200, {"ok": True, "message": "정지를 요청했습니다."})
            return
        if action == "resume_hazard":
            with status_lock:
                waiting_for_hazard_clear = status.get("hazard_wait", False)
                hazard_is_clear = status.get("hazard_clear_confirmed", False)
            if not waiting_for_hazard_clear:
                self._send_json(409, {"error": "현재 위험 정지 상태가 아닙니다."})
                return
            if not hazard_is_clear:
                self._send_json(
                    409,
                    {"error": "CLASS1 감지가 아직 끝나지 않았습니다. 위험 요소를 치운 뒤 잠시 기다려 주세요."},
                )
                return
            hazard_resume.set()
            self._send_json(200, {"ok": True, "message": "위험 제거를 확인했습니다. 이동을 재개합니다."})
            return
        self._send_json(400, {"error": "지원하지 않는 명령입니다."})


def stop_dog():
    try:
        dog.move(STOP)
    except Exception:
        pass
    try:
        dog.spin(STOP)
    except Exception:
        pass


def clear_head_led():
    """Turn off the eye matrix using both clear and explicit blank-frame APIs."""
    cleared = False
    errors = []

    # headLEDClear exists in some library versions. Explicitly draw a blank
    # frame as well, because that API is documented and reliably replaces an
    # active eye expression on versions where clear alone is not sufficient.
    try:
        dog.headLEDClear()
        cleared = True
    except Exception as exc:
        errors.append(f"headLEDClear: {exc}")
    try:
        blank = bytearray(8)
        dog.headLEDDraw(blank, bytearray(8))
        cleared = True
    except Exception as exc:
        errors.append(f"headLEDDraw: {exc}")

    if not cleared:
        raise RuntimeError("눈 LED 끄기 명령 실패: " + "; ".join(errors))
    if errors:
        print("눈 LED 초기화 대체 명령 사용:", "; ".join(errors))
    # Let the RoboDog receive and apply the serial command before Close().
    time.sleep(0.3)


EMERGENCY_EYE_FRAMES = {
    "EARTHQUAKE": (
        [0x02, 0xF2, 0x82, 0x9E, 0x82, 0xF2, 0x02, 0x02],
        [0x00, 0x22, 0x52, 0x22, 0x02, 0xFA, 0x22, 0x22],
    ),
    "HEAT": (
        [0x02, 0xF2, 0x82, 0x9E, 0x82, 0xF2, 0x02, 0x02],
        [0x00, 0x22, 0x52, 0x22, 0x02, 0xFA, 0x22, 0x22],
    ),
    "FIRE": (
        [0x20, 0x70, 0x00, 0x74, 0x54, 0x77, 0x24, 0xFC],
        [0x00, 0xF5, 0x15, 0x27, 0x55, 0x8D, 0x05, 0x05],
    ),
    "GAS": (
        [0xF4, 0x14, 0x14, 0x17, 0x14, 0x34, 0x24, 0x44],
        [0x18, 0x18, 0x24, 0x24, 0xC3, 0x81, 0x00, 0xFF],
    ),
}


def show_emergency_eye_pattern(disaster_code):
    """Display the requested E/F/G/H emergency bitmap on RoboDog's eyes."""
    frames = EMERGENCY_EYE_FRAMES.get(disaster_code)
    if not frames:
        return False
    opened = False
    try:
        with status_lock:
            connected = bool(status.get("connected"))
        if not connected:
            with job_lock:
                with status_lock:
                    connected = bool(status.get("connected"))
                if not connected:
                    opened = bool(dog.Open(ROBOT_PORT))
                    if not opened:
                        raise RuntimeError(f"로보독 {ROBOT_PORT} 포트 연결 실패")
        dog.headLEDDraw(bytearray(frames[0]), bytearray(frames[1]))
        update_status(head_led_on=True, head_led_mode=DISASTER_LABELS[disaster_code])
        return True
    except Exception as exc:
        print(f"재난 눈 LED 표시 오류: {exc}")
        update_status(head_led_mode=f"표시 실패: {DISASTER_LABELS[disaster_code]}")
        return False
    finally:
        if opened:
            try:
                dog.Close()
            except Exception:
                pass


def set_head_led(enabled):
    """Set the eye display over the active RoboDog session or open it while idle."""
    with job_lock:
        running = job_thread is not None and job_thread.is_alive()
        if running:
            with status_lock:
                connected = status.get("connected", False)
            if not connected:
                return False, "로보독 연결이 완료된 뒤 눈 LED를 조작할 수 있습니다. 잠시 후 다시 눌러 주세요."
        else:
            with status_lock:
                connected = bool(status.get("connected"))

        opened = False
        try:
            if not connected:
                opened = dog.Open(ROBOT_PORT)
                if not opened:
                    return False, f"로보독 {ROBOT_PORT} 연결 실패. 포트 번호와 USB 연결을 확인해 주세요."
            if enabled:
                # RoboDog 공개 API의 내장 표정으로 눈 LED를 켭니다.
                dog.headLEDExp(초롱초롱)
                time.sleep(0.3)
                update_status(head_led_on=True, head_led_mode="초롱초롱")
                record("HEAD_LED_ON", "초롱초롱 표정")
                return True, "눈 LED를 켰습니다."

            clear_head_led()
            update_status(head_led_on=False, head_led_mode="꺼짐")
            record("HEAD_LED_OFF", "눈 LED 초기화")
            return True, "눈 LED를 껐습니다."
        except Exception as exc:
            return False, f"눈 LED 제어 오류: {exc}"
        finally:
            if opened:
                try:
                    dog.Close()
                except Exception:
                    pass


def set_eye_led_for_mode(enabled):
    """운행 중 인식 모드에 맞춰 눈 LED를 켜거나 끕니다. 이미 같은 상태면 건너뜁니다."""
    with status_lock:
        if status.get("active_emergencies"):
            return
        if status.get("head_led_on") == enabled:
            return
    try:
        if enabled:
            dog.headLEDExp(초롱초롱)
            time.sleep(0.3)
            record("HEAD_LED_ON", "QR 인식 모드 자동 켜기")
        else:
            clear_head_led()
            record("HEAD_LED_OFF", "인물 인식 모드 자동 끄기")
        update_status(head_led_on=enabled, head_led_mode="초롱초롱" if enabled else "꺼짐")
    except Exception as exc:
        print("눈 LED 자동 제어 오류:", exc)


def read_relative_tilt():
    """시작 시 수평 기준값을 뺀 roll/pitch를 반환합니다."""
    roll, pitch = dog.get_tilt()
    return float(roll) - tilt_roll_zero, float(pitch) - tilt_pitch_zero


def log_tilt(phase, tilt=None):
    """상대 roll/pitch를 설정된 간격으로 CSV에 기록합니다."""
    global _last_tilt_log
    now = time.monotonic()
    if now - _last_tilt_log < TILT_UPDATE_INTERVAL:
        return
    try:
        roll, pitch = tilt if tilt is not None else read_relative_tilt()
        update_status(roll=round(float(roll), 2), pitch=round(float(pitch), 2))
        new_file = not TILT_LOG_FILE.exists()
        with TILT_LOG_FILE.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "visit_id", "phase", "roll_deg", "pitch_deg"])
            w.writerow([
                datetime.now().isoformat(timespec="seconds"), visit_id, phase,
                round(float(roll), 2), round(float(pitch), 2),
            ])
        _last_tilt_log = now
    except Exception as exc:
        print("기울기 측정/기록 오류:", exc)


def get_class():
    try:
        if not dog.is_ai_alive():
            update_status(ai_class=None)
            return "UNKNOWN"
        value = dog.get_face_recognition_class()
        if value is not None:
            value = int(value)
            update_status(ai_class=value)
            return value
        update_status(ai_class=None)
        return None  # AI is alive but currently recognizes no class.
    except Exception as exc:
        print("AI 인식 확인 오류:", exc)
        update_status(ai_class=None)
        return "UNKNOWN"
def handle_hazard_during_move():
    """CLASS1이면 멈추고, 관제 화면의 재개 확인과 장애물 제거를 기다립니다."""
    if stop_requested.is_set():
        return False
    found = get_class()
    if found != 1:
        return True
    stop_dog()
    try:
        dog.sound(멍멍, 크게)
    except Exception as exc:
        print("짖기 소리 재생 오류:", exc)
    hazard_resume.clear()
    report_control_center("HAZARD_CLASS1", "CLASS1 감지, 로보독 정지")
    update_status(
        state="위험 정지", hazard_wait=True, hazard_clear_confirmed=False
    )
    while not stop_requested.is_set():
        time.sleep(0.2)
        if stop_requested.is_set():
            return False
        current_class = get_class()
        hazard_cleared = current_class is not None and current_class != 1 and current_class != "UNKNOWN"
        update_status(hazard_clear_confirmed=hazard_cleared)
        resume_requested = hazard_resume.is_set()
        if resume_requested:
            hazard_resume.clear()
        if hazard_cleared and resume_requested:
            update_status(
                state="이동 재개", hazard_wait=False,
                hazard_clear_confirmed=False,
            )
            report_control_center("HAZARD_CLEARED", "관제 재개 확인 및 CLASS1 해제")
            return True
    return True


def get_raw_angle(samples=GYRO_SAMPLE_COUNT, delay=GYRO_SAMPLE_DELAY):
    total = 0.0
    for _ in range(samples):
        total += dog.get_rotation()
        time.sleep(delay)
    return total / samples


def absolute_angle():
    return get_raw_angle() - gyro_zero_offset


def fast_angle():
    return dog.get_rotation() - gyro_zero_offset


def angle_error(target, current):
    error = target - current
    while error > 180:
        error -= 360
    while error < -180:
        error += 360
    return error


def calibrate_gyro():
    global gyro_zero_offset, tilt_roll_zero, tilt_pitch_zero
    stop_dog()
    time.sleep(0.8)
    gyro_zero_offset = get_raw_angle(15, 0.03)
    samples = [dog.get_tilt() for _ in range(10)]
    tilt_roll_zero = sum(sample[0] for sample in samples) / len(samples)
    tilt_pitch_zero = sum(sample[1] for sample in samples) / len(samples)
    print(f"자이로 영점 설정: {gyro_zero_offset:.1f}°")
    print(f"기울기 영점 설정: roll={tilt_roll_zero:.1f}°, pitch={tilt_pitch_zero:.1f}°")


def rotate_by(degrees):
    global current_heading
    if peek_redirect_area():
        stop_dog()
        return REDIRECT_REQUESTED
    requested = int(round(degrees))
    if requested == 0:
        return True
    stop_dog()
    time.sleep(STABILIZE_DELAY)
    # rotate() is itself a blocking relative-turn API. Avoid a second
    # absolute-angle correction loop, which can add another turn if the yaw
    # reading is stale or wrapped after a greeting/QR interaction.
    # Short signed relative turns also let us check stop/redirect between steps.
    remaining = requested
    while remaining:
        if emergency_hold.is_set():
            emergency_result = process_pending_emergency_command()
            if emergency_result == "HOME":
                return REDIRECT_REQUESTED
            if emergency_result == "EVACUATED":
                return EMERGENCY_INTERRUPTED
            if emergency_result == "ABORT":
                return False
        if stop_requested.is_set():
            stop_dog()
            return False
        if peek_redirect_area():
            stop_dog()
            return REDIRECT_REQUESTED
        step = max(-TURN_CHUNK_DEG, min(TURN_CHUNK_DEG, remaining))
        dog.rotate(step, TURN_SPEED)
        current_heading += step
        remaining -= step
        update_status(heading_deg=round(current_heading % 360, 1))
    stop_dog()
    time.sleep(STABILIZE_DELAY)
    print(
        f"[회전 완료] 요청={requested:+d}°, 누적 방향={current_heading % 360:.1f}°"
    )
    return True


def move_forward_cm(distance_cm):
    global map_x_cm, map_y_cm
    if distance_cm <= 0:
        return True
    target = distance_cm * NORMAL_SCALE * DRIVE_DISTANCE_MULTIPLIER
    travelled = 0.0
    dt = 0.05
    try:
        while travelled < target:
            if emergency_hold.is_set():
                stop_dog()
                emergency_result = process_pending_emergency_command()
                if emergency_result == "HOME":
                    return REDIRECT_REQUESTED
                if emergency_result == "EVACUATED":
                    return EMERGENCY_INTERRUPTED
                if emergency_result == "ABORT":
                    return False
            if not handle_hazard_during_move():
                if peek_redirect_area() == "HOME":
                    return REDIRECT_REQUESTED
                return False
            if emergency_hold.is_set():
                stop_dog()
                emergency_result = process_pending_emergency_command()
                if emergency_result == "HOME":
                    return REDIRECT_REQUESTED
                if emergency_result == "EVACUATED":
                    return EMERGENCY_INTERRUPTED
                if emergency_result == "ABORT":
                    return False
            if peek_redirect_area():
                stop_dog()
                return REDIRECT_REQUESTED
            try:
                tilt = read_relative_tilt()
            except Exception as exc:
                print("기울기 읽기 오류, 평면 이동량을 근사값으로 계산합니다:", exc)
                tilt = (0.0, 0.0)
            log_tilt("이동", tilt)
            # move()는 sleep() 뒤 자동 정지되므로 짧은 주기마다 명령을 갱신합니다.
            dog.move(FORWARD, SPEED)
            time.sleep(dt)
            slope_step_cm = CM_PER_SEC * dt
            # pitch 기울기만큼 경사면 거리를 수평 평면 거리로 투영합니다.
            planar_step_cm = slope_step_cm * max(
                0.0, math.cos(math.radians(tilt[1]))
            )
            travelled += planar_step_cm
            # Keep the displayed map progress tied to the selected point despite
            # the longer physical drive-time calibration.
            map_step_cm = planar_step_cm / (NORMAL_SCALE * DRIVE_DISTANCE_MULTIPLIER)
            heading_rad = math.radians(current_heading)
            map_x_cm += map_step_cm * math.cos(heading_rad)
            map_y_cm += map_step_cm * math.sin(heading_rad)
            point = {"x": round(map_x_cm, 1), "y": round(map_y_cm, 1)}
            with status_lock:
                status.update(
                    x_cm=point["x"], y_cm=point["y"],
                    heading_deg=round(current_heading % 360, 1), state="이동 중",
                )
                trail = status.setdefault("trail", [])
                if not trail or math.dist(
                    (trail[-1]["x"], trail[-1]["y"]), (point["x"], point["y"])
                ) >= 0.8:
                    trail.append(point)
                    if len(trail) > 500:
                        del trail[:-500]
        return True
    finally:
        stop_dog()
        time.sleep(STABILIZE_DELAY)


def follow_map_path(points):
    """현재 위치부터 순서대로 (x_cm, y_cm) 지도 좌표를 방문합니다."""
    global current_heading
    update_status(can_redirect=True, state="경로 이동 중")
    for index, (target_x, target_y) in enumerate(points, start=1):
        while True:
            if stop_requested.is_set():
                update_status(can_redirect=False)
                return False
            if emergency_hold.is_set():
                emergency_result = process_pending_emergency_command()
                if emergency_result == "HOME":
                    update_status(can_redirect=False)
                    return REDIRECT_REQUESTED
                if emergency_result == "EVACUATED":
                    continue
                if emergency_result == "ABORT":
                    update_status(can_redirect=False)
                    return False
            if peek_redirect_area():
                stop_dog()
                update_status(can_redirect=False)
                return REDIRECT_REQUESTED
            dx = target_x - map_x_cm
            dy = target_y - map_y_cm
            distance = math.hypot(dx, dy)
            if distance < 1.0:
                break
            target_heading = math.degrees(math.atan2(dy, dx))
            turn = angle_error(target_heading, current_heading)
            print(
                f"[지도 구간 {index}] 목표=({target_x:.1f}, {target_y:.1f})cm, "
                f"현재 추정=({map_x_cm:.1f}, {map_y_cm:.1f})cm, 거리={distance:.1f}cm, "
                f"현재 방향={current_heading % 360:.1f}°, 목표 방향={target_heading % 360:.1f}°, "
                f"회전={turn:+.1f}°"
            )
            rotated = rotate_by(turn)
            if rotated == EMERGENCY_INTERRUPTED:
                continue
            if rotated == REDIRECT_REQUESTED:
                stop_dog()
                update_status(can_redirect=False)
                return REDIRECT_REQUESTED
            if not rotated:
                if close_redirect_window():
                    stop_dog()
                    return REDIRECT_REQUESTED
                update_status(can_redirect=False)
                return False
            moved = move_forward_cm(distance)
            if moved == EMERGENCY_INTERRUPTED:
                continue
            if moved == REDIRECT_REQUESTED:
                stop_dog()
                update_status(can_redirect=False)
                return REDIRECT_REQUESTED
            if not moved:
                if close_redirect_window():
                    stop_dog()
                    return REDIRECT_REQUESTED
                update_status(can_redirect=False)
                return False
            if math.hypot(target_x - map_x_cm, target_y - map_y_cm) >= 1.0:
                continue
            break
    if close_redirect_window():
        stop_dog()
        return REDIRECT_REQUESTED
    print(f"[지도 코스 완료] 추정 위치=({map_x_cm:.1f}, {map_y_cm:.1f})cm")
    return True


def wait_for_target_person(area):
    target = TARGET_CLASS[area]
    deadline = time.monotonic() + PERSON_TIMEOUT
    update_status(
        state="인물 인식 대기", current_area=area, ai_class=None,
        can_redirect=False,
    )
    try:
        dog.ai_mode(FACE_RECOGNITION)
    except Exception as exc:
        print("얼굴 인식 모드 전환 오류:", exc)
    set_eye_led_for_mode(False)
    print(f"{AREA_NAME[area]}에서 인물 카드 CLASS{target}을 기다립니다 ({PERSON_TIMEOUT}초).")
    while time.monotonic() < deadline:
        emergency_result = process_pending_emergency_command()
        if emergency_result == "HOME":
            return RETURN_HOME_REQUESTED
        if emergency_result == "ABORT":
            return "ABORT"
        if peek_redirect_area() == "HOME":
            return RETURN_HOME_REQUESTED
        if not handle_hazard_during_move():
            if peek_redirect_area() == "HOME":
                return RETURN_HOME_REQUESTED
            return "ABORT"
        log_tilt("인물 대기")
        found = get_class()
        if found == target:
            stop_dog()
            record("PERSON_CARD_FOUND", f"{area}/CLASS{target}")
            report_control_center("PERSON_CARD_FOUND", f"{area}/CLASS{target}")
            return "FOUND"
        time.sleep(POLL_INTERVAL)
    return "TIMEOUT"


def greet(dog):
    emergency_result = process_pending_emergency_command()
    if emergency_result in ("HOME", "ABORT"):
        return
    print("로보독: 반가워요! 안부 카드와 배송 물품을 가져왔어요.")
    try:
        dog.bodyLED((0, 200, 0))
    except Exception:
        pass
    try:
        dog.gesture("인사하기")
        time.sleep(2)  # 제스처 후 균형을 잡을 시간을 줍니다.
    except Exception as exc:
        print("인사 동작 오류:", exc)


def perform_evacuation_alert(area, emergency=None):
    """Stop at an affected delivery point and issue the active evacuation warning."""
    emergency = emergency or active_emergency_for_area(area)
    if emergency is None:
        return False

    stop_dog()
    details = []
    try:
        dog.bodyLED((255, 24, 24))
    except Exception as exc:
        details.append(f"빨간 LED 오류: {exc}")

    sound_ok = True
    for _ in range(EVACUATION_BARK_COUNT):
        try:
            dog.sound(멍멍, 크게)
            time.sleep(0.7)
        except Exception as exc:
            sound_ok = False
            details.append(f"짖기 소리 오류: {exc}")
            break

    detail = (
        f"{emergency.get('label', '재난')} 위치 {emergency.get('location_code')} · "
        f"{AREA_NAME[area]} 대피 안내 지점 도착 · "
        f"빨간 LED 및 짖기 {EVACUATION_BARK_COUNT}회"
    )
    if details:
        detail += " · " + " / ".join(details)
    update_status(last_evacuation_alert={
        "area": area, "location_code": emergency.get("location_code"),
        "label": emergency.get("label"), "sound_ok": sound_ok,
        "time": datetime.now().isoformat(timespec="seconds"),
    })
    report_control_center("EVACUATION_ALERT", detail)
    update_status(state="대피 알림 완료")
    return True


def process_pending_emergency_command():
    """Hold for the dashboard, then evacuate affected points or redirect home."""
    if not emergency_hold.is_set():
        return None
    stop_dog()
    update_status(
        emergency_waiting=True,
        state="재난 신호 수신 · 관제 명령 대기",
        can_redirect=False,
    )
    while not stop_requested.is_set() and emergency_hold.is_set():
        if not emergency_decision_ready.wait(0.1):
            continue
        with emergency_command_lock:
            command = pending_emergency_command
            emergency_decision_ready.clear()
        if not command:
            if not emergency_hold.is_set():
                return None
            continue

        action = command.get("action")
        location_code = str(command.get("location_code", ""))
        with status_lock:
            emergency = status.get("active_emergencies", {}).get(location_code)
            course_points = dict(status.get("course_points", {}))
            planned_areas = list(status.get("delivery_areas", []))
        if emergency is None:
            emergency_hold.clear()
            update_status(
                emergency_waiting=False, emergency_command=None,
                state="활성 재난 신호 없음",
            )
            report_control_center(
                "EMERGENCY_COMMAND_CANCELLED",
                f"위치 {location_code} 재난 신호가 해제되어 명령을 취소했습니다.",
            )
            return "ABORT"

        emergency_hold.clear()
        update_status(
            emergency_waiting=False,
            emergency_command="대피 안내 실행" if action == "evacuate" else "출발점 복귀",
            state="대피 안내 경로 계산 중" if action == "evacuate" else "재난 상황 출발점 복귀 중",
            can_redirect=True,
        )
        if action == "emergency_return":
            report_control_center(
                "EMERGENCY_RETURN_START",
                f"{emergency.get('label', '재난')} 위치 {location_code} · 출발점으로 복귀",
            )
            request_area_redirect("HOME", source="재난 관제 명령")
            return "HOME"

        try:
            points = {
                key: (float(value[0]), float(value[1]))
                for key, value in course_points.items()
                if key in ("start", "A", "B", "C")
            }
            relative_points = points_relative_to_start(points)
        except (KeyError, TypeError, ValueError, IndexError):
            emergency_hold.set()
            update_status(
                emergency_waiting=True, emergency_command=None,
                state="대피 경로 좌표 오류 · 관제 명령 대기",
            )
            report_control_center(
                "EMERGENCY_ROUTE_ERROR",
                "출발점 및 A/B/C 지도 좌표를 읽지 못했습니다.",
            )
            return "ABORT"

        affected_areas = list(emergency.get("affected_areas", []))
        if not affected_areas:
            affected_areas = list(EMERGENCY_AREAS.get(location_code, ()))
        if planned_areas:
            affected_areas = [area for area in affected_areas if area in planned_areas]
        if not affected_areas:
            update_status(emergency_command=None, can_redirect=False)
            report_control_center(
                "EVACUATION_NO_TARGET",
                f"위치 {location_code} 영향 배송지는 이번 운행 목적지에 포함되지 않아 이동하지 않습니다.",
            )
            return "EVACUATED"

        report_control_center(
            "EVACUATION_ROUTE_START",
            f"위치 {location_code} 영향 배송지 순서: {'→'.join(affected_areas)}",
        )
        for area in affected_areas:
            if area not in relative_points:
                continue
            update_status(current_area=area, state=f"{area} 지역 대피 안내 장소로 이동 중")
            route_result = follow_map_path([relative_points[area]])
            if route_result == REDIRECT_REQUESTED:
                return "HOME" if peek_redirect_area() == "HOME" else "ABORT"
            if not route_result:
                update_status(
                    emergency_waiting=True, emergency_command=None,
                    state="대피 경로 이동 실패 · 관제 명령 대기",
                )
                emergency_hold.set()
                report_control_center(
                    "EVACUATION_ROUTE_ABORTED",
                    f"{area} 지역 대피 안내 장소에 도착하지 못했습니다.",
                )
                return "ABORT"
            update_status(current_area=area, state=f"{area} 지역 대피 안내 중")
            report_control_center("EVACUATION_ARRIVED", f"{AREA_NAME[area]} 대피 안내 지점 도착")
            perform_evacuation_alert(area, emergency)

        update_status(emergency_command=None, can_redirect=False)
        report_control_center(
            "EVACUATION_ROUTE_DONE",
            f"위치 {location_code} 영향 배송지 대피 안내 완료",
        )
        return "EVACUATED"

    emergency_hold.clear()
    emergency_decision_ready.set()
    if not stop_requested.is_set():
        update_status(emergency_waiting=False, emergency_command=None)
        return None
    return "ABORT"


def report_missed_evacuation_target(area):
    emergency = active_emergency_for_area(area)
    if emergency:
        report_control_center(
            "EVACUATION_PERSON_NOT_FOUND",
            f"{emergency.get('label', '재난')} 위치 {emergency.get('location_code')} 영향 지역인 "
            f"{AREA_NAME[area]}에서 60초 동안 CLASS{TARGET_CLASS[area]} 미인식 · 대피 알림 미실행",
        )


def play_delivery_audio():
    """공개 API에는 임의 MP3 파일 재생이 없어 내장 인사 소리로 대체합니다."""
    try:
        dog.sound(DELIVERY_SOUND_TRACK, 중간)
    except Exception as exc:
        print("내장 안내 소리 재생 오류:", exc)
        print("공개 API 문서에 MP3 파일 재생 메서드가 없어 실제 MP3는 재생할 수 없습니다.")


def wait_for_go_qr():
    """RoboDog QR 인식 모드에서 GO 문자열을 제한 시간 동안 읽습니다."""
    if peek_redirect_area() == "HOME":
        return RETURN_HOME_REQUESTED
    update_status(state="GO QR 인식 대기", can_redirect=False)
    print(f"QR을 스캔해 주세요. {QR_TIMEOUT}초 동안 GO 문자열을 기다립니다.")
    set_eye_led_for_mode(True)
    try:
        try:
            dog.ai_mode(QRCODE_READ)
        except Exception as exc:
            print("QR 인식 모드 전환 오류:", exc)
            return False

        deadline = time.monotonic() + QR_TIMEOUT
        while time.monotonic() < deadline:
            emergency_result = process_pending_emergency_command()
            if emergency_result == "HOME":
                return RETURN_HOME_REQUESTED
            if emergency_result == "ABORT":
                return False
            if stop_requested.is_set():
                return False
            if peek_redirect_area() == "HOME":
                return RETURN_HOME_REQUESTED
            try:
                value = dog.get_qrcode()
                if value is not None:
                    value = str(value).strip()
                    if value:
                        print("QR 인식:", value)
                        if value.upper() == "GO":
                            report_control_center("GO_QR_SCANNED", value)
                        return value.upper() == "GO"
            except Exception as exc:
                print("QR 데이터 읽기 오류:", exc)
                return False
            time.sleep(POLL_INTERVAL)
        return False
    finally:
        set_eye_led_for_mode(False)

def qr_delivery_step():
    for attempt in range(1, QR_RETRIES + 1):
        if stop_requested.is_set():
            return False
        emergency_result = process_pending_emergency_command()
        if emergency_result == "HOME":
            return RETURN_HOME_REQUESTED
        if emergency_result == "ABORT":
            return False
        if peek_redirect_area() == "HOME":
            return RETURN_HOME_REQUESTED
        play_delivery_audio()
        qr_result = wait_for_go_qr()
        if qr_result == RETURN_HOME_REQUESTED:
            return RETURN_HOME_REQUESTED
        if qr_result:
            record("GO_QR_SCANNED", f"시도 {attempt}")
            return True
        if stop_requested.is_set():
            return False
        print(f"GO QR을 확인하지 못했습니다 ({attempt}/{QR_RETRIES}). 안내를 다시 재생합니다.")
    if not stop_requested.is_set():
        report_control_center("QR_NOT_SCANNED", f"{QR_RETRIES}회 안내 후 QR 미인식")
    return False


def choose_area():
    while True:
        area = input("배송 지역을 선택하세요 (A/B/C): ").strip().upper()
        if area in TARGET_CLASS:
            return area
        print("A, B, C 중 하나를 입력해 주세요.")


def choose_run_mode():
    while True:
        mode = input("실행 모드: 1=지역 선택 배송, 2=순차 배송 A→B→C (50cm 정사각형): ").strip()
        if mode in ("1", "2"):
            return mode
        print("1 또는 2를 입력해 주세요.")


def handle_redirected_delivery(area, relative_points):
    """Handle a changed destination or a return-home request from the dashboard."""
    while area and not stop_requested.is_set():
        area = str(area).upper()
        if area == "HOME":
            record("RETURN_HOME_START", "관제 화면에서 출발점 귀환 요청")
            update_status(current_area="출발점 복귀", state="출발점 귀환 중", can_redirect=True)
            report_control_center("RETURN_HOME_START", "현재 이동 위치에서 출발점으로 귀환")
            result = follow_map_path([(0, 0)])
            if result == REDIRECT_REQUESTED:
                area = take_redirect_area()
                continue
            if result:
                record("RETURNED", "관제 귀환 요청")
                update_status(current_area="출발점", state="출발점 복귀", can_redirect=False)
                report_control_center("RETURNED", "관제 귀환 요청 완료")
            elif not stop_requested.is_set():
                report_control_center("ROUTE_ABORTED", "출발점 귀환 중 이동 중단")
            return
        if area not in TARGET_CLASS:
            return
        record("ROUTE_REDIRECTED", area)
        update_status(current_area=area, state=f"{area} 지역으로 경로 변경", can_redirect=True)
        report_control_center("ROUTE_REDIRECTED", f"새 목적지 {AREA_NAME[area]}로 이동")

        route_result = follow_map_path([relative_points[area]])
        if route_result == REDIRECT_REQUESTED:
            area = take_redirect_area()
            continue
        if not route_result:
            if not stop_requested.is_set():
                report_control_center("ROUTE_ABORTED", f"{area} 지역으로 변경 중 이동 중단")
            return

        record("ARRIVED", area)
        update_status(current_area=area, state="배송지 도착", can_redirect=False)
        report_control_center("ARRIVED", area)
        result = wait_for_target_person(area)
        if result == RETURN_HOME_REQUESTED:
            area = take_redirect_area()
            continue
        if result == "FOUND":
            greet(dog)
            record("GREETING", area)
            report_control_center("GREETING", area)
            if qr_delivery_step() == RETURN_HOME_REQUESTED:
                area = take_redirect_area()
                continue
        elif result == "TIMEOUT":
            report_control_center(
                "PERSON_NOT_FOUND",
                f"{AREA_NAME[area]} 60초 대기 후 인물 카드 미인식",
            )
            report_missed_evacuation_target(area)
        else:
            return

        report_control_center("RETURN_START", f"{AREA_NAME[area]} 단일 배송 종료 후 복귀")
        return_result = follow_map_path([(0, 0)])
        if return_result == REDIRECT_REQUESTED:
            area = take_redirect_area()
            continue
        if return_result:
            record("RETURNED", area)
            update_status(current_area="출발점", state="출발점 복귀", can_redirect=False)
            report_control_center("RETURNED", area)
        elif not stop_requested.is_set():
            report_control_center("ROUTE_ABORTED", "출발점 복귀 중 이동 중단")
        return


def run_delivery(area, target_point, relative_points):
    record("VISIT_START", area)
    update_status(current_area=area, state="배송 시작")
    report_control_center("ROUTE_START", f"{AREA_NAME[area]} 배송 시작")
    route_result = follow_map_path([target_point])
    if route_result == REDIRECT_REQUESTED:
        handle_redirected_delivery(take_redirect_area(), relative_points)
        return
    if not route_result:
        report_control_center("ROUTE_ABORTED", area)
        return
    record("ARRIVED", area)
    report_control_center("ARRIVED", area)

    result = wait_for_target_person(area)
    if result == RETURN_HOME_REQUESTED:
        handle_redirected_delivery(take_redirect_area(), relative_points)
        return
    if result == "ABORT":
        return
    if result != "FOUND":
        report_control_center("PERSON_NOT_FOUND", f"{AREA_NAME[area]} 60초 대기 후 인물 카드 미인식")
        report_missed_evacuation_target(area)
        report_control_center("RETURN_START", "인물 미인식으로 출발점 복귀")
        return_result = follow_map_path([(0, 0)])
        if return_result == REDIRECT_REQUESTED:
            handle_redirected_delivery(take_redirect_area(), relative_points)
        elif return_result:
            record("RETURNED", "인물 미인식")
            update_status(current_area="출발점", can_redirect=False)
            report_control_center("RETURNED", "인물 미인식 후 출발점 복귀")
        return

    greet(dog)
    record("GREETING", area)
    report_control_center("GREETING", area)
    if qr_delivery_step() == RETURN_HOME_REQUESTED:
        handle_redirected_delivery(take_redirect_area(), relative_points)
        return
    report_control_center("RETURN_START", f"{AREA_NAME[area]} 배송 절차 종료")
    return_result = follow_map_path([(0, 0)])
    if return_result == REDIRECT_REQUESTED:
        handle_redirected_delivery(take_redirect_area(), relative_points)
    elif return_result:
        record("RETURNED", area)
        update_status(current_area="출발점", can_redirect=False)
        report_control_center("RETURNED", area)
    record("VISIT_END", area)


def run_sequential_point_delivery(side_x, side_y, course_points):
    """Visit the map's A/B/C points in order, then return to the selected start."""
    relative_points = points_relative_to_start(course_points)
    visit_order = [(area, relative_points[area]) for area in ("A", "B", "C")]
    start = course_points["start"]
    summary = (
        f"지도 {side_x}×{side_y}cm, 출발점 ({start[0]:g}, {start[1]:g}), "
        "A→B→C 점 순서 · "
        + " · ".join(
            f"{area}=({course_points[area][0]:g},{course_points[area][1]:g})"
            for area in ("A", "B", "C")
        )
    )
    record("SEQUENTIAL_ROUTE_START", summary)
    report_control_center(
        "SEQUENTIAL_ROUTE_START",
        summary,
    )

    previous_area = "출발점"
    for area, waypoint in visit_order:
        next_detail = (
            f"{previous_area} 완료 후 다음 목표 {area} "
            f"(지도 좌표 {course_points[area][0]:g},{course_points[area][1]:g}cm)"
        )
        record("SEQUENTIAL_NEXT_WAYPOINT", next_detail)
        update_status(state=f"다음 배송지 {area}로 이동 중")
        report_control_center("SEQUENTIAL_NEXT_WAYPOINT", next_detail)
        route_result = follow_map_path([waypoint])
        if route_result == REDIRECT_REQUESTED:
            handle_redirected_delivery(take_redirect_area(), relative_points)
            return
        if not route_result:
            report_control_center("ROUTE_ABORTED", f"{area} 도착 전 이동 중단")
            return
        record("ARRIVED", area)
        update_status(current_area=area)
        report_control_center("ARRIVED", area)
        result = wait_for_target_person(area)
        if result == RETURN_HOME_REQUESTED:
            handle_redirected_delivery(take_redirect_area(), relative_points)
            return
        if result == "ABORT":
            return
        if result != "FOUND":
            report_control_center(
                "PERSON_NOT_FOUND",
                f"{area}에서 60초 대기 후 CLASS{TARGET_CLASS[area]} 미인식",
            )
            report_missed_evacuation_target(area)
            if result == "TIMEOUT":
                report_control_center("RETURN_START", "인물 미인식으로 출발점 복귀")
                return_result = follow_map_path([(0, 0)])
                if return_result == REDIRECT_REQUESTED:
                    handle_redirected_delivery(take_redirect_area(), relative_points)
                elif return_result:
                    record("RETURNED", f"{area} 인물 미인식 후 복귀")
                    update_status(current_area="출발점", can_redirect=False)
                    report_control_center("RETURNED", f"{area} 인물 미인식 후 출발점 복귀")
            return

        greet(dog)
        record("GREETING", area)
        if qr_delivery_step() == RETURN_HOME_REQUESTED:
            handle_redirected_delivery(take_redirect_area(), relative_points)
            return
        previous_area = area

    report_control_center("RETURN_START", "A/B/C 배송 완료 후 출발점 복귀")
    return_result = follow_map_path([(0, 0)])
    if return_result == REDIRECT_REQUESTED:
        handle_redirected_delivery(take_redirect_area(), relative_points)
    elif return_result:
        record("SEQUENTIAL_ROUTE_DONE", "A/B/C 배송 후 출발점 복귀")
        report_control_center("SEQUENTIAL_ROUTE_DONE", "출발점 복귀 완료")


def run_job(mode, area, side_x, side_y, course_points):
    global visit_id, current_heading, map_x_cm, map_y_cm
    visit_id = datetime.now().strftime("VISIT-%Y%m%d-%H%M%S-%f")
    run_description = "A→B→C 순차 배송" if mode == "sequential" else f"{area} 지역 선택 배송"
    record("RUN_START", run_description)
    current_heading = 0.0
    map_x_cm = 0.0
    map_y_cm = 0.0
    update_status(
        visit_id=visit_id, x_cm=0.0, y_cm=0.0, heading_deg=0.0,
        trail=[{"x": 0.0, "y": 0.0}], current_area="출발점",
        state="로보독 연결 중", can_redirect=False, redirect_area=None,
        course_width_cm=side_x, course_height_cm=side_y,
        course_points=course_points,
    )
    connected = False
    try:
        # Serialize port open/close with dashboard LED commands.
        with job_lock:
            with status_lock:
                connected = bool(status.get("connected"))
            if not connected:
                connected = dog.Open(ROBOT_PORT)
            if connected:
                try:
                    # Clear stale eye patterns before enabling the dashboard LED controls.
                    if not emergency_hold.is_set():
                        clear_head_led()
                        update_status(head_led_on=False, head_led_mode="꺼짐")
                except Exception as exc:
                    print("눈 LED 초기화 오류:", exc)
        if not connected:
            report_control_center("ERROR", f"로보독 {ROBOT_PORT} 포트 연결 실패")
            return
        update_status(connected=True, state="초기화 중")
        print("로보독 연결 성공. 이동 경로와 비상 정지 방법을 확인하세요.")
        dog.ai_mode(FACE_RECOGNITION)
        calibrate_gyro()
        relative_points = points_relative_to_start(course_points)
        if mode == "single":
            run_delivery(area, relative_points[area], relative_points)
        else:
            run_sequential_point_delivery(side_x, side_y, course_points)
    except Exception as exc:
        report_control_center("ERROR", str(exc))
        update_status(state="오류")
    finally:
        stop_dog()
        if stop_requested.is_set():
            report_control_center("USER_ABORT", "관제 화면에서 정지 요청")
        with status_lock:
            final_state = status.get("state", "작업 종료")
        record("RUN_END", final_state)
        if connected:
            with job_lock:
                try:
                    clear_head_led()
                    update_status(head_led_on=False, head_led_mode="꺼짐")
                except Exception as exc:
                    print("운행 종료 후 눈 LED 끄기 오류:", exc)
        update_status(
            busy=False, hazard_wait=False,
            can_redirect=False, redirect_area=None,
            emergency_waiting=False, emergency_command=None,
        )
        if stop_requested.is_set():
            update_status(state="정지 완료")
        else:
            update_status(state="대기", current_area="출발점")


def ensure_dashboard_file():
    """Find the companion dashboard, asking the user if Thonny hid the script path."""
    global DASHBOARD_FILE, LOG_FILE
    if DASHBOARD_FILE.is_file():
        return True

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        selected = filedialog.askopenfilename(
            title="PawCare 관제 HTML 파일 선택",
            filetypes=[("HTML 파일", "*.html"), ("모든 파일", "*.*")],
        )
        root.destroy()
    except Exception as exc:
        print("관제 HTML 파일 선택창을 열 수 없습니다:", exc)
        selected = ""

    if selected and Path(selected).is_file():
        DASHBOARD_FILE = Path(selected).resolve()
        LOG_FILE = DASHBOARD_FILE.with_name("pawcare_delivery_log.csv")
        print("관제 HTML 파일:", DASHBOARD_FILE)
        return True

    print(
        "관제 HTML을 찾지 못했습니다. ZIP 파일을 먼저 '모두 압축 풀기'한 뒤 "
        "Python 코드와 pawcare_control.html을 함께 두고 다시 실행하세요."
    )
    return False


def main():
    if not ensure_dashboard_file():
        return
    server = ThreadingHTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), DashboardHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    microbit_threads = [
        threading.Thread(target=microbit_serial_receiver, args=(port,), daemon=True)
        for port in MICROBIT_PORTS
    ]
    server_thread.start()
    for microbit_thread in microbit_threads:
        microbit_thread.start()
    url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/"
    if os.environ.get("AIGO_CONNECT") == "1":
        url += "?connect=1&port=" + ROBOT_PORT
    print(f"관제 페이지: {url}")
    print("브라우저에서 배송 시작/정지와 재난 대응을 조작할 수 있습니다.")
    if MICROBIT_PORTS:
        print(f"micro:bit 수신 포트: {', '.join(MICROBIT_PORTS)} ({MICROBIT_BAUDRATE} baud)")
    try:
        if os.environ.get("AIGO_NO_BROWSER") != "1":
            webbrowser.open(url)
    except Exception:
        pass
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        on_service.stop_event.set()
        stop_requested.set()
        hazard_resume.set()
        stop_dog()
    finally:
        on_service.stop_event.set()
        if job_thread is not None:
            job_thread.join(timeout=4)
        microbit_shutdown.set()
        server.shutdown()
        try:
            dog.Close()
        except Exception:
            pass
        print("관제 서버를 종료했습니다.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_dog()
        report_control_center("USER_ABORT", "사용자 중단")
    except Exception as exc:
        stop_dog()
        report_control_center("ERROR", str(exc))
        raise








