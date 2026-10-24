"""Build an Excel project sheet from a folder of .docx profiles.

    python scripts/build_projects_sheet.py "D:\\Documents\\My Profiles" [-o scripts/sample_projects.xlsx]

The folder is only read, never modified. Each profile lists the projects the
person worked on ("Project Name: ... / Technologies: ... / Description: ...");
the same project usually appears in many role-specific variants, so entries are
deduplicated by name and the most detailed version wins.

Two kinds of data end up in the sheet:
  * Extracted from the documents: name, technologies, summary (first sentences of the
    description) and the Frontend / Backend / Database / Cloud grouping of the technologies.
  * Curated in CURATION below: domain, business problem, solution, key features and AI/ML
    components. These are wording of ours, written from each description - review them.
    A project not in CURATION still imports (domain "Other", those fields empty) and is
    reported at the end so it can be filled in.

Only project facts are read. Names, contact details and any other personal data in the
profiles are never copied into the sheet.
"""

import argparse
import html
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

HEADERS = [
    "Project Name",
    "Domain",
    "Related Domains",
    "Summary",
    "Business Problem",
    "Solution Provided",
    "Key Features",
    "Technologies",
    "AI/ML Components",
    "Frontend",
    "Backend",
    "Database",
    "Cloud / DevOps",
]
WIDTHS = [26, 22, 26, 60, 50, 60, 60, 50, 44, 22, 30, 30, 36]

