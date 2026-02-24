from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    telegram_id: str
    token_balance: int
    subscription_active: bool
    free_generations_used: int = 0
    free_generations_left: int = 3
    copy_generations_used: int = 0
    copy_generations_left: int = 1


class UserAdminUpdate(BaseModel):
    token_balance: int
    subscription_active: bool
