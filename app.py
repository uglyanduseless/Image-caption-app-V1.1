"""
COMP5349 Assignment 2: Enhanced Image Caption Application
Now using Lambda functions for image processing and thumbnail generation

Main changes:
1. Database structure adapted for new images table
2. Removed direct Gemini API calls - now handled by Lambda
3. Added thumbnail support
4. Improved error handling and status display
"""

import boto3
import mysql.connector
from flask import Flask, request, render_template, jsonify, redirect, url_for, flash
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
import uuid
import os
from PIL import Image

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

# AWS Configuration - using your existing configuration
S3_BUCKET = "chqu0370-assignment2-bucket"
S3_REGION = "us-east-1"

def get_s3_client():
    """Get S3 client"""
    return boto3.client("s3", region_name=S3_REGION)

# Database Configuration - using your existing configuration
DB_HOST = "assignment2-database.cfvojcdvmjtw.us-east-1.rds.amazonaws.com"
DB_NAME = "image_caption_db"
DB_USER = "admin"
DB_PASSWORD = "Qc20000215!"

def get_db_connection():
    """Establish database connection"""
    try:
        connection = mysql.connector.connect(
            host=DB_HOST, 
            database=DB_NAME, 
            user=DB_USER, 
            password=DB_PASSWORD,
            autocommit=True
        )
        return connection
    except mysql.connector.Error as err:
        print("Database connection error:", err)
        return None

# Allowed file types
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def allowed_file(filename):
    """Check if file type is allowed"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_image_info(file_data):
    """Get image information"""
    try:
        image = Image.open(BytesIO(file_data))
        return {
            'width': image.width,
            'height': image.height,
            'format': image.format,
            'mode': image.mode
        }
    except Exception as e:
        print(f"Error getting image info: {e}")
        return {'width': 0, 'height': 0, 'format': 'UNKNOWN', 'mode': 'UNKNOWN'}

@app.route("/")
def upload_form():
    """Home page - upload form"""
    return render_template("index.html")

@app.route("/upload", methods=["GET", "POST"])
def upload_image():
    ...  # unchanged upload logic

@app.route("/gallery")
def gallery():
    """
    Image gallery - display all images and their annotations/thumbnails
    Now getting data from new images table
    """
    try:
        connection = get_db_connection()
        if connection is None:
            return render_template("gallery.html", error="Database connection error")

        cursor = connection.cursor(dictionary=True)

        # Query from new images table using preview instead of full annotation
        query = """
            SELECT 
                filename, original_filename, annotation_status,
                thumbnail_status, uploaded_at, file_size, image_width, image_height,
                LEFT(annotation, 100) AS preview
            FROM images 
            ORDER BY uploaded_at DESC
        """

        cursor.execute(query)
        results = cursor.fetchall()
        connection.close()

        # Generate presigned URLs
        s3 = get_s3_client()
        images_with_data = []

        for row in results:
            try:
                # Original image URL
                image_url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": f"uploads/{row['filename']}"},
                    ExpiresIn=3600
                )

                # Thumbnail URL (always use thumbnails/ prefix)
                thumbnail_url = None
                try:
                    thumbnail_url = s3.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": S3_BUCKET, "Key": f"thumbnails/{row['filename']}"},
                        ExpiresIn=3600
                    )
                except:
                    thumbnail_url = None

                images_with_data.append({
                    "filename": row["filename"],
                    "original_filename": row["original_filename"],
                    "url": image_url,
                    "thumbnail_url": thumbnail_url,
                    "annotation": row["preview"] or "Generating preview...",
                    "annotation_status": row["annotation_status"],
                    "thumbnail_status": row["thumbnail_status"],
                    "uploaded_at": row["uploaded_at"],
                    "file_size": row["file_size"],
                    "dimensions": f"{row['image_width']}x{row['image_height']}" if row['image_width'] else "Unknown"
                })
            except Exception as e:
                print(f"Error processing image {row['filename']}: {e}")
                continue

        return render_template("gallery.html", images=images_with_data)

    except Exception as e:
        return render_template("gallery.html", error=f"Database error: {str(e)}")

...  # keep other route definitions unchanged

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
