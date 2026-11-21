"""AWS renderer profile (simulated naming only -- nothing is provisioned)."""

PROFILE = {
    "provider": "aws",
    "display_name": "Amazon Web Services (simulated)",
    "compute": {
        "containers": "Amazon ECS on Fargate",
        "artifact_registry": "Amazon ECR",
        "vm": "Amazon EC2",
        "batch": "AWS Batch",
    },
    "database": {
        "postgres": "Amazon RDS for PostgreSQL",
        "mysql": "Amazon RDS for MySQL",
        "sqlserver": "Amazon RDS for SQL Server",
        "oracle_bridge": "Amazon RDS Custom for Oracle (bridge only)",
        "object_storage": "Amazon S3",
    },
    "secrets": "AWS Secrets Manager",
    "observability": "Amazon CloudWatch + AWS X-Ray",
    "messaging": "Amazon EventBridge + SQS",
    "identity": {
        "sso": "IAM Identity Center (SSO)",
        "ldap": "AWS Managed Microsoft AD",
    },
    "file_transfer": "AWS Transfer Family",
    "saas_file_hub": "AWS Transfer Family + S3 drop buckets",
    "network": {
        "vpc": "Amazon VPC",
        "private_dns": "Route 53 Private Hosted Zone",
        "waf": "AWS WAF",
    },
}