# Curated classification, keyed by the project name with everything but letters and
# digits removed and lower-cased. Wording is derived from each project's description.
CURATION = {
    "fitai": {
        "domain": "Travel & Hospitality",
        "related_domains": ["Healthcare"],
        "business_problem": "Diners can't easily find meals that fit their preferences, because restaurant menus and ingredient lists are unstructured documents that can't be searched meaningfully.",
        "solution_provided": "Restaurant admins upload menus (PDF, DOC); the files are parsed into vector embeddings stored in OpenSearch, so users get LLM-powered semantic search and meal recommendations matched to their preferences.",
        "key_features": [
            "Menu and ingredient upload (PDF, DOC) with automatic parsing",
            "Semantic search over menus using vector embeddings",
            "Personalized meal recommendations powered by LLMs",
            "Calendar integration",
            "Background document processing with Celery",
        ],
        "ai_ml_components": [
            "Sentence Transformers embeddings",
            "Vector search on OpenSearch",
            "LLM-powered meal recommendations",
            "NLP document parsing",
        ],
    },
    "quadrixai": {
        "domain": "Logistics & Supply Chain",
        "related_domains": [],
        "business_problem": "Brokers and drivers coordinate shipments, pricing and paperwork by phone and email, which is manual, slow and hard to track.",
        "solution_provided": "AI agents handle calls (Twilio + ElevenLabs) and email (Gmail + GCP Pub/Sub), collect shipment details and negotiate pricing, while AWS Textract extracts data from shipping documents; everything updates one order record in real time.",
        "key_features": [
            "Voice AI agents that call brokers and drivers to gather shipment details and negotiate pricing",
            "Gmail agent that reads logistics emails and automates responses",
            "Document extraction from invoices, rate confirmations, order confirmations and shipping labels",
            "Real-time order status updates over WebSockets",
            "Multi-agent orchestration around a shared order record",
        ],
        "ai_ml_components": [
            "Voice AI agents (Twilio + ElevenLabs)",
            "Email agent (Gmail API + GCP Pub/Sub)",
            "Document data extraction (AWS Textract)",
            "LLMs on AWS Bedrock",
            "Multi-agent orchestration",
        ],
    },
    "orionchat": {
        "domain": "Other",
        "related_domains": ["HR & Recruitment"],
        "business_problem": "Employees can't quickly find answers spread across Slack, Gmail, Jira and internal documents, which drives internal support tickets and slows onboarding.",
        "solution_provided": "A RAG-powered enterprise chatbot that ingests those systems into a vector database and answers questions in natural language 24/7, reducing internal support tickets by 40%.",
        "key_features": [
            "Connectors for Slack, Gmail, Jira and S3 to ingest company knowledge",
            "Hybrid semantic search over Milvus with a LangChain retriever",
            "Intent classification decides when to use RAG versus the LLM",
            "OAuth2 login (Google, Microsoft) and Stripe subscription tiers",
            "Microservices on Kubernetes; Redis caching cut token cost by 30%",
            "Scheduled embedding refresh with Lambda and EventBridge",
        ],
        "ai_ml_components": [
            "RAG pipeline (LangChain + Milvus)",
            "OpenAI GPT-4o answer generation",
            "OpenAI text-embedding-3-large embeddings",
            "Fine-tuned DistilBERT intent classifier",
        ],
    },
    "impactx": {
        "domain": "Education",
        "related_domains": ["Banking & Finance"],
        "business_problem": "Students struggle to find scholarships they qualify for and to complete applications, and manual identity and document checks slow every review.",
        "solution_provided": "A scholarship platform that matches students to eligible scholarships, verifies identity and documents automatically (Karza, Signzy, OCR) and keeps application status updated in real time.",
        "key_features": [
            "Eligibility-based scholarship applications",
            "Identity verification through the Karza API",
            "Document validation through the Signzy API",
            "OCR extraction from student documents (Docling, Surya)",
            "Real-time application updates with Supabase",
        ],
        "ai_ml_components": ["OCR document extraction (Docling OCR, Surya OCR)"],
    },
    "dktireb2bplatform": {
        "domain": "Retail & E-Commerce",
        "related_domains": ["Logistics & Supply Chain"],
        "business_problem": "Tire wholesalers and retailers manage orders, inventory and pricing across disconnected tools, which limits operational efficiency.",
        "solution_provided": "A centralized B2B platform for orders, inventory and pricing with secure CardPointe payments, real-time Pusher notifications, SendGrid email and Redis caching, deployed on scalable AWS infrastructure.",
        "key_features": [
            "B2B order creation and tracking",
            "Inventory and pricing management",
            "CardPointe payment processing",
            "Real-time notifications with Pusher",
            "Transactional email with SendGrid",
        ],
        "ai_ml_components": [],
    },
    "perkypet": {
        "domain": "Healthcare",
        "related_domains": [],
        "business_problem": "Pet parents find it hard to keep track of their pets' medical records and to get timely, personalized health guidance.",
        "solution_provided": "An AI platform where uploaded vet records are processed with DocumentAI into a health dashboard, with an AI assistant for pet-health questions, reminders and personalized wellness plans.",
        "key_features": [
            "Veterinary record upload with automatic data extraction",
            "Dashboard that auto-populates pet health data",
            "Conversational assistant for pet health questions",
            "Reminders for vet visits and preventive care",
            "Personalized wellness and treatment plans",
        ],
        "ai_ml_components": [
            "DocumentAI record extraction",
            "AI health assistant (OpenAI API, LlamaIndex, HuggingFace)",
            "Personalized treatment plan generation",
        ],
    },
    "zysecai": {
        "domain": "Other",
        "related_domains": [],
        "business_problem": "Cybersecurity teams need to query categorized files and playbooks and get reports quickly, without digging through them by hand.",
        "solution_provided": "A chat interface to a security-focused LLM that searches categorized files and playbooks in OpenSearch to generate accurate reports, with JWT-secured user access.",
        "key_features": [
            "Natural-language chat with cybersecurity expert personas",
            "OpenSearch vector store of categorized files and playbooks",
            "Security-focused LLM hosted on RunPods",
            "User registration, login and file upload with JWT",
        ],
        "ai_ml_components": [
            "Security-focused LLM (RunPods)",
            "Vector search on OpenSearch",
            "Neo4j graph data",
        ],
    },
    "tireplanet": {
        "domain": "Retail & E-Commerce",
        "related_domains": ["Logistics & Supply Chain"],
        "business_problem": "Customers have no simple way to buy tires from nearby retailers and distributors with accurate delivery cost and fulfillment.",
        "solution_provided": "A B2C e-commerce platform that uses geolocation to pick the nearest retailer, calculates shipping cost from distance and order size, and runs orders from distributor to retailer to customer.",
        "key_features": [
            "Nearest-retailer selection using geocoding and distance",
            "Dynamic shipping cost calculation (FedEx, Roadie)",
            "Order pipeline linking distributors, retailers and users",
            "Contract agreement PDF generation",
            "Real-time inventory tracking",
        ],
        "ai_ml_components": [],
    },
    "softsuaveaiassistant": {
        "domain": "Other",
        "related_domains": [],
        "business_problem": "Website visitors need accurate answers about the company's services and an easy way to book a meeting with sales, without waiting for a person.",
        "solution_provided": "A RAG assistant that answers questions from the company website and uploaded PDFs, detects meeting intent and schedules calls with the sales team automatically, improving customer engagement and reducing OpenAI API costs.",
        "key_features": [
            "RAG over the company website with automatic weekly re-indexing",
            "PDF ingestion to enrich the knowledge base",
            "Intent detection with automatic meeting scheduling (NeetoCal)",
            "Automatic model failover and outage alerts",
        ],
        "ai_ml_components": [
            "RAG with Chroma DB",
            "OpenAI LLM with dynamic model switching",
            "Intent recognition",
        ],
    },
    "neonaicopilotagents": {
        "domain": "Other",
        "related_domains": [],
        "business_problem": "Organizations spend time manually processing documents, web content and emails across disconnected tools.",
        "solution_provided": "A multi-agent platform where specialized AI agents analyze documents, compose email, scrape the web and process policies, keeping conversation context and managing tokens across OpenAI and Ollama.",
        "key_features": [
            "Specialized agents for document analysis, email composition, web scraping and policy processing",
            "Support for multiple AI providers (OpenAI, Ollama) with token management",
            "Conversation context kept across interactions",
            "Asynchronous processing for concurrent document handling",
        ],
        "ai_ml_components": ["Multi-agent orchestration", "OpenAI and Ollama LLMs"],
    },
    "eaglebotsaas": {
        "domain": "Other",
        "related_domains": [],
        "business_problem": "Users have to switch between many third-party services to get things done instead of asking in one place.",
        "solution_provided": "A chatbot that uses machine learning to extract parameters from a user's message and run real-time calls to integrated services (Google, Microsoft, JIRA, Twitter), with OAuth for access and Stripe for payments.",
        "key_features": [
            "Real-time third-party API calls driven by chat",
            "OAuth sign-in with Google, Microsoft, JIRA and Twitter",
            "Stripe payments",
            "Dockerized microservices on Azure App Services",
            "Celery and RabbitMQ task management",
        ],
        "ai_ml_components": [
            "ML parameter extraction from user input",
            "Stable Diffusion model deployed on an Azure VM",
        ],
    },
}

