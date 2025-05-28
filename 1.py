import json
import boto3
import mysql.connector
import base64
import requests
import os
from datetime import datetime
import logging

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
DB_HOST = os.environ['DB_HOST']
DB_NAME = os.environ['DB_NAME'] 
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
S3_BUCKET = os.environ['S3_BUCKET']

# AWS client
s3_client = boto3.client('s3')

def get_db_connection():
    """Create database connection"""
    try:
        connection = mysql.connector.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            autocommit=True,
            connection_timeout=10
        )
        return connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise e

def update_annotation_status(filename, status, annotation=None, error_message=None):
    """Update annotation status in database"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        if status == 'completed':
            query = """
                UPDATE images 
                SET annotation_status = %s, 
                    annotation = %s, 
                    annotation_generated_at = %s 
                WHERE filename = %s
            """
            cursor.execute(query, (status, annotation, datetime.now(), filename))
        else:
            query = """
                UPDATE images 
                SET annotation_status = %s, 
                    annotation_error = %s 
                WHERE filename = %s
            """
            cursor.execute(query, (status, error_message, filename))
        
        connection.close()
        logger.info(f"Updated annotation status for {filename}: {status}")
        
    except Exception as e:
        logger.error(f"Database update error: {e}")
        raise e

def generate_caption_with_gemini(image_data):
    """Generate image description using Google Gemini API"""
    try:
        # Gemini API endpoint
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        
        # Encode image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Request payload
        payload = {
            "contents": [{
                "parts": [
                    {
                        "text": "Please provide a detailed description of this image. Focus on the main subjects, setting, colors, and overall composition."
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
        
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        # Extract description
        if 'candidates' in result and len(result['candidates']) > 0:
            caption = result['candidates'][0]['content']['parts'][0]['text']
            return caption.strip()
        else:
            raise Exception("Gemini API did not return a valid description")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API request error: {e}")
        raise Exception(f"Gemini API error: {str(e)}")
    except Exception as e:
        logger.error(f"Description generation error: {e}")
        raise e

def lambda_handler(event, context):
    """Main Lambda handler function"""
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Process each S3 record
        for record in event['Records']:
            # Extract S3 information
            bucket = record['s3']['bucket']['name']
            key = record['s3']['object']['key']
            
            # Only process files in uploads/ folder
            if not key.startswith('uploads/'):
                logger.info(f"Skipping non-upload file: {key}")
                continue
            
            # Extract filename
            filename = key.split('/')[-1]
            
            logger.info(f"Processing image annotation: {filename}")
            
            # Update status to processing
            update_annotation_status(filename, 'processing')
            
            try:
                # Download image from S3
                response = s3_client.get_object(Bucket=bucket, Key=key)
                image_data = response['Body'].read()
                
                logger.info(f"Downloaded image: {len(image_data)} bytes")
                
                # Generate description using Gemini
                caption = generate_caption_with_gemini(image_data)
                
                logger.info(f"Generated description: {caption[:100]}...")
                
                # Update database to completed status
                update_annotation_status(filename, 'completed', annotation=caption)
                
                logger.info(f"✅ Successfully processed annotation: {filename}")
                
            except Exception as e:
                logger.error(f"❌ Processing error for {filename}: {e}")
                update_annotation_status(filename, 'failed', error_message=str(e))
                
    except Exception as e:
        logger.error(f"❌ Lambda execution error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Annotation processing completed'
        })
    }