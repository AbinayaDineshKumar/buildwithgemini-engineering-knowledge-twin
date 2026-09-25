"""Seed script for Firestore incidents collection."""
from google.cloud import firestore

# Project ID hardcoded as a string (per requirements for Agent Platform compatibility)
PROJECT_ID = "qwiklabs-gcp-01-8bad3776c23c"

def seed_database():
    db = firestore.Client(project=PROJECT_ID)
    incidents_ref = db.collection("incidents")

    sample_incidents = [
        {
            "incident_id": "INC-101",
            "title": "High 504 Timeout Rate on Auth Endpoint",
            "service": "auth-service",
            "severity": "SEV-1",
            "status": "INVESTIGATING",
            "description": "504 Gateway Timeouts spiked to 12% on /oauth/token following deployment v2.4.1.",
            "assigned_to": "alice@novasmart.com",
            "created_at": "2026-09-25T04:15:00Z"
        },
        {
            "incident_id": "INC-102",
            "title": "Database Connection Pool Exhaustion",
            "service": "billing-service",
            "severity": "SEV-2",
            "status": "OPEN",
            "description": "PostgreSQL connection pool maxed out at 100 connections causing payment processing failures.",
            "assigned_to": "bob@novasmart.com",
            "created_at": "2026-09-25T05:00:00Z"
        },
        {
            "incident_id": "INC-103",
            "title": "Cache Misconfiguration Causing Slow Dashboard Load",
            "service": "analytics-frontend",
            "severity": "SEV-3",
            "status": "RESOLVED",
            "description": "Redis cache TTL expired prematurely causing heavy fallback queries to BigQuery.",
            "assigned_to": "charlie@novasmart.com",
            "created_at": "2026-09-24T18:30:00Z"
        },
    ]

    for item in sample_incidents:
        incidents_ref.document(item["incident_id"]).set(item)
        print(f"Seeded incident: {item['incident_id']} - {item['title']}")

if __name__ == "__main__":
    seed_database()
