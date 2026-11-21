"""Google Cloud renderer profile (simulated naming only -- nothing is provisioned)."""

PROFILE = {
    "provider": "gcp",
    "display_name": "Google Cloud (simulated)",
    "compute": {
        "containers": "Cloud Run",
        "artifact_registry": "Artifact Registry",
        "vm": "Compute Engine",
        "batch": "Cloud Batch",
    },
    "database": {
        "postgres": "Cloud SQL for PostgreSQL",
        "mysql": "Cloud SQL for MySQL",
        "sqlserver": "Cloud SQL for SQL Server",
        "oracle_bridge": "Bare Metal Solution for Oracle (bridge only)",
        "object_storage": "Cloud Storage",
    },
    "secrets": "Secret Manager",
    "observability": "Cloud Monitoring + Cloud Trace",
    "messaging": "Pub/Sub",
    "identity": {
        "sso": "Cloud Identity / Identity Platform",
        "ldap": "Managed Service for Microsoft AD",
    },
    "file_transfer": "Cloud Storage transfer + SFTP partner",
    "saas_file_hub": "Cloud Storage bucket-based file hub",
    "network": {
        "vpc": "Virtual Private Cloud",
        "private_dns": "Cloud DNS private zone",
        "waf": "Cloud Armor",
    },
}
