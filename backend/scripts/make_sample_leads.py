"""Generate backend/scripts/sample_leads.xlsx - a test sheet for Contacts > Import Excel.

Run:  python scripts/make_sample_leads.py   (from backend/)

Pairs with scripts/sample_projects.xlsx: the leads are in industries the sample
projects can be matched to, so after importing both you can see "similar past
work" appear on a lead. Every phone number is in the reserved fictional US range
(555-0100..0199), so a power-dial test can never ring a real person. Companies
and websites are real public organisations, so the Research button has
something to read.

Importing this file into an empty database (country code: "Numbers already
include country code") should report:
    10 imported · 1 updated · 2 skipped
      row 9  - Invalid or missing contact number for 'No Number Lead'
      row 10 - Missing client name
Rows are chosen to cover each path:
    row 2   Techila         the sample lead from the CRM schema
    row 3   Priya Raman     lower-case priority ("medium") is normalised to "Medium"
    row 5   Meera Iyer      two numbers in one cell -> second becomes the secondary phone
    row 7   Anil Kumar      no website -> Research asks for one; the Project column drives matching
    row 8   Priya Raman     same phone AND project as row 3 -> counts as updated, fills blanks only
                            (a known phone with a different project is recorded as a new client row)
    row 11  (blank)         ignored
    row 12  Localhost Corp  unsafe website -> imported, but Research asks for a public one
    row 15  Jordan Blake    OpenTable's robots.txt blocks automated readers -> Research reports it

Expected project match per lead (the first project listed ranks first; matching is by domain
overlap with sample_projects.xlsx, so leads classified as "Other" get all five "Other" projects):
    PetMD -> Perky Pet            Tire Rack -> DK Tire B2B, Tireplanet   Flexport -> Quadrix AI
    Scholarship America -> ImpactX   Harbor Table / OpenTable -> FitAI   Techila -> Orion-Chat (HR & Recruitment)
    Atlassian, CrowdStrike -> the "Other" projects (Orion-Chat, Zysec AI, SoftSuave AI Assistant, ...)
"""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

HEADERS = [
    "Lead Name",
    "Company Name",
    "Mobile No",
    "Secondary Phone",
    "Webpage",
    "Industries",
    "Employees Size",
    "Country",
    "Branch",
    "Source",
    "Priority",
    "Project",
]

ROWS = [
    [
        "Techila Global Services",
        "Techila Global Services",
        "+1 212 555 0101",
        "",
        "https://techilaservices.com/",
        "IT Services and IT Consulting",
        "1,001-5,000 employees",
        "India",
        "Chennai",
        "Linkedin-Sales",
        "High",
        "Staff augmentation portal",
    ],
    [
        "Priya Raman",
        "PetMD",
        "+1 212 555 0102",
        "+1 212 555 0112",
        "petmd.com",
        "Veterinary Services",
        "51-200 employees",
        "United States",
        "Chennai",
        "Linkedin-Sales",
        "medium",
        "Pet health records assistant",
    ],
    [
        "Daniel Okafor",
        "Tire Rack",
        "+1 212 555 0103",
        "",
        "https://www.tirerack.com",
        "Retail Motor Vehicles",
        "501-1,000 employees",
        "United States",
        "Bengaluru",
        "Cold Email",
        "Low",
        "",
    ],
    [
        "Meera Iyer",
        "Flexport",
        "+1 212 555 0104; +1 212 555 0114",
        "",
        "flexport.com",
        "Transportation, Logistics, Supply Chain and Storage",
        "1,001-5,000 employees",
        "United States",
        "Chennai",
        "Linkedin-Sales",
        "HIGH",
        "",
    ],
    [
        "Sam Carter",
        "Scholarship America",
        "+1 212 555 0105",
        "",
        "scholarshipamerica.org",
        "Non-profit Organizations",
        "51-200 employees",
        "United States",
        "Chennai",
        "Website Form",
        "Medium",
        "Scholarship application platform",
    ],
    [
        "Anil Kumar",
        "Harbor Table Restaurants Pvt Ltd",
        "+1 212 555 0106",
        "",
        "",
        "Restaurants",
        "51-200 employees",
        "India",
        "Chennai",
        "Linkedin-Sales",
        "Medium",
        "Menu recommendation app for diners",
    ],
    [
        "Priya Raman",
        "PetMD",
        "+1 212 555 0102",
        "",
        "",
        "Veterinary Services",
        "",
        "",
        "",
        "",
        "",
        "Pet health records assistant",
    ],
    [
        "No Number Lead",
        "Numberless Inc",
        "12",
        "",
        "numberless.example",
        "Software Development",
        "1-10 employees",
        "India",
        "Chennai",
        "Linkedin-Sales",
        "Low",
        "",
    ],
    [
        "",
        "Nameless Co",
        "+1 212 555 0107",
        "",
        "nameless.example",
        "Software Development",
        "1-10 employees",
        "India",
        "Chennai",
        "Linkedin-Sales",
        "Low",
        "",
    ],
    [],
    [
        "Localhost Corp",
        "Localhost Corp",
        "+1 212 555 0108",
        "",
        "http://localhost:3000",
        "Software Development",
        "1-10 employees",
        "India",
        "Chennai",
        "Website Form",
        "Low",
        "",
    ],
    [
        "Rahul Menon",
        "Atlassian",
        "+1 212 555 0109",
        "",
        "https://www.atlassian.com",
        "Software Development",
        "5,001-10,000 employees",
        "Australia",
        "Bengaluru",
        "Linkedin-Sales",
        "High",
        "Internal knowledge chatbot",
    ],
    [
        "Elena Petrova",
        "CrowdStrike",
        "+1 212 555 0110",
        "",
        "crowdstrike.com",
        "Computer and Network Security",
        "5,001-10,000 employees",
        "United States",
        "Chennai",
        "Cold Email",
        "Medium",
        "Security analyst assistant",
    ],
    [
        "Jordan Blake",
        "OpenTable",
        "+1 212 555 0111",
        "",
        "opentable.com",
        "Restaurants",
        "1,001-5,000 employees",
        "United States",
        "Chennai",
        "Linkedin-Sales",
        "Low",
        "",
    ],
]

WIDTHS = [26, 32, 32, 18, 32, 44, 24, 16, 12, 16, 10, 34]


def build(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Leads"
    sheet.append(HEADERS)
    for row in ROWS:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(WIDTHS):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
    sheet.freeze_panes = "A2"
    workbook.save(path)


if __name__ == "__main__":
    target = Path(__file__).with_name("sample_leads.xlsx")
    build(target)
    print(f"Wrote {target}")
