input.onGesture(Gesture.Shake, function () {
    message = "E1"
    receivedCount += 1
    // 실제 무선 메시지를 받았을 때만 USB로 전달
    serial.writeLine("RX:" + message)
})
radio.onReceivedString(function (message) {
    latestMessage = message
    receivedCount += 1
    // 실제 무선 메시지를 받았을 때만 USB로 전달
    serial.writeLine("RX:" + message)
})
let latestMessage = ""
let message = ""
radio.setGroup(1)
serial.redirectToUSB()
serial.setBaudRate(BaudRate.BaudRate115200)
led.enable(true)
basic.showString("-")
let displayedCount = 0
let receivedCount = 0
basic.forever(function () {
    if (receivedCount != displayedCount) {
        displayedCount = receivedCount
        basic.showString(message)
        displayedCount += 1
    }
    basic.pause(20)
})
