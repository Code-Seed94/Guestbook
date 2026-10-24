# 비둘기 서비스

메시지와 파일을 주고받는 작은 웹앱입니다. 들어오는 방법은 세 가지입니다.

| 입장 방법 | 할 수 있는 일 |
| --- | --- |
| 허순태·곽승현 (아이디 + `APP_PASSWORD`) | 각자의 1:1 방에서 대화 |
| 홍록기 (아이디 + `MASTER_PASSWORD`) | 1:1 방 두 개 + 운영진 대시보드 |
| Guest 입장 (이름만 입력) | 게스트방 대화, 개인·단체방 만들기 |

| 대화방 | 들어갈 수 있는 사람 |
| --- | --- |
| room1 | 허순태, 홍록기 |
| room2 | 곽승현, 홍록기 |
| 게스트방 | 모든 게스트 (운영진은 읽기만) |
| 개인·단체방 | 만든 게스트가 접속 중인 게스트 중에서 초대 (운영진은 읽기만) |

- 운영진 대시보드(`/admin`): 비밀 메시지, 강퇴 1시간, 채팅 금지 1·5·10·30분, 모든 방 열람·삭제
- 제재는 게스트 쿠키 또는 같은 이름에 적용 (IP는 쓰지 않음)
- 개인·단체방 삭제는 복구할 수 없음: 메시지와 파일이 모두 지워짐 (만든 게스트 또는 운영진만)
- 대화방 권한은 모든 요청에서 서버가 확인 (규칙은 `auth.py` 한 곳)
- 카카오톡 형식 말풍선, 3초마다 새 메시지만 받아와서 깜빡임 없음
- 사진·음성·동영상·기타 파일 첨부 (파일당 20MB, 실행 파일 차단)
- `/health`: UptimeRobot이 5분마다 호출, Supabase DB도 가볍게 조회

## 구조

| 파일 | 역할 |
| --- | --- |
| `main.py` | FastAPI 앱과 주소별 처리 |
| `auth.py` | 사용자·대화방 권한 규칙, 서명 쿠키 |
| `store.py` | Supabase 저장소(배포)와 메모리 저장소(로컬·테스트) |
| `templates.py` | HTML 화면 |
| `models.py` | 메시지 입력 검증 |
| `static/style.css`, `static/chat.js` | 디자인, 3초 새 메시지 받기 |
| `supabase_schema.sql` | Supabase 테이블·버킷 생성 SQL (1차) |
| `supabase_migration_v2.sql` | 게스트·개인/단체방·제재용 테이블 추가 SQL (2차) |

## 환경변수

| 이름 | 설명 |
| --- | --- |
| `APP_PASSWORD` | 허순태·곽승현 공용 비밀번호 |
| `MASTER_PASSWORD` | 홍록기(운영진) 비밀번호 |
| `SESSION_SECRET` | 로그인 쿠키 서명용 긴 무작위 문자열 |
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_KEY` | Supabase secret(service_role) 키. 서버에만 둡니다 |

Render에서 실행할 때 위 값이 없으면 앱이 시작되지 않습니다.
로컬에서 `SUPABASE_*`가 없으면 메모리 저장소를 쓰며, 서버를 끄면 대화가 사라집니다.

## 로컬 실행

```bat
cd /d C:\Users\qlsjt\Desktop\Guestbook
set APP_PASSWORD=local-test
set MASTER_PASSWORD=local-master
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다.

## 테스트

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

테스트는 메모리 저장소를 사용하므로 Supabase에 접속하지 않습니다.

## 배포 (Render 무료 + Supabase 무료 + UptimeRobot 무료)

1. Supabase에서 프로젝트를 만들고 SQL Editor에서 `supabase_schema.sql`, 이어서 `supabase_migration_v2.sql`을 실행합니다.
2. Render 서비스의 Environment에 환경변수 5개를 등록합니다.
3. `main` 브랜치에 푸시하면 Render가 자동으로 배포합니다.
4. UptimeRobot에서 `https://<서비스 주소>/health`를 5분 간격 HTTP 모니터로 등록합니다.
