# Truck-Booking-App

## Project Overview
This is a Flask-based web application for booking and tracking truck deliveries. The system allows users to book trucks for cargo transport between predefined locations, and drivers can accept rides and track their progress. The application uses real-time route optimization, cost calculation, and vehicle movement simulation.

## Features
- **User Panel**: Estimate fare, book rides with multiple intermediate stops, live tracking, route display.
- **Truck Configuration**: Manually select combinations and quantities of mixed trucks (Light, Small, Big) with capacity validation.
- **Constraints**: Pre-booking road compatibility validation prevents large trucks from being routed through narrow streets.
- **Driver Panel**: View pending bookings, see truck mix details, accept rides, simulate movement, and manage stops.
- **In-gate pass approval**: A campus booking raises a pending gate pass for the selected hostel or department. That authority approves or rejects it. Campus security can verify the pass; only an approved pass is valid for entry.
- **Halt Management**: Drivers can report arrivals/departures at intermediate stops, accruing halt charges (₹100/hr) automatically.
- **Simulation**: Realistic multi-leg simulation traversing from pickup, through all stops, to final drop.
- **Routing**: Prioritizes OpenRouteService (requires API key), falls back to OSRM public API, and finally to straight-line calculation.
- **Pricing**: Dynamic cost calculation based on distance, weight, traffic factors, and accumulated halt times.
- **Persistence**: Thread-safe SQLite database for robust, concurrent connections and live geolocation tracking.
- **IIT campus heavy vehicles**: Campus gates, hostels, labs, and halls can be booked alongside the original Mumbai locations. A big truck that touches campus needs a requester, purpose, official gate, and a morning or evening entry window. A campus security fee is added to the existing fare. Narrow hostel lanes still reject big trucks.

## Technology Stack
- **Backend**: Python 3, Flask, flask-cors, python-dotenv, requests, sqlite3
- **Frontend**: HTML5, CSS3, Bootstrap 5, Leaflet.js (for maps)
- **Data**: SQLite embedded database (`app.db`)

## Project Structure & File Description

### Backend
- **`backend/app.py`**: The main entry point. Initializes the Flask app, configures CORS, registers blueprints (`user_bp`, `driver_bp`), and defines core routes for the UI (`/`, `/user_panel`, `/driver_panel`) and simulation (`/simulate`).
- **`backend/models/`**:
  - **`booking.py`**: Manages booking data persistence. Functions to load/save the DB, create bookings, and update booking fields.
  - **`vehicle.py`**: Manages vehicle data. Functions to get vehicle info, update positions, and list all vehicles.
- **`backend/services/`**:
  - **`route_optimizer.py`**: Handles route calculation. Fetches route geometry, distance, and duration from OpenRouteService or OSRM. Includes a haversine fallback.
  - **`cost_calculator.py`**: Implements pricing logic. Calculates total cost based on base rates, distance, weight multipliers, and traffic factors (peak hour surcharges).
  - **`simulator.py`**: Handles the background simulation of vehicle movement. Moves the truck along the route coordinates in a separate thread, updating its position in real-time.
- **`backend/routes/`**:
  - **`user_routes.py`**: API endpoints for users (`/api/user/...`). Handles fetching locations, estimating costs, creating bookings, validating road constraints, and tracking mixed truck configurations.
  - **`driver_routes.py`**: API endpoints for drivers (`/api/driver/...`). Handles listing pending jobs, accepting bookings, logging stop arrivals/departures, and updating load status.
- **`backend/database/`**:
  - **`db.py`**: thread-safe SQLite connection pool, schema initiation, and seeding for Mumbai locations and vehicle fleet.
  - **`app.db`**: SQLite database file containing structured tables (`vehicles`, `bookings`, `booking_stops`, `locations`).

### Frontend
- **`frontend/templates/`**: HTML templates for the application (`index.html`, `user_panel.html`, `driver_panel.html`, `map_view.html`).
- **`frontend/static/js/`**:
  - **`user.js`**: Client-side logic for the user panel. Handles map initialization, booking flow, polling for updates, and UI interactions.
  - **`driver.js`**: Client-side logic for the driver panel. Handles job acceptance, status updates, and route visualization.

