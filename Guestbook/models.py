"""방명록 입력 검증 모델."""

from pydantic import BaseModel, ConfigDict, Field


class GuestbookCreate(BaseModel):
    """HTML 폼에서 받은 이름과 메시지를 검증한다."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=20)
    message: str = Field(min_length=1, max_length=500)
