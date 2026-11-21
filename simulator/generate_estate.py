"""Deterministic application-estate simulator.

Generates a seeded, persisted enterprise estate (~120 apps) with CMDB-like records,
network flow logs, batch scheduler extracts and file-transfer logs. Plants:

* one UNDOCUMENTED dependency (an app FTP-ing nightly into another app's drop dir)
  discoverable only by correlating transfer logs with the app inventory;
* showcase apps covering every 7R strategy, two planted wave-conflict blockers and
  one wave-1 app with an Oracle-only runtime incompatibility that must fail and roll back.

Same seed -> byte-identical world. Ground truth for the evaluation suite is written to
evaluation/ground_truth.json at seed time.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

SEED = 20260815

ROOT_DIR = Path(__file__).resolve().parents[1]
GROUND_TRUTH_PATH = ROOT_DIR / "evaluation" / "ground_truth.json"

# Relations covered by the dependency-discovery evaluation.
TRUTH_RELATIONS = {
    "APP_CALLS_APP",
    "APP_USES_DATABASE",
    "APP_USES_IDENTITY",
    "APP_USES_FILE_SHARE",
    "APP_SENDS_FILE_TO",
    "APP_PUBLISHES_EVENT",
    "APP_CONSUMES_EVENT",
}

HIDDEN_SOURCE = "warehouse-inventory-sync"
HIDDEN_TARGET = "partner-portal"
HIDDEN_MOUNT = "/srv/drops/partner-portal/inbound"

WAVE1_INCOMPATIBLE_APP = "receivables-matching-service"

# Wave-0 pilot workloads: leaf apps with a dedicated direct-compat database.
PILOT_APPS = ("expense-capture-tool", "feedback-survey-collector")

STRATEGY_LABELS = [
    {"application": "payments-api-gateway", "expected": "REHOST"},
    {"application": "receivables-matching-service", "expected": "REHOST"},
    {"application": "commission-settlement-engine", "expected": "REHOST"},
    {"application": "card-dispute-tracker", "expected": "REHOST"},
    {"application": "expense-capture-tool", "expected": "REHOST"},
    {"application": "feedback-survey-collector", "expected": "REHOST"},
    {"application": "customer-onboarding-orchestrator", "expected": "REPLATFORM"},
    {"application": "policy-administration-monolith", "expected": "REFACTOR"},
    {"application": "legacy-report-archive", "expected": "RETIRE"},
    {"application": "sftp-drop-hub", "expected": "REPURCHASE"},
    {"application": "core-ledger-batch", "expected": "RETAIN"},
    {"application": "treasury-risk-analytics", "expected": "RELOCATE"},
]

EXPECTED_BLOCKED_MIGRATIONS = ["commission-settlement-engine", "card-dispute-tracker"]

# ------------------------------------------------------------------ catalogues

OS_TABLE = {
    "windows-2012": {"family": "Windows Server", "version": "2012 R2", "eol": True},
    "windows-2019": {"family": "Windows Server", "version": "2019", "eol": False},
    "rhel7": {"family": "Red Hat Enterprise Linux", "version": "7.9", "eol": True},
    "rhel9": {"family": "Red Hat Enterprise Linux", "version": "9.3", "eol": False},
    "ubuntu-20": {"family": "Ubuntu LTS", "version": "20.04", "eol": True},
    "ubuntu-22": {"family": "Ubuntu LTS", "version": "22.04", "eol": False},
    "zos-sim": {"family": "z/OS (simulated)", "version": "2.5", "eol": False},
}

RUNTIME_PROFILES = {
    "java8-weblogic": {
        "language": "Java", "framework": "Java EE on WebLogic 12c", "version": "Java 8",
        "eol": True, "os_pool": ["windows-2012", "rhel7"], "deployment": "app-server",
        "weight": 0.14,
    },
    "dotnet48-iis": {
        "language": "C#", "framework": ".NET Framework 4.8 on IIS", "version": "4.8",
        "eol": False, "os_pool": ["windows-2012", "windows-2019"], "deployment": "iis",
        "weight": 0.14,
    },
    "python-flask": {
        "language": "Python", "framework": "Flask", "version": "3.8 / Flask 2.x",
        "eol": False, "os_pool": ["rhel7", "ubuntu-20", "ubuntu-22"], "deployment": "vm",
        "weight": 0.18,
    },
    "node14-express": {
        "language": "JavaScript", "framework": "Express", "version": "Node 14",
        "eol": True, "os_pool": ["ubuntu-20"], "deployment": "vm",
        "weight": 0.12,
    },
    "php-legacy": {
        "language": "PHP", "framework": "CodeIgniter", "version": "5.6",
        "eol": True, "os_pool": ["windows-2012", "rhel7"], "deployment": "vm",
        "weight": 0.10,
    },
    "cobol-mainframe": {
        "language": "COBOL", "framework": "z/OS JCL batch", "version": "Enterprise COBOL 6",
        "eol": False, "os_pool": ["zos-sim"], "deployment": "mainframe-batch",
        "weight": 0.03,
    },
    "go": {
        "language": "Go", "framework": "net/http", "version": "1.21",
        "eol": False, "os_pool": ["rhel9", "ubuntu-22"], "deployment": "vm",
        "weight": 0.10,
    },
    "springboot-17": {
        "language": "Java", "framework": "Spring Boot", "version": "3.2 / Java 17",
        "eol": False, "os_pool": ["ubuntu-22", "rhel9"], "deployment": "jar",
        "weight": 0.19,
    },
}

DB_ENGINE_TABLE = {
    "oracle-11g": {"eol": True, "managed_equivalent": "managed-postgres-16", "compatibility": "conversion-required", "license_bump": 9000},
    "sqlserver-2014": {"eol": True, "managed_equivalent": "managed-sqlserver-2022", "compatibility": "upgrade-required", "license_bump": 4200},
    "mysql-5.7": {"eol": True, "managed_equivalent": "managed-mysql-8", "compatibility": "direct", "license_bump": 1500},
    "postgres-13": {"eol": False, "managed_equivalent": "managed-postgres-16", "compatibility": "direct", "license_bump": 1200},
    "db2": {"eol": False, "managed_equivalent": None, "compatibility": "none", "license_bump": 7000},
    "flat-files": {"eol": False, "managed_equivalent": "object-storage", "compatibility": "conversion-required", "license_bump": 0},
}

SHARED_SERVICES = [
    {"id": "svc-corporate-ldap", "display_name": "Corporate LDAP", "kind": "identity",
     "description": "Central directory for app authentication binds.", "wave_assignment": 0,
     "replacement_note": "Migrate to managed directory / cloud IAM bridge in wave 0."},
    {"id": "svc-sso-provider", "display_name": "SSO Provider (SAML/OIDC)", "kind": "sso",
     "description": "Single sign-on federation for user-facing apps.", "wave_assignment": 0,
     "replacement_note": "Move to managed identity provider; keep protocol bridge."},
    {"id": "svc-esb-messaging", "display_name": "ESB Messaging Backbone", "kind": "messaging",
     "description": "Enterprise message bus carrying most inter-app events.", "wave_assignment": 1,
     "replacement_note": "Replace with managed event broker; dual-publish during transition."},
    {"id": "svc-sftp-hub", "display_name": "SFTP Transfer Hub", "kind": "file-transfer",
     "description": "Central SFTP endpoint for inter-system file exchange.", "wave_assignment": 2,
     "replacement_note": "Retire homegrown hub with the SaaS-equivalent file transfer service."},
    {"id": "svc-shared-oracle-11g", "display_name": "Shared Oracle 11g Instance", "kind": "database",
     "description": "Shared EOL Oracle instance serving multiple applications.", "wave_assignment": 2,
     "replacement_note": "Convert schemas to managed PostgreSQL; move consumers off before decommission."},
    {"id": "svc-monitoring-stack", "display_name": "Monitoring Stack (Nagios/Grafana)", "kind": "monitoring",
     "description": "Legacy monitoring and alerting.", "wave_assignment": 0,
     "replacement_note": "Stand up central cloud observability in wave 0."},
]

DOMAINS = [
    ("Payments", "Payments Platform Org"),
    ("Lending", "Lending Org"),
    ("Retail Banking", "Branch Channel Org"),
    ("Insurance Claims", "Claims Org"),
    ("Human Resources", "People Ops"),
    ("Finance", "Corporate Finance"),
    ("Customer Service", "CX Org"),
    ("Marketing", "Growth Org"),
    ("Logistics", "Supply Chain Org"),
    ("Procurement", "Procurement Org"),
    ("Risk", "Risk Management Org"),
    ("Compliance", "Compliance Org"),
    ("IT Operations", "Platform Engineering"),
    ("Sales", "Revenue Ops"),
    ("Legal", "Legal Affairs"),
    ("Data & Analytics", "Data Org"),
]

NAME_NOUNS = [
    "Gateway", "Manager", "Service", "Portal", "Engine", "Processor", "Tracker",
    "Dashboard", "Adapter", "Hub", "Console", "Scheduler", "Reporter", "Connector",
    "Validator", "Aggregator", "Catalog", "Registry", "Notifier", "Importer",
    "Exporter", "Calculator", "Auditor", "Monitor", "Workbench", "Reconciler",
]

LIBRARY_POOL = [
    "internal-payments-sdk", "log4j-2.14", "commons-collections-3.1", "jackson-databind",
    "lodash-4.17", "flask-login", "cx-oracle", "odbc32-wrapper", "struts-core-2.3",
    "company-json-utils", "legacy-soap-client", "quartz-scheduler",
]

TOPIC_POOL = [
    "payments.settled", "orders.created", "claims.filedd", "customer.updated",
    "invoice.issued", "shipment.dispatched", "ledger.posted", "risk.scored",
    "inventory.changed", "contract.signed", "case.opened", "payment.failed",
]


@dataclass
class AppSpec:
    """Everything known about one generated application."""
    id: str
    name: str
    domain: str
    business_owner: str
    language: str
    framework: str
    runtime_id: str
    os_id: str
    database_row_id: str | None
    server_count: int
    api_surface: str
    auth_method: str
    statefulness: str
    compliance_scope: str
    usage_per_day: int
    monthly_usage_trend_pct: float
    annual_infra_cost_usd: float
    criticality: int
    commodity_capability: bool = False
    specialized_os_deps: bool = False
    hypervisor_hosted: bool = False
    requested_wave_override: int | None = None
    lifecycle: str = "active"
    description: str = ""
    # runtime details
    monolith_loc: int = 0
    manual_deployments: bool = False
    has_observability: bool = False
    hardcoded_secrets_found: bool = False
    oracle_only_feature: bool = False
    shared_database: bool = False
    change_frequency: str = "monthly"
    last_change_months_ago: int = 6
    # inventory facts
    file_shares: list[str] = field(default_factory=list)  # "name:mount-path"
    publishes: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    batch_jobs: list[dict] = field(default_factory=list)
    transfers: list[dict] = field(default_factory=list)


@dataclass
class EstateData:
    applications: list[AppSpec] = field(default_factory=list)
    databases: list[dict] = field(default_factory=list)
    servers: list[dict] = field(default_factory=list)
    integrations: list[dict] = field(default_factory=list)
    network_flows: list[dict] = field(default_factory=list)
    batch_jobs: list[dict] = field(default_factory=list)
    file_transfers: list[dict] = field(default_factory=list)
    cmdb_records: list[dict] = field(default_factory=list)

    def slug(self, name: str) -> str:
        return name.lower().replace("&", "and").replace(" ", "-")


# ----------------------------------------------------------------- helpers

def _weighted_choice(rng: random.Random, table: dict) -> str:
    keys = list(table.keys())
    weights = [table[k]["weight"] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _db_engine_for(rng: random.Random, runtime_id: str) -> str:
    if runtime_id == "cobol-mainframe":
        return rng.choices(["db2", "flat-files"], weights=[0.75, 0.25], k=1)[0]
    return rng.choices(
        list(DB_ENGINE_TABLE.keys()),
        weights=[0.16, 0.18, 0.17, 0.24, 0.09, 0.16],
        k=1,
    )[0]


def _api_surface_for(rng: random.Random, runtime_id: str) -> str:
    if runtime_id == "cobol-mainframe":
        return "batch-only"
    return rng.choices(
        ["none", "SOAP", "REST-internal", "REST-public", "gRPC"],
        weights=[0.13, 0.13, 0.37, 0.15, 0.22],
        k=1,
    )[0]


def _earliness(spec: dict) -> int:
    """Static proxy for how early an app can migrate (lower = earlier). Used to
    bias synthetic call/event edges so they point at same-or-earlier-wave targets."""
    score = 0
    score += 2 if RUNTIME_PROFILES[spec["runtime_id"]]["eol"] else 0
    score += 1 if OS_TABLE[spec["os_id"]]["eol"] else 0
    if spec["statefulness"] != "stateless":
        score += 2
    if spec["compliance_scope"] != "none":
        score += 2
    score += max(0, spec["criticality"] - 3)
    if spec["monolith_loc"] > 250_000:
        score += 2
    return score


# --------------------------------------------------------- generic app builder

def _make_generic_app(rng: random.Random, idx: int, name: str, used_names: set) -> AppSpec:
    domain, owner = DOMAINS[idx % len(DOMAINS)]
    runtime_id = _weighted_choice(rng, RUNTIME_PROFILES)
    profile = RUNTIME_PROFILES[runtime_id]
    os_id = rng.choice(profile["os_pool"])
    api_surface = _api_surface_for(rng, runtime_id)
    auth_method = rng.choices(
        ["none", "basic", "ldap", "local-db", "sso"], weights=[0.10, 0.15, 0.28, 0.26, 0.21], k=1
    )[0]
    if runtime_id == "cobol-mainframe":
        statefulness = "stateless"
        api_surface = "batch-only"
    else:
        statefulness = rng.choices(
            ["stateless", "sticky-sessions", "session-replication"],
            weights=[0.62, 0.23, 0.15], k=1,
        )[0]
    criticality = rng.choices([1, 2, 3, 4, 5], weights=[0.10, 0.22, 0.38, 0.22, 0.08], k=1)[0]
    compliance = "none"
    roll = rng.random()
    if domain in ("Payments",) and roll < 0.30:
        compliance = "PCI"
    elif domain in ("Human Resources", "Customer Service") and roll < 0.25:
        compliance = "PII"

    server_count = rng.choices([1, 2, 3, 4, 6, 8, 12], weights=[0.18, 0.20, 0.20, 0.18, 0.12, 0.08, 0.04], k=1)[0]
    if runtime_id == "cobol-mainframe":
        server_count = 1

    monolith_loc = 0
    if profile["deployment"] in ("app-server", "iis"):
        monolith_loc = rng.randrange(40_000, 900_000)
    elif profile["deployment"] in ("vm", "jar"):
        monolith_loc = rng.randrange(5_000, 160_000)

    usage_per_day = int(rng.triangular(20, 400_000, 6_000))
    trend = round(rng.uniform(-70.0, 40.0), 1)
    unit_cost = rng.uniform(750, 2400)
    engine = _db_engine_for(rng, runtime_id)
    annual_cost = server_count * unit_cost * 12 + DB_ENGINE_TABLE[engine]["license_bump"]
    if runtime_id == "cobol-mainframe":
        annual_cost += 120_000

    change_frequency = rng.choices(["rare", "monthly", "weekly", "daily"], weights=[0.25, 0.42, 0.23, 0.10], k=1)[0]

    file_shares: list[str] = []
    if rng.random() < 0.28 and runtime_id != "cobol-mainframe":
        slug_hint = name.lower().replace(" ", "-")
        file_shares.append(f"fs-{slug_hint}:/srv/shares/{slug_hint}")

    publishes: list[str] = []
    consumes: list[str] = []
    if rng.random() < 0.34 and api_surface != "batch-only":
        publishes.append(rng.choice(TOPIC_POOL))
    if rng.random() < 0.36 and api_surface != "batch-only":
        consumes.append(rng.choice(TOPIC_POOL))

    libraries = rng.sample(LIBRARY_POOL, k=rng.randint(1, 4))

    batch_jobs: list[dict] = []
    if rng.random() < 0.42 or runtime_id == "cobol-mainframe":
        batch_jobs.append({
            "job_name": f"{name.lower().replace(' ', '-')}-nightly",
            "schedule": "daily",
            "window_start": f"0{rng.randint(1, 3)}:{rng.choice(['00', '15', '30'])}",
            "duration_minutes": rng.randint(15, 180),
            "change_frequency": change_frequency,
            "last_change_months_ago": rng.randint(1, 30),
        })

    manual_deployments = rng.random() < 0.35
    has_obs = rng.random() < 0.45
    secrets = rng.random() < 0.15

    return AppSpec(
        id="", name=name, domain=domain, business_owner=owner,
        language=profile["language"], framework=profile["framework"],
        runtime_id=runtime_id, os_id=os_id, database_row_id=None,
        server_count=server_count, api_surface=api_surface, auth_method=auth_method,
        statefulness=statefulness, compliance_scope=compliance,
        usage_per_day=max(usage_per_day, 2), monthly_usage_trend_pct=trend,
        annual_infra_cost_usd=round(annual_cost, 2), criticality=criticality,
        specialized_os_deps=rng.random() < 0.06,
        hypervisor_hosted=rng.random() < 0.55,
        description=f"{domain} application '{name}' ({profile['framework']}).",
        monolith_loc=monolith_loc,
        manual_deployments=manual_deployments,
        has_observability=has_obs,
        hardcoded_secrets_found=secrets,
        change_frequency=change_frequency,
        last_change_months_ago=rng.randint(1, 30),
        file_shares=file_shares,
        publishes=publishes,
        consumes=consumes,
        libraries=libraries,
        batch_jobs=batch_jobs,
    )


# ---------------------------------------------------------------- planted apps

def _planted_apps() -> list[AppSpec]:
    apps: list[AppSpec] = []

    def p(**kw) -> None:
        apps.append(AppSpec(**kw))

    # --- REHOST: healthy modern runtime, stateless, clean, REST public
    p(id="payments-api-gateway", name="Payments API Gateway", domain="Payments",
      business_owner="Payments Platform Org", language="Java", framework="Spring Boot",
      runtime_id="springboot-17", os_id="ubuntu-22", database_row_id=None, server_count=4,
      api_surface="REST-public", auth_method="sso", statefulness="stateless",
      compliance_scope="PCI", usage_per_day=210_000, monthly_usage_trend_pct=12.0,
      annual_infra_cost_usd=96_400.0, criticality=4,
      description="Public payments API gateway fronting settlement rails.",
      monolith_loc=48_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="weekly", last_change_months_ago=1,
      publishes=["payments.settled"], consumes=["ledger.posted"],
      libraries=["spring-boot-starter-web", "jackson-databind", "company-json-utils"])

    # --- REPLATFORM: EOL app-server runtime, lift-shiftable, managed DB path exists
    p(id="customer-onboarding-orchestrator", name="Customer Onboarding Orchestrator",
      domain="Retail Banking", business_owner="Branch Channel Org", language="Java",
      framework="Java EE on WebLogic 12c", runtime_id="java8-weblogic", os_id="rhel7",
      database_row_id=None, server_count=5, api_surface="REST-internal", auth_method="ldap",
      statefulness="sticky-sessions", compliance_scope="PII", usage_per_day=64_000,
      monthly_usage_trend_pct=3.0, annual_infra_cost_usd=88_200.0, criticality=4,
      description="Orchestrates account opening steps across KYC, cards and core banking.",
      monolith_loc=185_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=False, change_frequency="monthly", last_change_months_ago=2,
      consumes=["customer.updated"],
      libraries=["struts-core-2.3", "legacy-soap-client", "log4j-2.14"])

    # --- REFACTOR: huge monolith, heavy debt, mission critical, PCI
    p(id="policy-administration-monolith", name="Policy Administration Monolith",
      domain="Insurance Claims", business_owner="Claims Org", language="C#",
      framework=".NET Framework 4.8 on IIS", runtime_id="dotnet48-iis", os_id="windows-2012",
      database_row_id=None, server_count=8, api_surface="SOAP", auth_method="ldap",
      statefulness="session-replication", compliance_scope="PCI+PII", usage_per_day=130_000,
      monthly_usage_trend_pct=-2.5, annual_infra_cost_usd=210_500.0, criticality=5,
      description="Core policy administration system; 850k LOC single deployable.",
      monolith_loc=850_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=True, shared_database=True, change_frequency="weekly",
      last_change_months_ago=1, consumes=["claims.filedd"],
      libraries=["odbc32-wrapper", "company-json-utils"])

    # --- RETIRE: near-zero usage, lowest criticality, steep decline
    p(id="legacy-report-archive", name="Legacy Report Archive", domain="Finance",
      business_owner="Corporate Finance", language="Python", framework="Flask",
      runtime_id="python-flask", os_id="rhel7", database_row_id=None, server_count=1,
      api_surface="none", auth_method="basic", statefulness="stateless",
      compliance_scope="none", usage_per_day=4, monthly_usage_trend_pct=-85.0,
      annual_infra_cost_usd=9_800.0, criticality=1,
      description="Quarterly report archive UI; superseded by the BI platform.",
      monolith_loc=9_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=False, change_frequency="rare", last_change_months_ago=41,
      libraries=["flask-login"])

    # --- REPURCHASE: homegrown commodity capability (FTP-like hub)
    p(id="sftp-drop-hub", name="Partner File Drop Hub", domain="IT Operations",
      business_owner="Platform Engineering", language="Python", framework="Flask",
      runtime_id="python-flask", os_id="ubuntu-20", database_row_id=None, server_count=2,
      api_surface="none", auth_method="basic", statefulness="stateless",
      compliance_scope="none", usage_per_day=18_000, monthly_usage_trend_pct=1.0,
      annual_infra_cost_usd=21_300.0, criticality=3, commodity_capability=True,
      description="Homegrown SFTP drop-directory hub for partner file exchange.",
      monolith_loc=14_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=True, change_frequency="rare", last_change_months_ago=22,
      libraries=["paramiko", "flask-login"])

    # --- RETAIN: mainframe batch, stable, rarely changed, mission critical
    p(id="core-ledger-batch", name="Core Ledger Batch", domain="Finance",
      business_owner="Corporate Finance", language="COBOL", framework="z/OS JCL batch",
      runtime_id="cobol-mainframe", os_id="zos-sim", database_row_id=None, server_count=1,
      api_surface="batch-only", auth_method="none", statefulness="stateless",
      compliance_scope="none", usage_per_day=1, monthly_usage_trend_pct=0.0,
      annual_infra_cost_usd=340_000.0, criticality=5, lifecycle="retain-on-mainframe",
      description="Nightly general-ledger posting batch on the mainframe.",
      monolith_loc=420_000, manual_deployments=True, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="rare", last_change_months_ago=34,
      batch_jobs=[{"job_name": "glr100-nightly-posting", "schedule": "daily",
                   "window_start": "01:00", "duration_minutes": 95,
                   "change_frequency": "rare", "last_change_months_ago": 34}],
      libraries=[])

    # --- RELOCATE: modern runtime but hypervisor/licence-coupled, stateful
    p(id="treasury-risk-analytics", name="Treasury Risk Analytics", domain="Risk",
      business_owner="Risk Management Org", language="Go", framework="net/http",
      runtime_id="go", os_id="rhel9", database_row_id=None, server_count=6,
      api_surface="gRPC", auth_method="sso", statefulness="session-replication",
      compliance_scope="none", usage_per_day=9_500, monthly_usage_trend_pct=8.0,
      annual_infra_cost_usd=142_000.0, criticality=4, specialized_os_deps=True,
      hypervisor_hosted=True,
      description="Monte-Carlo risk engine licensed per physical socket; NUMA-tuned.",
      monolith_loc=90_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="monthly", last_change_months_ago=3,
      publishes=["risk.scored"], libraries=["company-json-utils"])

    # --- hidden dependency pair: secret nightly FTP into partner portal drop dir
    p(id=HIDDEN_SOURCE, name="Warehouse Inventory Sync", domain="Logistics",
      business_owner="Supply Chain Org", language="JavaScript", framework="Express",
      runtime_id="node14-express", os_id="ubuntu-20", database_row_id=None, server_count=1,
      api_surface="REST-internal", auth_method="local-db", statefulness="stateless",
      compliance_scope="none", usage_per_day=3_200, monthly_usage_trend_pct=-4.0,
      annual_infra_cost_usd=11_400.0, criticality=2,
      description="Syncs warehouse stock levels; pushes files to partners nightly.",
      monolith_loc=22_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=False, change_frequency="monthly", last_change_months_ago=5,
      libraries=["lodash-4.17"])
    p(id=HIDDEN_TARGET, name="Partner Portal", domain="Sales",
      business_owner="Revenue Ops", language="PHP", framework="CodeIgniter",
      runtime_id="php-legacy", os_id="windows-2012", database_row_id=None, server_count=2,
      api_surface="REST-public", auth_method="local-db", statefulness="stateless",
      compliance_scope="none", usage_per_day=15_000, monthly_usage_trend_pct=-6.0,
      annual_infra_cost_usd=18_900.0, criticality=3,
      description="Partner-facing portal; consumes inbound drop-dir files.",
      monolith_loc=76_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=True, change_frequency="rare", last_change_months_ago=17,
      file_shares=[f"partner-portal-drop:{HIDDEN_MOUNT}"],
      libraries=["legacy-soap-client"])

    # --- BLOCKED(dependency): modern stateless app pinned onto shared Oracle 11g
    p(id="commission-settlement-engine", name="Commission Settlement Engine",
      domain="Sales", business_owner="Revenue Ops", language="Java", framework="Spring Boot",
      runtime_id="springboot-17", os_id="ubuntu-22", database_row_id="svc-shared-oracle-11g",
      server_count=3, api_surface="REST-internal", auth_method="sso", statefulness="stateless",
      compliance_scope="none", usage_per_day=41_000, monthly_usage_trend_pct=5.0,
      annual_infra_cost_usd=44_600.0, criticality=4, requested_wave_override=1,
      description="Computes partner commissions; still anchored to shared Oracle 11g.",
      monolith_loc=64_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, shared_database=True, change_frequency="monthly",
      last_change_months_ago=2, libraries=["cx-oracle", "jackson-databind"])

    # --- BLOCKED(security zone): operator override pulls PCI app into wave 1
    p(id="card-dispute-tracker", name="Card Dispute Tracker", domain="Payments",
      business_owner="Payments Platform Org", language="Java", framework="Spring Boot",
      runtime_id="springboot-17", os_id="ubuntu-22", database_row_id=None, server_count=2,
      api_surface="REST-internal", auth_method="sso", statefulness="stateless",
      compliance_scope="PCI", usage_per_day=27_000, monthly_usage_trend_pct=6.5,
      annual_infra_cost_usd=31_800.0, criticality=4, requested_wave_override=1,
      description="Tracks chargeback lifecycle; PCI-scoped data handling.",
      monolith_loc=51_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="weekly", last_change_months_ago=1,
      consumes=["payment.failed"], libraries=["spring-boot-starter-web"])

    # --- wave-1 app with pre-existing incompatibility (Oracle AQ only feature)
    p(id=WAVE1_INCOMPATIBLE_APP, name="Receivables Matching Service", domain="Finance",
      business_owner="Corporate Finance", language="Python", framework="Flask",
      runtime_id="python-flask", os_id="ubuntu-22", database_row_id=None, server_count=2,
      api_surface="REST-internal", auth_method="local-db", statefulness="stateless",
      compliance_scope="none", usage_per_day=52_000, monthly_usage_trend_pct=2.0,
      annual_infra_cost_usd=24_700.0, criticality=3, requested_wave_override=1,
      description="Matches incoming remittances; uses Oracle AQ queue callbacks.",
      monolith_loc=31_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, oracle_only_feature=True, change_frequency="monthly",
      last_change_months_ago=4, libraries=["cx-oracle", "flask-login"])

    # --- wave 0 pilots: tiny, stateless, leaf, low criticality, direct DB
    p(id="expense-capture-tool", name="Expense Capture Tool", domain="Human Resources",
      business_owner="People Ops", language="Python", framework="Flask",
      runtime_id="python-flask", os_id="ubuntu-22", database_row_id=None, server_count=1,
      api_surface="REST-internal", auth_method="local-db", statefulness="stateless",
      compliance_scope="none", usage_per_day=6_400, monthly_usage_trend_pct=4.0,
      annual_infra_cost_usd=8_200.0, criticality=1,
      description="Receipt submission tool; ideal low-risk pilot workload.",
      monolith_loc=11_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="monthly", last_change_months_ago=2,
      libraries=["flask-login"])
    p(id="feedback-survey-collector", name="Feedback Survey Collector", domain="Customer Service",
      business_owner="CX Org", language="Go", framework="net/http", runtime_id="go",
      os_id="ubuntu-22", database_row_id=None, server_count=1, api_surface="REST-public",
      auth_method="none", statefulness="stateless", compliance_scope="none",
      usage_per_day=33_000, monthly_usage_trend_pct=9.0, annual_infra_cost_usd=7_600.0,
      criticality=1, description="Anonymous survey intake API; perfect pilot candidate.",
      monolith_loc=8_000, manual_deployments=False, has_observability=True,
      hardcoded_secrets_found=False, change_frequency="rare", last_change_months_ago=9,
      libraries=[])

    # --- second commodity capability for the REPURCHASE rule family
    p(id="marketing-content-cms", name="Marketing Content CMS", domain="Marketing",
      business_owner="Growth Org", language="PHP", framework="CodeIgniter",
      runtime_id="php-legacy", os_id="rhel7", database_row_id=None, server_count=2,
      api_surface="REST-internal", auth_method="basic", statefulness="stateless",
      compliance_scope="none", usage_per_day=8_800, monthly_usage_trend_pct=-9.0,
      annual_infra_cost_usd=16_400.0, criticality=2, commodity_capability=True,
      description="Homegrown CMS for landing pages; commodity SaaS-equivalent exists.",
      monolith_loc=58_000, manual_deployments=True, has_observability=False,
      hardcoded_secrets_found=True, change_frequency="monthly", last_change_months_ago=7,
      libraries=["legacy-soap-client"])

    for a in apps:
        a.id = a.id or ""
    return apps


# ------------------------------------------------------------------- assembly

def generate_estate(size: int = 120) -> EstateData:
    rng = random.Random(SEED)
    estate = EstateData()

    planted = _planted_apps()
    n_generic = max(0, size - len(planted))

    used_names = {a.name for a in planted}
    generic: list[AppSpec] = []
    i = 0
    while len(generic) < n_generic:
        noun = NAME_NOUNS[i % len(NAME_NOUNS)]
        domain_idx = i % len(DOMAINS)
        candidate = f"{DOMAINS[domain_idx][0]} {noun} {i // len(NAME_NOUNS) + 1}"
        i += 1
        if candidate in used_names:
            continue
        spec = _make_generic_app(rng, domain_idx, candidate, used_names)
        used_names.add(candidate)
        generic.append(spec)

    all_apps = planted + generic

    # ---- stable slug ids for every application
    seen_ids: set[str] = set()
    for spec in all_apps:
        if not spec.id:
            slug = spec.name.lower().replace("&", "and").replace(" ", "-")
            base_slug = slug
            n = 2
            while slug in seen_ids:
                slug = f"{base_slug}-{n}"
                n += 1
            spec.id = slug
        seen_ids.add(spec.id)

    # ---- dedicated database rows + shared-oracle wiring
    estate.databases.append({
        "id": "svc-shared-oracle-11g", "display_name": "Shared Oracle 11g (platform service)",
        "engine": "oracle-11g", "version": "11.2.0.4", "eol": True,
        "is_shared_service": True, "managed_equivalent": "managed-postgres-16",
        "compatibility": "conversion-required",
    })
    for spec in all_apps:
        if spec.database_row_id == "svc-shared-oracle-11g":
            continue
        if spec.id in PILOT_APPS:
            engine = "postgres-13"  # pilots must qualify for wave 0 (direct compat)
        elif spec.runtime_id == "cobol-mainframe":
            engine = "db2"
        else:
            roll = rng.random()
            engine = (
                "postgres-13" if roll < 0.26
                else "mysql-5.7" if roll < 0.46
                else "sqlserver-2014" if roll < 0.65
                else "oracle-11g" if roll < 0.79
                else "flat-files" if roll < 0.92
                else "db2"
            )
        db_id = f"db-{spec.id}"
        meta = DB_ENGINE_TABLE[engine]
        estate.databases.append({
            "id": db_id, "display_name": f"{engine} for {spec.name}",
            "engine": engine, "version": "", "eol": meta["eol"],
            "is_shared_service": False,
            "managed_equivalent": meta["managed_equivalent"],
            "compatibility": meta["compatibility"],
        })
        spec.database_row_id = db_id

    # ---- shared-database consumers (hard topo dependency on svc-shared-oracle-11g)
    eligible = [
        a for a in all_apps
        if a.id not in {p.id for p in planted} and a.runtime_id != "cobol-mainframe"
        and a.monolith_loc < 300_000
    ]
    rng.shuffle(eligible)
    for a in eligible[:7]:
        a.database_row_id = "svc-shared-oracle-11g"
        a.shared_database = True

    # ---- static earliness ranking used to bias edges toward same-or-earlier waves
    def earliness(a: AppSpec) -> int:
        return _earliness({
            "runtime_id": a.runtime_id, "os_id": a.os_id, "statefulness": a.statefulness,
            "compliance_scope": a.compliance_scope, "criticality": a.criticality,
            "monolith_loc": a.monolith_loc,
        })

    earliness_by_id = {a.id: earliness(a) for a in all_apps}
    crit5_ids = {a.id for a in all_apps if a.criticality == 5}
    mainframe_ids = {a.id for a in all_apps if a.runtime_id == "cobol-mainframe"}
    planted_ids = {a.id for a in planted}

    # ---- servers
    for spec in all_apps:
        cores, ram = (8, 32) if spec.runtime_id == "cobol-mainframe" else (rng.choice([2, 4, 4, 8]), rng.choice([8, 16, 16, 32]))
        for si in range(1, spec.server_count + 1):
            estate.servers.append({
                "application_id": spec.id, "hostname": f"{spec.id}-vm{si:02d}",
                "cpu_cores": cores, "ram_gb": ram, "environment": "prod",
                "zone": "pci" if "PCI" in spec.compliance_scope else "general",
            })

    # ---- network flows (who-calls-whom): bias toward same-or-earlier targets
    candidates = [a for a in all_apps if a.id not in mainframe_ids]
    no_outgoing = set(PILOT_APPS) | {WAVE1_INCOMPATIBLE_APP}
    for spec in all_apps:
        if spec.id in no_outgoing:
            continue  # pilots are leaf apps; receivables must stay pinned to wave 1
        n_calls = 0 if spec.runtime_id == "cobol-mainframe" else rng.choices([0, 1, 2, 3], weights=[0.35, 0.35, 0.20, 0.10], k=1)[0]
        for _ in range(n_calls):
            if rng.random() < 0.30:
                dst, kind = "svc-esb-messaging", "service"
            else:
                my_e = earliness_by_id[spec.id]
                pool = [
                    a.id for a in candidates
                    if a.id != spec.id and a.id not in crit5_ids
                    and earliness_by_id[a.id] <= my_e
                    and a.id not in PILOT_APPS
                ]
                if not pool:
                    continue
                dst, kind = rng.choice(pool), "application"
            estate.network_flows.append({
                "src_app_id": spec.id, "dst_node_id": dst, "dst_kind": kind,
                "port": rng.choice([443, 8443, 8080]), "protocol": "https",
                "connections_daily": rng.randint(200, 90_000),
            })
            estate.integrations.append({
                "source_id": spec.id, "target_id": dst,
                "kind": "sync-api", "transport": "https",
                "description": "Observed recurring API traffic in network flow logs.",
            })

    # ---- event publish/consume recorded as CMDB facts (bus carried by ESB)
    for spec in all_apps:
        for topic in spec.publishes:
            estate.cmdb_records.append({
                "application_id": spec.id, "service_id": None, "field": "publishes_topic",
                "value": topic, "source_system": "cmdb-sim", "confidence": 0.95,
            })
        for topic in spec.consumes:
            estate.cmdb_records.append({
                "application_id": spec.id, "service_id": None, "field": "consumes_topic",
                "value": topic, "source_system": "cmdb-sim", "confidence": 0.95,
            })

    # ---- batch jobs
    for spec in all_apps:
        for job in spec.batch_jobs:
            estate.batch_jobs.append({"application_id": spec.id, **job})

    # ---- file transfers
    for spec in all_apps:
        for share in spec.file_shares:
            estate.cmdb_records.append({
                "application_id": spec.id, "service_id": None, "field": "file_share",
                "value": share, "source_system": "cmdb-sim", "confidence": 0.9,
            })
            # receivers (like Partner Portal) only register the drop dir; they do not push.
        if spec.file_shares or rng.random() < 0.18:
            slug = spec.id
            estate.file_transfers.append({
                "source_app_id": spec.id, "direction": "send", "remote_system": "sftp-hub",
                "remote_path": f"/hub-out/{slug}/daily-export.csv", "frequency": "nightly",
                "file_pattern": "daily-export.csv", "avg_mb": round(rng.uniform(0.5, 60), 1),
                "hour_of_day": rng.randint(0, 5),
            })

    # THE hidden undocumented dependency: only visible by correlating this transfer's
    # remote_path with Partner Portal's registered drop-dir mount.
    estate.file_transfers.append({
        "source_app_id": HIDDEN_SOURCE, "direction": "send", "remote_system": "sftp-hub",
        "remote_path": f"{HIDDEN_MOUNT}/inventory_snapshot_*.csv", "frequency": "nightly",
        "file_pattern": "inventory_snapshot_*.csv", "avg_mb": 84.0, "hour_of_day": 2,
    })
    estate.integrations.append({
        "source_id": HIDDEN_SOURCE, "target_id": HIDDEN_TARGET, "kind": "file",
        "transport": "sftp", "description": "Undocumented nightly inventory drop.",
    })

    # ---- CMDB records per app
    for spec in all_apps:
        records = [
            ("business_owner", spec.business_owner),
            ("environment", "prod"),
            ("tier", f"crit-{spec.criticality}"),
            ("identity_method", spec.auth_method),
            ("libraries", ",".join(spec.libraries)),
            ("change_frequency", spec.change_frequency),
        ]
        for fld, val in records:
            estate.cmdb_records.append({
                "application_id": spec.id, "service_id": None, "field": fld,
                "value": val, "source_system": "cmdb-sim", "confidence": 0.92,
            })
        estate.applications.append(spec)

    # ---- service CMDB records
    for svc in SHARED_SERVICES:
        estate.cmdb_records.append({
            "application_id": None, "service_id": svc["id"], "field": "service_kind",
            "value": svc["kind"], "source_system": "cmdb-sim", "confidence": 0.99,
        })

    estate.applications.sort(key=lambda a: a.id)
    return estate


# ------------------------------------------------------------------ truth set

def build_true_edges(estate: EstateData) -> list[list[str]]:
    edges: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, rel: str) -> None:
        edges.add((src, dst, rel))

    for spec in estate.applications:
        if spec.database_row_id:
            add(spec.id, spec.database_row_id, "APP_USES_DATABASE")
        if spec.auth_method == "ldap":
            add(spec.id, "svc-corporate-ldap", "APP_USES_IDENTITY")
        elif spec.auth_method == "sso":
            add(spec.id, "svc-sso-provider", "APP_USES_IDENTITY")
        for share in spec.file_shares:
            share_name = share.split(":", 1)[0]
            add(spec.id, f"fs:{share_name}", "APP_USES_FILE_SHARE")
        for topic in spec.publishes:
            add(spec.id, f"topic:{topic}", "APP_PUBLISHES_EVENT")
        for topic in spec.consumes:
            add(spec.id, f"topic:{topic}", "APP_CONSUMES_EVENT")
    for flow in estate.network_flows:
        if flow["dst_kind"] == "application":
            add(flow["src_app_id"], flow["dst_node_id"], "APP_CALLS_APP")
    for tr in estate.file_transfers:
        if tr["remote_system"] == "sftp-hub":
            add(tr["source_app_id"], "svc-sftp-hub", "APP_USES_FILE_SHARE")
    # the hidden undocumented dependency itself
    add(HIDDEN_SOURCE, HIDDEN_TARGET, "APP_SENDS_FILE_TO")

    return sorted([list(e) for e in edges])


def write_ground_truth(estate: EstateData) -> int:
    true_edges = build_true_edges(estate)
    payload = {
        "meta": {
            "seed": SEED,
            "estate_size": len(estate.applications),
            "note": "Machine-generated deterministic truth. Hand-authored labels below are constants in simulator/generate_estate.py.",
        },
        "truth_relations": sorted(TRUTH_RELATIONS),
        "hidden_dependency": {
            "source_app": HIDDEN_SOURCE,
            "target_app": HIDDEN_TARGET,
            "relation": "APP_SENDS_FILE_TO",
            "evidence_source": "transfer-log-correlation",
            "detail": f"{HIDDEN_SOURCE} sends nightly files to {HIDDEN_TARGET}'s drop dir ({HIDDEN_MOUNT}); not present in CMDB or flow logs.",
        },
        "true_edges": true_edges,
        "strategy_labels": STRATEGY_LABELS,
        "expected_blocked_migrations": EXPECTED_BLOCKED_MIGRATIONS,
        "wave1_incompatible_app": WAVE1_INCOMPATIBLE_APP,
        "expectations": {
            "wave1_incompatible_app_must_fail_and_roll_back": True,
            "wave1_other_members_must_complete": True,
        },
    }
    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(true_edges)