_FRONTEND = {
    "react",
    "react.js",
    "reactjs",
    "tailwind",
    "tailwind css",
    "tailwindcss",
    "next.js",
    "angular",
    "vue",
}
_DATABASE = {
    "mongodb", "postgresql", "postgres", "sql", "mysql", "sqlite", "redis", "opensearch", "milvus", "neo4j",
    "spanner db", "spanner", "dynamodb", "chroma db", "chromadb", "firebase", "supabase",
}  # fmt: skip
_BACKEND = {
    "python", "fastapi", "django", "flask", "sqlalchemy", "celery", "rabbitmq", "pytest", "uvicorn",
    "asyncio", "pydantic", "websockets", "jwt",
}  # fmt: skip
_CLOUD = {"docker", "kubernetes", "github actions", "gitlab ci", "minio", "runpods", "runpod", "bitbucket"}
_CLOUD_PREFIXES = ("aws", "gcp", "azure", "google cloud", "g cloud")


@dataclass
class RawProject:
    name: str
    technologies: list[str]
    description: str
    source: str
    size: int


def clean(text: str) -> str:
    text = html.unescape(text)
    for bad, good in {
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2014": "-",
        "\u2013": "-",
        "\u00a0": " ",
    }.items():
        text = text.replace(bad, good)
    return " ".join(text.split())


