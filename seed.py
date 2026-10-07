"""Creates the tables (if needed) and inserts one demo org/team/user/account/contact,
plus one Resolution Time SLA and one example trigger.

Run with:
    python seed.py
"""
import asyncio
import json

from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal, Base, engine
from app.models import SLA, Account, Contact, Organization, Team, Trigger, TriggerAction, TriggerCondition, User


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        org = await session.scalar(select(Organization))

        if org is None:
            org = Organization(name="Commsworth")
            session.add(org)
            await session.flush()

            team = Team(org_id=org.id, name="Support")
            user = User(org_id=org.id, name="Dana Support", email="dana@commsworth.com", role="agent")
            account = Account(org_id=org.id, name="Acme Corp", primary_domain="acme.com")
            session.add_all([team, user, account])
            await session.flush()

            contact = Contact(org_id=org.id, account_id=account.id, name="Jamie Customer", email="jamie@acme.com")
            session.add(contact)
            await session.flush()

            print(f"Seeded org={org.id} team={team.id} user={user.id} account={account.id} contact={contact.id}")
        else:
            print(f"Org/team/user/account/contact already present (org={org.id}), skipping.")

        sla = await session.scalar(select(SLA).where(SLA.org_id == org.id, SLA.name == "Resolution Time"))
        if sla is None:
            sla = SLA(org_id=org.id, name="Resolution Time", target_minutes=480, counts_business_hours_only=False)
            session.add(sla)
            await session.commit()
            print(f"Seeded sla={sla.id}")
        else:
            print(f"Resolution Time SLA already present (sla={sla.id}), skipping.")

        trigger = await session.scalar(select(Trigger).where(Trigger.org_id == org.id, Trigger.name == "Tag urgent issues"))
        if trigger is None:
            trigger = Trigger(
                org_id=org.id,
                name="Tag urgent issues",
                kickoff_event="issue.created",
                position=1,
                is_enabled=True,
            )
            session.add(trigger)
            await session.flush()

            session.add(
                TriggerCondition(
                    trigger_id=trigger.id,
                    field="issue.title",
                    operator="contains",
                    value="urgent",
                )
            )
            session.add(
                TriggerAction(
                    trigger_id=trigger.id,
                    action_type="add_tag",
                    params=json.dumps({"tag_name": "urgent"}),
                    position=1,
                )
            )
            await session.commit()
            print(f"Seeded trigger={trigger.id}")
        else:
            print(f"Example trigger already present (trigger={trigger.id}), skipping.")


if __name__ == "__main__":
    asyncio.run(seed())
