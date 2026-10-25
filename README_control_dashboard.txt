PawCare 배송 관제 · 성공했던 RoboDog 구성

최종 연동 코드
- robodog_abc_delivery.py : Thonny에서 실행하는 Python 코드입니다. RoboDog 배송, 인물·QR 확인, 재난 신호 처리와 관제 HTML 서버를 실행합니다.
- microbit_pc_receiver_makecode.ts : PC USB 수신 micro:bit용 MakeCode JavaScript입니다. 라디오 신호를 RX:<신호> 한 줄로 Python에 전달합니다.
- microbit_disaster_station_sender_makecode.ts : 관측소 센서 송신 micro:bit용 MakeCode JavaScript입니다.

장치 연결
- RoboDog: PC USB COM8.
- PC 수신 게이트웨이 micro:bit: PC USB COM10, 115200 baud.
- 관측소 송신 micro:bit: 라디오 그룹 1로 PC 수신 micro:bit에 신호 전송.
- 두 micro:bit의 라디오 그룹은 1이어야 합니다.
- Windows 장치 관리자에서 포트 번호를 확인하고, 다른 경우 Python 파일의 ROBODOG_PORT 또는 MICROBIT_PORT 설정을 바꿉니다.

재난 신호
- 앞 글자 E=지진, F=화재, G=가스 유출, H=무더위.
- 뒤 숫자 1은 A·B, 2는 B·C 영향 위치입니다.
- 신호가 오면 로보독이 멈추고 관제 화면에 재난을 표시합니다. 화면에서 대피 안내 또는 출발점 복귀를 선택합니다.

실행 순서
1. 관측소 송신 코드와 PC 수신 게이트웨이 코드를 각각 MakeCode에 올립니다.
2. 두 micro:bit의 라디오 그룹이 1인지 확인합니다.
3. 수신 micro:bit를 PC에 연결해 COM10인지 확인하고, RoboDog는 COM8로 연결합니다.
4. robodog_abc_delivery.py와 pawcare_control.html을 같은 폴더에 둡니다.
5. Thonny에서 robodog_abc_delivery.py를 실행하고 브라우저에서 http://127.0.0.1:8765/ 를 엽니다.

이 묶음은 이전에 성공했던 로보독 구성의 코드입니다. 현재 장비의 포트와 실기기 동작은 다시 확인하세요. GitHub Pages는 정적 화면이며, 실제 COM 통신과 로봇 제어는 PC에서 실행한 Python 프로그램이 담당합니다.
