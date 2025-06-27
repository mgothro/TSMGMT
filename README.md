# TSMGMT

**TSMGMT** is a streamlined web-based task management system built with **Flask**, designed to support internal operational workflows. This public-facing repository contains a cleaned version of the application code intended for demonstration and resume purposes. The full production system is hosted and versioned in TFS.

---

## Features

- Internal task dashboard for team collaboration
- User-based task assignment and status tracking
- Integration with Basecamp for synced task data
- Role-based access (admin/user)
- Custom task status updates and reordering
- Live sync view using Server-Sent Events (SSE)

---

## Getting Started

### Requirements
- Python 3.8+
- Flask
- SQL Server

### Installation

```bash
git clone https://github.com/mgothro/TSMGMT.git
cd TSMGMT
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Variables
Create a `.env` file or set the following environment variables:

```
EMAIL_COLORS={"user@example.com": "primary"}
BASECAMP_CLIENT_ID=your_client_id
BASECAMP_CLIENT_SECRET=your_secret
BASECAMP_REDIRECT_URI=http://localhost:5000/work_status/basecamp_callback
```

---

## Overview

- `work_status/` — Blueprint for Basecamp task syncing and live status updates
- `db/` — Utility modules for executing SQL queries
- `templates/` — HTML views using Jinja2
- `static/` — CSS/JS for frontend behavior
- `runserver.py` — App entry point

---

## Project Goals

- Support team coordination on deliverables
- Act as a Basecamp companion interface with enhanced filtering and tagging

---

## License

MIT License — see [`LICENSE`](LICENSE) for full terms.

---

## Author
**Matthew Gothro**  
[github.com/mgothro](https://github.com/mgothro)

---

> This repository is for demonstration purposes only. Proprietary data and logic have been excluded or anonymized.
