import base64
import subprocess
from time import monotonic, sleep

import serial
from pyjuni.robodog import RoboDog

MICROBIT_PORT = "COM10"
ROBODOG_PORT = "COM8"
BAUD_RATE = 115200

MOVE_SPEED = 10
SIDE_SECONDS = 10.0
TURN_SPEED = 30
TURN_TIMEOUT = 10.0

AFTER_ANNOUNCEMENT_SECONDS = 1.0
REARM_SILENCE = 5.0

ZONES = {
    "1": "A, B",
    "2": "B, C"
}

KINDS = {
    "E": "지진",
    "F": "화재",
    "H": "무더위",
    "G": "가스"
}

EYES = {
    "E": (
        ([0xF4, 0x24, 0x54, 0x54, 0x00, 0x00, 0x00, 0x00]),
        ([0xF9, 0x21, 0x21, 0x61, 0x90, 0x40, 0x40, 0x7E])
    ),
        
    "F": (
        [0x20, 0x70, 0x00, 0x74, 0x54, 0x77, 0x24, 0xFC],
        [0x00, 0xF5, 0x15, 0x27, 0x55, 0x8D, 0x05, 0x05]
    ),
    "H": (
        [0x02, 0xF2, 0x82, 0x9E, 0x82, 0xF2, 0x02, 0x02],
        [0x00, 0x22, 0x52, 0x22, 0x02, 0xFA, 0x22, 0x22]
    ),
    "G": (
        [0xF4, 0x14, 0x14, 0x17, 0x14, 0x34, 0x24, 0x44],
        [0x18, 0x18, 0x24, 0x24, 0xC3, 0x81, 0x00, 0xFF]
    )
}


def parse_message(message):
    message = message.strip()

    if message.startswith("RX:"):
        message = message[3:]

    message = message.strip().upper()

    if len(message) != 2:
        return None

    kind, station = message

    if kind not in KINDS or station not in ZONES:
        return None

    return kind, station


def guidance(kind, station):
    instructions = {
        "E": (
            "지진 위험 신호입니다. 몸을 보호하고, "
            "흔들림이 멈춘 뒤 담당자의 안내에 따라 대피하세요."
        ),
        "F": (
            "화재 위험 신호입니다. 위험한 곳에서 벗어나 "
            "담당자의 안내에 따라 대피하세요."
        ),
        "H": (
            "무더위 위험 신호입니다. "
            "시원한 실내나 무더위 쉼터로 이동하세요."
        ),
        "G": (
            "가스 위험 신호입니다. "
            "불이나 전기 스위치를 조작하지 말고, "
            "위험한 곳에서 벗어나세요."
        )
    }

    return (
        ZONES[station]
        + " 지역에 안내합니다. "
        + instructions[kind]
    )


def start_speech(text):
    text = text.replace("'", "''")

    script = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer

try {
    $speaker.SelectVoiceByHints(
        [System.Speech.Synthesis.VoiceGender]::NotSet,
        [System.Speech.Synthesis.VoiceAge]::NotSet,
        0,
        [System.Globalization.CultureInfo]::GetCultureInfo('ko-KR')
    )
    $speaker.Volume = 90
    $speaker.Rate = 0
    $speaker.Speak('""" + text + """')
}
finally {
    $speaker.Dispose()
}
"""

    encoded = base64.b64encode(
        script.encode("utf-16le")
    ).decode("ascii")

    return subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded
        ],
        creationflags=subprocess.CREATE_NO_WINDOW
    )


class EyeDisplay:
    def __init__(self, dog, idle_expression=None):
        self.dog = dog
        self.last_kind = None
        self.idle_expression = idle_expression

    def clear(self):
        self.last_kind = None
        blank = bytearray(8)
        self.dog.headLEDDraw(blank, blank)

    def show(self, kind):
        self.last_kind = kind
        self.restore()

    def restore(self):
        if self.last_kind is None:
            if self.idle_expression is None:
                blank = bytearray(8)
                self.dog.headLEDDraw(blank, blank)
            else:
                self.dog.headLEDExp(self.idle_expression)
        else:
            left, right = EYES[self.last_kind]

            # 도안의 첫 글자를 왼쪽 눈, 둘째 글자를 오른쪽 눈에 표시합니다.
            self.dog.headLEDDraw(
                bytearray(left),
                bytearray(right)
            )


class SquarePatrol:
    def __init__(self, dog, eyes):
        self.dog = dog
        self.eyes = eyes
        self.phase = "START"
        self.deadline = 0.0
        self.side = 1

    def pause(self):
        self.dog.move(0)
        self.phase = "START"
        self.side = 1

    def tick(self, now):
        if self.phase == "START":
            self.dog.move(0)
            self.dog.gesture(0)

            # 받은 그림이 없으면 빈 눈, 있으면 마지막 그림 유지
            self.eyes.restore()

            self.deadline = now + 0.7
            self.phase = "READY"

        elif self.phase == "READY":
            if now >= self.deadline:
                print(
                    "정사각형 순찰:",
                    self.side,
                    "번째 변 전진"
                )

                self.dog.move(MOVE_SPEED)
                self.deadline = now + SIDE_SECONDS
                self.phase = "WALK"

        elif self.phase == "WALK":
            if now >= self.deadline:
                self.dog.move(0)
                self.dog.gesture(0)
                self.eyes.restore()

                self.deadline = now + 0.5
                self.phase = "TURN_READY"

        elif self.phase == "TURN_READY":
            if now >= self.deadline:
                print("왼쪽 90도 회전")

                self.dog.rotate(-90, TURN_SPEED)
                self.deadline = now + TURN_TIMEOUT
                self.phase = "TURN"

        elif self.phase == "TURN":
            angle = self.dog.get_rotation()

            if (
                isinstance(angle, (int, float))
                and abs(angle + 90) <= 8
            ):
                self.dog.move(0)
                self.side = self.side % 4 + 1
                self.deadline = now + 0.4
                self.phase = "REST"

            elif now >= self.deadline:
                self.dog.move(0)
                raise RuntimeError(
                    "90도 회전 확인 실패: 정지했습니다."
                )

        elif self.phase == "REST":
            if now >= self.deadline:
                self.phase = "READY"


class MessageGate:
    def __init__(self):
        self.last_seen = {}

    def is_new_event(self, message, now):
        previous = self.last_seen.get(message)
        self.last_seen[message] = now

        return (
            previous is None
            or now - previous >= REARM_SILENCE
        )


def main():
    dog = RoboDog()

    microbit = None
    connected = False
    speech = None

    buffer = bytearray()
    pending = []
    queued = set()
    active_message = None

    gate = MessageGate()
    paused = False
    resume_at = 0.0

    eyes = EyeDisplay(dog)
    patrol = SquarePatrol(dog, eyes)

    try:
        microbit = serial.Serial(
            MICROBIT_PORT,
            BAUD_RATE,
            timeout=0
        )

        connected = (
            dog.Open(ROBODOG_PORT) is not False
        )

        if not connected:
            raise RuntimeError("로보독 연결 실패")

        sleep(2)
        dog.move(0)

        # 시작할 때만 눈 LED 초기화
        eyes.clear()

        microbit.reset_input_buffer()
        dog.bodyLED(0x0F, 0, 255, 0)

        print("마이크로비트:", MICROBIT_PORT)
        print("로보독:", ROBODOG_PORT)
        print("한 변 10초 전진 → 왼쪽 90도 회전")
        print("신호 수신 → 정지·눈 LED·음성 안내")
        print("안내 완료 → 순찰 재개")
        print("종료: Ctrl+C")

        while True:
            now = monotonic()

            if speech is not None:
                if speech.poll() is not None:
                    if speech.returncode != 0:
                        raise RuntimeError(
                            "음성 안내 실패: "
                            "Windows 한국어 음성을 확인하세요."
                        )

                    speech = None
                    active_message = None
                    resume_at = (
                        now + AFTER_ANNOUNCEMENT_SECONDS
                    )

            count = microbit.in_waiting

            if count:
                buffer.extend(microbit.read(count))

            while b"\n" in buffer:
                line, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)

                try:
                    text = line.decode("utf-8").strip()
                except UnicodeDecodeError:
                    continue

                parsed = parse_message(text)

                if parsed is None:
                    if text:
                        print("무시한 메시지:", repr(text))
                    continue

                kind, station = parsed
                message = kind + station

                if not gate.is_new_event(message, now):
                    continue

                if (
                    message == active_message
                    or message in queued
                ):
                    continue

                # 새 신호를 받으면 정지하고 해당 눈 표시
                patrol.pause()
                paused = True

                dog.bodyLED(0x0F, 255, 0, 0)
                eyes.show(kind)

                pending.append(message)
                queued.add(message)

                print(
                    "새 신호:",
                    message,
                    "→ 정지 /",
                    ZONES[station],
                    "지역 안내"
                )

            if len(buffer) > 1024:
                buffer.clear()

            if speech is None and pending:
                message = pending.pop(0)
                queued.remove(message)

                kind = message[0]
                station = message[1]

                text = guidance(kind, station)
                print("안내:", text)

                speech = start_speech(text)
                active_message = message
                paused = True

            if (
                paused
                and speech is None
                and not pending
                and now >= resume_at
            ):
                print("안내 완료: 순찰 재개")

                # 눈은 마지막으로 받은 그림 유지
                eyes.restore()

                dog.bodyLED(0x0F, 0, 255, 0)
                paused = False

            if (
                not paused
                and speech is None
                and not pending
            ):
                patrol.tick(now)

            sleep(0.03)

    except KeyboardInterrupt:
        print("프로그램 종료")

    except Exception as error:
        print("오류:", error)

    finally:
        try:
            if speech is not None:
                if speech.poll() is None:
                    speech.terminate()
                    speech.wait(timeout=2)

        finally:
            try:
                if connected:
                    try:
                        dog.move(0)
                    finally:
                        dog.Close()

            finally:
                if microbit is not None:
                    microbit.close()


if __name__ == "__main__":
    main()
