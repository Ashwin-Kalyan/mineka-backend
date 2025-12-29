from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import logging
import json

# Configure logging for gunicorn
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (for local development only)
# On Render, we use environment variables from dashboard
if os.path.exists('.env'):
    load_dotenv()
    logger.info("✓ Loaded .env file for local development")
else:
    logger.info("ℹ Running on Render - using environment variables from dashboard")

app = Flask(__name__)

# Configure CORS - allow all origins for simplicity
# You can restrict this to your Wix domain in production
CORS(app)
logger.info("CORS configured for all origins")

# Google Sheets configuration
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]

# Define the Render secret file path
RENDER_SECRETS_PATH = '/etc/secrets/credentials.json'

def get_google_sheets_client():
    """Initialize and return Google Sheets client for Render"""
    try:
        # Priority 1: Check for Render secret file (your specific case)
        if os.path.exists(RENDER_SECRETS_PATH):
            logger.info(f"✓ Using credentials from Render secret file: {RENDER_SECRETS_PATH}")
            
            # Verify the file is readable and contains valid JSON
            try:
                with open(RENDER_SECRETS_PATH, 'r') as f:
                    creds_content = f.read()
                    # Validate JSON
                    json.loads(creds_content)
                
                credentials = Credentials.from_service_account_file(RENDER_SECRETS_PATH, scopes=SCOPE)
                client = gspread.authorize(credentials)
                
                # Test the credentials by getting the email
                service_account_email = credentials.service_account_email
                logger.info(f"✓ Authenticated as service account: {service_account_email}")
                
                return client
                
            except json.JSONDecodeError as e:
                logger.error(f"✗ Invalid JSON in secret file: {e}")
                raise ValueError(f"Invalid JSON in {RENDER_SECRETS_PATH}")
            except Exception as e:
                logger.error(f"✗ Error reading secret file: {e}")
                raise
        
        # Priority 2: Check for GOOGLE_CREDENTIALS_JSON environment variable (fallback)
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            logger.info("✓ Using GOOGLE_CREDENTIALS_JSON from environment")
            try:
                creds_dict = json.loads(creds_json)
                credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
                client = gspread.authorize(credentials)
                logger.info(f"✓ Authenticated as: {credentials.service_account_email}")
                return client
            except json.JSONDecodeError as e:
                logger.error(f"✗ Invalid JSON in GOOGLE_CREDENTIALS_JSON: {e}")
                raise ValueError("Invalid JSON in GOOGLE_CREDENTIALS_JSON")
        
        # Priority 3: Check for GOOGLE_CREDENTIALS_PATH (local development)
        creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH', './credentials.json')
        if os.path.exists(creds_path):
            logger.info(f"✓ Using local credentials file: {creds_path}")
            credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPE)
            client = gspread.authorize(credentials)
            logger.info(f"✓ Authenticated as: {credentials.service_account_email}")
            return client
        
        # No credentials found
        error_msg = (
            "❌ Google credentials not found!\n\n"
            "On Render:\n"
            f"1. Upload your credentials.json to: {RENDER_SECRETS_PATH}\n"
            "   OR set GOOGLE_CREDENTIALS_JSON environment variable\n\n"
            "Locally:\n"
            "1. Create a .env file with GOOGLE_CREDENTIALS_PATH\n"
            "2. Or place credentials.json in the project root\n"
        )
        logger.error(error_msg)
        raise ValueError("Google credentials configuration missing")
    
    except Exception as e:
        logger.error(f"✗ Failed to initialize Google Sheets client: {e}", exc_info=True)
        raise

