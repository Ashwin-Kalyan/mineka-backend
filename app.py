from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import json
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables for local development
if os.path.exists('.env'):
    load_dotenv()
    logger.info("✓ Loaded .env file for local development")

app = Flask(__name__)

# Configure CORS - allow all origins for development
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Google Sheets configuration
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]

# Render secrets path
RENDER_SECRETS_PATH = '/etc/secrets/credentials.json'

def get_google_sheets_client():
    """
    Initialize and return Google Sheets client.
    Tries multiple credential sources in order of priority.
    """
    logger.info("🔐 Initializing Google Sheets client...")
    
    # 1. Try Render secrets file first
    if os.path.exists(RENDER_SECRETS_PATH):
        try:
            logger.info(f"✓ Using Render secret file: {RENDER_SECRETS_PATH}")
            credentials = Credentials.from_service_account_file(
                RENDER_SECRETS_PATH, 
                scopes=SCOPE
            )
            client = gspread.authorize(credentials)
            logger.info(f"✓ Authenticated as: {credentials.service_account_email}")
            return client
        except Exception as e:
            logger.error(f"✗ Failed to use Render secret file: {e}")
            # Continue to next method
    
    # 2. Try GOOGLE_CREDENTIALS_JSON environment variable
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json and creds_json.strip():
        try:
            logger.info("✓ Using GOOGLE_CREDENTIALS_JSON from environment")
            creds_dict = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
            client = gspread.authorize(credentials)
            logger.info(f"✓ Authenticated as: {credentials.service_account_email}")
            return client
        except json.JSONDecodeError as e:
            logger.error(f"✗ Invalid JSON in GOOGLE_CREDENTIALS_JSON: {e}")
        except Exception as e:
            logger.error(f"✗ Failed to use environment credentials: {e}")
    
    # 3. Try local credentials file
    creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH', 'credentials.json')
    if os.path.exists(creds_path):
        try:
            logger.info(f"✓ Using local credentials file: {creds_path}")
            credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPE)
            client = gspread.authorize(credentials)
            logger.info(f"✓ Authenticated as: {credentials.service_account_email}")
            return client
        except Exception as e:
            logger.error(f"✗ Failed to use local credentials file: {e}")
    
    # No credentials found
    error_msg = "❌ No valid Google credentials found. Please configure:"
    error_msg += "\n1. Upload credentials.json to Render as a Secret File, OR"
    error_msg += "\n2. Set GOOGLE_CREDENTIALS_JSON environment variable, OR"
    error_msg += "\n3. Place credentials.json in the project root for local development"
    logger.error(error_msg)
    raise ValueError(error_msg)

