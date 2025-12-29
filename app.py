from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# Load environment variables from .env file
# This will look for .env in the current directory and parent directories
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"✓ Loaded environment variables from {env_path}")
else:
    # Try loading from current directory (for when running from different locations)
    load_dotenv()
    if not os.path.exists('.env'):
        print("⚠ Warning: .env file not found. Make sure to create one with your configuration.")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Google Sheets configuration
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

def get_google_sheets_client():
    """Initialize and return Google Sheets client"""
    import json
    
    # Try to get credentials from file path first (preferred method)
    creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
    if creds_path:
        if not os.path.exists(creds_path):
            raise FileNotFoundError(f"Credentials file not found: {creds_path}")
        credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPE)
        return gspread.authorize(credentials)
    
    # Fallback to JSON string from environment variable
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        creds_dict = json.loads(creds_json)
        credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        return gspread.authorize(credentials)
    
    raise ValueError(
        "Google credentials not found. Please set either GOOGLE_CREDENTIALS_PATH "
        "(path to JSON file) or GOOGLE_CREDENTIALS_JSON (JSON string) in your .env file"
    )

@app.route('/api/booking', methods=['POST'])
def submit_booking():
    """Handle booking form submissions"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'phone', 'time', 'location']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Get Google Sheets client
        gc = get_google_sheets_client()
        
        # Open the spreadsheet (use the spreadsheet ID from .env)
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            return jsonify({'error': 'Google Spreadsheet ID not configured'}), 500
        
        # Remove any fragment identifier (#gid=0) from the spreadsheet ID
        spreadsheet_id = spreadsheet_id.split('#')[0].strip()
        
        try:
            spreadsheet = gc.open_by_key(spreadsheet_id)
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            # Get the service account email for better error message
            try:
                import json
                creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
                if creds_path and os.path.exists(creds_path):
                    with open(creds_path, 'r') as f:
                        creds_data = json.load(f)
                        service_email = creds_data.get('client_email', 'your service account email')
                else:
                    service_email = 'mineka-google-sheets@nortiq-mineka-hokkaido.iam.gserviceaccount.com'
            except:
                service_email = 'mineka-google-sheets@nortiq-mineka-hokkaido.iam.gserviceaccount.com'
            
            # Check if it's an API not enabled error
            if 'API has not been used' in error_msg or 'SERVICE_DISABLED' in error_msg or 'sheets.googleapis.com' in error_msg:
                return jsonify({
                    'error': 'Google Sheets API is not enabled. Please enable it:\n\n1. Go to: https://console.cloud.google.com/apis/library/sheets.googleapis.com\n2. Select your project (nortiq-mineka-hokkaido)\n3. Click "Enable"\n4. Wait a few minutes for it to activate\n5. Also enable Google Drive API: https://console.cloud.google.com/apis/library/drive.googleapis.com'
                }), 403
            
            if 'Permission' in error_msg or 'permission' in error_msg or '403' in error_msg or error_type == 'PermissionError':
                return jsonify({
                    'error': f'Permission denied. Please share your Google Spreadsheet with this email: {service_email}\n\nSteps:\n1. Open your Google Spreadsheet\n2. Click "Share" button\n3. Add this email: {service_email}\n4. Give it "Editor" access\n5. Click "Send"'
                }), 403
            raise
        
        # Use the first worksheet (Sheet1) or create Bookings if it doesn't exist
        try:
            worksheet = spreadsheet.worksheet('Bookings')
        except gspread.exceptions.WorksheetNotFound:
            # Try to use the first sheet if Bookings doesn't exist
            try:
                worksheet = spreadsheet.sheet1  # Get the first sheet
            except:
                # Create a new worksheet if no sheets exist
                worksheet = spreadsheet.add_worksheet(title='Bookings', rows=1000, cols=10)
        
        # Check if headers exist, if not add them
        try:
            existing_headers = worksheet.row_values(1)
            if not existing_headers or len(existing_headers) == 0 or existing_headers[0] != 'Name':
                # Add headers if they don't exist or are wrong
                if existing_headers and len(existing_headers) > 0:
                    # Headers exist but wrong, update them
                    worksheet.update('A1:D1', [['Name', 'Phone Number', 'When', 'Where']])
                else:
                    # No headers, add them
                    worksheet.append_row(['Name', 'Phone Number', 'When', 'Where'])
        except Exception as header_error:
            print(f"Warning: Could not check/update headers: {str(header_error)}")
            # Try to add headers anyway
            try:
                worksheet.append_row(['Name', 'Phone Number', 'When', 'Where'])
            except:
                pass
        
        # Prepare the row data (matching the column order: Name, Phone Number, When, Where)
        row_data = [
            data['name'],
            data['phone'],
            data['time'],
            data['location']
        ]
        
        # Append the row to the spreadsheet
        try:
            worksheet.append_row(row_data, value_input_option='USER_ENTERED')
            print(f"✓ Successfully appended row to spreadsheet: {row_data}")
        except Exception as append_error:
            print(f"✗ Error appending row: {str(append_error)}")
            import traceback
            traceback.print_exc()
            raise
        
        return jsonify({
            'success': True,
            'message': 'Booking submitted successfully'
        }), 200
        
    except Exception as e:
        import traceback
        error_msg = str(e) if str(e) else f"Unknown error: {type(e).__name__}"
        print(f"Error processing booking: {error_msg}")
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': error_msg}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

def validate_env_config():
    """Validate that required environment variables are set"""
    errors = []
    
    # Check for credentials (either path or JSON)
    creds_path = os.getenv('GOOGLE_CREDENTIALS_PATH')
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    
    if not creds_path and not creds_json:
        errors.append("Missing GOOGLE_CREDENTIALS_PATH or GOOGLE_CREDENTIALS_JSON")
    elif creds_path and not os.path.exists(creds_path):
        errors.append(f"Credentials file not found: {creds_path}")
    
    # Check for spreadsheet ID
    if not os.getenv('GOOGLE_SPREADSHEET_ID'):
        errors.append("Missing GOOGLE_SPREADSHEET_ID")
    
    if errors:
        print("\n❌ Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
        print("\nPlease check your .env file and ensure all required variables are set.")
        print("See README.md for setup instructions.\n")
        return False
    
    print("✓ Environment configuration validated")
    return True

if __name__ == '__main__':
    # Validate configuration before starting
    if not validate_env_config():
        print("Server not started due to configuration errors.")
        exit(1)
    
    port = int(os.getenv('PORT', 3000))
    print(f"🚀 Starting server on http://0.0.0.0:{port}")
    app.run(debug=True, host='0.0.0.0', port=port)

