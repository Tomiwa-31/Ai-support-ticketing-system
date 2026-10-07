
#Defines the teams table: groups of support agents (like "Billing" or "Support"). Each team belongs to one organization and can own many issues.
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False) #a real foreign key column storing which org the team belongs t
    name: Mapped[str] = mapped_column(String, nullable=False)

    
    #team has an attribute called org
    org: Mapped["Organization"] = relationship(back_populates="teams")#team.org, the one organization this team belongs to. It pairs with Organization.teams
    issues: Mapped[list["Issue"]] = relationship(back_populates="team")#Gives you team.issues, a list of all issues assigned to this team. It pairs with a team attribute that will sit on Issue, powered by a team_id foreign key on the issues table.
