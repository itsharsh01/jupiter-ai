from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field


class ApplicationType(str, Enum):
    BANKING_ASSISTANT = "Banking Assistant"
    CUSTOMER_SUPPORT_AGENT = "Customer Support Agent"
    LOAN_ASSISTANT = "Loan Assistant"
    INVESTMENT_ASSISTANT = "Investment Assistant"
    FRAUD_DETECTION_AGENT = "Fraud Detection Agent"
    KYC_ASSISTANT = "KYC Assistant"
    CUSTOM = "Custom"


class Environment(str, Enum):
    PRODUCTION = "Production"
    STAGING = "Staging"
    DEVELOPMENT = "Development"


class ToolCategory(str, Enum):
    DATA_ACCESS = "Data Access"
    PAYMENT = "Payment"
    IDENTITY = "Identity"
    CREDIT = "Credit"
    COMPLIANCE = "Compliance"
    COMMUNICATION = "Communication"
    ANALYTICS = "Analytics"
    INTEGRATION = "Integration"
    OTHER = "Other"


class SensitiveDataAsset(str, Enum):
    CUSTOMER_EMAIL = "Customer Email"
    PHONE_NUMBER = "Phone Number"
    PAN = "PAN"
    AADHAAR = "Aadhaar"
    ACCOUNT_NUMBER = "Account Number"
    TRANSACTION_HISTORY = "Transaction History"
    BALANCE_INFORMATION = "Balance Information"
    LOAN_INFORMATION = "Loan Information"
    CREDIT_SCORE = "Credit Score"
    KYC_DOCUMENTS = "KYC Documents"


class PolicyType(str, Enum):
    GOVERNANCE = "governance"
    PRIVACY = "privacy"
    SECURITY = "security"
    COMPLIANCE = "compliance"


# --- Requests ---


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    company: str | None = Field(None, max_length=200)


class SystemInformationUpdate(BaseModel):
    application_name: str = Field(..., min_length=1, max_length=200)
    application_description: str = Field(..., min_length=1, max_length=5000)
    application_type: ApplicationType
    environment: Environment
    custom_application_type: str | None = Field(
        None, max_length=200, description="Required when application_type is Custom"
    )


class ToolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    category: ToolCategory


class ToolsReplace(BaseModel):
    tools: list[ToolCreate] = Field(default_factory=list)


class CustomAssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class DataAssetsUpdate(BaseModel):
    sensitive_data_assets: list[SensitiveDataAsset] = Field(default_factory=list)
    custom_assets: list[CustomAssetCreate] = Field(default_factory=list)


# --- Stored models ---


class ToolRecord(ToolCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))


class CustomAssetRecord(CustomAssetCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))


class PolicyFileRecord(BaseModel):
    policy_type: PolicyType
    filename: str
    stored_path: str
    uploaded_at: datetime


class PhoenixConfigRecord(BaseModel):
    api_key: str = Field(..., min_length=1)
    collector_endpoint: str = Field(..., min_length=1)
    project_name: str = Field(default="governai", min_length=1)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PhoenixConfigUpdate(BaseModel):
    api_key: str = Field(..., min_length=1)
    collector_endpoint: str = Field(..., min_length=1)
    project_name: str = Field(default="governai", min_length=1)


class PhoenixConfigResponse(BaseModel):
    customer_id: str
    collector_endpoint: str
    project_name: str
    api_key_set: bool
    updated_at: datetime


class PhoenixConfigCredentialsResponse(BaseModel):
    """Full credentials for GovernAI SDK / agent runtimes."""
    customer_id: str
    api_key: str
    collector_endpoint: str
    project_name: str
    updated_at: datetime


class SystemInformationRecord(SystemInformationUpdate):
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CustomerRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    email: EmailStr
    company: str | None = None
    password_hash: str | None = Field(
        default=None,
        description="PBKDF2 hash for platform login; omitted from API responses",
    )
    discovery_session_id: str | None = Field(
        default=None,
        description="Single discovery session id for this customer",
    )
    phoenix_config: PhoenixConfigRecord | None = Field(
        default=None,
        description="Per-customer Phoenix/Arize tracing credentials",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system_information: SystemInformationRecord | None = None
    tools: list[ToolRecord] = Field(default_factory=list)
    sensitive_data_assets: list[SensitiveDataAsset] = Field(default_factory=list)
    custom_assets: list[CustomAssetRecord] = Field(default_factory=list)
    policies: list[PolicyFileRecord] = Field(default_factory=list)

    def onboarding_status(self) -> dict[str, bool]:
        return {
            "step_1_system_information": self.system_information is not None,
            "step_2_tools": len(self.tools) > 0,
            "step_3_data_assets": bool(self.sensitive_data_assets or self.custom_assets),
            "step_3_policies": len(self.policies) > 0,
        }


class CustomerResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    company: str | None
    created_at: datetime
    onboarding: dict[str, bool]
    system_information: SystemInformationRecord | None
    tools: list[ToolRecord]
    sensitive_data_assets: list[SensitiveDataAsset]
    custom_assets: list[CustomAssetRecord]
    policies: list[PolicyFileRecord]

    @classmethod
    def from_record(cls, record: CustomerRecord) -> CustomerResponse:
        return cls(
            id=record.id,
            name=record.name,
            email=record.email,
            company=record.company,
            created_at=record.created_at,
            onboarding=record.onboarding_status(),
            system_information=record.system_information,
            tools=record.tools,
            sensitive_data_assets=record.sensitive_data_assets,
            custom_assets=record.custom_assets,
            policies=record.policies,
        )


class MessageResponse(BaseModel):
    message: str
    customer_id: str | None = None
    data: dict[str, Any] | None = None
