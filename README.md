# 우리의 방명록

`01-Day1`부터 `08-Day8`까지 학습한 파이썬, FastAPI, Pydantic, pytest를 활용한 최소 구성 방명록입니다.

## 기능

- 이름과 메시지 작성
- 최근 작성 글부터 최대 100개 표시
- SQLite 파일에 데이터 저장
- 입력 길이 검증과 HTML 이스케이프
- 상태 확인용 `GET /health`

데이터베이스는 파이썬 내장 `sqlite3`를 사용하며 `entries` 테이블 하나만 생성합니다. 화면은 HTML과 CSS로만 구성하고 JavaScript는 사용하지 않습니다.

## 로컬 실행

Education 폴더의 공용 가상환경을 사용하는 경우:

```bat
cd /d "C:\Users\qlsjt\Desktop\encore-multi-agent\Education\day1-8"
..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다.

독립 가상환경이 필요하면 먼저 사용자 확인 후 `day1-8\.venv`를 생성합니다.

## 테스트

독립 가상환경에서 테스트까지 설치할 때는 `requirements-dev.txt`를 사용합니다. 배포용 `requirements.txt`에는 실행에 필요한 패키지만 들어 있습니다.

```bat
python -m pip install -r requirements-dev.txt
..\.venv\Scripts\python.exe -m pytest -q
```

테스트 데이터베이스는 pytest의 임시 폴더를 사용하므로 실제 `data\guestbook.db`를 변경하지 않습니다.

## 배포 전 확인

무료 배포 서비스 중 일부는 재시작할 때 로컬 SQLite 파일이 삭제될 수 있습니다. 따라서 배포 서비스와 SQLite 지속 저장 방식은 사용자 승인 후 결정하고, 승인 전에는 배포나 외부 저장소 생성을 진행하지 않습니다.

공식 문서를 비교한 결과와 승인 후 절차는 `DEPLOYMENT_OPTIONS.md`에 정리했습니다. 현재 우선 후보는 PythonAnywhere이며 실제 계정 작업은 승인 후 진행합니다.