def read_docx_lines(path: Path) -> list[str]:
    """Paragraph text of a .docx, using only the standard library."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return [line for line in (clean(line) for line in xml.split("\n")) if line]


def split_technologies(value: str) -> list[str]:
    """Comma split that keeps commas inside parentheses: 'AWS (S3, SQS), Redis' -> 2 items."""
    items, current, depth = [], [], 0
    for char in value:
        depth += char in "(["
        depth -= char in ")]" and depth > 0
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [i.strip(" .") for i in items if i.strip(" .")]


_ENTRY = re.compile(r"^(?:project name|project)\s*:\s*(.+)$", re.I)


def parse_projects(lines: list[str], source: str) -> list[RawProject]:
    starts = [i for i, line in enumerate(lines) if _ENTRY.match(line)]
    projects = []
    for n, start in enumerate(starts):
        block = lines[start : starts[n + 1] if n + 1 < len(starts) else len(lines)]
        name = _ENTRY.match(block[0]).group(1).strip()

        technologies = ""
        description = ""
        for i, line in enumerate(block[1:], start=1):
            lower = line.lower()
            if lower.startswith("technologies") and not technologies:
                technologies = line.split(":", 1)[1].strip() if ":" in line else ""
                # a value that ends in a comma continues on the next line
                j = i
                while technologies.endswith(",") and j + 1 < len(block):
                    j += 1
                    technologies += " " + block[j]
            elif lower.startswith("description") and not description:
                same_line = line.split(":", 1)[1].strip() if ":" in line else ""
                description = " ".join([same_line, *block[i + 1 :]]).strip()
        projects.append(
            RawProject(
                name=name,
                technologies=split_technologies(technologies),
                description=description,
                source=source,
                size=len(" ".join(block)),
            )
        )
    return projects


def project_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def collect_projects(folder: Path) -> list[RawProject]:
    """Every distinct project in the folder (recursively), richest variant of each."""
    best: dict[str, RawProject] = {}
    for path in sorted(folder.rglob("*.docx")):
        if path.name.startswith("~$"):  # Word lock files
            continue
        try:
            lines = read_docx_lines(path)
        except (zipfile.BadZipFile, KeyError) as e:
            print(f"skipped unreadable file {path.name}: {type(e).__name__}", file=sys.stderr)
            continue
        for project in parse_projects(lines, path.name):
            key = project_key(project.name)
            if key not in best or project.size > best[key].size:
                best[key] = project
    return sorted(best.values(), key=lambda p: p.name.lower())


def summarize(description: str, max_chars: int = 400) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", description.strip())
    summary = " ".join(sentences[:2])
    return summary if len(summary) <= max_chars else summary[: max_chars - 1].rsplit(" ", 1)[0] + "..."


def group_technologies(technologies: list[str]) -> dict[str, list[str]]:
    groups = {"frontend": [], "backend": [], "database": [], "cloud_devops": []}
    for tech in technologies:
        t = re.sub(r"\s*\(.*\)", "", tech.lower()).strip()  # "Milvus (Vector DB)" groups as "milvus"
        if t in _FRONTEND:
            groups["frontend"].append(tech)
        elif t in _DATABASE:
            groups["database"].append(tech)
        elif t in _BACKEND:
            groups["backend"].append(tech)
        elif t in _CLOUD or t.startswith(_CLOUD_PREFIXES):
            groups["cloud_devops"].append(tech)
    return groups  # anything unmatched stays only in the flat Technologies column


def sheet_row(project: RawProject) -> list[str]:
    curated = CURATION.get(project_key(project.name), {})
    groups = group_technologies(project.technologies)
    return [
        project.name,
        curated.get("domain", "Other"),
        ", ".join(curated.get("related_domains", [])),
        summarize(project.description),
        curated.get("business_problem", ""),
        curated.get("solution_provided", ""),
        "\n".join(curated.get("key_features", [])),
        ", ".join(project.technologies),
        "\n".join(curated.get("ai_ml_components", [])),
        ", ".join(groups["frontend"]),
        ", ".join(groups["backend"]),
        ", ".join(groups["database"]),
        ", ".join(groups["cloud_devops"]),
    ]


def write_workbook(projects: list[RawProject], target: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Projects"
    sheet.append(HEADERS)
    for project in projects:
        sheet.append(sheet_row(project))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(WIDTHS):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "B2"
    workbook.save(target)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a project Excel sheet from a folder of .docx profiles."
    )
    parser.add_argument("folder", type=Path, help="folder containing the .docx profiles (read only)")
    parser.add_argument("-o", "--output", type=Path, default=Path(__file__).with_name("sample_projects.xlsx"))
    args = parser.parse_args()
    if not args.folder.is_dir():
        print(f"Not a folder: {args.folder}", file=sys.stderr)
        return 1

    projects = collect_projects(args.folder)
    if not projects:
        print("No 'Project Name:' entries found.", file=sys.stderr)
        return 1
    write_workbook(projects, args.output)
    print(f"Wrote {len(projects)} projects to {args.output}")
    uncurated = [p.name for p in projects if project_key(p.name) not in CURATION]
    if uncurated:
        print("Needs curation (domain, problem, solution, features): " + ", ".join(uncurated))
    return 0


if __name__ == "__main__":
    sys.exit(main())
