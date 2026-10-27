# 정선 AIGO · ON & OUT

ON 순찰·재난 안내와 OUT 배송서비스의 전체 코드, Windows 연결 도우미, 수신 micro:bit HEX를 포함한 GitHub 업로드용 통합본입니다.

## 처음 사용하는 PC · IN + ON/OUT 한 번에 설치

[AIGO 전체 통합 ZIP](https://github.com/Yoon-nana/AIGO-On-n-Out/releases/latest/download/AIGO_All_In_One.zip)을 받아 모두 압축 푼 뒤 최상위 폴더의 `Install_All.cmd`를 한 번 실행하세요. Python 3.10~3.14와 Windows `py` 실행기가 필요합니다. 이후 같은 폴더의 `Start_ON_OUT.cmd` 또는 `Start_IN.cmd`를 실행합니다. 두 서비스는 한 `.venv`를 공유합니다.

## 이번 통합본

- ON 순찰은 화면에서 정한 S·A·B·C 좌표와 순서를 따라 상대 회전 후 정해진 시간만큼 전진합니다. 화면 위치는 주행 시간으로 계산한 예상 위치입니다.
- 순찰 중 몸체 LED는 초록색, 눈 LED는 초롱초롱 표정으로 켜집니다. 멧돼지 이미지로 학습한 CLASS1을 연속 인식하면 한 번 짖고 관제 알림에 남기며 순찰을 이어갑니다.
- 재난 대피 안내는 선택한 지역을 순서대로 방문합니다. 각 지역에서 인물 인식을 10초씩 최대 5회 시도하며, 찾지 못해도 다음 선택 지역을 방문합니다. 찾으면 S까지 안내한 뒤 다음 지역으로 갑니다.

- 브라우저 탭 제목·상단·하단 이름: **ON & OUT**.
- AIGO_Install.ps1과 AIGO_Launch.ps1을 모두 포함했습니다. 확장자는 .psl이 아니라 마지막 글자가 숫자 1인 **.ps1**입니다.
- PS1 누락 안내, 최초 실행 설치, 폴더 이동 후 설정 재생성, Python 3.10~3.14 확인을 포함합니다.
- ON 수신 오류를 화면에 계속 표시하고 일시적인 시리얼 읽기 오류를 복구합니다.
- microbit-receiver-check.html: ON 프레임·Python 서버와 별개로 USB만 확인하는 단독 진단 파일.
- receiver_test_original.hex: 제공받은 수신 테스트 HEX의 내용 변경 없는 복사본.

## GitHub 전체 파일 업로드

1. ZIP을 **모두 압축 풀기** 합니다.
2. **본인 계정**의 저장소 첫 화면에서 **Add file → Upload files**를 엽니다.
3. pawcare-github-upload 폴더 **안의 파일 전체**를 올립니다. 바깥 폴더로 한 단계 감싸거나 ZIP 자체만 올리지 마세요.
4. **Commit changes**로 저장합니다. 같은 경로의 파일은 업데이트되며 ZIP에 없는 옛날 파일은 자동 삭제되지 않습니다.

저장소 첫 화면에 index.html, pawcare_control.html, 두 PS1, 두 CMD, Python 파일과 HEX가 바로 보여야 합니다. 이 통합본은 파일 100개 미만이며 각 파일도 GitHub 웹 업로드 제한인 25MiB보다 작습니다.

PC에서 생성된 .venv, work, aigo-helper.local.json, 운행 기록과 개인 설정은 업로드하지 마세요. 이 ZIP에는 포함하지 않았습니다.

## GitHub Pages 배포

**이 ON & OUT 프로젝트는 main 브랜치의 / (root)를 배포합니다. 이전 IN 프로젝트인 With-AI-Complete의 /docs와 다릅니다.**

1. 본인 저장소의 **Settings → Pages**를 엽니다.
2. Source: **Deploy from a branch**.
3. Branch: **main**, 폴더: **/ (root)** → **Save**. 기본 브랜치 이름이 다르면 실제 브랜치를 선택하세요.
4. **Actions → pages build and deployment**가 완료되면 **Settings → Pages → Visit site**를 누릅니다.
5. 공유할 사이트 주소는 **https://본인아이디.github.io/저장소이름/**입니다. **Custom domain은 비워둡니다.**

index.html과 pawcare_control.html은 같은 화면입니다. 수정 시 두 파일을 함께 올리고 배포 완료 후 Ctrl+F5로 새로고침하세요.

상단의 연결 도우미 설치 파일 링크는 github.io에서 현재 사이트의 계정·저장소를 따라갑니다. 로컬 파일이나 별도 도메인에서는 이 README를 엽니다. 수신 HEX 다운로드와 USB 단독 진단 링크도 상단에 있습니다.

공식 안내: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

## Windows PC 설치·실행

1. Python 3.10~3.14 중 하나와 py 실행기를 설치합니다. 설치 프로그램은 3.14부터 우선 확인합니다.
2. 프로젝트 전체를 압축 푼 폴더에서 **AIGO_Install.cmd**를 한 번 실행합니다. 최초 설치에는 인터넷이 필요합니다.
3. **AIGO_Start.cmd**를 실행합니다. 설치가 없으면 설치를 이어서 진행합니다.
4. 자동으로 열리는 **http://127.0.0.1:8765/** 로컬 관제에서 사용합니다.
5. 로보독과 수신 micro:bit의 실제 USB 포트를 각각 구별해 선택합니다.

PS1을 직접 더블클릭하지 말고 CMD로 실행하세요. 설치 폴더를 옮기면 새 폴더에서 AIGO_Install.cmd를 다시 실행합니다. 로그는 work/aigo-runtime/bridge.stderr.log와 bridge.stdout.log입니다.

GitHub Pages는 정적 관제 화면과 다운로드 파일을 제공합니다. Python 서버·로보독 제어는 장치가 연결된 PC에서 실행합니다. GitHub에 업데이트해도 PC의 로컬 설치 폴더는 자동으로 바뀌지 않습니다.

## 수신 micro:bit HEX

**[receiver_test_original.hex](receiver_test_original.hex)**는 사용자가 제공한 microbit-데모데이-마빗-테스트코드.hex의 복사본입니다. 파일명만 영문으로 정리했으며 내용은 바꾸지 않았습니다. 내장 MakeCode 소스는 receiver_test_original.ts로 추출했습니다.

1. **PC에 연결할 수신 micro:bit**의 MICROBIT 드라이브에 HEX를 복사합니다.
2. 설치·재시작이 끝나면 데스크톱 Chrome·Edge에서 ON의 **수신기 연결**을 누릅니다.
3. 로보독 포트와 구별해서 수신 micro:bit를 선택합니다. 사용자 PC에서는 마빗이 COM6으로 확인됐지만 PC마다 번호가 다릅니다.
4. 이 HEX는 **라디오 그룹 1**, **USB 115200 baud**를 사용합니다.
5. 무선 문자열을 RX: 접두사와 함께 USB로 전달합니다. 예: RX:E1.
6. **흔들기 → RX:E1 출력** 테스트 기능이 있습니다. 단독 진단 파일에서 확인할 수 있습니다.

E1은 지진 재난 테스트 신호입니다. 로봇을 운행 중인 상태에서 흔들기 테스트를 하지 마세요. 이 HEX는 PC 수신기용입니다. 관측소 송신기 프로그램과 구별하고 무선 시험 시 송신기도 그룹 1을 사용하세요.

## COM6 연결 오류 해결 기록

실제 PC의 단독 진단에서 다음 오류가 확인됐습니다.

    NetworkError: Failed to execute open on SerialPort: Failed to open serial port.

이는 포트를 고른 다음 여는 단계에서 발생했던 오류입니다. **사용자가 PC를 재부팅한 뒤 연결이 정상적으로 됐다고 확인했습니다.** 재부팅으로 해소된 원인이 백그라운드 포트 점유인지 드라이버·장치 상태인지는 확정하지 않았습니다. 이 연결 오류를 고치기 위해 HEX를 변경할 필요는 없었습니다.

1. **microbit-receiver-check.html**을 Chrome·Edge로 엽니다. 사이트 상단 **USB 단독 진단**으로도 열 수 있습니다.
2. **① 수신 마빗 선택·연결**을 눌러 마빗 포트를 선택합니다.
3. 중앙의 실패 단계·오류와 아래 진단 기록을 확인합니다.
4. PC를 재시작한 뒤 도우미·MakeCode·Thonny를 실행하지 않고 마빗만 연결하여 검사하면 백그라운드 포트 점유 여부를 좁힐 수 있습니다.
5. 계속 실패하면 장치 관리자 → 포트(COM 및 LPT) → 마빗 COM 포트 → 속성 → 일반의 **장치 상태**를 확인합니다.

이미 Python 도우미가 같은 마빗 포트를 열었다면 브라우저가 동시에 열 수 없습니다. ON에 연결 도우미 수신기 연결됨이라고 나오면 도우미 연결 상태부터 확인하세요.

## 주요 파일

| 파일 | 역할 |
|---|---|
| index.html, pawcare_control.html | ON & OUT 관제·Pages 시작 화면 |
| AIGO_Install.cmd, AIGO_Install.ps1 | 가상환경·의존성 설치와 도우미 등록 |
| AIGO_Start.cmd, AIGO_Launch.ps1 | 로컬 서버·관제 시작 |
| robodog_abc_delivery.py | 서버·OUT 배송·공통 장치 처리 |
| aigo_on_patrol.py, on_demo_original.py | ON 순찰·재난 안내 |
| requirements-bridge.txt | Python 의존성 |
| receiver_test_original.hex | 제공받은 PC 수신 테스트 펌웨어 |
| receiver_test_original.ts | 해당 HEX에서 추출한 원본 소스 |
| microbit-receiver-check.html | 독립 USB 연결 진단 |
| microbit_pc_receiver_makecode.ts | 기존 프로젝트의 PC 수신기 소스 |
| microbit_disaster_station_sender_makecode.ts | 기존 관측소 송신기 소스 |

기타 README와 계획 문서는 기존 참고 자료입니다. 최신 실행 방법·배포 설정·연결 문제 상태는 이 README를 우선 확인하세요.

## 검증과 한계

- PS1 구문 및 모의 설치·실행 검증본을 포함했습니다.
- ON 연결 유지·오류 표시·일시 오류 복구 등 모의 테스트 8개를 통과했습니다.
- 독립 진단의 포트 취소·열기 실패·정상 연결 모의 테스트를 통과했습니다.
- HEX 내장 소스의 그룹·baud rate·형식과 RX:E1 파싱을 확인했습니다.
- 스크립트 구문·HTML 두 파일 일치·ZIP 필수 파일과 무결성을 검사했습니다.
- 사용자 확인: PC 재부팅 후 수신 마빗 연결 성공. 전체 로봇 주행·무선 수신·재난 안내 과정의 성공 여부는 별도 확인 대상입니다.

**이 ZIP의 복사본만 수정했습니다. 다른 사람의 GitHub 저장소나 사이트는 변경하지 않았습니다.**

## 수신 테스트 HEX

`receiver_test_original.hex`는 제공받은 테스트 파일을 내용 변경 없이 포함했습니다.
