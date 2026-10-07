from pydantic import BaseModel, ConfigDict


class AccountCreate(BaseModel):
    org_id: int
    name: str
    primary_domain: str


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    name: str
    primary_domain: str
