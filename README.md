# GeoNizam – Workforce Management System

> A professional desktop-based workforce management system designed to simplify employee attendance, task management, GPS tracking, notifications, requests, salary management, and administrative control.

GeoNizam is an **offline-first workforce management application** built with Python. It provides separate dashboards and permissions for **Super Admins, Admins, and Employees**, with data stored locally using SQLite.

---

## 🚀 Key Features

- 🔐 Role-based Login System
- 👑 Super Admin Dashboard
- 🛡️ Admin Management & Permissions
- 👥 Employee Management
- 📍 Live GPS Tracking
- 📸 Selfie-Based Attendance
- ✅ Manual Attendance Approval / Rejection
- 📋 Task Assignment & Management
- 🔔 Notifications
- 📩 Employee Requests
- 💰 Salary & Payroll Management
- 📊 Activity & Attendance Monitoring
- 🗺️ Real-Time Employee Location
- 💾 Local SQLite Database
- 🖥️ Desktop Application
- 🔒 Permission-Based Feature Control

---

# 👥 User Roles

## 👑 Super Admin

The Super Admin has system-wide control over the application.

### Responsibilities

- Create and manage Admins
- Manage Admin permissions
- Monitor system statistics
- Control available Admin features
- Manage overall system access

---

## 🛡️ Admin

Admins manage employees assigned to them.

### Responsibilities

- Add and manage employees
- Monitor attendance
- Approve or reject selfie attendance
- Track employee locations
- Assign tasks
- Send notifications
- Manage employee requests
- Calculate salaries
- Monitor employee activities

---

## 👤 Employee

Employees can access their personal workforce dashboard.

### Available Features

- Selfie Attendance
- View Assigned Tasks
- Update Task Status
- View Notifications
- Submit Requests
- Share Location
- View Personal Information
- Monitor Attendance & Work Activity

---

# 📸 Application Screenshots

The following screenshots demonstrate the major features and interfaces available in GeoNizam.

---

## 🔐 Authentication & Startup

### Splash Screen

The application starts with a professional branded splash screen before opening the login interface.

![Splash Screen](Screenshot/Splash%20Screen.png)

---

### Main Login Screen

Secure login interface supporting the application's different user roles.

![Main Login Screen](Screenshot/Main%20Login%20Screen.png)

---

# 👑 Super Admin Dashboard

### Super Admin Dashboard

The central dashboard provides the Super Admin with an overview and system-wide administrative controls.

![Super Admin Dashboard](Screenshot/Super%20Admin%20Dashboard.png)

---

### Manage Admin Permissions

Super Admins can control which features are available to individual Admin accounts.

![Manage Admin Permission](Screenshot/Manage%20Admin%20Permission.png)

---

### Reset All Data

Administrative data-management functionality for resetting application data when required.

![Reset All Data](Screenshot/Reset%20All%20Data.png)

---

# 👥 Employee Management

### Add Employees

Admins can create and manage employee accounts from the employee management interface.

![Add Employees](Screenshot/Add%20Employees.png)

---

### Employee Requests

Admins can review requests submitted by employees.

![Employees Requests](Screenshot/Employees%20Requests.png)

---

### Send Requests

Employees can submit requests directly through the application.

![Send Requests](Screenshot/Send%20Requests.png)

---

# 📸 Attendance Management

### Selfie Capture for Attendance

Employees can capture a selfie through the attendance system and submit it for verification.

![Selfie Capture for Attendance](Screenshot/Selfie%20Capture%20for%20Attendance.png)

---

### Selfie Approved or Rejected

Admins can manually review submitted attendance selfies and approve or reject them.

![Selfie Approved or Rejected](Screenshot/Selfie%20approved%20or%20rejected.png)

---

# 📍 GPS & Location Tracking

### Live GPS Tracking

Admins can monitor the current location of employees through the live tracking interface.

![Live GPS Tracking](Screenshot/Live%20GPS%20Tracking.png)

---

### GPS Location Sharing

Employees can share their current location with the workforce management system.

![GPS Location Share](Screenshot/GPS%20Location%20Share.png)

---

### Live Activity Tracking

Admins can monitor employee activity through the live activity tracking interface.

![Live Activity Tracking](Screenshot/Live%20Activity%20Tracking.png)

---

# 📋 Task Management

### New Task Assignment

Admins can assign tasks to employees with relevant task information and deadlines.

![New Task Assign](Screenshot/New%20Task%20Assign.png)

---

# 🔔 Notification System

### Send Notification to Employee

Admins can send important announcements and notifications directly to employees.