@app.route('/api/booking', methods=['POST', 'OPTIONS'])
def submit_booking():
    """Handle booking form submissions from Wix"""
    # Handle preflight requests for CORS
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        if not data:
            logger.error("No JSON data received in request")
            return jsonify({'error': 'No JSON data received'}), 400
        
        logger.info(f"📥 Received booking request: {data}")
        
        # Validate required fields
        required_fields = ['name', 'phone', 'time', 'location']
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            logger.warning(f"Missing fields: {missing_fields}")
            return jsonify({'error': f'Missing required fields: {", ".join(missing_fields)}'}), 400
        
        # Get Google Sheets client
        logger.info("🔐 Initializing Google Sheets client...")
        gc = get_google_sheets_client()
        
        # Get spreadsheet ID from environment
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            logger.error("GOOGLE_SPREADSHEET_ID not set in environment")
            return jsonify({'error': 'Google Spreadsheet ID not configured'}), 500
        
        # Clean the spreadsheet ID
        spreadsheet_id = spreadsheet_id.split('#')[0].strip()
        logger.info(f"📊 Using spreadsheet ID: {spreadsheet_id}")
        
        try:
            logger.info(f"🔍 Opening spreadsheet...")
            spreadsheet = gc.open_by_key(spreadsheet_id)
            logger.info("✅ Successfully opened spreadsheet")
            
            # Get the service account email for sharing instructions
            credentials = gc.auth.credentials
            service_email = credentials.service_account_email
            logger.info(f"👤 Service account: {service_email}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Failed to open spreadsheet: {error_msg}")
            
            # Try to get service email from credentials
            try:
                credentials = gc.auth.credentials
                service_email = credentials.service_account_email
            except:
                service_email = "mineka-google-sheets@nortiq-mineka-hokkaido.iam.gserviceaccount.com"
            
            # User-friendly error messages
            if 'API has not been used' in error_msg or 'SERVICE_DISABLED' in error_msg:
                return jsonify({
                    'error': 'Google Sheets API is not enabled. Please enable it:\n\n'
                            '1. Go to: https://console.cloud.google.com/apis/library/sheets.googleapis.com\n'
                            '2. Select your project (nortiq-mineka-hokkaido)\n'
                            '3. Click "Enable"\n'
                            '4. Also enable Google Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com'
                }), 403
            
            if 'Permission' in error_msg or 'permission' in error_msg or '403' in error_msg:
                share_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                return jsonify({
                    'error': f'Permission denied. Please share your Google Spreadsheet with this email:\n\n'
                            f'📧 {service_email}\n\n'
                            f'Steps:\n'
                            f'1. Open your spreadsheet: {share_url}\n'
                            f'2. Click "Share" button (top-right)\n'
                            f'3. Add email: {service_email}\n'
                            f'4. Set as "Editor"\n'
                            f'5. Click "Send"'
                }), 403
            
            if 'not found' in error_msg.lower():
                return jsonify({
                    'error': f'Spreadsheet not found. Check your GOOGLE_SPREADSHEET_ID:\n\n{spreadsheet_id}'
                }), 404
            
            return jsonify({'error': f'Failed to access spreadsheet: {error_msg}'}), 500
        
        # Use or create 'Bookings' worksheet
        try:
            worksheet = spreadsheet.worksheet('Bookings')
            logger.info("📝 Using existing 'Bookings' worksheet")
        except gspread.exceptions.WorksheetNotFound:
            try:
                # Try to use the first sheet
                worksheet = spreadsheet.get_worksheet(0)
                if worksheet.title == 'Sheet1':
                    worksheet.update_title('Bookings')
                logger.info("📝 Using first worksheet (renamed to 'Bookings')")
            except Exception as e:
                # Create a new worksheet
                logger.info("📝 Creating new 'Bookings' worksheet")
                worksheet = spreadsheet.add_worksheet(title='Bookings', rows=1000, cols=10)
        
        # Check and ensure headers exist
        try:
            existing_headers = worksheet.row_values(1)
            expected_headers = ['Name', 'Phone Number', 'When', 'Where', 'Timestamp', 'IP Address']
            
            if not existing_headers or existing_headers[0] != 'Name':
                logger.info("📋 Adding headers to worksheet")
                worksheet.update('A1:F1', [expected_headers])
        except Exception as header_error:
            logger.warning(f"Could not check/update headers: {header_error}")
            # Try to add headers anyway
            try:
                worksheet.append_row(expected_headers)
            except:
                pass
        
        # Prepare row data with timestamp and IP
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ip_address = request.remote_addr
        row_data = [
            data['name'],
            data['phone'],
            data['time'],
            data['location'],
            timestamp,
            ip_address
        ]
        
        # Append the row
        logger.info(f"✍️ Appending row: {row_data}")
        try:
            worksheet.append_row(row_data, value_input_option='USER_ENTERED')
            logger.info("✅ Successfully saved booking to Google Sheets")
            
            # Get the row number for reference
            all_values = worksheet.get_all_values()
            row_number = len(all_values)
            
            return jsonify({
                'success': True,
                'message': 'Booking submitted successfully! ✅',
                'timestamp': timestamp,
                'row_number': row_number,
                'spreadsheet_url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}'
            }), 200
            
        except Exception as append_error:
            logger.error(f"❌ Error appending row: {append_error}", exc_info=True)
            return jsonify({'error': f'Failed to save booking: {str(append_error)}'}), 500
        
    except Exception as e:
        logger.error(f"💥 Unexpected error in submit_booking: {str(e)}", exc_info=True)
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render monitoring"""
    try:
        # Check if secret file exists
        secret_file_exists = os.path.exists(RENDER_SECRETS_PATH)
        
        # Check spreadsheet ID
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', 'Not set')
        has_spreadsheet_id = bool(spreadsheet_id and spreadsheet_id.strip())
        
        # Try to initialize Google Sheets client (but don't fail if it doesn't work)
        sheets_status = 'unknown'
        service_email = 'unknown'
        
        try:
            gc = get_google_sheets_client()
            credentials = gc.auth.credentials
            service_email = credentials.service_account_email
            sheets_status = 'connected'
        except Exception as e:
            sheets_status = f'error: {str(e)[:100]}'
        
        return jsonify({
            'status': 'healthy',
            'service': 'mineka-booking-api',
            'environment': os.getenv('RENDER', 'local'),
            'timestamp': datetime.now().isoformat(),
            'config': {
                'secret_file_exists': secret_file_exists,
                'secret_file_path': RENDER_SECRETS_PATH,
                'spreadsheet_id_set': has_spreadsheet_id,
                'google_sheets_status': sheets_status,
                'service_account_email': service_email
            }
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'service': 'mineka-booking-api',
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/config', methods=['GET'])
def config_check():
    """Check configuration without connecting to Google"""
    secret_file_exists = os.path.exists(RENDER_SECRETS_PATH)
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', 'Not set')
    
    # Check if secret file has valid JSON
    secret_valid = False
    if secret_file_exists:
        try:
            with open(RENDER_SECRETS_PATH, 'r') as f:
                content = f.read()
                creds = json.loads(content)
                secret_valid = True
                service_email = creds.get('client_email', 'Unknown')
        except:
            service_email = 'Invalid JSON'
    else:
        service_email = 'File not found'
    
    return jsonify({
        'render_secrets_file': {
            'path': RENDER_SECRETS_PATH,
            'exists': secret_file_exists,
            'valid': secret_valid,
            'service_email': service_email
        },
        'spreadsheet_id': spreadsheet_id,
        'environment': os.getenv('RENDER_ENV', 'unknown'),
        'port': os.getenv('PORT', 'Not set')
    })

@app.route('/api/test-connection', methods=['GET'])
def test_connection():
    """Test Google Sheets connection"""
    try:
        gc = get_google_sheets_client()
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        
        if not spreadsheet_id:
            return jsonify({'error': 'No spreadsheet ID configured'}), 400
        
        spreadsheet_id = spreadsheet_id.split('#')[0].strip()
        
        # Try to open the spreadsheet
        spreadsheet = gc.open_by_key(spreadsheet_id)
        credentials = gc.auth.credentials
        
        return jsonify({
            'success': True,
            'service_account': credentials.service_account_email,
            'spreadsheet_title': spreadsheet.title,
            'spreadsheet_id': spreadsheet_id,
            'sheets': [ws.title for ws in spreadsheet.worksheets()],
            'message': '✅ Connection successful!'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '❌ Connection failed'
        }), 500

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint"""
    return jsonify({
        'message': 'Mineka Booking API is running! 🚀',
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'deployment': 'Render',
        'secrets_path': RENDER_SECRETS_PATH,
        'secrets_exists': os.path.exists(RENDER_SECRETS_PATH),
        'endpoints': {
            'POST /api/booking': 'Submit booking',
            'GET /api/health': 'Health check',
            'GET /api/config': 'Configuration check',
            'GET /api/test-connection': 'Test Google Sheets connection'
        }
    })

