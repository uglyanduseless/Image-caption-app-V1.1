
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
    if request.method == "POST":
        if "file" not in request.files:
            return render_template("upload.html", error="No file selected")

        file = request.files["file"]
        if file.filename == "":
            return render_template("upload.html", error="No file selected")

        if not allowed_file(file.filename):
            return render_template("upload.html", error="Unsupported file type, please upload an image file")

        file_data = file.read()
        file_size = len(file_data)
        
        if file_size > MAX_FILE_SIZE:
            return render_template("upload.html", error="File too large, maximum 10MB supported")

        original_filename = secure_filename(file.filename)
        file_extension = original_filename.rsplit(".", 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"

        image_info = get_image_info(file_data)

        try:
            s3 = get_s3_client()
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"uploads/{unique_filename}",
                Body=file_data,
                ContentType=file.content_type or f"image/{file_extension}",
                Metadata={
                    'original-filename': original_filename,
                    'uploaded-by': 'web-app',
                    'file-size': str(file_size)
                }
            )
            print(f"✅ File uploaded to S3: {unique_filename}")
        except Exception as e:
            return render_template("upload.html", error=f"S3 upload error: {str(e)}")

        try:
            connection = get_db_connection()
            if connection is None:
                return render_template("upload.html", error="Database connection error")

            cursor = connection.cursor()
            insert_query = """
                INSERT INTO images (
                    filename, original_filename, file_size, mime_type,
                    s3_key, s3_bucket, image_width, image_height, image_format,
                    upload_ip, annotation_status, thumbnail_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                unique_filename,
                original_filename,
                file_size,
                file.content_type or f"image/{file_extension}",
                unique_filename,
                S3_BUCKET,
                image_info['width'],
                image_info['height'],
                image_info['format'],
                request.remote_addr,
                'pending',
                'pending'
            ))
            image_id = cursor.lastrowid
            connection.close()
            print(f"✅ Metadata saved to database, image ID: {image_id}")
        except Exception as e:
            return render_template("upload.html", error=f"Database error: {str(e)}")

        file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/uploads/{unique_filename}"
        encoded_image = base64.b64encode(file_data).decode("utf-8")

        return render_template("upload.html", 
                             image_data=encoded_image, 
                             file_url=file_url, 
                             filename=unique_filename,
                             processing_message="Image uploaded! Generating annotation and thumbnail in background...")

    return render_template("upload.html")

@app.route("/gallery")
def gallery():
    try:
        connection = get_db_connection()
        if connection is None:
            return render_template("gallery.html", error="Database connection error")

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT 
                filename, original_filename, annotation_status,
                LEFT(annotation, 100) AS preview,
                uploaded_at, file_size, image_width, image_height
            FROM images 
            ORDER BY uploaded_at DESC
        """
        cursor.execute(query)
        results = cursor.fetchall()
        connection.close()

        s3 = get_s3_client()
        images_with_data = []
        
        for row in results:
            try:
                image_url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": f"uploads/{row['filename']}"},
                    ExpiresIn=3600
                )

                thumbnail_key = f"thumbnails/{row['filename']}"
                thumbnail_url = s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": thumbnail_key},
                    ExpiresIn=3600
                )

                images_with_data.append({
                    "filename": row["filename"],
                    "original_filename": row["original_filename"],
                    "url": image_url,
                    "thumbnail_url": thumbnail_url,
                    "annotation": row["preview"] or "Generating annotation...",
                    "annotation_status": row["annotation_status"],
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

@app.route("/api/image/<filename>/status")
def get_image_status(filename):
    try:
        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database connection error"})

        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT annotation_status, thumbnail_status, annotation, 
                   annotation_generated_at, thumbnail_generated_at
            FROM images 
            WHERE filename = %s
        """, (filename,))

        result = cursor.fetchone()
        connection.close()

        if not result:
            return jsonify({"error": "Image not found"})

        return jsonify({
            "annotation_status": result["annotation_status"],
            "thumbnail_status": result["thumbnail_status"],
            "annotation": result["annotation"],
            "annotation_generated_at": str(result["annotation_generated_at"]) if result["annotation_generated_at"] else None,
            "thumbnail_generated_at": str(result["thumbnail_generated_at"]) if result["thumbnail_generated_at"] else None
        })

    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/stats")
def stats():
    try:
        connection = get_db_connection()
        if connection is None:
            return render_template("stats.html", error="Database connection error")

        cursor = connection.cursor(dictionary=True)
        stats_query = """
            SELECT 
                COUNT(*) as total_images,
                SUM(CASE WHEN annotation_status = 'completed' THEN 1 ELSE 0 END) as completed_annotations,
                SUM(CASE WHEN thumbnail_status = 'completed' THEN 1 ELSE 0 END) as completed_thumbnails,
                SUM(CASE WHEN annotation_status = 'failed' OR thumbnail_status = 'failed' THEN 1 ELSE 0 END) as failed_processing,
                AVG(file_size) as avg_file_size,
                SUM(file_size) as total_storage_used
            FROM images
        """

        cursor.execute(stats_query)
        stats = cursor.fetchone()
        connection.close()

        return render_template("stats.html", stats=stats)

    except Exception as e:
        return render_template("stats.html", error=f"Error: {str(e)}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)