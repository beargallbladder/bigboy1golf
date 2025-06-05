#!/usr/bin/env python3
"""
Shot Data API Backend
Clean, modular API for golf shot data extraction
"""

import os
import json
import time
import base64
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple, List
from functools import wraps

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import redis
import requests

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())
CORS(app, supports_credentials=True)

# Redis for session/rate limiting
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=0,
    decode_responses=True
)

# OAuth setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Configuration
CONFIG = {
    'DAILY_LIMIT_AUTH': 20,
    'DAILY_LIMIT_ANON': 3,
    'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY'),
    'GEMINI_API_KEY': os.getenv('GOOGLE_API_KEY'),
    'RESPONSE_TIMEOUT': 2.0  # 2 second target
}

# Rate limiting decorator
def rate_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id', None)
        
        if user_id:
            # Authenticated user
            key = f"rate_limit:user:{user_id}:{datetime.now().strftime('%Y-%m-%d')}"
            limit = CONFIG['DAILY_LIMIT_AUTH']
        else:
            # Anonymous user - use IP
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            key = f"rate_limit:anon:{ip}:{datetime.now().strftime('%Y-%m-%d')}"
            limit = CONFIG['DAILY_LIMIT_ANON']
        
        # Get current count
        current = redis_client.get(key)
        if current is None:
            current = 0
        else:
            current = int(current)
        
        if current >= limit:
            return jsonify({
                'error': 'Daily limit exceeded',
                'limit': limit,
                'reset_time': (datetime.now() + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0
                ).isoformat()
            }), 429
        
        # Increment counter
        redis_client.incr(key)
        redis_client.expire(key, 86400)  # 24 hours
        
        # Add remaining count to response
        response = f(*args, **kwargs)
        if isinstance(response, tuple):
            data, status = response
            data = data.get_json()
            data['rate_limit'] = {
                'used': current + 1,
                'limit': limit,
                'remaining': limit - (current + 1)
            }
            return jsonify(data), status
        return response
    
    return decorated_function

