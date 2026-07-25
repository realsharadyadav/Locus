from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Collection


def seed_database(db: Session) -> None:
    if db.scalar(select(func.count(Collection.id))):
        return

    db.add_all([
        Collection(title="Product thinking", description="Frameworks, notes & references for building products people love.", color="violet"),
        Collection(title="AI & the future", description="Research, ideas and signals about intelligent systems.", color="peach"),
        Collection(title="Books & essays", description="Highlights and ideas worth returning to.", color="green"),
    ])
    db.commit()
