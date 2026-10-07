from pydantic import BaseModel, ConfigDict


class ContactCreate(BaseModel):
    org_id: int
    account_id: int
    name: str
    email: str


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    account_id: int
    name: str
    email: str