@app.route('/api/booking', methods=['POST', 'OPTIONS'])
def submit_booking():
    """
    Handle booking form submissions.
    Accepts: name, phone, time, location
    Returns: success/error message
    """
    # Handle CORS preflight requests
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response, 200
    
    try:
        # Parse JSON data
        data = request.get_json(force=True, silent=True)
        
        if not data:
            logger.warning("No JSON data received in booking request")
            return jsonify({'error': 'No JSON data received'}), 400
        
        logger.info(f"📥 Received booking request: {data}")
        
        # Validate required fields
        required_fields = ['name', 'phone', 'time', 'location']
        missing_fields = []
        
        for field in required_fields:
            if field not in data or not str(data[field]).strip():
                missing_fields.append(field)
        
        if missing_fields:
            logger.warning(f"Missing required fields: {missing_fields}")
            return jsonify({
                'error': f'Missing required fields: {", ".join(missing_fields)}',
                'required_fields': required_fields
            }), 400
        
        # Clean and validate data
        booking_data = {
            'name': str(data['name']).strip(),
            'phone': str(data['phone']).strip(),
            'time': str(data['time']).strip(),
            'location': str(data['location']).strip()
        }
        
        # Get Google Sheets client
        gc = get_google_sheets_client()
        
        # Get spreadsheet ID from environment
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            logger.error("GOOGLE_SPREADSHEET_ID not configured")
            return jsonify({'error': 'Google Spreadsheet ID not configured'}), 500
        
        # Clean spreadsheet ID
        spreadsheet_id = spreadsheet_id.strip()
        if '#' in spreadsheet_id:
            spreadsheet_id = spreadsheet_id.split('#')[0]
        
        logger.info(f"📊 Processing spreadsheet ID: {spreadsheet_id[:20]}...")
        
        try:
            # Open the spreadsheet
            spreadsheet = gc.open_by_key(spreadsheet_id)
            spreadsheet_title = spreadsheet.title
            logger.info(f"✅ Opened spreadsheet: {spreadsheet_title}")
            
            # Get service account email for error messages
            service_email = gc.auth.credentials.service_account_email
            logger.info(f"👤 Service account: {service_email}")
            
        except gspread.exceptions.SpreadsheetNotFound:
            error_msg = f"Spreadsheet not found with ID: {spreadsheet_id}"
            logger.error(error_msg)
            return jsonify({
                'error': error_msg,
                'help': 'Check your GOOGLE_SPREADSHEET_ID environment variable'
            }), 404
            
        except gspread.exceptions.APIError as e:
            error_msg = str(e)
            logger.error(f"Google Sheets API Error: {error_msg}")
            
            # Get service account email
            try:
                service_email = gc.auth.credentials.service_account_email
            except:
                service_email = "mineka-google-sheets@nortiq-mineka-hokkaido.iam.gserviceaccount.com"
            
            # User-friendly error messages
            if 'PERMISSION_DENIED' in error_msg.upper() or '403' in error_msg:
                share_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                return jsonify({
                    'error': 'Permission denied',
                    'details': f'Spreadsheet is not shared with the service account.',
                    'solution': f'Please share the spreadsheet with: {service_email}',
                    'steps': [
                        f'1. Open your spreadsheet: {share_url}',
                        '2. Click the "Share" button (top-right)',
                        f'3. Add this email: {service_email}',
                        '4. Select "Editor" access',
                        '5. Click "Send"'
                    ]
                }), 403
                
            elif 'disabled' in error_msg.lower() or 'not enabled' in error_msg.lower():
                return jsonify({
                    'error': 'Google Sheets API is not enabled',
                    'solution': 'Enable the Google Sheets API in Google Cloud Console',
                    'steps': [
                        '1. Go to: https://console.cloud.google.com/apis/library/sheets.googleapis.com',
                        '2. Select your project: "nortiq-mineka-hokkaido"',
                        '3. Click "Enable"',
                        '4. Wait a few minutes',
                        '5. Also enable Google Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com'
                    ]
                }), 403
                
            else:
                return jsonify({
                    'error': f'Google Sheets API error: {error_msg}',
                    'help': 'Check your Google Cloud project configuration'
                }), 500
        
        except Exception as e:
            logger.error(f"Unexpected error opening spreadsheet: {e}", exc_info=True)
            return jsonify({
                'error': f'Failed to access spreadsheet: {str(e)}',
                'help': 'Check your spreadsheet ID and internet connection'
            }), 500
        
        # Get or create the 'Bookings' worksheet
        try:
            worksheet = spreadsheet.worksheet('Bookings')
            logger.info("📝 Using existing 'Bookings' worksheet")
        except gspread.exceptions.WorksheetNotFound:
            try:
                # Try to use the first sheet
                worksheet = spreadsheet.sheet1
                logger.info("📝 Using first worksheet (Sheet1)")
            except:
                # Create a new worksheet
                logger.info("📝 Creating new 'Bookings' worksheet")
                worksheet = spreadsheet.add_worksheet(
                    title='Bookings', 
                    rows=1000, 
                    cols=10
                )
        
        # Ensure headers exist
        try:
            headers = worksheet.row_values(1)
            expected_headers = ['Name', 'Phone', 'Time', 'Location', 'Timestamp', 'Status']
            
            if not headers or headers[0] != 'Name':
                logger.info("📋 Adding headers to worksheet")
                worksheet.update('A1:F1', [expected_headers], value_input_option='USER_ENTERED')
        except Exception as e:
            logger.warning(f"Could not check/update headers: {e}")
            # Try to append headers
            try:
                worksheet.append_row(['Name', 'Phone', 'Time', 'Location', 'Timestamp', 'Status'])
            except:
                pass
        
        # Prepare data for the spreadsheet
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row_data = [
            booking_data['name'],
            booking_data['phone'],
            booking_data['time'],
            booking_data['location'],
            timestamp,
            'Submitted'  # Status column
        ]
        
        # Append the data to the spreadsheet
        logger.info(f"✍️ Saving booking to spreadsheet: {booking_data['name']}")
        try:
            worksheet.append_row(row_data, value_input_option='USER_ENTERED')
            
            # Get the row number for reference
            all_values = worksheet.get_all_values()
            row_number = len(all_values)
            
            logger.info(f"✅ Booking saved successfully! Row: {row_number}")
            
            return jsonify({
                'success': True,
                'message': '✅ Booking submitted successfully!',
                'booking_id': f"BK{timestamp.replace('-', '').replace(':', '').replace(' ', '')}",
                'timestamp': timestamp,
                'row_number': row_number,
                'spreadsheet': spreadsheet_title,
                'service_account': service_email,
                'spreadsheet_url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}'
            }), 200
            
        except Exception as e:
            logger.error(f"❌ Failed to save booking: {e}", exc_info=True)
            return jsonify({
                'error': f'Failed to save booking to spreadsheet: {str(e)}',
                'help': 'Check if the worksheet is writable'
            }), 500
        
    except ValueError as e:
        logger.error(f"Credentials error: {e}")
        return jsonify({
            'error': 'Google Sheets configuration error',
            'details': str(e),
            'help': 'Check your credentials configuration on Render'
        }), 500
        
    except Exception as e:
        logger.error(f"💥 Unexpected error in submit_booking: {e}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'details': str(e),
            'help': 'Check server logs for more information'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for monitoring.
    Returns detailed status information.
    """
    try:
        # Basic info
        status_info = {
            'status': 'healthy',
            'service': 'mineka-booking-api',
            'version': '1.0.0',
            'timestamp': datetime.now().isoformat(),
            'environment': os.getenv('RENDER', 'local'),
            'port': os.getenv('PORT', 'unknown')
        }
        
        # Check configuration
        config_info = {
            'secret_file_exists': os.path.exists(RENDER_SECRETS_PATH),
            'secret_file_path': RENDER_SECRETS_PATH,
            'spreadsheet_id': os.getenv('GOOGLE_SPREADSHEET_ID', 'Not set')
        }
        
        # Test Google Sheets connection
        sheets_status = {
            'status': 'unknown',
            'service_account': 'unknown'
        }
        
        try:
            gc = get_google_sheets_client()
            sheets_status['service_account'] = gc.auth.credentials.service_account_email
            
            # Try to access spreadsheet if ID is configured
            spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
            if spreadsheet_id:
                spreadsheet_id = spreadsheet_id.strip().split('#')[0]
                spreadsheet = gc.open_by_key(spreadsheet_id)
                sheets_status['status'] = 'connected'
                sheets_status['spreadsheet'] = spreadsheet.title
            else:
                sheets_status['status'] = 'no_spreadsheet_id'
                
        except Exception as e:
            sheets_status['status'] = f'error: {str(e)}'
        
        status_info['config'] = config_info
        status_info['google_sheets'] = sheets_status
        
        return jsonify(status_info), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/test-connection', methods=['GET'])
def test_connection():
    """
    Test Google Sheets connection and permissions.
    """
    try:
        gc = get_google_sheets_client()
        
        # Get service account info
        service_email = gc.auth.credentials.service_account_email
        
        # Get spreadsheet ID
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            return jsonify({
                'success': False,
                'error': 'GOOGLE_SPREADSHEET_ID not configured',
                'service_account': service_email
            }), 400
        
        spreadsheet_id = spreadsheet_id.strip().split('#')[0]
        
        # Try to open the spreadsheet
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Get worksheet info
        worksheets = []
        for ws in spreadsheet.worksheets():
            worksheets.append({
                'title': ws.title,
                'row_count': ws.row_count,
                'col_count': ws.col_count
            })
        
        return jsonify({
            'success': True,
            'message': '✅ Successfully connected to Google Sheets!',
            'service_account': service_email,
            'spreadsheet': {
                'id': spreadsheet_id,
                'title': spreadsheet.title,
                'url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}',
                'worksheet_count': len(worksheets),
                'worksheets': worksheets
            },
            'permissions': '✅ Has read/write access'
        }), 200
        
    except gspread.exceptions.SpreadsheetNotFound:
        return jsonify({
            'success': False,
            'error': f'Spreadsheet not found with ID: {spreadsheet_id}',
            'help': 'Check your GOOGLE_SPREADSHEET_ID environment variable'
        }), 404
        
    except gspread.exceptions.APIError as e:
        error_msg = str(e)
        if 'PERMISSION_DENIED' in error_msg.upper():
            return jsonify({
                'success': False,
                'error': 'Permission denied',
                'service_account': service_email if 'service_email' in locals() else 'unknown',
                'solution': f'Share the spreadsheet with the service account email'
            }), 403
        else:
            return jsonify({
                'success': False,
                'error': f'Google Sheets API error: {error_msg}'
            }), 500
            
    except Exception as e:
        logger.error(f"Connection test failed: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Connection failed: {str(e)}'
        }), 500

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """
    Simple test endpoint to verify API is working.
    """
    return jsonify({
        'message': 'Mineka Booking API is running! 🚀',
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'endpoints': {
            'POST /api/booking': 'Submit a booking',
            'GET /api/health': 'Health check',
            'GET /api/test-connection': 'Test Google Sheets connection',
            'GET /api/test': 'This test endpoint'
        },
        'documentation': 'Embed the HTML form in Wix and point it to this API'
    })

@app.route('/api/debug', methods=['GET'])
def debug_info():
    """
    Debug endpoint for troubleshooting.
    """
    return jsonify({
        'environment_variables': {
            'GOOGLE_SPREADSHEET_ID': os.getenv('GOOGLE_SPREADSHEET_ID', 'Not set'),
            'PORT': os.getenv('PORT', 'Not set'),
            'RENDER': os.getenv('RENDER', 'Not set')
        },
        'file_system': {
            'render_secrets_exists': os.path.exists(RENDER_SECRETS_PATH),
            'current_directory': os.getcwd(),
            'files_in_current_dir': os.listdir('.')
        },
        'python_info': {
            'version': os.sys.version,
            'gspread_version': gspread.__version__,
            'flask_version': '3.0.0'
        }
    })

@app.route('/', methods=['GET'])
def index():
    """
    Root endpoint - API information.
    """
    return jsonify({
        'name': 'Mineka Booking API',
        'description': 'Backend API for Mineka booking system that saves to Google Sheets',
        'version': '2.0.0',
        'status': 'operational',
        'deployment': 'Render',
        'author': 'Ashwin',
        'endpoints': [
            {'path': '/', 'method': 'GET', 'description': 'API information'},
            {'path': '/api/booking', 'method': 'POST', 'description': 'Submit booking form'},
            {'path': '/api/health', 'method': 'GET', 'description': 'Health check'},
            {'path': '/api/test-connection', 'method': 'GET', 'description': 'Test Google Sheets'},
            {'path': '/api/test', 'method': 'GET', 'description': 'Simple test endpoint'},
            {'path': '/api/debug', 'method': 'GET', 'description': 'Debug information'}
        ],
        'setup': {
            'credentials': 'Upload credentials.json as Secret File on Render',
            'spreadsheet': 'Set GOOGLE_SPREADSHEET_ID environment variable',
            'sharing': f'Share spreadsheet with service account email'
        },
        'frontend': 'Embed HTML form in Wix with fetch() to this API'
    })

# Gunicorn logging integration
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

if __name__ == '__main__':
    # Configuration validation
    logger.info("🔍 Validating configuration...")
    
    # Check credentials
    if not os.path.exists(RENDER_SECRETS_PATH):
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH', 'credentials.json')
        
        if not creds_json and not os.path.exists(creds_path):
            logger.warning("⚠ No Google credentials found. Set up credentials for production.")
        else:
            logger.info("✓ Google credentials configured")
    else:
        logger.info(f"✓ Found Render secret file: {RENDER_SECRETS_PATH}")
    
    # Check spreadsheet ID
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
    if spreadsheet_id:
        logger.info(f"✓ Spreadsheet ID configured: {spreadsheet_id[:20]}...")
    else:
        logger.warning("⚠ GOOGLE_SPREADSHEET_ID not set. Booking submissions will fail.")
    
    # Start server
    port = int(os.getenv('PORT', 3000))
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    
    logger.info(f"""
    🚀 Starting Mineka Booking API
    ═════════════════════════════════════
    📍 Port: {port}
    🔧 Debug: {debug_mode}
    🌐 Environment: {os.getenv('FLASK_ENV', 'production')}
    ═════════════════════════════════════
    """)
    
    app.run(
        debug=debug_mode,
        host='0.0.0.0',
        port=port,
        use_reloader=debug_mode
    )