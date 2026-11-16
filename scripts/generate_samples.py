"""Rebuild fictional, redistributable resumes and the benchmark input data."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JOBS = [
    {
        "id": "job-backend", "title": "Python Backend Engineer", "department": "Engineering",
        "location": "Bengaluru / Remote", "employment_type": "Full-time",
        "description": "Build reliable Python APIs with FastAPI and PostgreSQL. Write automated tests and collaborate with our product team. We value evidence of delivered work.",
        "criteria": [
            {"id": "python", "label": "Python", "weight": 35},
            {"id": "fastapi", "label": "FastAPI", "weight": 25},
            {"id": "postgresql", "label": "PostgreSQL", "weight": 25},
            {"id": "testing", "label": "Automated testing", "weight": 15},
        ],
    },
    {
        "id": "job-frontend", "title": "Frontend Engineer", "department": "Product Engineering",
        "location": "Pune / Hybrid", "employment_type": "Full-time",
        "description": "Create accessible React and TypeScript interfaces. Own component testing, responsive design and thoughtful user experiences.",
        "criteria": [
            {"id": "react", "label": "React", "weight": 35},
            {"id": "typescript", "label": "TypeScript", "weight": 25},
            {"id": "accessibility", "label": "Accessibility", "weight": 20},
            {"id": "testing", "label": "Automated testing", "weight": 20},
        ],
    },
    {
        "id": "job-fullstack", "title": "Full-stack Product Engineer", "department": "Platform",
        "location": "Remote, India", "employment_type": "Full-time",
        "description": "Ship full-stack features using Python, React and PostgreSQL. Take ownership of deployment and production reliability.",
        "criteria": [
            {"id": "python", "label": "Python", "weight": 25},
            {"id": "react", "label": "React", "weight": 25},
            {"id": "postgresql", "label": "PostgreSQL", "weight": 25},
            {"id": "deployment", "label": "Deployment", "weight": 25},
        ],
    },
]

# Fictional descriptions are deliberately varied; no real employment history is used.
PEOPLE = [
    ("Mira Rowan", "Backend engineer", "Python, FastAPI, PostgreSQL, pytest, Docker", 5, "Bengaluru", "Built Python order APIs using FastAPI and PostgreSQL. Added automated testing with pytest and reduced API error rates through integration tests.", "job-backend", "shortlisted"),
    ("Arjun Vale", "Python API engineer", "Python, FastAPI, PostgreSQL, unittest", 4, "Hyderabad", "Delivered FastAPI services in Python backed by PostgreSQL. Maintained automated testing with unittest and contract tests.", "job-backend", "assessment"),
    ("Nila Hart", "Platform developer", "Python, FastAPI, PostgreSQL, pytest, CI/CD", 6, "Pune", "Owned Python payment processing with FastAPI and PostgreSQL migrations. Established automated testing and CI/CD deployment pipelines.", "job-backend", "interview"),
    ("Dev Mercer", "Backend developer", "Python, FastAPI, PostgreSQL, Docker", 3, "Chennai", "Built Python reporting services with FastAPI, SQL transactions in PostgreSQL and deployment with Docker. Testing responsibilities were shared with a separate team.", "job-backend", "screening"),
    ("Tara Finch", "API developer", "Python, Django, PostgreSQL, pytest", 4, "Remote", "Maintained Python and Django APIs with PostgreSQL. Wrote automated testing suites using pytest. No FastAPI project is described.", "job-backend", "new"),
    ("Ishan Brook", "Frontend engineer", "React, TypeScript, Accessibility, Playwright", 4, "Pune", "Built React applications in TypeScript. Led accessibility work with keyboard navigation and screen-reader checks. Added automated testing with Playwright.", "job-frontend", "shortlisted"),
    ("Rhea Linden", "UI engineer", "React, TypeScript, Accessibility, Vitest", 5, "Bengaluru", "Shipped React and TypeScript design-system components. Improved accessibility with semantic HTML and maintained automated testing using Vitest.", "job-frontend", "assessment"),
    ("Kabir Reed", "Frontend developer", "React, TypeScript, Accessibility, Jest", 3, "Delhi", "Created React dashboards with TypeScript, accessibility reviews and automated testing in Jest.", "job-frontend", "interview"),
    ("Anya Frost", "Product UI developer", "React, TypeScript, CSS, Vitest", 2, "Remote", "Implemented React interfaces and TypeScript state management. Added automated testing with Vitest and responsive CSS layouts.", "job-frontend", "screening"),
    ("Neil Arbor", "Web engineer", "React, JavaScript, Accessibility, Cypress", 3, "Mumbai", "Built React applications in JavaScript with accessibility improvements. Automated testing in Cypress covers major user journeys.", "job-frontend", "new"),
    ("Sana Wren", "Full-stack engineer", "Python, React, PostgreSQL, Docker, Deployment", 5, "Remote", "Delivered Python APIs and React interfaces using PostgreSQL. Owned deployment using Docker and GitHub Actions.", "job-fullstack", "shortlisted"),
    ("Vihaan Alder", "Product engineer", "Python, React, PostgreSQL, Deployment", 4, "Bengaluru", "Built Python and React product features. Designed PostgreSQL schemas and managed deployment and rollback procedures.", "job-fullstack", "assessment"),
    ("Leah Cove", "Full-stack developer", "Python, React, PostgreSQL, CI/CD", 3, "Pune", "Shipped Python backend features, React pages and PostgreSQL queries. Operated CI/CD deployment workflows.", "job-fullstack", "hired"),
    ("Aadi Quinn", "Application engineer", "Python, React, PostgreSQL, Docker", 2, "Hyderabad", "Developed Python services and React forms backed by PostgreSQL. Helped deployment with Docker in a supervised project.", "job-fullstack", "screening"),
    ("Zoya Elm", "Web application developer", "Python, React, SQLite, Deployment", 3, "Remote", "Created Python and React web applications with SQLite. Owned deployment to a hosted container platform.", "job-fullstack", "new"),
    ("Omar Birch", "Data analyst", "Python, pandas, SQL, Tableau", 2, "Delhi", "Analyzed synthetic sales data with Python and pandas. Built Tableau dashboards and SQL reports.", "job-backend", "new"),
    ("Pia Moss", "Java services developer", "Java, Spring, MySQL, JUnit", 4, "Chennai", "Delivered Java services using Spring and MySQL. Wrote JUnit integration tests for billing workflows.", "job-backend", "rejected"),
    ("Evan Lake", "UX designer", "Figma, Research, Accessibility, HTML", 3, "Mumbai", "Designed Figma prototypes, conducted research and audited accessibility of semantic HTML prototypes.", "job-frontend", "new"),
    ("Kira Ash", "Mobile developer", "Flutter, Dart, Firebase", 2, "Pune", "Developed Flutter applications in Dart using Firebase authentication and offline storage.", "job-frontend", "withdrawn"),
    ("Rohan Fern", "Infrastructure engineer", "Go, Kubernetes, Terraform, Deployment", 5, "Remote", "Operated Go services on Kubernetes. Automated infrastructure deployment with Terraform and rollback drills.", "job-fullstack", "new"),
]


def build_data() -> dict:
    candidates = []
    for index, (name, headline, skills, years, location, work, job_id, stage) in enumerate(PEOPLE, 1):
        email = f"candidate{index:02d}@example.test"
        text = (
            f"SYNTHETIC PORTFOLIO RESUME - FICTIONAL PERSON\nName: {name}\n{email}\n"
            f"{headline}\nLocation: {location}\nExperience: {years} years\n"
            f"Skills: {skills}\n\nProject experience\n{work}\n\n"
            "Education: Example Institute, software studies. Fictional institution.\n"
            f"Notice period: {30 if index % 3 else 60} days\n"
            "Salary expectation: Discuss with recruiter.\n"
            "This document is synthetic and may be used for portfolio demonstrations."
        )
        candidates.append({
            "id": f"candidate-{index:02d}", "name": name, "email": email, "headline": headline,
            "skills": [s.strip() for s in skills.split(",")], "experience_years": years,
            "location": location, "notice_period_days": 30 if index % 3 else 60,
            "salary_expectation": "Discuss with recruiter.", "profile_version": 1,
            "resume_text": text, "segments": [{"id": "page-1", "text": text}],
            "job_id": job_id, "stage": stage,
        })
    return {"synthetic": True, "jobs": JOBS, "candidates": candidates}


def main() -> None:
    from docx import Document
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    data = build_data()
    directory = ROOT / "samples" / "resumes"
    directory.mkdir(parents=True, exist_ok=True)
    (ROOT / "fixtures").mkdir(exist_ok=True)
    for index, candidate in enumerate(data["candidates"]):
        suffix = ".pdf" if index % 2 == 0 else ".docx"
        path = directory / (candidate["id"] + suffix)
        if suffix == ".pdf":
            styles = getSampleStyleSheet()
            parts = []
            for line in candidate["resume_text"].splitlines():
                parts.extend([Paragraph(escape(line) or " ", styles["BodyText"]), Spacer(1, 7)])
            SimpleDocTemplate(str(path), pagesize=A4).build(parts)
        else:
            document = Document()
            for line in candidate["resume_text"].splitlines():
                document.add_paragraph(line)
            document.save(path)
        candidate["sample_file"] = str(path.relative_to(ROOT)).replace("\\", "/")
    (ROOT / "fixtures" / "synthetic.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    labels = {
        "description": "Author-assigned relevance judgements on fictional software-role resumes; not a validated hiring benchmark.",
        "relevant_candidates": {
            "job-backend": [f"candidate-{n:02d}" for n in [1, 2, 3, 4, 5, 11, 12, 13, 14]],
            "job-frontend": [f"candidate-{n:02d}" for n in [6, 7, 8, 9, 10, 11, 12, 13, 14]],
            "job-fullstack": [f"candidate-{n:02d}" for n in [11, 12, 13, 14, 15]],
        },
    }
    (ROOT / "fixtures" / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"Generated {len(data['candidates'])} fictional resumes and 3 jobs.")


if __name__ == "__main__":
    main()
