/**
 * 변수
 */
// ==============================================================
// 학습자료 5 — 환경센서 데이터 송신 예제
// 마이크로비트 V2 + IO:BIT + 환경센서 키트
// ==============================================================
// 
// 이 예제로 할 수 있는 것
// - 학습자료 4와 똑같이 저장하면서,
// - 라디오로 상태(OK/DANGER)를 다른 마이크로비트(예: 로보독)에 보낸다.
// 
// 받는 쪽 예제: 학습자료 6 (로보독 데이터 수신 예제)
// → 두 마이크로비트의 radio.set_group 번호가 같아야 한다.
// 
// 필요한 메이크코드 확장
// - OLED, bplab, datalogger
// ==============================================================
// 데이터로거 메모리 가득 처리
datalogger.onLogFull(function () {
    basic.showIcon(IconNames.No)
    datalogger.deleteLog()
    basic.clearScreen()
})
input.onGesture(Gesture.Shake, function () {
    EARTHQUACK = "1"
    state = "E1"
})
let gas = 0
let temp = 0
let EARTHQUACK = ""
let state = ""
let fire = 0
// 임계값 (우리 교실에서 측정 후 조정)
let GAS_DANGER = 800
state = "OK"
// 초기 설정
radio.setGroup(1)
OLED.init(128, 64)
OLED.clear()
OLED.writeStringNewLine("TX START")
datalogger.includeTimestamp(FlashLogTimeStampFormat.Seconds)
datalogger.mirrorToSerial(true)
datalogger.setColumnTitles(
"Temp",
"Gas",
"Fire",
"EARTHQUACK",
"State"
)
input.soundLevel()
basic.pause(2000)
basic.forever(function () {
    let hum = 0
    // 센서 읽기
    temp = input.temperature()
    gas = pins.analogReadPin(AnalogReadWritePin.P1)
    fire = pins.digitalReadPin(DigitalPin.P3)
    // 상태 판단
    if (fire == 0) {
        state = "F1"
    } else if (gas > GAS_DANGER) {
        state = "G1"
    } else if (temp > 30) {
        state = "H1"
    }
    // OLED 출력
    OLED.clear()
    OLED.writeStringNewLine("=== TX ===")
    OLED.writeStringNewLine("T:" + ("" + temp) + " H:" + ("" + hum))
    OLED.writeStringNewLine("Gas:" + ("" + gas) + " F:" + ("" + fire))
    OLED.writeStringNewLine("STATE: " + state)
    OLED.writeStringNewLine("(group 19)")
    // 데이터 기록
    datalogger.log(
    datalogger.createCV("Temp", temp),
    datalogger.createCV("Gas", gas),
    datalogger.createCV("Fire", fire),
    datalogger.createCV("EARTHQUACK", EARTHQUACK),
    datalogger.createCV("State", state)
    )
    // 라디오 송신
    radio.sendString(state)
    basic.showString(state)
    basic.pause(2500)
})