## Setup & Installation

1. **Clone the repository**
   ```bash
   git clone <https://github.com/yakshbhesaniya/Truck-Booking-WebApp.git>
   cd Truck-Booking-App
   ```

2. **Set up the environment** (Windows PowerShell)
   ```powershell
   python -m venv .venv
   . .\.venv\Scripts\Activate.ps1
   pip install Flask flask-cors python-dotenv requests
   ```

3. **Configure Environment Variables** (Optional)
   Create a `.env` file in the root directory:
   ```
   OPENROUTESERVICE_API_KEY=YOUR_ORS_KEY
   ```
   *Note: Without a key, the app defaults to OSRM public routing or straight-line paths.*

## Running the Application

```powershell
python -m backend.app
```
The application will start on `http://localhost:8000`.

## Usage Guide

1. **Open the Application**:
   - **User Interface**: `http://localhost:8000/user_panel`
   - **Driver Interface**: `http://localhost:8000/driver_panel`
   - **Gate pass approval**: `http://localhost:8000/authority`
   - **Security verification**: `http://localhost:8000/security`

2. **User Flow**:
   - Select a Pickup and Drop location.
   - Enter cargo weight and click **"Get Estimate"** to see the fare and route.
   - Click **"Book Now"**. The request is sent to the driver.
   - Wait for a driver to accept. Once the driver arrives, click **"Mark Loaded"**.

3. **Driver Flow**:
   - View the **"Pending Bookings"** list.
   - Click **"Accept"** on a booking. The truck will simulate driving to the pickup point.
   - Once arrived, click **"Mark Loaded"**.
   - After both parties confirm, the truck simulates driving to the drop location.

## In-gate pass

Campus trips (a stop inside IIT Bombay) ask who booked the truck, their category, the hostel or department, and the purpose. Confirming the booking creates one gate pass with status `PENDING`. City trips do not create a pass.

The gate office signs in at `/authority` and sees every hostel and department request. Approve and Reject record the authority and the time. A second decision is rejected. Security signs in at `/security` and looks up the gate pass id. Pending and rejected passes are not valid for entry.

Demo accounts are created on the server and hashed before storage. They are not included in the frontend. Override any password with `GATEPASS_PASSWORD_HOSTEL_1`, `GATEPASS_PASSWORD_CSE`, `GATEPASS_PASSWORD_SECURITY`, and the same pattern for the other units.

| Unit | Username | Password |
| --- | --- | --- |
| Gate office (every request) | `gate` | `gate123` |
| Hostel-1 | `hostel1.warden` | `Hostel1-Approve` |
| Hostel-3 | `hostel3.warden` | `Hostel3-Approve` |
| Hostel-12 | `hostel12.warden` | `Hostel12-Approve` |
| Computer Science and Engineering | `cse.office` | `Cse-Approve` |
| SJMSOM | `sjmsom.office` | `Sjmsom-Approve` |
| Central Library | `library.office` | `Library-Approve` |
| Estate Office | `estate.office` | `Estate-Approve` |
| Guest House | `guesthouse.office` | `Guest-Approve` |
| Campus Security | `security.gate` | `Security-Verify` |

## API Endpoints

### User API
- `GET /api/user/locations`: List available locations.
- `POST /api/user/estimate`: Get trip cost and route details.
- `POST /api/user/book`: Create a new booking.
- `GET /api/user/booking/<id>`: Get booking status.
- `POST /api/user/confirm_loaded`: User confirmation of cargo loading.

### Driver API
- `GET /api/driver/pending`: List available bookings.
- `POST /api/driver/accept`: Accept a booking.
- `POST /api/driver/mark_loaded`: Driver confirmation of cargo loading.
- `POST /api/driver/update_status`: Update booking status.

## License
This project is developed as part of the GIS (Semester Course) course at IIT Bombay.

## Author
Yaksh Bhesaniya & Team
#   l o g i s t i c s - t r a c k i n g  
 #   l o g i s t i c s - t r a c k i n g  
 #   l o g i s t i c s - t r a c k i n g  
 