![Send Notification to Employee](Screenshot/Send%20Notification%20to%20Employee.png)

---

### Notifications from Admin

Employees can view notifications and announcements received from their Admin.

![Notifications from Admin](Screenshot/Notifications%20from%20Admin.png)

---

# 💰 Salary Management

### Calculate Salary

The system provides salary calculation functionality for employee payroll management.

![Calculate Salary](Screenshot/Calculate%20Salary.png)

---

# 🖥️ Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core Application |
| CustomTkinter | Modern Desktop UI |
| SQLite | Local Database |
| OpenCV | Camera & Selfie Capture |
| Tkinter | Desktop Interface |
| HTML5 Geolocation | Device Location |
| OpenStreetMap | Map Data |
| Nominatim | Reverse Geocoding |
| Git & GitHub | Version Control |

---

# ⚙️ Requirements

- Python **3.11.9**
- Windows/Linux compatible Python environment
- Working webcam
- Location-enabled device
- Internet connection for map and location services

---

# 📦 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/MUdevelops/GeoNizam-Workforce-Management-System.git
````

### 2. Open the Project

```bash
cd GeoNizam-Workforce-Management-System
```

### 3. Create a Virtual Environment

```bash
python -m venv venv
```

### 4. Activate the Virtual Environment

#### Windows

```bash
venv\Scripts\activate
```

#### Linux / macOS

```bash
source venv/bin/activate
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run GeoNizam

```bash
python Main.py
```

---

# 🗂️ Project Structure

```text
GeoNizam/
│
├── Main.py
├── Admin.py
├── Employee.py
├── SuperAdmin.py
│
├── attendance.py
├── activity_engine.py
├── gps_realtime.py
├── notification_engine.py
├── realtime_hub.py
├── task_engine.py
├── database.py
├── config.py
├── utils.py
│
├── assets/
│   └── Splash.png
│
├── data/
│   └── geonizam.db
│
├── Screenshot/
│   ├── Splash Screen.png
│   ├── Main Login Screen.png
│   ├── Super Admin Dashboard.png
│   ├── Manage Admin Permission.png
│   ├── Add Employees.png
│   ├── Selfie Capture for Attendance.png
│   ├── Selfie approved or rejected.png
│   ├── Live GPS Tracking.png
│   ├── GPS Location Share.png
│   ├── Live Activity Tracking.png
│   ├── New Task Assign.png
│   ├── Send Notification to Employee.png
│   ├── Notifications from Admin.png
│   ├── Send Requests.png
│   ├── Employees Requests.png
│   ├── Calculate Salary.png
│   └── Reset All Data.png
│
├── tests/
│
├── requirements.txt
└── README.md
```

---

# 🔄 Core Workflow

```text
                    GeoNizam
                       │
            ┌──────────┴──────────┐
            │                     │
       Super Admin              Login
            │                     │
     Manage Admins       ┌────────┴────────┐
     & Permissions        │                 │
                         Admin           Employee
                           │                 │
                    Manage Employees    Attendance
                           │             Tasks
                    Assign Tasks         Requests
                    Attendance           Notifications
                    GPS Tracking         Location
                    Notifications
                    Salary
```

---

# 🔒 Data & Privacy

GeoNizam is designed as an **offline-first desktop application**.

Application data is stored locally using SQLite. The system does not require a dedicated GeoNizam cloud server for its core functionality.

Location and attendance functionality may require external services such as map tiles and reverse-geocoding depending on the feature being used.

> **Important:** Do not commit real employee attendance photos, private databases, passwords, API keys, or other sensitive information to a public GitHub repository.

---

# 🧪 Testing

Automated and functional tests are maintained inside:

```text
tests/
```

Run the test suite with:

```bash
python -m pytest
```

---

# 🛠️ Project Status

**Status:** Active Development

GeoNizam is continuously being improved with new workforce-management features, interface improvements, security enhancements, and performance optimizations.

---

# 👨‍💻 Developer

**Muhammad Umar Jamal**

GitHub: **[@MUdevelops](https://github.com/MUdevelops)**

---

# 📄 License

This project is licensed under the **MIT License**.

See the `LICENSE` file for more information.

---

## ⭐ Support the Project

If you find GeoNizam useful or interesting:

* ⭐ Star the repository
* 🍴 Fork the project
* 🐛 Report issues
* 💡 Suggest improvements
* 🔧 Contribute to development

---

# GeoNizam

### Workforce Management .

````
git clone https://github.com/MUdevelops/GeoNizam-Workforce-Management-System.git