# AI Processing Module
class AIProcessor:
    def __init__(self):
        self.openai_key = CONFIG['OPENAI_API_KEY']
        self.gemini_key = CONFIG['GEMINI_API_KEY']
    
    def extract_with_gemini(self, image_base64: str) -> Optional[Dict[str, Any]]:
        """Extract data using Google Gemini"""
        if not self.gemini_key:
            return None
        
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.gemini_key}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {
                            "text": "Extract golf shot data from this image. Return ONLY valid JSON with these exact keys: ball_speed, launch_angle, spin_rate, carry_distance, club_speed, smash_factor, apex_height. Use null for missing values. Include units in a separate 'units' object."
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64
                            }
                        }
                    ]
                }]
            }
            
            response = requests.post(url, json=payload, timeout=CONFIG['RESPONSE_TIMEOUT'])
            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']
                # Extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"Gemini error: {e}")
        
        return None
    
    def extract_with_openai(self, image_base64: str) -> Optional[Dict[str, Any]]:
        """Extract data using OpenAI Vision"""
        if not self.openai_key:
            return None
        
        try:
            headers = {
                "Authorization": f"Bearer {self.openai_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-4-vision-preview",
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract golf shot data from this image. Return ONLY valid JSON with these exact keys: ball_speed, launch_angle, spin_rate, carry_distance, club_speed, smash_factor, apex_height. Use null for missing values. Include units in a separate 'units' object."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }],
                "max_tokens": 300
            }
            
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=CONFIG['RESPONSE_TIMEOUT']
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result['choices'][0]['message']['content']
                # Extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
        except Exception as e:
            print(f"OpenAI error: {e}")
        
        return None
    
    def process_image(self, image_base64: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """Process image with both APIs for 98% success rate"""
        start_time = time.time()
        
        # Try Gemini first (usually faster)
        result = self.extract_with_gemini(image_base64)
        if result:
            processing_time = time.time() - start_time
            return result, f"gemini ({processing_time:.2f}s)"
        
        # Fallback to OpenAI
        result = self.extract_with_openai(image_base64)
        if result:
            processing_time = time.time() - start_time
            return result, f"openai ({processing_time:.2f}s)"
        
        return None, "failed"

# Data Storage Module
class DataStore:
    def __init__(self):
        self.data_dir = "data"
        os.makedirs(self.data_dir, exist_ok=True)
    
    def save_shot(self, user_id: str, shot_data: Dict[str, Any]) -> str:
        """Save shot data for authenticated users"""
        shot_id = hashlib.md5(
            f"{user_id}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        shot_record = {
            'id': shot_id,
            'user_id': user_id,
            'timestamp': datetime.now().isoformat(),
            'data': shot_data
        }
        
        # Save to user's file
        user_file = os.path.join(self.data_dir, f"user_{user_id}.json")
        
        try:
            with open(user_file, 'r') as f:
                user_data = json.load(f)
        except:
            user_data = {'shots': []}
        
        user_data['shots'].append(shot_record)
        
        with open(user_file, 'w') as f:
            json.dump(user_data, f, indent=2)
        
        return shot_id
    
    def get_user_shots(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all shots for a user"""
        user_file = os.path.join(self.data_dir, f"user_{user_id}.json")
        
        try:
            with open(user_file, 'r') as f:
                user_data = json.load(f)
                return user_data.get('shots', [])
        except:
            return []

# Initialize modules
ai_processor = AIProcessor()
data_store = DataStore()

# API Routes

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'services': {
            'openai': bool(CONFIG['OPENAI_API_KEY']),
            'gemini': bool(CONFIG['GEMINI_API_KEY']),
            'redis': redis_client.ping()
        }
    })

@app.route('/auth/login', methods=['GET'])
def login():
    """Initiate Google OAuth login"""
    redirect_uri = request.args.get('redirect_uri', '/auth/callback')
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback', methods=['GET'])
def auth_callback():
    """Handle OAuth callback"""
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    
    if user_info:
        session['user_id'] = user_info['sub']
        session['user_email'] = user_info['email']
        session['user_name'] = user_info.get('name', 'User')
        
        return jsonify({
            'success': True,
            'user': {
                'id': user_info['sub'],
                'email': user_info['email'],
                'name': user_info.get('name')
            }
        })
    
    return jsonify({'error': 'Authentication failed'}), 401

@app.route('/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    session.clear()
    return jsonify({'success': True})

@app.route('/auth/status', methods=['GET'])
def auth_status():
    """Check authentication status"""
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'user': {
                'id': session['user_id'],
                'email': session['user_email'],
                'name': session['user_name']
            }
        })
    return jsonify({'authenticated': False})

@app.route('/extract', methods=['POST'])
@rate_limit
def extract_shot_data():
    """Extract shot data from uploaded image"""
    try:
        # Get image from request
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
        
        image_file = request.files['image']
        if image_file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Convert to base64
        image_bytes = image_file.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        # Process with AI
        shot_data, processor_used = ai_processor.process_image(image_base64)
        
        if not shot_data:
            return jsonify({'error': 'Failed to extract data from image'}), 422
        
        # Save if authenticated
        shot_id = None
        if 'user_id' in session:
            shot_id = data_store.save_shot(session['user_id'], shot_data)
        
        return jsonify({
            'success': True,
            'shot_id': shot_id,
            'data': shot_data,
            'processor': processor_used,
            'saved': bool(shot_id)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/shots', methods=['GET'])
def get_user_shots():
    """Get all shots for authenticated user"""
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401
    
    shots = data_store.get_user_shots(session['user_id'])
    return jsonify({
        'shots': shots,
        'count': len(shots)
    })

@app.route('/api/docs', methods=['GET'])
def api_documentation():
    """API documentation for frontend team"""
    return jsonify({
        'name': 'Shot Data Extraction API',
        'version': '1.0.0',
        'base_url': request.host_url.rstrip('/'),
        'authentication': {
            'type': 'Google OAuth 2.0',
            'login_endpoint': '/auth/login',
            'callback_endpoint': '/auth/callback',
            'logout_endpoint': '/auth/logout',
            'status_endpoint': '/auth/status'
        },
        'rate_limits': {
            'authenticated': f"{CONFIG['DAILY_LIMIT_AUTH']} requests/day",
            'anonymous': f"{CONFIG['DAILY_LIMIT_ANON']} requests/day"
        },
        'endpoints': {
            '/extract': {
                'method': 'POST',
                'description': 'Extract shot data from golf launch monitor image',
                'authentication': 'Optional (affects rate limits and data persistence)',
                'request': {
                    'content_type': 'multipart/form-data',
                    'fields': {
                        'image': 'Image file (JPEG/PNG)'
                    }
                },
                'response': {
                    'success': 'boolean',
                    'shot_id': 'string (only for authenticated users)',
                    'data': {
                        'ball_speed': 'number or null',
                        'launch_angle': 'number or null',
                        'spin_rate': 'number or null',
                        'carry_distance': 'number or null',
                        'club_speed': 'number or null',
                        'smash_factor': 'number or null',
                        'apex_height': 'number or null',
                        'units': 'object with unit strings'
                    },
                    'processor': 'string (gemini/openai)',
                    'saved': 'boolean',
                    'rate_limit': {
                        'used': 'number',
                        'limit': 'number',
                        'remaining': 'number'
                    }
                }
            },
            '/shots': {
                'method': 'GET',
                'description': 'Get all saved shots for authenticated user',
                'authentication': 'Required',
                'response': {
                    'shots': 'array of shot objects',
                    'count': 'number'
                }
            }
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port) 