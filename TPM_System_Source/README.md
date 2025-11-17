# TPM System - Source Package

This is the complete source code package for the Blue Origin TPM (Total Preventative Maintenance) System, ready for Git version control and future development.

## 🚀 Quick Start

### Development Mode
```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode
python app.py
```

### Build Executable
```bash
# Build console version
build_executable.bat

# Build GUI version (recommended)
build_gui_executable.bat
```

## 📁 Project Structure

```
TPM_System_Source/
├── app.py                    # Main console application
├── app_gui_fixed.py         # GUI application with all fixes
├── requirements.txt         # Python dependencies
├── templates/
│   ├── dashboard.html       # Main web interface
│   └── login.html          # Login page
├── build/
│   └── app.spec            # PyInstaller configuration
├── build_executable.bat    # Build script for console version
├── build_gui_executable.bat # Build script for GUI version
├── OperationalExcellence.ico # Application icon
└── README.md               # This file
```

## 🔧 Key Features

### Core Functionality
- **Task Management**: Create, edit, and track maintenance tasks
- **User Management**: Admin and operator roles with shift assignments
- **Shift-Based Scheduling**: Configurable shift patterns (A, B, C, D)
- **Interval Types**: Start/end of shift daily/weekly scheduling
- **Priority System**: High, medium, low priority tasks
- **Completion Tracking**: Task completion history and notes

### Advanced Features
- **Export/Import System**: Backup and migrate data between systems
- **Reporting**: Comprehensive reports with filtering
- **CSV Export**: Export completion data for analysis
- **Ignition Integration**: API endpoints for SCADA integration
- **Run Permissive Logic**: Safety interlocks based on task completion

### System Integration
- **Web Interface**: Modern responsive design
- **REST API**: Full API for external integrations
- **Database**: SQLite with automatic initialization
- **System Tray**: Background operation with tray icon
- **Auto-Launch**: Automatic browser opening

## 🛠️ Recent Fixes (v1.2.1)

### Database Operations Fixed
- ✅ Fixed user creation using correct `password_hash` column
- ✅ Fixed user updates and password changes
- ✅ Fixed import functionality column references
- ✅ Corrected all database queries for consistency

### Import/Export System Fixed
- ✅ Fixed import endpoint to handle JSON data from frontend
- ✅ Export functionality working correctly
- ✅ Proper error handling and validation
- ✅ Support for both file upload and JSON data formats

### GUI Application Stability
- ✅ Fixed secret key consistency issues
- ✅ Resolved database initialization errors
- ✅ Corrected all API endpoints for frontend compatibility
- ✅ System tray integration working properly

## 🔧 Development Setup

### Prerequisites
- Python 3.8+ (tested with Python 3.14)
- Windows 10/11 (for executable building)

### Installation
1. Clone or extract this source package
2. Install dependencies: `pip install -r requirements.txt`
3. Run development server: `python app.py`
4. Access at: http://localhost:8080

### Default Credentials
- **Admin**: admin / admin123
- **Operator**: operator / operator123 (Shift A)

## 🏗️ Building Executables

### Console Version
```bash
build_executable.bat
```
- Creates: `dist/TPM_System/TPM_System.exe`
- Shows console window during operation
- Good for debugging and development

### GUI Version (Recommended)
```bash
build_gui_executable.bat
```
- Creates: `dist/TPM_System_GUI/TPM_System_GUI.exe`
- Runs in background with system tray
- Professional deployment option
- No console window visible

## 📊 API Endpoints

### Task Management
- `GET /api/tasks` - List all tasks
- `POST /api/tasks` - Create new task
- `PUT /api/tasks/{id}` - Update task
- `DELETE /api/tasks/{id}` - Delete task
- `POST /api/tasks/{id}/complete` - Complete task

### User Management
- `GET /api/users` - List users
- `POST /api/users` - Create user
- `PUT /api/users/{id}` - Update user
- `DELETE /api/users/{id}` - Delete user

### Reports & Export
- `GET /api/reports/summary` - Generate reports
- `GET /api/reports/export` - Export CSV
- `GET /api/admin/export` - Export system data
- `POST /api/admin/import` - Import system data

### Ignition Integration
- `GET /api/ignition/tasks` - Get tasks for SCADA
- `GET /api/ignition/active-shift` - Get current shift
- `GET /api/ignition/run_permissive` - Check run permissive

## 🔄 Shift Configuration

### Default Shifts
- **Shift A**: 04:30-15:30 Mon-Thu
- **Shift B**: 16:30-03:30 Mon-Thu (overnight)
- **Shift C**: 05:00-17:00 Fri-Sun
- **Shift D**: 17:00-05:00 Fri-Sun (overnight)

### Interval Types
- **Start of Shift Daily**: Due at shift start each active day
- **Start of Shift Weekly**: Due at first shift day of week
- **End of Shift Daily**: Due at shift end each active day
- **End of Shift Weekly**: Due at last shift day of week

## 🐛 Troubleshooting

### Common Issues
1. **Import fails**: Ensure JSON file is valid TPM export format
2. **Database errors**: Delete `tpm_database.db` to reset
3. **Build fails**: Check Python and PyInstaller versions
4. **Port conflicts**: Change port in app.py if 8080 is in use

### Debug Mode
Run with debug enabled:
```python
app.run(debug=True, host='0.0.0.0', port=8080)
```

## 📝 Version History

### v1.2.1 (Current)
- Fixed all database column reference issues
- Fixed import/export functionality
- Improved error handling and logging
- Enhanced GUI stability

### v1.2.0
- Added GUI version with system tray
- Implemented export/import system
- Enhanced reporting capabilities
- Added Ignition API integration

### v1.1.0
- Added user management
- Implemented shift-based scheduling
- Added task completion tracking
- Web interface improvements

### v1.0.0
- Initial release
- Basic task management
- SQLite database
- Web interface

## 🤝 Contributing

This source package is ready for:
- Git version control
- Team development
- Feature additions
- Bug fixes
- Customization

## 📄 License

Internal Blue Origin project - All rights reserved.

## 📞 Support

For technical support or feature requests, contact the development team.

---

**Built with**: Python, Flask, SQLite, PyInstaller, HTML/CSS/JavaScript
**Tested on**: Windows 10/11, Python 3.8-3.14
**Last Updated**: November 2024