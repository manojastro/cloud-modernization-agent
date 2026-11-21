"""Azure renderer profile (simulated naming only -- nothing is provisioned)."""

PROFILE = {
    "provider": "azure",
    "display_name": "Microsoft Azure (simulated)",
    "compute": {
        "containers": "Azure Container Apps",
        "artifact_registry": "Azure Container Registry",
        "vm": "Azure Virtual Machines",
        "batch": "Azure Batch",
    },
    "database": {
        "postgres": "Azure Database for PostgreSQL Flexible Server",
        "mysql": "Azure Database for MySQL Flexible Server",
        "sqlserver": "Azure SQL Managed Instance",
        "oracle_bridge": "Oracle Database@Azure (bridge only)",
        "object_storage": "Azure Blob Storage",
    },
    "secrets": "Azure Key Vault",
    "observability": "Azure Monitor + Application Insights",
    "messaging": "Azure Service Bus + Event Grid",
    "identity": {
        "sso": "Microsoft Entra ID (SSO)",
        "ldap": "Microsoft Entra Domain Services",
    },
    "file_transfer": "Azure Logic Apps SFTP connector",
    "saas_file_hub": "Azure Storage + Logic Apps file hub",
    "network": {
        "vpc": "Azure Virtual Network",
        "private_dns": "Azure Private DNS",
        "waf": "Azure Front Door WAF",
    },
}
