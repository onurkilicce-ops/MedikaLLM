from __future__ import annotations
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Literal
import re

# bcrypt only accepts secrets of at most 72 bytes (UTF-8); bcrypt>=5 raises
# ValueError above that instead of truncating.
BCRYPT_MAX_PASSWORD_BYTES = 72

class UserBase(BaseModel):
    # used interally and in llm context
    user_id: str
    email: EmailStr
    name: str
    is_doctor: bool = False  # Computed from doctor_profile existence
    is_patient: bool = False  # Computed from patient_profile existence
    patient_id: str | None = None  # The patient profile UUID if is_patient
    
    def to_dto(self) -> UserDto:
        return UserDto(
            userId=self.user_id,
            email=self.email,
            name=self.name,
            isDoctor=self.is_doctor,
            isPatient=self.is_patient,
            patientId=self.patient_id,
        )
        
class User(UserBase):
    password: str
    created_at: str
    updated_at: str

class UserDto(BaseModel):
    # used in API responses
    userId: str
    email: EmailStr
    name: str
    isDoctor: bool = False
    isPatient: bool = False
    patientId: str | None = None

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1)
    account_type: Literal["user", "doctor", "patient"] = "user"
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least 1 uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least 1 lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least 1 number")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", v):
            raise ValueError("Password must contain at least 1 special character")
        return v
    
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    
class SendCodeRequest(RegisterRequest):
    pass

class VerificationCodeRequest(BaseModel):
    email: EmailStr
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str = Field(min_length=8)
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least 1 uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least 1 lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least 1 number")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", v):
            raise ValueError("Password must contain at least 1 special character")
        return v


class ChangePasswordRequest(BaseModel):
    """In-app password change. Requires the current password (so a leaked
    JWT alone cannot be used to lock the legitimate user out) and the new
    password — the same complexity rules as registration apply."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        # bcrypt (5.x) refuses secrets longer than 72 BYTES; the limit is on
        # the UTF-8 encoding, not on the character count ("ü" is 2 bytes).
        # Reject here (422) instead of failing at hash time (500); never
        # truncate silently.
        if len(v.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded "
                "(non-ASCII characters count as 2-4 bytes)"
            )
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least 1 uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least 1 lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least 1 number")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", v):
            raise ValueError("Password must contain at least 1 special character")
        return v

class AuthResponse(BaseModel):
    token: str
    user: UserDto