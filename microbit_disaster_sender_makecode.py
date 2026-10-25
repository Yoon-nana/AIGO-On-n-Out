# MakeCode Python: 재난 신호 송신 micro:bit
# 라디오 그룹 1. A=위치 1/2 전환, B=재난 종류 순환,
# A+B=선택한 신호 전송 (예: F1=화재 위치 1, E2=지진 위치 2)

radio.set_group(1)

disaster_codes = ["E", "F", "G", "H"]
disaster_index = 0
location_code = "1"


def on_forever():
    global disaster_index, location_code

    if input.button_is_pressed(Button.A) or input.button_is_pressed(Button.B):
        # A+B 조합이 눌렸는지 확인할 시간을 줍니다.
        basic.pause(150)
        a_pressed = input.button_is_pressed(Button.A)
        b_pressed = input.button_is_pressed(Button.B)

        if a_pressed and b_pressed:
            signal = disaster_codes[disaster_index] + location_code
            radio.send_string(signal)
            basic.show_string(signal)
        elif a_pressed:
            if location_code == "1":
                location_code = "2"
            else:
                location_code = "1"
            basic.show_string(disaster_codes[disaster_index] + location_code)
        elif b_pressed:
            disaster_index = (disaster_index + 1) % len(disaster_codes)
            basic.show_string(disaster_codes[disaster_index] + location_code)

        # 버튼을 놓을 때까지 기다려 한 번만 동작하게 합니다.
        while input.button_is_pressed(Button.A) or input.button_is_pressed(Button.B):
            basic.pause(20)

    basic.pause(30)


basic.show_string(disaster_codes[disaster_index] + location_code)
basic.forever(on_forever)
