from pydantic import BaseModel, Field, field_validator

from ..users.schemas import UserOut

EMAIL_RE = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$"


class EmailRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_RE)

    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class EmailVerifyIn(EmailRequestIn):
    code: str = Field(pattern=r"^\d{6}$")


class OtpRequestOut(BaseModel):
    detail: str
    retry_after: int
    dev_code: str | None = None


class AuthPairOut(BaseModel):
    user: UserOut
    access_token: str
    expires_in: int
