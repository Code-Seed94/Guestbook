"""비둘기 서비스 입력 검증 모델."""

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    """대화방 입력창에서 받은 메시지를 검증한다. 파일만 보낼 때는 비어 있어도 된다."""

    model_config = ConfigDict(str_strip_whitespace=True)

    body: str = Field(default="", max_length=1000)
