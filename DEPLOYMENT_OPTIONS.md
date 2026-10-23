# 무료 배포 서비스 검토

검토일: 2026-10-23

요구 조건은 FastAPI 실행, 파이썬 내장 SQLite 사용, 무료 범위 유지, 방명록 데이터 보존입니다. 실제 배포는 사용자 승인 전까지 진행하지 않습니다.

| 서비스 | FastAPI 무료 실행 | SQLite 파일 보존 | 판정 |
| --- | --- | --- | --- |
| PythonAnywhere Beginner | 무료 웹앱 1개, 워커 1개. FastAPI용 ASGI 배포 기능은 베타 | 무료 계정의 홈 파일 공간 512MiB에 저장 가능 | **우선 후보** |
| Render Free Web Service | 가능하지만 15분 동안 요청이 없으면 중지 | 재배포·재시작·중지 시 로컬 SQLite 파일 손실 | 제외 |
| Koyeb Free Instance | 무료 Web Service 1개 가능 | 무료 인스턴스는 영구 볼륨 연결 불가, 로컬 저장소는 임시 저장소 | 제외 |
| Hugging Face Spaces | 정적 사이트는 무료지만 FastAPI용 Docker 실행은 현재 유료 플랜 필요 | 기본 디스크는 영구 저장소가 아님 | 제외 |

## 권장안: PythonAnywhere

PythonAnywhere를 우선 후보로 선택한 이유는 현재 구조를 바꾸지 않고 FastAPI와 SQLite를 함께 유지할 수 있기 때문입니다.

주의할 점:

- ASGI 웹사이트 기능은 공식 문서에서 베타로 표시됩니다.
- 무료 웹앱은 1개월 만료 방식이므로 계속 사용하려면 갱신이 필요합니다.
- 무료 계정은 웹 워커가 1개이고 파일 공간은 512MiB입니다.
- 별도의 외부 API를 사용하지 않으므로 무료 계정의 외부 인터넷 제한은 현재 앱에 영향을 주지 않습니다.
- 플랫폼의 정적 파일 매핑 대신 현재 FastAPI 앱의 `/static` 경로가 CSS를 제공합니다. 배포 후 실제 CSS 응답을 확인해야 합니다.

## 승인 후 진행할 작업

1. 사용자의 PythonAnywhere 계정 이름을 확인합니다.
2. `day1-8` 소스만 PythonAnywhere 홈 폴더에 업로드합니다.
3. Python 3.10 이상 가상환경을 만들고 `requirements.txt`를 설치합니다.
4. 다음 형식으로 ASGI 웹사이트를 생성합니다.

```text
/home/사용자명/.virtualenvs/day1-8/bin/uvicorn --app-dir /home/사용자명/day1-8 --uds ${DOMAIN_SOCKET} main:app
```

5. 공개 URL에서 홈, CSS, 작성, SQLite 재조회, `/health`를 확인합니다.
6. 웹앱 재시작 후에도 작성한 글이 남는지 확인합니다.

## 공식 근거

- PythonAnywhere 무료 계정 기능: https://help.pythonanywhere.com/pages/FreeAccountsFeatures/
- PythonAnywhere FastAPI ASGI 배포: https://help.pythonanywhere.com/pages/ASGICommandLine
- PythonAnywhere 저장 공간: https://help.pythonanywhere.com/pages/DiskQuota
- Render 무료 서비스 제한: https://render.com/docs/free
- Koyeb 무료 인스턴스: https://www.koyeb.com/docs/reference/instances
- Koyeb 임시 저장소: https://www.koyeb.com/docs/reference/storage
- Hugging Face Spaces 개요: https://huggingface.co/docs/hub/spaces-overview
