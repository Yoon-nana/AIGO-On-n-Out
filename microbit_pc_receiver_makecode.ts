radio.setGroup(1)

serial.redirectToUSB()
serial.setBaudRate(BaudRate.BaudRate115200)
led.enable(true)

let latestMessage = ""
let receivedCount = 0
let displayedCount = 0

radio.onReceivedString(function (message) {
    latestMessage = message
    receivedCount += 1

    // 실제 무선 메시지를 받았을 때만 USB로 전달
    serial.writeLine("RX:" + message)
})

basic.showString("-")

basic.forever(function () {
    if (receivedCount != displayedCount) {
        displayedCount = receivedCount
        basic.showString(latestMessage)
    }

    basic.pause(20)
})

