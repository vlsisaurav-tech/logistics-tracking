"""Build the project guide PDF. Run from the project root:

    .\\.venv\\Scripts\\python docs\\generate_guide.py
"""

from pathlib import Path
from fpdf import FPDF

OUT = Path(__file__).resolve().parents[1] / "IIT_Heavy_Vehicle_Booking_Guide.pdf"


class Guide(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(15, 110, 107)
        self.cell(0, 8, "IIT Heavy Vehicle Booking  |  LogiTrek", align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 113, 108)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

    def h1(self, text):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(28, 25, 23)
        self.multi_cell(0, 8, text)
        self.ln(2)

    def h2(self, text):
        self.ln(2)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(15, 110, 107)
        self.multi_cell(0, 7, text)
        self.ln(1)

    def body(self, text):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(41, 37, 36)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def bullet(self, text):
        self.set_font("Helvetica", "", 11)
        self.set_text_color(41, 37, 36)
        self.multi_cell(0, 6, "- " + text)
        self.ln(0.5)


def build():
    pdf = Guide()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    pdf.h1("How the IIT campus heavy-vehicle booking works")
    pdf.body(
        "This note explains the code added on top of the existing LogiTrek truck booking app, "
        "and how to run it. The original user flow, driver flow, mixed trucks, halt charges, "
        "route simulation, and Mumbai locations are still in place."
    )

    pdf.h2("Problem this change serves")
    pdf.body(
        "The booking problem is to move heavy vehicles in the IIT Bombay area: hostel shifting, "
        "lab equipment, construction material, and mess supplies. A big truck cannot simply "
        "drive onto campus. It needs a requesting unit, a purpose, an official gate, and a "
        "morning or evening entry window. Inner hostel lanes stay closed to big trucks."
    )

    pdf.h2("What stayed the same")
    pdf.bullet("User panel: estimate, book, intermediate stops, live map, confirm loaded, cancel.")
    pdf.bullet("Driver panel: pending jobs, accept, halt timer, mark loaded, simulation.")
    pdf.bullet("Pricing for distance, truck mix, traffic, and halt time (Rs 100 per hour).")
    pdf.bullet("SQLite tables for vehicles, bookings, stops, and locations.")

    pdf.h2("What was added")
    pdf.bullet("A warmer teal and sand theme in frontend/static/css/style.css. Buttons, badges, maps, and both portals use it. No booking control was removed.")
    pdf.bullet("Campus places seeded beside the old city list: Main Gate, Y-Point Gate, Market Gate, Convocation Hall, VMCC, Central Library, KReSIT / CSE, SJMSOM, Guest House, Lakeside, Hostel-1, and Hostel-3. Hostel-12, Hostel-3, Narrow Street, and Market Road stay marked as narrow.")
    pdf.bullet("A second big truck, BIG-2 (Campus Heavy 2), parked near the Main Gate. LIGHT-1, SMALL-1, and BIG-1 are unchanged.")
    pdf.bullet("Gate pass fields on the user form: requesting unit, purpose, entry gate, and entry window.")
    pdf.bullet("A campus fee added to the existing fare: Rs 80 when any campus point is on the trip, Rs 250 when the truck is big.")
    pdf.bullet("Entry status OPEN when the chosen window matches the current clock, otherwise SCHEDULED. The booking is still accepted so a demo works outside those hours.")

    pdf.h2("Files and what they do")
    pdf.body("backend/services/campus.py")
    pdf.body(
        "Holds the campus catalogue rules: official gates, purposes, the two entry windows "
        "(06:00-09:30 and 16:30-19:30), and the two fees. assess_trip() looks at every stop name. "
        "If none of them are campus, gate, or narrow, the trip is a normal city booking and the "
        "new fields can be blank. If a big truck touches campus, purpose, gate, slot, and requester "
        "are required. public_rules() feeds GET /api/user/campus."
    )
    pdf.body("backend/database/db.py")
    pdf.body(
        "init_db() still creates the original tables. _ensure_location_columns() adds zone and "
        "heavy_ok to locations with ALTER TABLE, so an existing app.db is not wiped. Seed inserts "
        "use INSERT OR IGNORE, then UPDATE sets zone for the campus names. City rows stay zone=city."
    )
    pdf.body("backend/routes/user_routes.py")
    pdf.body(
        "_apply_campus() runs after the old fare breakdown. It adds campus_fee onto total_cost. "
        "POST /api/user/estimate and POST /api/user/book both call it. A missing gate pass returns "
        "HTTP 400 with a plain error. The booking stores purpose, entry_gate, entry_slot, requester, "
        "campus_trip, needs_pass, entry_status, and campus_fee in the existing extra_fields JSON "
        "column, so the bookings table schema did not need new columns. GET /api/user/locations now "
        "also returns zone and heavy_ok. GET /api/user/campus returns gates, purposes, slots, and fees."
    )
    pdf.body("frontend/templates and frontend/static/js")
    pdf.body(
        "index.html explains the campus use case and lists the new checks next to the old features. "
        "user_panel.html adds the gate-pass card and a campus line on the trip summary. "
        "user.js sends requester, purpose, entry_gate, and entry_slot with estimate and book, "
        "labels campus stops in the dropdowns, and shows the campus fee. driver_panel.html and "
        "driver.js show the gate, window, and requester on pending jobs and on the active trip. "
        "Map polylines use the same teal as the new theme."
    )

    pdf.h2("How a campus booking is decided")
    pdf.bullet("The user picks pickup, optional stops, drop, and weight, exactly as before.")
    pdf.bullet("Weight still chooses light (up to 1 t), small (up to 3 t), or big (above 3 t). Manual truck counts still override that.")
    pdf.bullet("If the truck is big and any stop name matches Hostel-12, Hostel-3, Narrow Street, or Market Road, the request is rejected.")
    pdf.bullet("If any stop is a campus or gate location and the truck is big, the four gate-pass fields are required.")
    pdf.bullet("The route, distance, ETA, and base fare are calculated by the original route optimizer and cost calculator. The campus fee is added afterwards.")
    pdf.bullet("The driver sees the campus line and accepts the job with the matching truck, same as a city job.")

    pdf.h2("How to run the app")
    pdf.body("From the project folder (the one that contains backend, frontend, and requirements.txt):")
    pdf.body("1. Create and activate a virtual environment if you do not already have .venv.")
    pdf.body("   python -m venv .venv")
    pdf.body("   .\\.venv\\Scripts\\Activate.ps1")
    pdf.body("2. Install dependencies.")
    pdf.body("   pip install -r requirements.txt")
    pdf.body("   pip install fpdf2")
    pdf.body("   fpdf2 is only needed to rebuild this PDF. The website does not import it.")
    pdf.body("3. Optional routing key. Create a .env file with OPENROUTESERVICE_API_KEY=your_key.")
    pdf.body("   Without it, routing uses the public OSRM service, then a straight line.")
    pdf.body("4. Start the server from the project folder so the backend package imports correctly.")
    pdf.body("   python -m backend.app")
    pdf.body("5. Open a browser.")
    pdf.body("   Home:        http://localhost:8000/")
    pdf.body("   Book a truck: http://localhost:8000/user_panel")
    pdf.body("   Driver:      http://localhost:8000/driver_panel")

    pdf.h2("How to see the new result")
    pdf.bullet("On the user panel, set weight to 4000 kg so the truck is big.")
    pdf.bullet("Set pickup to Powai and drop to Central Library (IIT) or VMCC (IIT).")
    pdf.bullet("Fill Requesting unit (for example CSE lab), Purpose (Lab equipment), Entry gate (IIT Bombay Main Gate), and Entry window.")
    pdf.bullet("Click Calculate Fare. The estimate includes the Rs 250 campus fee and says whether the window is open or scheduled.")
    pdf.bullet("Click Confirm Booking. The trip card shows the campus pass line.")
    pdf.bullet("Open the driver panel, choose the Big filter, and accept the job. The request shows the gate and requester.")
    pdf.bullet("Try the same trip with drop Hostel-12. It should be rejected because that lane is too narrow for a big truck.")
    pdf.bullet("Try pickup Colaba and drop Fort with 500 kg and blank gate-pass fields. That city booking should still succeed with no campus fee.")
    pdf.body("To rebuild this PDF after further edits, run:")
    pdf.body("   python docs\\generate_guide.py")
    pdf.body("The file is written to IIT_Heavy_Vehicle_Booking_Guide.pdf in the project folder.")

    pdf.output(str(OUT))
    print(OUT)


if __name__ == "__main__":
    build()
