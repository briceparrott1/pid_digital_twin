from neo4j import GraphDatabase
from core.config import get_settings

settings = get_settings()

driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password),
    notifications_disabled_categories=["UNRECOGNIZED"],
)

def get_driver():
    return driver