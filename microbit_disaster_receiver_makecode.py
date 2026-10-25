# MakeCode Python: RoboDog 탑재 micro:bit 수신·기록 코드
# 구간 micro:bit가 보낸 E/F/G/H + 위치 1/2 신호를 라디오 그룹 1로 받습니다.
# 신호와 이 micro:bit의 소리·빛 측정값은 DataLogger에 저장됩니다.
# PC USB 게이트웨이가 없으므로 serial.redirect_to_usb()는 사용하지 않습니다.

radio.set_group(1)
datalogger.set_column_titles("time_ms", "segment", "phase", "sound", "light", "event")

# 주신 코스값을 이용해 경과 시간으로 구간을 추정합니다.
# 실제 위치 센서가 없으므로 segment/phase는 계산값입니다.
speed_cm_per_s = 23
turn_time_per_degree = 2.80 / 180
course = [10, 100, 90, 30, 90, 100, -90, 30, -90, 100, 90, 30, 90, 100, -90, 30, -90, 100]

segment_end_times_ms = []
segment_phases = []
cumulative = 0
for i in range(len(course)):
    value = course[i]
    if (i + 1) % 2 == 1:
        duration_s = abs(value) * turn_time_per_degree
        phase_label = "TURN"
    else:
        duration_s = value / speed_cm_per_s
        phase_label = "STRAIGHT"
    cumulative += duration_s * 1000
    segment_end_times_ms.append(cumulative)
    segment_phases.append(phase_label)


def get_segment_info(t):
    for i in range(len(segment_end_times_ms)):
        if t < segment_end_times_ms[i]:
            return i + 1, segment_phases[i]
    return len(segment_end_times_ms) + 1, "DONE"


# A 버튼을 누르면 이전 기록을 지우고 측정을 시작합니다.
start_time = -1


def on_button_pressed_a():
    global start_time
    datalogger.delete_log()
    start_time = input.running_time()
    basic.show_icon(IconNames.YES)


input.on_button_pressed(Button.A, on_button_pressed_a)


def on_received_string(received_string):
    message = received_string
    if len(message) != 2:
        basic.show_string("?")
        return

    disaster_code = message[0]
    location_code = message[1]
    if (disaster_code != "E" and disaster_code != "F" and
            disaster_code != "G" and disaster_code != "H"):
        basic.show_string("?")
        return
    if location_code != "1" and location_code != "2":
        basic.show_string("?")
        return

    # E=지진, F=화재, G=가스, H=무더위.
    # 신호가 도착한 시각과 위치를 micro:bit 내부 기록에 남깁니다.
    event_name = "EARTHQUAKE"
    if disaster_code == "F":
        event_name = "FIRE"
    elif disaster_code == "G":
        event_name = "GAS"
    elif disaster_code == "H":
        event_name = "HEAT"

    event_time = input.running_time()
    if start_time >= 0:
        event_time = event_time - start_time
    datalogger.log(
        datalogger.create_cv("time_ms", event_time),
        datalogger.create_cv("segment", location_code),
        datalogger.create_cv("phase", "EVENT"),
        datalogger.create_cv("sound", ""),
        datalogger.create_cv("light", ""),
        datalogger.create_cv("event", event_name)
    )
    basic.show_string(message)


radio.on_received_string(on_received_string)


def on_forever():
    if start_time >= 0:
        elapsed = input.running_time() - start_time
        segment, phase = get_segment_info(elapsed)
        sound_value = input.sound_level()
        light_value = input.light_level()
        datalogger.log(
            datalogger.create_cv("time_ms", elapsed),
            datalogger.create_cv("segment", segment),
            datalogger.create_cv("phase", phase),
            datalogger.create_cv("sound", sound_value),
            datalogger.create_cv("light", light_value),
            datalogger.create_cv("event", "")
        )
        basic.show_number(sound_value)
    else:
        basic.show_icon(IconNames.SMALL_DIAMOND)
    basic.pause(500)


basic.forever(on_forever)