@app.route('/')
def index():
    """Root endpoint with API information"""
    return jsonify({
        'name': 'Mineka Booking API',
        'description': 'Backend API for Mineka booking system connected to Google Sheets',
        'version': '1.0.0',
        'deployment': 'Render',
        'secrets_config': 'Using /etc/secrets/credentials.json',
        'documentation': 'See the /api/test endpoint for available endpoints',
        'health_check': '/api/health',
        'repo': 'https://github.com/yourusername/mineka-booking-api'
    })

def validate_env_config():
    """Validate configuration on startup"""
    logger.info("🔍 Validating configuration...")
    
    # Check for secrets file
    if os.path.exists(RENDER_SECRETS_PATH):
        logger.info(f"✅ Found secrets file at: {RENDER_SECRETS_PATH}")
        
        # Validate JSON
        try:
            with open(RENDER_SECRETS_PATH, 'r') as f:
                creds = json.load(f)
                email = creds.get('client_email', 'Unknown')
                logger.info(f"✅ Valid JSON, service account: {email}")
        except json.JSONDecodeError:
            logger.error(f"❌ Invalid JSON in {RENDER_SECRETS_PATH}")
            return False
        except Exception as e:
            logger.error(f"❌ Error reading secrets file: {e}")
            return False
    else:
        logger.warning(f"⚠ Secrets file not found at: {RENDER_SECRETS_PATH}")
        logger.info("ℹ Will try environment variable GOOGLE_CREDENTIALS_JSON instead")
    
    # Check for spreadsheet ID
    spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
    if spreadsheet_id:
        logger.info(f"✅ Spreadsheet ID is set: {spreadsheet_id[:15]}...")
    else:
        logger.error("❌ GOOGLE_SPREADSHEET_ID is not set")
        return False
    
    logger.info("✅ Configuration validation complete")
    return True

# Gunicorn logging integration
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

if __name__ == '__main__':
    # Validate configuration
    if not validate_env_config():
        logger.error("❌ Server startup aborted due to configuration errors")
        exit(1)
    
    port = int(os.getenv('PORT', 3000))
    
    logger.info(f"""
    🚀 Starting Mineka Booking API
    ═════════════════════════════════════
    📍 Port: {port}
    🔐 Secrets: {RENDER_SECRETS_PATH}
    📊 Spreadsheet: {os.getenv('GOOGLE_SPREADSHEET_ID', 'Not set')[:20]}...
    🌐 Environment: {os.getenv('RENDER', 'Local Development')}
    ═════════════════════════════════════
    """)
    
    # Development server (not used on Render)
    app.run(debug=False, host='0.0.0.0', port=port)