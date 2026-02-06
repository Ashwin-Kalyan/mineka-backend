from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import gspread
from google.oauth2.service_account import Credentials
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Google Sheets configuration
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]

def get_google_sheets_client():
    """Initialize Google Sheets client"""
    try:
        # Check for credentials in Render secret file
        secret_path = '/etc/secrets/credentials.json'
        if os.path.exists(secret_path):
            credentials = Credentials.from_service_account_file(secret_path, scopes=SCOPE)
            return gspread.authorize(credentials)
        
        # Fallback to environment variable
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            creds_dict = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
            return gspread.authorize(credentials)
        
        raise ValueError("Google credentials not found")
        
    except Exception as e:
        print(f"Error initializing Google Sheets: {e}")
        raise

@app.route('/api/booking', methods=['POST', 'OPTIONS'])
def submit_booking():
    """Handle booking form submissions"""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'phone', 'time', 'location']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Get Google Sheets client
        gc = get_google_sheets_client()
        
        # Get spreadsheet ID
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            return jsonify({'error': 'Google Spreadsheet ID not configured'}), 500
        
        # Clean spreadsheet ID
        spreadsheet_id = spreadsheet_id.split('#')[0].strip()
        
        # Open spreadsheet
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Get or create worksheet
        try:
            worksheet = spreadsheet.worksheet('Bookings')
        except:
            worksheet = spreadsheet.sheet1
        
        # Check if headers exist
        headers = worksheet.row_values(1)
        if not headers or headers[0] != 'Name':
            worksheet.append_row(['Name', 'Phone', 'Time', 'Location', 'Timestamp'])
        
        # Append the row
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        row_data = [
            data['name'],
            data['phone'],
            data['time'],
            data['location'],
            timestamp
        ]
        
        worksheet.append_row(row_data)
        
        return jsonify({
            'success': True,
            'message': 'Booking submitted successfully'
        }), 200
        
    except Exception as e:
        print(f"Error processing booking: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contact', methods=['POST', 'OPTIONS'])
def submit_contact():
    """Handle contact form submissions"""
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.get_json() or {}

        # Validate required fields (common contact form fields)
        required_fields = ['name', 'email', 'message']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400

        gc = get_google_sheets_client()
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID')
        if not spreadsheet_id:
            return jsonify({'error': 'Google Spreadsheet ID not configured'}), 500

        spreadsheet_id = spreadsheet_id.split('#')[0].strip()
        spreadsheet = gc.open_by_key(spreadsheet_id)

        try:
            worksheet = spreadsheet.worksheet('Contact')
        except Exception:
            worksheet = spreadsheet.add_worksheet(title='Contact', rows=1000, cols=5)

        headers = worksheet.row_values(1)
        if not headers or headers[0] != 'Name':
            worksheet.append_row(['Name', 'Email', 'Message', 'Timestamp'])

        from datetime import datetime
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row_data = [
            data['name'],
            data['email'],
            data['message'],
            timestamp,
        ]
        worksheet.append_row(row_data)

        return jsonify({
            'success': True,
            'message': 'Contact form submitted successfully',
        }), 200

    except Exception as e:
        print(f"Error processing contact: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 3000))
    app.run(host='0.0.0.0', port=port)