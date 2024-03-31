from typing import Optional

from pydantic import BaseModel, Field

from forums.db.users import User


class UserAPI(BaseModel):
    """
    A slimmed down User object without any sensitive information
    """
    @classmethod
    def from_user(cls, user: User):
        """
        Create a UserAPI object from an existing User obj
        """
        return cls(user_id=user.user_id, username=user.username, display_name=user.display_name, flags=user.flags)

    # Note: none here indicates a fake user obj without any db equiv
    user_id: Optional[int]
    username: str = Field(default='system')
    display_name: str = Field(default='System')
    flags: int = Field(default=0, ge=0)

