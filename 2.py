import json
import boto3
import mysql.connector
import os
from PIL import Image
from io import BytesIO
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
S3_BUCKET = os.environ['S3_BUCKET']

# Thumbnail settings
THUMBNAIL_SIZE = (200, 200)
THUMBNAIL_QUALITY = 85

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

def update_thumbnail_status(filename, status, thumbnail_path=None, thumbnail_size=None, error_message=None):
    """Update thumbnail status in database"""
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        
        if status == 'completed':
            query = """
                UPDATE images 
                SET thumbnail_status = %s, 
                    thumbnail_generated = %s,
                    thumbnail_path = %s,
                    thumbnail_size = %s,
                    thumbnail_generated_at = %s 
                WHERE filename = %s
            """
            cursor.execute(query, (status, True, thumbnail_path, thumbnail_size, datetime.now(), filename))
        else:
            query = """
                UPDATE images 
                SET thumbnail_status = %s, 
                    thumbnail_error = %s 
                WHERE filename = %s
            """
            cursor.execute(query, (status, error_message, filename))
        
        connection.close()
        logger.info(f"Updated thumbnail status for {filename}: {status}")
        
    except Exception as e:
        logger.error(f"Database update error: {e}")
        raise e

def generate_thumbnail(image_data):
    """Generate thumbnail"""
    try:
        # Open image
        image = Image.open(BytesIO(image_data))
        
        # Convert to RGB (JPEG compatibility)
        if image.mode in ('RGBA', 'LA', 'P'):
            # Convert to RGB for JPEG compatibility
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image)
            image = background
        
        # Create thumbnail (maintain aspect ratio)
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        
        # Save to byte buffer
        thumbnail_buffer = BytesIO()
        image.save(thumbnail_buffer, format='JPEG', quality=THUMBNAIL_QUALITY, optimize=True)
        thumbnail_data = thumbnail_buffer.getvalue()
        
        return thumbnail_data, len(thumbnail_data)
        
    except Exception as e:
        logger.error(f"Thumbnail generation error: {e}")
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
            
            # Skip files that are already thumbnails
            if key.startswith('thumbnails/'):
                logger.info(f"Skipping thumbnail file: {key}")
                continue
            
            # Extract filename
            filename = key.split('/')[-1]
            
            logger.info(f"Processing thumbnail: {filename}")
            
            # Update status to processing
            update_thumbnail_status(filename, 'processing')
            
            try:
                # Download image from S3
                response = s3_client.get_object(Bucket=bucket, Key=key)
                image_data = response['Body'].read()
                
                logger.info(f"Downloaded image: {len(image_data)} bytes")
                
                # Generate thumbnail
                thumbnail_data, thumbnail_size = generate_thumbnail(image_data)
                
                logger.info(f"Generated thumbnail: {thumbnail_size} bytes")
                
                # Create thumbnail S3 key
                thumbnail_key = f"thumbnails/{filename}"
                
                # Upload thumbnail to S3
                s3_client.put_object(
                    Bucket=bucket,
                    Key=thumbnail_key,
                    Body=thumbnail_data,
                    ContentType='image/jpeg',
                    Metadata={
                        'original-key': key,
                        'thumbnail-size': str(thumbnail_size),
                        'generated-at': str(datetime.now().isoformat())
                    }
                )
                
                logger.info(f"Uploaded thumbnail to: {thumbnail_key}")
                
                # Update database to completed status
                update_thumbnail_status(filename, 'completed', 
                                      thumbnail_path=thumbnail_key, 
                                      thumbnail_size=thumbnail_size)
                
                logger.info(f"✅ Successfully processed thumbnail: {filename}")
                
            except Exception as e:
                logger.error(f"❌ Thumbnail processing error for {filename}: {e}")
                update_thumbnail_status(filename, 'failed', error_message=str(e))
                
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
            'message': 'Thumbnail processing completed'
        })
    }